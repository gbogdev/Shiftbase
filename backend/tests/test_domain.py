from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core import mail
from django.core.exceptions import ValidationError

from attendance import services as att
from attendance.models import TimeCorrection, TimeEntry
from core.errors import Conflict
from core.models import AuditLog
from leave import services as lv
from leave.models import LeaveType
from notifications.models import Notification
from notifications.services import notify, retry_failed_emails
from people.models import Availability, Qualification
from scheduling import services as sch
from scheduling.models import OpenShiftApplication, Shift
from scheduling.validation import validate
from tests.conftest import utc

pytestmark = pytest.mark.django_db
FUTURE = utc(2030, 5, 6, 9)  # a Monday


def codes(issues):
    return {i.code for i in issues}


# ---------- validation ----------

def test_overlap_is_blocking(w, mk_shift):
    mk_shift(w.ella, utc(2026, 3, 2, 9), utc(2026, 3, 2, 17))
    b = mk_shift(w.ella, utc(2026, 3, 2, 16), utc(2026, 3, 2, 20))
    issues = validate(w.org, [b])
    assert any(i.code == "overlap" and i.severity == "error" for i in issues)


def test_adjacent_shifts_do_not_overlap(w, mk_shift):
    mk_shift(w.ella, utc(2026, 3, 2, 9), utc(2026, 3, 2, 12))
    b = mk_shift(w.ella, utc(2026, 3, 2, 12), utc(2026, 3, 2, 15))
    assert "overlap" not in codes(validate(w.org, [b]))


def test_rest_period_and_weekly_hours_warn(w, mk_shift):
    mk_shift(w.ella, utc(2026, 3, 2, 14), utc(2026, 3, 2, 23))
    b = mk_shift(w.ella, utc(2026, 3, 3, 6), utc(2026, 3, 3, 14))
    issues = validate(w.org, [b])
    assert "rest" in codes(issues) and all(i.severity == "warning" for i in issues if i.code == "rest")
    w.org.max_weekly_hours = 10
    w.org.save()
    assert "weekly_hours" in codes(validate(w.org, [b]))


def test_missing_qualification_blocks(w, mk_shift):
    q = Qualification.objects.create(organization=w.org, name="Food hygiene")
    s = mk_shift(w.ella)
    s.required_qualifications.add(q)
    assert any(i.code == "qualification" and i.severity == "error" for i in validate(w.org, [s]))
    w.ella.qualifications.add(q)
    assert "qualification" not in codes(validate(w.org, [s]))


def test_unavailability_warns_and_can_block(w, mk_shift):
    Availability.objects.create(employee=w.ella, weekday=0, start_time="00:00", end_time="23:59", available=False)
    s = mk_shift(w.ella, utc(2026, 3, 2, 9), utc(2026, 3, 2, 17))  # Monday
    assert [i.severity for i in validate(w.org, [s]) if i.code == "unavailable"] == ["warning"]
    w.org.availability_blocks_publish = True
    w.org.save()
    assert [i.severity for i in validate(w.org, [s]) if i.code == "unavailable"] == ["error"]


def test_leave_blocks_scheduling(w, mk_shift):
    lt = LeaveType.objects.create(organization=w.org, name="Annual", requires_approval=False)
    lv.request_leave(w.ella, lt, date(2026, 3, 2), date(2026, 3, 3))
    assert "leave" in codes(validate(w.org, [mk_shift(w.ella)]))


# ---------- shifts API / publish ----------

def test_publish_blocked_by_errors_then_succeeds(w, mk_shift):
    c = w.client(w.manager)
    a = mk_shift(w.ella, utc(2026, 3, 2, 9), utc(2026, 3, 2, 17))
    b = mk_shift(w.ella, utc(2026, 3, 2, 12), utc(2026, 3, 2, 18))
    body = {"location": w.loc.pk, "start": "2026-03-02T00:00:00+00:00", "end": "2026-03-09T00:00:00+00:00"}
    r = c.post("/api/shifts/publish/", body, format="json")
    assert r.status_code == 409 and r.json()["issues"][0]["code"] == "overlap"
    assert Shift.objects.filter(status="published").count() == 0
    b.delete()
    r = c.post("/api/shifts/publish/", body, format="json")
    assert r.status_code == 200 and r.json()["published"] == 1
    a.refresh_from_db()
    assert a.status == "published" and a.published_at
    assert AuditLog.objects.filter(action="schedule.publish").exists()


