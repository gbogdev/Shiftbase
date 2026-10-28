from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import audit
from .access import IsAdmin, IsManager, IsOwner, org_scoped
from .errors import Conflict
from .models import AuditLog, Invitation, Organization, Role, User, hash_token


def _client_ip(request):
    return request.META.get("REMOTE_ADDR", "")


def _throttle_key(email, request):
    return f"login:{email.lower()}:{_client_ip(request)}"


class UserSerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(source="organization.name", read_only=True)
    timezone = serializers.CharField(source="organization.timezone", read_only=True)
    date_format = serializers.CharField(source="organization.date_format", read_only=True)
    employee_id = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "name", "role", "organization", "organization_name", "timezone", "date_format", "employee_id"]

    def get_employee_id(self, u):
        e = getattr(u, "employee", None)
        return e.pk if e else None


class CsrfView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"csrfToken": get_token(request)})


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []  # login itself is not CSRF-exempt: see enforce below

    def post(self, request):
        from rest_framework.authentication import SessionAuthentication

        SessionAuthentication().enforce_csrf(request)
        email = str(request.data.get("email", "")).strip().lower()
        password = str(request.data.get("password", ""))
        limit, window = settings.LOGIN_RATE_LIMIT
        key = _throttle_key(email, request)
        if cache.get(key, 0) >= limit:
            return Response({"detail": "Too many attempts. Try again later."}, status=429)
        user = authenticate(request, username=email, password=password)
        if user is None or not user.is_active or (user.organization_id is None):
            try:
                cache.add(key, 0, window)
                cache.incr(key)
            except ValueError:
                cache.set(key, 1, window)
            return Response({"detail": "Invalid email or password."}, status=400)
        cache.delete(key)
        login(request, user)
        audit.record(user, "auth.login")
        return Response(UserSerializer(user).data)


class LogoutView(APIView):
    def post(self, request):
        logout(request)
        return Response(status=204)


class MeView(APIView):
    def get(self, request):
        return Response(UserSerializer(request.user).data)


class OrgSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        exclude = ["created_at"]
        read_only_fields = ["id"]


class OrgView(APIView):
    def get_permissions(self):
        return [IsAdmin()] if self.request.method != "GET" else super().get_permissions()

    def get(self, request):
        return Response(OrgSerializer(request.user.organization).data)

    def patch(self, request):
        s = OrgSerializer(request.user.organization, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        audit.record(request.user, "org.settings", request.user.organization, changed=list(request.data.keys()))
        return Response(s.data)


def _invite_url(raw):
    return f"{settings.APP_BASE_URL}/accept-invite?token={raw}"


class InviteView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request):
        from people.models import Employee

        org = request.user.organization
        email = str(request.data.get("email", "")).strip().lower()
        role = request.data.get("role", Role.EMPLOYEE)
        if role not in Role.values or role == Role.OWNER:
            raise ValidationError("Invalid role.")
        if role in (Role.ADMIN,) and not request.user.at_least(Role.OWNER):
            raise ValidationError("Only owners can invite administrators.")
        if User.objects.filter(email=email).exists():
            raise Conflict("That email already has an account.")
        emp = None
        if request.data.get("employee"):
            emp = Employee.objects.get(pk=request.data["employee"], organization=org)
        with transaction.atomic():
            inv, raw = Invitation.issue(organization=org, email=email, role=role, employee=emp, invited_by=request.user)
            audit.record(request.user, "invite.create", inv, email=email, role=role)
        from django.core.mail import send_mail

        try:
            send_mail(f"You're invited to {org.name} on Shiftbase", f"Activate your account: {_invite_url(raw)}", None, [email])
        except Exception:
            pass  # invite stays valid; admin can re-issue
        body = {"id": inv.pk, "expires_at": inv.expires_at}
        if settings.DEBUG:
            body["debug_link"] = _invite_url(raw)
        return Response(body, status=201)


