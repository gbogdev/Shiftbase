from django.conf import settings
from django.db import models
from django.db.models import F, Q

from people.models import Employee, OrgOwned


class LeaveType(OrgOwned):
    name = models.CharField(max_length=80)
    paid = models.BooleanField(default=True)
    annual_allowance_days = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)  # null = untracked
    requires_approval = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="uniq_leavetype_name")]


class LeaveStatus(models.TextChoices):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class LeaveRequest(OrgOwned):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="leave_requests")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT)
    start_date = models.DateField()  # inclusive, organization-local calendar dates
    end_date = models.DateField()
    reason = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=12, choices=LeaveStatus.choices, default=LeaveStatus.PENDING)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(end_date__gte=F("start_date")), name="leave_dates_ordered")]
        indexes = [models.Index(fields=["employee", "start_date"])]

    @property
    def days(self):
        return (self.end_date - self.start_date).days + 1
