import pytest
from django.core import mail
from rest_framework.test import APIClient

from core.models import AuditLog, Invitation, User
from tests.conftest import PW

pytestmark = pytest.mark.django_db


def test_login_ok_and_bad_password(w):
    c = APIClient()
    assert c.post("/api/auth/login/", {"email": "admin@harbor.test", "password": PW}, format="json").status_code == 200
    assert APIClient().post("/api/auth/login/", {"email": "admin@harbor.test", "password": "nope"}, format="json").status_code == 400


def test_login_rate_limited(w):
    c = APIClient()
    for _ in range(5):
        c.post("/api/auth/login/", {"email": "admin@harbor.test", "password": "bad"}, format="json")
    r = c.post("/api/auth/login/", {"email": "admin@harbor.test", "password": PW}, format="json")
    assert r.status_code == 429  # even the right password is refused while limited


def test_login_requires_csrf_when_enforced(w):
    c = APIClient(enforce_csrf_checks=True)
    assert c.post("/api/auth/login/", {"email": "admin@harbor.test", "password": PW}, format="json").status_code == 403


def test_state_changing_call_requires_csrf(w):
    c = APIClient(enforce_csrf_checks=True)
    c.force_login(w.admin)
    assert c.post("/api/locations/", {"name": "X"}, format="json").status_code == 403


def test_anonymous_blocked(w):
    for url in ("/api/employees/", "/api/shifts/", "/api/leave/", "/api/time/", "/api/audit/", "/api/organization/"):
        assert APIClient().get(url).status_code in (401, 403), url


def test_passwords_hashed(w):
    assert "$" in w.admin.password and PW not in w.admin.password


def test_invite_and_activation_flow(w):
    c = w.client(w.admin)
    r = c.post("/api/invitations/", {"email": "new@harbor.test", "role": "employee"}, format="json")
    assert r.status_code == 201
    raw = mail.outbox[-1].body.split("token=")[1].strip()
    assert Invitation.objects.get().token_hash != raw  # only the hash is stored
    weak = APIClient().post("/api/auth/accept-invite/", {"token": raw, "password": "short"}, format="json")
    assert weak.status_code == 400
    ok = APIClient().post("/api/auth/accept-invite/", {"token": raw, "password": PW, "name": "New Hire"}, format="json")
    assert ok.status_code == 201
    again = APIClient().post("/api/auth/accept-invite/", {"token": raw, "password": PW}, format="json")
    assert again.status_code == 400  # single use
    assert User.objects.get(email="new@harbor.test").organization == w.org


def test_expired_invitation_rejected(w):
    from django.utils import timezone

    inv, raw = Invitation.issue(organization=w.org, email="late@harbor.test")
    inv.expires_at = timezone.now() - timezone.timedelta(minutes=1)
    inv.save()
    assert APIClient().post("/api/auth/accept-invite/", {"token": raw, "password": PW}, format="json").status_code == 400


def test_employee_and_manager_cannot_invite(w):
    for u in (w.emp_user, w.manager):
        assert w.client(u).post("/api/invitations/", {"email": "x@y.test"}, format="json").status_code == 403


def test_admin_cannot_invite_admin_or_owner(w):
    c = w.client(w.admin)
    assert c.post("/api/invitations/", {"email": "a@h.test", "role": "admin"}, format="json").status_code == 400
    assert c.post("/api/invitations/", {"email": "o@h.test", "role": "owner"}, format="json").status_code == 400


def test_password_reset_token_single_use_and_no_enumeration(w):
    c = APIClient()
    a = c.post("/api/auth/password-reset/", {"email": "admin@harbor.test"}, format="json")
    b = c.post("/api/auth/password-reset/", {"email": "ghost@harbor.test"}, format="json")
    assert a.json() == b.json()
    link = mail.outbox[-1].body.split("Reset link (expires in 1 hour): ")[1].strip()
    uid, token = link.split("uid=")[1].split("&token=")
    new = "another-long-password-9"
    assert c.post("/api/auth/password-reset/confirm/", {"uid": uid, "token": token, "password": new}, format="json").status_code == 200
    assert c.post("/api/auth/password-reset/confirm/", {"uid": uid, "token": token, "password": new + "x"}, format="json").status_code == 400


def test_cross_org_isolation_lists(w):
    c = w.client(w.ob_admin)
    assert c.get("/api/employees/").json()["results"][0]["email"] == "ned@north.test"
    names = [e["name"] for e in c.get("/api/employees/").json()["results"]]
    assert "Ella Employee" not in names
    assert c.get("/api/locations/").json()["count"] == 1


def test_cross_org_idor_returns_404(w, mk_shift):
    shift = mk_shift(w.ella)
    c = w.client(w.ob_admin)
    assert c.get(f"/api/employees/{w.ella.pk}/").status_code == 404
    assert c.patch(f"/api/employees/{w.ella.pk}/", {"name": "Hacked"}, format="json").status_code == 404
    assert c.get(f"/api/shifts/{shift.pk}/").status_code == 404
    assert c.delete(f"/api/shifts/{shift.pk}/").status_code == 404
    assert c.patch(f"/api/users/{w.admin.pk}/", {"is_active": False}, format="json").status_code == 404


