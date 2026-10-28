import hashlib
import secrets
import zoneinfo
from datetime import timedelta

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


def validate_tz(value):
    try:
        zoneinfo.ZoneInfo(value)
    except Exception as exc:
        raise ValidationError("Unknown time zone.") from exc


class Organization(models.Model):
    name = models.CharField(max_length=120)
    timezone = models.CharField(max_length=64, default="UTC", validators=[validate_tz])
    date_format = models.CharField(max_length=16, default="YYYY-MM-DD")
    week_start = models.PositiveSmallIntegerField(default=0, help_text="0=Monday .. 6=Sunday")
    # Scheduling policy. All configurable; none is legal advice (see docs/SCHEDULING_RULES.md).
    max_weekly_hours = models.DecimalField(max_digits=5, decimal_places=2, default=48)
    min_rest_hours = models.DecimalField(max_digits=4, decimal_places=2, default=11)
    availability_blocks_publish = models.BooleanField(default=False)
    swaps_need_approval = models.BooleanField(default=True)
    open_shift_applications_need_approval = models.BooleanField(default=True)
    leave_min_staff_warning = models.PositiveSmallIntegerField(default=1)
    email_notifications = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    @property
    def tz(self):
        return zoneinfo.ZoneInfo(self.timezone)


class Role(models.TextChoices):
    OWNER = "owner"
    ADMIN = "admin"
    MANAGER = "manager"
    EMPLOYEE = "employee"


ROLE_RANK = {"owner": 4, "admin": 3, "manager": 2, "employee": 1}


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra):
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=120, blank=True)
    organization = models.ForeignKey(
        Organization, null=True, blank=True, on_delete=models.PROTECT, related_name="users"
    )
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.EMPLOYEE)
    # Manager scope: empty means whole organization.
    managed_locations = models.ManyToManyField("people.Location", blank=True, related_name="managers")
    managed_departments = models.ManyToManyField("people.Department", blank=True, related_name="managers")
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    @property
    def rank(self):
        return ROLE_RANK.get(self.role, 0)

    def at_least(self, role):
        return self.rank >= ROLE_RANK[str(role)]


def hash_token(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


class Invitation(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    email = models.EmailField()
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.EMPLOYEE)
    employee = models.ForeignKey("people.Employee", null=True, blank=True, on_delete=models.SET_NULL)
    token_hash = models.CharField(max_length=64, unique=True)  # raw token is only ever emailed
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    invited_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def issue(cls, **kw):
        raw = secrets.token_urlsafe(32)
        inv = cls.objects.create(
            token_hash=hash_token(raw), expires_at=timezone.now() + timedelta(days=7), **kw
        )
        return inv, raw

    @property
    def usable(self):
        return self.accepted_at is None and self.expires_at > timezone.now()


class AuditQuerySet(models.QuerySet):
    def update(self, *a, **k):
        raise PermissionError("Audit records are append-only.")

    def delete(self):
        raise PermissionError("Audit records cannot be deleted.")


class AuditLog(models.Model):
    """Append-only at the ORM level; see docs/SECURITY.md for the DB-level hardening step."""

    organization = models.ForeignKey(Organization, null=True, on_delete=models.PROTECT, related_name="+")
    actor = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=64, db_index=True)
    target_type = models.CharField(max_length=64, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = AuditQuerySet.as_manager()

    class Meta:
        ordering = ["-id"]

    def save(self, *args, **kwargs):
        if self.pk:
            raise PermissionError("Audit records are append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Audit records cannot be deleted.")