def test_publish_notifies_once_per_employee_and_not_duplicated(w, mk_shift):
    mk_shift(w.ella, utc(2026, 3, 2, 9), utc(2026, 3, 2, 12))
    mk_shift(w.ella, utc(2026, 3, 3, 9), utc(2026, 3, 3, 12))
    sch.publish(w.manager, w.loc, utc(2026, 3, 2), utc(2026, 3, 9))
    assert Notification.objects.filter(user=w.emp_user, kind="schedule_published").count() == 1
    assert not Notification.objects.filter(user=w.emp_user2).exists()


def test_edit_published_shift_flags_and_logs_and_notifies(w, mk_shift):
    s = mk_shift(w.ella, status="published")
    r = w.client(w.manager).patch(f"/api/shifts/{s.pk}/", {"end": "2026-03-02T18:00:00Z", "version": 1}, format="json")
    assert r.status_code == 200
    s.refresh_from_db()
    assert s.modified_since_publish and s.version == 2
    assert s.changes.filter(kind="edited").exists()
    assert Notification.objects.filter(user=w.emp_user, kind="shift_changed").exists()
    assert AuditLog.objects.filter(action="shift.edit", target_id=str(s.pk)).exists()


def test_stale_version_conflicts(w, mk_shift):
    s = mk_shift(w.ella)
    c = w.client(w.manager)
    assert c.patch(f"/api/shifts/{s.pk}/", {"notes": "a", "version": 1}, format="json").status_code == 200
    assert c.patch(f"/api/shifts/{s.pk}/", {"notes": "b", "version": 1}, format="json").status_code == 409


def test_employee_cannot_modify_shifts(w, mk_shift):
    s = mk_shift(w.ella, status="published")
    c = w.client(w.emp_user)
    assert c.patch(f"/api/shifts/{s.pk}/", {"employee": w.sam.pk}, format="json").status_code == 403
    assert c.delete(f"/api/shifts/{s.pk}/").status_code == 403
    assert c.post("/api/shifts/publish/", {}, format="json").status_code == 403


def test_employee_sees_only_published(w, mk_shift):
    mk_shift(w.ella, status="draft")
    pub = mk_shift(w.ella, status="published", start=utc(2026, 3, 3, 9), end=utc(2026, 3, 3, 17))
    ids = [s["id"] for s in w.client(w.emp_user).get("/api/shifts/").json()["results"]]
    assert ids == [pub.pk]


def test_cannot_assign_inactive_or_foreign_employee(w, mk_shift):
    s = mk_shift(None)
    c = w.client(w.manager)
    assert c.patch(f"/api/shifts/{s.pk}/", {"employee": w.ob_emp.pk}, format="json").status_code == 400
    w.sam.status = "inactive"
    w.sam.save()
    assert c.patch(f"/api/shifts/{s.pk}/", {"employee": w.sam.pk}, format="json").status_code == 400


def test_recurring_and_template_and_duplicate(w):
    base = dict(location=w.loc, start=utc(2026, 3, 2, 9), end=utc(2026, 3, 2, 17), break_minutes=30)
    made = sch.create_recurring(w.manager, base, weekdays=[0, 2], until=date(2026, 3, 15))
    assert len(made) == 4 and len({s.series_id for s in made}) == 1
    dup = sch.duplicate_shift(w.manager, made[0], days=7)
    assert dup.start == made[0].start + timedelta(days=7) and dup.status == "draft"
    from scheduling.models import ScheduleTemplate

    t = ScheduleTemplate.objects.create(organization=w.org, name="Week", location=w.loc,
                                        shifts=[{"weekday": 1, "start": "22:00", "end": "06:00"}])
    (night,) = sch.apply_template(w.manager, t, date(2026, 3, 9))
    assert night.end - night.start == timedelta(hours=8)


# ---------- time zones / DST ----------

def test_recurring_shift_keeps_local_time_across_dst(w):
    # UK clocks go forward on 2026-03-29: 09:00 local is 09:00 UTC before, 08:00 UTC after.
    london = ZoneInfo("Europe/London")
    base = dict(location=w.loc, start=utc(2026, 3, 23, 9), end=utc(2026, 3, 23, 17))
    made = sch.create_recurring(w.manager, base, weekdays=[0], until=date(2026, 3, 30))
    local = [s.start.astimezone(london).strftime("%H:%M") for s in made]
    assert local == ["09:00", "09:00"]
    assert made[1].start.astimezone(ZoneInfo('UTC')).hour == 8


