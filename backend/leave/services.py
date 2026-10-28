from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core import audit
from core.errors import Conflict
from notifications.services import notify
from people.models import Employee, EmploymentStatus
from scheduling.models import Shift

from .models import LeaveRequest, LeaveStatus


def days_used(employee, leave_type, year):
    total = 0
    for r in LeaveRequest.objects.filter(
        employee=employee, leave_type=leave_type, status=LeaveStatus.APPROVED, start_date__year=year
    ):
        total += r.days
    return total


@transaction.atomic
def request_leave(employee, leave_type, start_date, end_date, reason=""):
    if leave_type.organization_id != employee.organization_id:
        raise ValidationError("Unknown leave type.")
    if end_date < start_date:
        raise ValidationError("End date is before start date.")
    if LeaveRequest.objects.filter(
        employee=employee, status__in=[LeaveStatus.PENDING, LeaveStatus.APPROVED],
        start_date__lte=end_date, end_date__gte=start_date,
    ).exists():
        raise Conflict("You already have leave requested for these dates.")
    req = LeaveRequest.objects.create(
        organization_id=employee.organization_id, employee=employee, leave_type=leave_type,
        start_date=start_date, end_date=end_date, reason=reason,
        status=LeaveStatus.PENDING if leave_type.requires_approval else LeaveStatus.APPROVED,
    )
    if not leave_type.requires_approval:
        audit.record(None, "leave.auto_approve", req, org=employee.organization)
    return req


def staffing_warnings(req):
    """Per day of the request: how many other active same-department employees are not on approved leave."""
    org, out = req.employee.organization, []
    if not req.employee.department_id:
        return out
    colleagues = Employee.objects.filter(
        organization=org, department=req.employee.department, status=EmploymentStatus.ACTIVE
    ).exclude(pk=req.employee_id)
    day = req.start_date
    while day <= req.end_date:
        away = LeaveRequest.objects.filter(
            employee__in=colleagues, status=LeaveStatus.APPROVED, start_date__lte=day, end_date__gte=day
        ).values("employee").distinct().count()
        left = colleagues.count() - away
        if left < org.leave_min_staff_warning:
            out.append({"date": day.isoformat(), "available_colleagues": left})
        day += timedelta(days=1)
    return out


def affected_shifts(req):
    tz = req.employee.organization.tz
    lo = datetime.combine(req.start_date, datetime.min.time(), tzinfo=tz)
    hi = datetime.combine(req.end_date + timedelta(days=1), datetime.min.time(), tzinfo=tz)
    return Shift.objects.filter(employee=req.employee, start__gte=lo, start__lt=hi)


@transaction.atomic
def decide_leave(actor, req_id, approve, note=""):
    req = (
        LeaveRequest.objects.select_for_update(of=("self",))
        .select_related("employee__user", "employee__organization", "leave_type")
        .get(pk=req_id, organization=actor.organization)
    )
    if req.status != LeaveStatus.PENDING:
        raise Conflict("Request has already been decided.")
    if req.employee.user_id == actor.pk:
        raise ValidationError("You cannot decide your own request.")
    from core.access import can_manage_employee

    if not can_manage_employee(actor, req.employee):
        raise PermissionError
    if approve:
        allowance = req.leave_type.annual_allowance_days
        if allowance is not None and days_used(req.employee, req.leave_type, req.start_date.year) + req.days > allowance:
            raise Conflict("Approving would exceed the leave allowance.")
    req.status = LeaveStatus.APPROVED if approve else LeaveStatus.REJECTED
    req.decided_by, req.decided_at, req.decision_note = actor, timezone.now(), note
    req.save()
    warnings = staffing_warnings(req) if approve else []
    audit.record(actor, "leave.approve" if approve else "leave.reject", req, note=note, warnings=len(warnings))
    notify(req.employee.user, "request_decision", f"Leave {req.status}", note, f"leave:{req.pk}:{req.status}")
    return req, warnings, list(affected_shifts(req).values_list("id", flat=True)) if approve else []


@transaction.atomic
def cancel_leave(employee, req_id):
    req = LeaveRequest.objects.select_for_update().get(pk=req_id, employee=employee)
    if req.status not in (LeaveStatus.PENDING,):
        raise Conflict("Only pending requests can be cancelled.")
    req.status = LeaveStatus.CANCELLED
    req.save()
    return req


__all__ = ["request_leave", "decide_leave", "cancel_leave", "staffing_warnings", "days_used", "Q"]