class AcceptInviteView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []

    @transaction.atomic
    def post(self, request):
        from people.models import Employee

        inv = Invitation.objects.select_for_update().filter(token_hash=hash_token(str(request.data.get("token", "")))).first()
        if not inv or not inv.usable:
            return Response({"detail": "This invitation is invalid or has expired."}, status=400)
        password = str(request.data.get("password", ""))
        try:
            validate_password(password)
        except ValidationError as e:
            return Response({"detail": e.messages}, status=400)
        if User.objects.filter(email=inv.email).exists():
            return Response({"detail": "This invitation is invalid or has expired."}, status=400)
        name = str(request.data.get("name", "")).strip() or inv.email
        user = User.objects.create_user(inv.email, password, name=name, organization=inv.organization, role=inv.role)
        emp = inv.employee or Employee.objects.filter(organization=inv.organization, email=inv.email, user__isnull=True).first()
        if emp:
            emp.user = user
            emp.save(update_fields=["user"])
        inv.accepted_at = timezone.now()
        inv.save(update_fields=["accepted_at"])
        audit.record(user, "invite.accept", inv)
        return Response({"detail": "Account activated."}, status=201)


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        email = str(request.data.get("email", "")).strip().lower()
        key = f"reset:{email}:{_client_ip(request)}"
        if cache.get(key, 0) < 5:
            cache.set(key, cache.get(key, 0) + 1, 3600)
            user = User.objects.filter(email=email, is_active=True, organization__isnull=False).first()
            if user:
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                link = f"{settings.APP_BASE_URL}/reset-password?uid={uid}&token={default_token_generator.make_token(user)}"
                try:
                    from django.core.mail import send_mail

                    send_mail("Reset your Shiftbase password", f"Reset link (expires in 1 hour): {link}", None, [email])
                except Exception:
                    pass
        return Response({"detail": "If that account exists, an email has been sent."})  # no account enumeration


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        try:
            user = User.objects.get(pk=urlsafe_base64_decode(str(request.data.get("uid", ""))).decode())
        except Exception:
            user = None
        if not user or not default_token_generator.check_token(user, str(request.data.get("token", ""))):
            return Response({"detail": "This reset link is invalid or has expired."}, status=400)
        password = str(request.data.get("password", ""))
        try:
            validate_password(password, user)
        except ValidationError as e:
            return Response({"detail": e.messages}, status=400)
        user.set_password(password)  # also invalidates the token (it hashes the password)
        user.save(update_fields=["password"])
        audit.record(user, "auth.password_reset")
        return Response({"detail": "Password updated."})


class UserListView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        return Response(UserSerializer(org_scoped(User.objects.all(), request.user).order_by("email"), many=True).data)


class UserDetailView(APIView):
    """Role and active-state changes. Admins cannot touch owners or grant admin; nobody edits themselves."""

    permission_classes = [IsAdmin]

    @transaction.atomic
    def patch(self, request, pk):
        target = org_scoped(User.objects.select_for_update(), request.user).get(pk=pk)
        actor = request.user
        if target.pk == actor.pk:
            raise ValidationError("You cannot change your own role or status.")
        if target.rank >= actor.rank:
            raise ValidationError("You cannot modify a user of equal or higher role.")
        changes = {}
        if "role" in request.data:
            role = request.data["role"]
            if role not in Role.values or role == Role.OWNER or ROLE_ORDER(role) >= actor.rank:
                raise ValidationError("Invalid role for your permission level.")
            changes["role"] = (target.role, role)
            target.role = role
        if "is_active" in request.data:
            changes["is_active"] = (target.is_active, bool(request.data["is_active"]))
            target.is_active = bool(request.data["is_active"])
        target.save()
        if "managed_locations" in request.data:
            target.managed_locations.set(
                list(_org_objs("Location", actor, request.data["managed_locations"])))
        if "managed_departments" in request.data:
            target.managed_departments.set(
                list(_org_objs("Department", actor, request.data["managed_departments"])))
        if not target.is_active:
            from django.contrib.sessions.models import Session

            for s in Session.objects.all():
                if str(s.get_decoded().get("_auth_user_id")) == str(target.pk):
                    s.delete()
        audit.record(actor, "user.update", target, changes={k: list(v) for k, v in changes.items()})
        return Response(UserSerializer(target).data)


def ROLE_ORDER(role):
    from .models import ROLE_RANK

    return ROLE_RANK[role]


def _org_objs(model, actor, ids):
    from people import models as pm

    return getattr(pm, model).objects.filter(organization=actor.organization, pk__in=ids)


class AuditView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        qs = org_scoped(AuditLog.objects.select_related("actor"), request.user)[:500]
        return Response([{"id": a.id, "at": a.created_at, "actor": a.actor.email if a.actor else None,
                          "action": a.action, "target": f"{a.target_type}:{a.target_id}", "detail": a.detail} for a in qs])


__all__ = ["IsManager", "IsOwner"]