def test_spring_forward_shift_hours_are_real_elapsed(w):
    london = ZoneInfo("Europe/London")
    from datetime import datetime

    utc_ = ZoneInfo('UTC')  # the database always hands back UTC
    s = Shift(start=datetime(2026, 3, 28, 22, 0, tzinfo=london).astimezone(utc_),
              end=datetime(2026, 3, 29, 6, 0, tzinfo=london).astimezone(utc_))
    assert s.hours == 7  # the clock hour that does not exist is not worked


def test_week_endpoint_uses_org_timezone(w):
    r = w.client(w.manager).get("/api/week/?date=2026-03-29").json()
    assert r["week_start"] == "2026-03-23" and r["end"].startswith("2026-03-30T00:00:00+01:00")


# ---------- swaps and open shifts ----------

def _published(mk_shift, emp, **kw):
    return mk_shift(emp, start=kw.pop("start", FUTURE), end=kw.pop("end", FUTURE + timedelta(hours=8)), status="published")


def test_swap_needs_manager_approval_by_default(w, mk_shift):
    s = _published(mk_shift, w.ella)
    req = sch.request_swap(w.ella, s, w.sam)
    sch.accept_swap(w.sam, req.pk)
    s.refresh_from_db()
    assert s.employee == w.ella  # unchanged until a manager approves
    sch.decide_swap(w.manager, req.pk, True)
    s.refresh_from_db()
    assert s.employee == w.sam and s.modified_since_publish
    assert AuditLog.objects.filter(action="swap.approve").exists()


def test_swap_double_approval_rejected(w, mk_shift):
    s = _published(mk_shift, w.ella)
    req = sch.request_swap(w.ella, s, w.sam)
    sch.accept_swap(w.sam, req.pk)
    sch.decide_swap(w.manager, req.pk, True)
    with pytest.raises(Conflict):
        sch.decide_swap(w.admin, req.pk, True)


def test_swap_auto_when_org_does_not_require_approval(w, mk_shift):
    w.org.swaps_need_approval = False
    w.org.save()
    s = _published(mk_shift, w.ella)
    req = sch.request_swap(w.ella, s)
    w.ella.organization.refresh_from_db()
    sch.accept_swap(w.sam, req.pk)
    s.refresh_from_db()
    assert s.employee == w.sam


def test_swap_validation_blocks_conflicting_acceptor(w, mk_shift):
    s = _published(mk_shift, w.ella)
    _published(mk_shift, w.sam, start=FUTURE + timedelta(hours=2), end=FUTURE + timedelta(hours=10))
    req = sch.request_swap(w.ella, s, w.sam)
    sch.accept_swap(w.sam, req.pk)
    with pytest.raises(Conflict):
        sch.decide_swap(w.manager, req.pk, True)


def test_swap_authorization_rules(w, mk_shift):
    s = _published(mk_shift, w.ella)
    with pytest.raises(ValidationError):
        sch.request_swap(w.sam, s)  # not your shift
    req = sch.request_swap(w.ella, s, w.sam)
    with pytest.raises(ValidationError):
        sch.accept_swap(w.ella, req.pk)  # cannot accept own
    assert w.client(w.emp_user2).post(f"/api/swaps/{req.pk}/decide/", {"approve": True}, format="json").status_code == 403
    assert w.client(w.emp_user).post(f"/api/swaps/{req.pk}/decide/", {"approve": True}, format="json").status_code == 403
    assert w.client(w.ob_admin).post(f"/api/swaps/{req.pk}/accept/").status_code in (404, 400)


def test_open_shift_first_approval_wins(w, mk_shift):
    s = _published(mk_shift, None)
    a1, a2 = sch.apply_open_shift(w.ella, s), sch.apply_open_shift(w.sam, s)
    sch.decide_application(w.manager, a1.pk, True)
    a2.refresh_from_db()
    assert a2.status == "rejected"
    s.refresh_from_db()
    assert s.employee == w.ella
    with pytest.raises(Conflict):
        sch.decide_application(w.manager, a2.pk, True)
    with pytest.raises(Conflict):
        sch.apply_open_shift(w.sam, s)  # no longer open


def test_duplicate_application_rejected(w, mk_shift):
    s = _published(mk_shift, None)
    sch.apply_open_shift(w.ella, s)
    with pytest.raises(Conflict):
        sch.apply_open_shift(w.ella, s)
    assert OpenShiftApplication.objects.count() == 1


# ---------- leave ----------

