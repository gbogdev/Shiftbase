from django.conf import settings
from django.db import models
from django.db.models import F, Q

from people.models import Department, Employee, Location, OrgOwned, Position, Qualification


class ShiftStatus(models.TextChoices):
    DRAFT = "draft"
    PUBLISHED = "published"


class Shift(OrgOwned):
    location = models.ForeignKey(Location, on_delete=models.PROTECT)
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.PROTECT)
    position = models.ForeignKey(Position, null=True, blank=True, on_delete=models.PROTECT)
    employee = models.ForeignKey(Employee, null=True, blank=True, on_delete=models.PROTECT, related_name="shifts")
    start = models.DateTimeField()  # always stored in UTC
    end = models.DateTimeField()
    break_minutes = models.PositiveSmallIntegerField(default=0)
    notes = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=12, choices=ShiftStatus.choices, default=ShiftStatus.DRAFT)
    published_at = models.DateTimeField(null=True, blank=True)
    modified_since_publish = models.BooleanField(default=False)
    required_qualifications = models.ManyToManyField(Qualification, blank=True)
    series_id = models.UUIDField(null=True, blank=True)  # shifts created by one recurrence request
    version = models.PositiveIntegerField(default=1)  # optimistic concurrency token

    class Meta:
        indexes = [
            models.Index(fields=["organization", "start"]),
            models.Index(fields=["employee", "start"]),
        ]
        constraints = [models.CheckConstraint(condition=Q(end__gt=F("start")), name="shift_end_after_start")]
        ordering = ["start", "id"]

    @property
    def hours(self):
        return max((self.end - self.start).total_seconds() / 3600 - self.break_minutes / 60, 0)


class ShiftChange(models.Model):
    """History of edits. Lets the UI show which published shifts changed and how."""

    shift = models.ForeignKey(Shift, on_delete=models.CASCADE, related_name="changes")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    kind = models.CharField(max_length=24)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    at = models.DateTimeField(auto_now_add=True)


class ScheduleTemplate(OrgOwned):
    name = models.CharField(max_length=120)
    location = models.ForeignKey(Location, on_delete=models.CASCADE)
    # [{"weekday":0,"start":"09:00","end":"17:00","break_minutes":30,"department":id|null,"position":id|null}]
    shifts = models.JSONField(default=list)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="uniq_template_name")]


class RequestStatus(models.TextChoices):
    PENDING = "pending"  # waiting for the other employee (swap) or manager
    ACCEPTED = "accepted"  # peer accepted, waiting for manager
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class SwapRequest(OrgOwned):
    """to_employee set = direct swap offer; null = shift offered to anyone eligible."""

    shift = models.ForeignKey(Shift, on_delete=models.CASCADE, related_name="swap_requests")
    from_employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="+")
    to_employee = models.ForeignKey(Employee, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    status = models.CharField(max_length=12, choices=RequestStatus.choices, default=RequestStatus.PENDING)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class OpenShiftApplication(OrgOwned):
    shift = models.ForeignKey(Shift, on_delete=models.CASCADE, related_name="applications")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="+")
    status = models.CharField(max_length=12, choices=RequestStatus.choices, default=RequestStatus.PENDING)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["shift", "employee"], condition=Q(status="pending"), name="uniq_pending_application"
            )
        ]
