from django.conf import settings
from django.db import models
from django.db.models import F, Q

from people.models import Employee, OrgOwned
from scheduling.models import Shift


class EntryStatus(models.TextChoices):
    OPEN = "open"
    SUBMITTED = "submitted"
    APPROVED = "approved"


class TimeEntry(OrgOwned):
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="time_entries")
    shift = models.ForeignKey(Shift, null=True, blank=True, on_delete=models.SET_NULL)
    clock_in = models.DateTimeField()
    clock_out = models.DateTimeField(null=True, blank=True)
    break_minutes = models.PositiveSmallIntegerField(default=0)
    break_started_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=EntryStatus.choices, default=EntryStatus.OPEN)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            # At most one open (not clocked-out) entry per employee, enforced by the database.
            models.UniqueConstraint(fields=["employee"], condition=Q(clock_out__isnull=True), name="one_open_entry"),
            models.CheckConstraint(
                condition=Q(clock_out__isnull=True) | Q(clock_out__gte=F("clock_in")), name="entry_out_after_in"
            ),
        ]
        indexes = [models.Index(fields=["organization", "clock_in"])]

    @property
    def worked_hours(self):
        if not self.clock_out:
            return 0
        return max((self.clock_out - self.clock_in).total_seconds() / 3600 - self.break_minutes / 60, 0)


class TimeCorrection(models.Model):
    """Immutable record of every manager correction: original values, new values, actor, reason."""

    entry = models.ForeignKey(TimeEntry, on_delete=models.CASCADE, related_name="corrections")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    reason = models.CharField(max_length=500)
    old_values = models.JSONField()
    new_values = models.JSONField()
    at = models.DateTimeField(auto_now_add=True)