def test_leave_flow_with_record_and_staffing_warning(w):
    lt = LeaveType.objects.create(organization=w.org, name="Annual", annual_allowance_days=2)
    w.org.leave_min_staff_warning = 2  # want 2 colleagues cover; only Sam is left
    w.org.save()
    req = lv.request_leave(w.ella, lt, date(2026, 6, 1), date(2026, 6, 2), "trip")
    assert req.status == "pending"
    with pytest.raises(Conflict):
        lv.request_leave(w.ella, lt, date(2026, 6, 2), date(2026, 6, 3))  # overlapping request
    done, warnings, _ = lv.decide_leave(w.manager, req.pk, True, "enjoy")
    assert done.status == "approved" and done.decided_by == w.manager and done.decision_note == "enjoy"
    assert warnings  # Sam is the only other Kitchen colleague - threshold is 1, then 1 left => ok; Ella's team of 2
    assert AuditLog.objects.filter(action="leave.approve").exists()
    with pytest.raises(Conflict):
        lv.decide_leave(w.admin, req.pk, False)  # already decided


def test_leave_allowance_enforced(w):
    lt = LeaveType.objects.create(organization=w.org, name="Annual", annual_allowance_days=1)
    req = lv.request_leave(w.ella, lt, date(2026, 6, 1), date(2026, 6, 3))
    with pytest.raises(Conflict):
        lv.decide_leave(w.manager, req.pk, True)


def test_cannot_approve_own_leave(w):
    lt = LeaveType.objects.create(organization=w.org, name="Annual")
    mgr_emp = w.employee(w.manager)
    req = lv.request_leave(mgr_emp, lt, date(2026, 6, 1), date(2026, 6, 1))
    with pytest.raises(ValidationError):
        lv.decide_leave(w.manager, req.pk, True)
    assert w.client(w.emp_user).post(f"/api/leave/{req.pk}/decide/", {"approve": True}, format="json").status_code == 403


def test_leave_isolation(w):
    lt = LeaveType.objects.create(organization=w.org, name="Annual")
    req = lv.request_leave(w.ella, lt, date(2026, 6, 1), date(2026, 6, 1))
    assert w.client(w.ob_admin).post(f"/api/leave/{req.pk}/decide/", {"approve": True}, format="json").status_code == 404
    assert w.client(w.emp_user2).get("/api/leave/").json() == []


# ---------- attendance ----------

def test_clock_cycle_with_break(w):
    t0 = utc(2026, 3, 2, 9)
    e = att.clock_in(w.ella, t0)
    att.start_break(w.ella, t0 + timedelta(hours=4))
    att.end_break(w.ella, t0 + timedelta(hours=4, minutes=30))
    e = att.clock_out(w.ella, t0 + timedelta(hours=8))
    assert e.break_minutes == 30 and e.worked_hours == 7.5


def test_double_clock_in_and_stray_clock_out(w):
    att.clock_in(w.ella)
    with pytest.raises(Conflict):
        att.clock_in(w.ella)
    with pytest.raises(Conflict):
        att.clock_out(w.sam)
    assert TimeEntry.objects.filter(clock_out__isnull=True).count() == 1


def test_late_arrival_notifies_manager(w, mk_shift):
    s = mk_shift(w.ella, utc(2026, 3, 2, 9), utc(2026, 3, 2, 17), status="published")
    att.clock_in(w.ella, utc(2026, 3, 2, 9, 30))
    assert Notification.objects.filter(user=w.manager, title="Late arrival").exists()
    assert TimeEntry.objects.get().shift == s


def test_missed_clock_out_flagged_once(w):
    att.clock_in(w.ella, utc(2026, 3, 2, 9))
    first = att.flag_missed_clock_outs(utc(2026, 3, 3, 9))
    second = att.flag_missed_clock_outs(utc(2026, 3, 3, 10))
    assert first > 0 and second == 0


def test_correction_requires_reason_and_keeps_original(w):
    e = att.clock_in(w.ella, utc(2026, 3, 2, 9))
    att.clock_out(w.ella, utc(2026, 3, 2, 17))
    with pytest.raises(ValidationError):
        att.correct_entry(w.manager, e.pk, "  ", clock_out=utc(2026, 3, 2, 18))
    att.correct_entry(w.manager, e.pk, "Forgot to clock out at 18:00", clock_out=utc(2026, 3, 2, 18))
    c = TimeCorrection.objects.get()
    assert c.old_values["clock_out"].startswith("2026-03-02T17:00") and c.new_values["clock_out"].startswith("2026-03-02T18:00")
    assert c.actor == w.manager and c.reason
    assert AuditLog.objects.filter(action="timesheet.correct").exists()