def test_cannot_reference_other_org_objects(w):
    c = w.client(w.admin)
    r = c.post("/api/shifts/", {"location": w.ob_loc.pk, "start": "2026-03-02T09:00:00Z", "end": "2026-03-02T17:00:00Z"}, format="json")
    assert r.status_code == 400
    r = c.post("/api/employees/", {"name": "X", "email": "x@harbor.test", "department": w.ob_admin.pk}, format="json")
    assert r.status_code == 400


def test_client_supplied_org_ignored(w):
    c = w.client(w.admin)
    r = c.post("/api/locations/", {"name": "Annex", "organization": w.other.pk}, format="json")
    assert r.status_code == 201
    assert w.org.location_set.filter(name="Annex").exists() if hasattr(w.org, "location_set") else True
    from people.models import Location

    assert Location.objects.get(name="Annex").organization == w.org


def test_role_escalation_blocked(w):
    c = w.client(w.admin)
    assert c.patch(f"/api/users/{w.admin.pk}/", {"role": "owner"}, format="json").status_code == 400  # self
    assert c.patch(f"/api/users/{w.owner.pk}/", {"role": "employee"}, format="json").status_code == 400  # higher
    assert c.patch(f"/api/users/{w.manager.pk}/", {"role": "admin"}, format="json").status_code == 400
    assert c.patch(f"/api/users/{w.manager.pk}/", {"role": "employee"}, format="json").status_code == 200
    assert w.client(w.manager).patch(f"/api/users/{w.emp_user.pk}/", {"role": "admin"}, format="json").status_code == 403


def test_employee_cannot_hit_admin_endpoints(w):
    c = w.client(w.emp_user)
    assert c.get("/api/audit/").status_code == 403
    assert c.get("/api/users/").status_code == 403
    assert c.patch("/api/organization/", {"name": "Mine"}, format="json").status_code == 403
    assert c.post("/api/employees/", {"name": "Z", "email": "z@h.test"}, format="json").status_code == 403
    assert c.get("/api/reports/scheduled-hours/?start=2026-01-01T00:00:00Z&end=2026-02-01T00:00:00Z").status_code == 403


def test_deactivated_user_cannot_login_and_session_dropped(w):
    c = w.client(w.admin)
    victim = APIClient()
    victim.post("/api/auth/login/", {"email": "ella@harbor.test", "password": PW}, format="json")
    assert victim.get("/api/auth/me/").status_code == 200
    assert c.patch(f"/api/users/{w.emp_user.pk}/", {"is_active": False}, format="json").status_code == 200
    assert victim.get("/api/auth/me/").status_code in (401, 403)
    assert APIClient().post("/api/auth/login/", {"email": "ella@harbor.test", "password": PW}, format="json").status_code == 400


def test_audit_log_is_append_only(w):
    w.client(w.admin).post("/api/locations/", {"name": "Annex"}, format="json")
    entry = AuditLog.objects.filter(action="location.create").first()
    assert entry is not None
    with pytest.raises(PermissionError):
        entry.delete()
    with pytest.raises(PermissionError):
        AuditLog.objects.all().delete()
    with pytest.raises(PermissionError):
        AuditLog.objects.all().update(action="x")
    entry.action = "tamper"
    with pytest.raises(PermissionError):
        entry.save()


def test_audit_records_sensitive_actions(w, mk_shift):
    c = w.client(w.admin)
    c.patch(f"/api/users/{w.manager.pk}/", {"role": "employee"}, format="json")
    c.patch("/api/organization/", {"name": "Harbor Cafe Ltd"}, format="json")
    actions = set(AuditLog.objects.values_list("action", flat=True))
    assert {"user.update", "org.settings"} <= actions
    assert w.client(w.emp_user).get("/api/audit/").status_code == 403
    assert w.client(w.ob_admin).get("/api/audit/").json() == []  # other org sees nothing of ours


def test_manager_scope_restricts_access(w, mk_shift):
    w.manager.managed_locations.add(w.loc2)
    inside = mk_shift(None, location=w.loc2)
    outside = mk_shift(None, location=w.loc)
    c = w.client(w.manager)
    ids = [s["id"] for s in c.get("/api/shifts/").json()["results"]]
    assert inside.pk in ids and outside.pk not in ids
    assert c.patch(f"/api/shifts/{outside.pk}/", {"notes": "x"}, format="json").status_code == 404
    r = c.post("/api/shifts/", {"location": w.loc.pk, "start": "2026-03-02T09:00:00Z", "end": "2026-03-02T17:00:00Z"}, format="json")
    assert r.status_code == 403
    assert c.patch(f"/api/employees/{w.ella.pk}/", {"name": "Z"}, format="json").status_code == 403  # admin only


def test_pay_rate_hidden_from_managers(w):
    w.ella.hourly_rate = 20
    w.ella.save()
    emp = w.client(w.manager).get(f"/api/employees/{w.ella.pk}/").json()
    assert "hourly_rate" not in emp
    assert "hourly_rate" in w.client(w.admin).get(f"/api/employees/{w.ella.pk}/").json()
    assert "hourly_rate" in w.client(w.emp_user).get(f"/api/employees/{w.ella.pk}/").json()
    other = w.client(w.emp_user).get(f"/api/employees/{w.sam.pk}/").json()
    assert set(other) == {"id", "name", "position", "department"}