def test_timesheet_approval_and_csv(w):
    e = att.clock_in(w.ella, utc(2026, 3, 2, 9))
    att.clock_out(w.ella, utc(2026, 3, 2, 17))
    assert att.approve_entries(w.manager, [e.pk]) == 0  # must be submitted first
    assert att.submit_entries(w.ella, [e.pk]) == 1
    assert att.approve_entries(w.manager, [e.pk]) == 1
    assert att.approve_entries(w.manager, [e.pk]) == 0  # no double approval
    with pytest.raises(Conflict):
        att.correct_entry(w.manager, e.pk, "late fix", break_minutes=10)
    c = w.client(w.manager)
    r = c.get("/api/time/export/?start=2026-03-01T00:00:00Z&end=2026-04-01T00:00:00Z")
    assert r.status_code == 200 and "Ella Employee" in r.content.decode() and "8.00" in r.content.decode()
    assert w.client(w.emp_user).get("/api/time/export/").status_code == 403
    assert "Ella" not in w.client(w.ob_admin).get("/api/time/export/?start=2026-03-01T00:00:00Z&end=2026-04-01T00:00:00Z").content.decode()


def test_cannot_approve_own_time(w):
    me = w.employee(w.manager)
    e = att.clock_in(me, utc(2026, 3, 2, 9))
    att.clock_out(me, utc(2026, 3, 2, 17))
    att.submit_entries(me, [e.pk])
    assert att.approve_entries(w.manager, [e.pk]) == 0
    assert att.approve_entries(w.admin, [e.pk]) == 1


def test_csv_formula_injection_neutralised(w):
    w.ella.name = "=HYPERLINK(\"http://evil\")"
    w.ella.save()
    e = att.clock_in(w.ella, utc(2026, 3, 2, 9))
    att.clock_out(w.ella, utc(2026, 3, 2, 10))
    att.submit_entries(w.ella, [e.pk])
    att.approve_entries(w.manager, [e.pk])
    body = att.export_csv(w.org, TimeEntry.objects.all())
    assert "\"'=HYPERLINK" in body


def test_timeentry_correction_wrong_org_404(w):
    e = att.clock_in(w.ella, utc(2026, 3, 2, 9))
    r = w.client(w.ob_admin).post(f"/api/time/{e.pk}/correct/", {"reason": "x", "break_minutes": 5}, format="json")
    assert r.status_code == 404


# ---------- notifications ----------

def test_notification_dedupe(w):
    assert notify(w.emp_user, "x", "Hello", dedupe_key="evt:1") is not None
    assert notify(w.emp_user, "x", "Hello", dedupe_key="evt:1") is None
    assert Notification.objects.count() == 1


def test_email_failure_keeps_notification_and_retries(w, settings, django_capture_on_commit_callbacks):
    settings.EMAIL_BACKEND = "tests.helpers.FailingBackend"
    with django_capture_on_commit_callbacks(execute=True):
        notify(w.emp_user, "x", "Hello", dedupe_key="evt:2")
    n = Notification.objects.get()
    assert n.email_sent_at is None and n.email_error
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    retry_failed_emails()
    n.refresh_from_db()
    assert n.email_sent_at and any(m.to == ["ella@harbor.test"] for m in mail.outbox)


def test_notification_endpoint_only_own(w):
    notify(w.emp_user, "x", "Mine", dedupe_key="a")
    notify(w.emp_user2, "x", "Theirs", dedupe_key="b")
    titles = [n["title"] for n in w.client(w.emp_user).get("/api/notifications/").json()]
    assert titles == ["Mine"]


# ---------- reports ----------

def test_reports_scoped_and_csv(w, mk_shift):
    mk_shift(w.ella, utc(2026, 3, 2, 9), utc(2026, 3, 2, 17), status="published")
    mk_shift(None, utc(2026, 3, 3, 9), utc(2026, 3, 3, 17), status="published")
    q = "?start=2026-03-01T00:00:00Z&end=2026-04-01T00:00:00Z"
    c = w.client(w.manager)
    assert c.get(f"/api/reports/scheduled-hours/{q}").json()["rows"] == [["Ella Employee", 8.0]]
    assert len(c.get(f"/api/reports/open-shifts/{q}").json()["rows"]) == 1
    assert c.get(f"/api/reports/coverage/{q}").json()["rows"]
    assert c.get(f"/api/reports/scheduled-hours/{q}&export=csv")["Content-Type"].startswith("text/csv")
    assert w.client(w.ob_admin).get(f"/api/reports/scheduled-hours/{q}").json()["rows"] == []
    assert c.get(f"/api/reports/labor-cost/{q}").json()["rows"][0][0].startswith("Labor cost reports require")
    assert c.get("/api/reports/nope/" + q).status_code == 404
