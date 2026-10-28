"""Scheduling workflows. All state changes run in transactions and lock the rows they decide on."""
import uuid
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core import audit
from core.errors import Conflict
from notifications.services import notify
from people.models import Employee, EmploymentStatus

from .models import (
    OpenShiftApplication,
    RequestStatus,
    ScheduleTemplate,
    Shift,
    ShiftChange,
    ShiftStatus,
    SwapRequest,
)
from .validation import ERROR, validate, validate_assignment

TRACKED = ("employee_id", "start", "end", "break_minutes", "location_id", "notes")


def snapshot(shift):
    return {f: (getattr(shift, f).isoformat() if hasattr(getattr(shift, f), "isoformat") else getattr(shift, f)) for f in TRACKED}


def _user_of(employee):
    return employee.user if employee and employee.user_id else None


def _check_employee(org, employee):
    if employee is None:
        return
    if employee.organization_id != org.id:
        raise ValidationError("Employee belongs to another organization.")
    if employee.status != EmploymentStatus.ACTIVE:
        raise ValidationError("Employee is not active.")


@transaction.atomic
def save_shift(actor, shift, expected_version=None, **fields):
    """Create or edit a shift. Edits to published shifts are flagged and logged and notify the employee."""
    org = actor.organization
    if shift.pk:
        shift = Shift.objects.select_for_update().get(pk=shift.pk, organization=org)
        if expected_version is not None and shift.version != expected_version:
            raise Conflict("Shift was changed by someone else. Reload and try again.")
    before = snapshot(shift) if shift.pk else {}
    old_emp = shift.employee if shift.pk else None
    quals = fields.pop("required_qualifications", None)
    for k, v in fields.items():
        setattr(shift, k, v)
    shift.organization = org
    if shift.end <= shift.start:
        raise ValidationError("Shift must end after it starts.")
    _check_employee(org, shift.employee)
    for fk in ("location", "department", "position"):
        obj = getattr(shift, fk)
        if obj is not None and obj.organization_id != org.id:
            raise ValidationError(f"{fk} belongs to another organization.")
    creating = shift.pk is None
    if not creating:
        shift.version += 1
        if shift.status == ShiftStatus.PUBLISHED:
            shift.modified_since_publish = True
    shift.save()
    if quals is not None:
        shift.required_qualifications.set([q for q in quals if q.organization_id == org.id])
    after = snapshot(shift)
    ShiftChange.objects.create(shift=shift, actor=actor, kind="created" if creating else "edited", before=before, after=after)
    audit.record(actor, "shift.create" if creating else "shift.edit", shift, before=before, after=after)
    if not creating and shift.status == ShiftStatus.PUBLISHED:
        for emp in {old_emp, shift.employee} - {None}:
            notify(_user_of(emp), "shift_changed", "Your shift was changed",
                   f"Shift on {shift.start:%Y-%m-%d %H:%M} UTC was updated.", f"shift-changed:{shift.pk}:{shift.version}")
    return shift


@transaction.atomic
def delete_shift(actor, shift):
    shift = Shift.objects.select_for_update().get(pk=shift.pk, organization=actor.organization)
    audit.record(actor, "shift.delete", shift, before=snapshot(shift))
    if shift.status == ShiftStatus.PUBLISHED:
        notify(_user_of(shift.employee), "shift_changed", "A shift was removed",
               f"Shift on {shift.start:%Y-%m-%d %H:%M} UTC was cancelled.", f"shift-deleted:{shift.pk}")
    shift.delete()


@transaction.atomic
def duplicate_shift(actor, shift, days=0, employee=None):
    return save_shift(
        actor,
        Shift(location=shift.location),
        department=shift.department, position=shift.position, employee=employee,
        start=shift.start + timedelta(days=days), end=shift.end + timedelta(days=days),
        break_minutes=shift.break_minutes, notes=shift.notes,
        required_qualifications=list(shift.required_qualifications.all()),
    )


@transaction.atomic
def create_recurring(actor, base: dict, weekdays, until):
    """Create one shift per matching local date from base.start's date to `until` (inclusive)."""
    tz = actor.organization.tz
    first, last = base["start"].astimezone(tz), base["end"].astimezone(tz)
    span = last - first
    day, out, series = first.date(), [], uuid.uuid4()
    if (until - day).days > 366:
        raise ValidationError("Recurrence is limited to one year.")
    while day <= until:
        if day.weekday() in weekdays:
            start = datetime.combine(day, first.time(), tzinfo=tz)  # re-anchored in local time: DST-safe
            out.append(save_shift(actor, Shift(series_id=series), **{**base, "start": start, "end": start + span}))
        day += timedelta(days=1)
    return out


@transaction.atomic
def apply_template(actor, template: ScheduleTemplate, week_start_date):
    tz = actor.organization.tz
    out = []
    for row in template.shifts:
        day = week_start_date + timedelta(days=row["weekday"])
        sh, sm = map(int, row["start"].split(":"))
        eh, em = map(int, row["end"].split(":"))
        start = datetime(day.year, day.month, day.day, sh, sm, tzinfo=tz)
        end_day = day + timedelta(days=1) if (eh, em) <= (sh, sm) else day
        end = datetime(end_day.year, end_day.month, end_day.day, eh, em, tzinfo=tz)
        out.append(save_shift(actor, Shift(), location=template.location, start=start, end=end,
                              break_minutes=row.get("break_minutes", 0),
                              department_id=row.get("department"), position_id=row.get("position")))
    return out


@transaction.atomic
def publish(actor, location, start, end, force_warnings=True):
    """Publish draft shifts for a location/date range. Blocking errors abort; warnings are returned."""
    org = actor.organization
    shifts = list(
        Shift.objects.select_for_update(of=("self",))
        .filter(organization=org, location=location, status=ShiftStatus.DRAFT, start__gte=start, start__lt=end)
        .select_related("employee")
    )
    issues = validate(org, shifts)
    errors = [i.as_dict() for i in issues if i.severity == ERROR]
    if errors:
        raise Conflict("Schedule has blocking conflicts.", errors)
    now = timezone.now()
    for s in shifts:
        s.status, s.published_at, s.modified_since_publish = ShiftStatus.PUBLISHED, now, False
        s.save(update_fields=["status", "published_at", "modified_since_publish"])
    audit.record(actor, "schedule.publish", location, count=len(shifts), start=start.isoformat(), end=end.isoformat())
    for emp_id in {s.employee_id for s in shifts if s.employee_id}:
        emp = Employee.objects.select_related("user").get(pk=emp_id)
        notify(_user_of(emp), "schedule_published", "New schedule published",
               f"Shifts from {start:%Y-%m-%d} to {end:%Y-%m-%d} are now published.",
               f"publish:{location.pk}:{start:%Y%m%d}:{end:%Y%m%d}:{now:%Y%m%d%H%M%S}")
    return {"published": len(shifts), "warnings": [i.as_dict() for i in issues]}


# ---------- employee self-service ----------

def _approve_needed(org, kind):
    return org.swaps_need_approval if kind == "swap" else org.open_shift_applications_need_approval


@transaction.atomic
def request_swap(employee, shift, to_employee=None):
    shift = Shift.objects.select_for_update().get(pk=shift.pk, organization_id=employee.organization_id)
    if shift.employee_id != employee.id:
        raise ValidationError("You can only offer your own shifts.")
    if shift.status != ShiftStatus.PUBLISHED or shift.start <= timezone.now():
        raise ValidationError("Only upcoming published shifts can be offered.")
    if to_employee and to_employee.organization_id != employee.organization_id:
        raise ValidationError("Unknown colleague.")
    if SwapRequest.objects.filter(shift=shift, status__in=["pending", "accepted"]).exists():
        raise Conflict("This shift already has an open swap request.")
    req = SwapRequest.objects.create(organization_id=employee.organization_id, shift=shift,
                                     from_employee=employee, to_employee=to_employee)
    if to_employee:
        notify(_user_of(to_employee), "swap_offered", "Shift swap offered", f"{employee.name} offered you a shift.", f"swap:{req.pk}:offer")
    return req


@transaction.atomic
def accept_swap(employee, req_id):
    req = SwapRequest.objects.select_for_update().get(pk=req_id, organization_id=employee.organization_id)
    if req.status != RequestStatus.PENDING:
        raise Conflict("Request is no longer open.")
    if req.to_employee_id and req.to_employee_id != employee.id:
        raise ValidationError("This offer is for someone else.")
    if employee.id == req.from_employee_id:
        raise ValidationError("You cannot accept your own offer.")
    req.to_employee, req.status = employee, RequestStatus.ACCEPTED
    req.save()
    org = employee.organization
    if not org.swaps_need_approval:
        return _complete_swap(req, None)
    return req


@transaction.atomic
def decide_swap(actor, req_id, approve, note=""):
    req = SwapRequest.objects.select_for_update().get(pk=req_id, organization=actor.organization)
    if req.status != RequestStatus.ACCEPTED:
        raise Conflict("Request is not awaiting a manager decision.")
    if not approve:
        req.status, req.decided_by, req.decided_at, req.note = RequestStatus.REJECTED, actor, timezone.now(), note
        req.save()
        audit.record(actor, "swap.reject", req)
        for e in (req.from_employee, req.to_employee):
            notify(_user_of(e), "request_decision", "Shift swap rejected", note, f"swap:{req.pk}:rejected")
        return req
    return _complete_swap(req, actor)


def _complete_swap(req, actor):
    shift = Shift.objects.select_for_update().get(pk=req.shift_id)
    if shift.employee_id != req.from_employee_id:
        raise Conflict("The shift is no longer assigned to the requester.")
    issues = [i for i in validate_assignment(shift, req.to_employee) if i.severity == ERROR]
    if issues:
        raise Conflict("Swap would create blocking conflicts.", [i.as_dict() for i in issues])
    shift.employee, shift.version = req.to_employee, shift.version + 1
    shift.modified_since_publish = True
    shift.save()
    ShiftChange.objects.create(shift=shift, actor=actor and actor, kind="swap",
                               before={"employee_id": req.from_employee_id}, after={"employee_id": req.to_employee_id})
    req.status, req.decided_by, req.decided_at = RequestStatus.APPROVED, actor, timezone.now()
    req.save()
    audit.record(actor, "swap.approve", req, shift=shift.pk, to=req.to_employee_id)
    for e in (req.from_employee, req.to_employee):
        notify(_user_of(e), "request_decision", "Shift swap approved", "", f"swap:{req.pk}:approved")
    return req


@transaction.atomic
def apply_open_shift(employee, shift):
    shift = Shift.objects.select_for_update().get(pk=shift.pk, organization_id=employee.organization_id)
    if shift.employee_id or shift.status != ShiftStatus.PUBLISHED:
        raise Conflict("Shift is not open.")
    if OpenShiftApplication.objects.filter(shift=shift, employee=employee, status="pending").exists():
        raise Conflict("You already applied.")
    app = OpenShiftApplication.objects.create(organization_id=employee.organization_id, shift=shift, employee=employee)
    if not employee.organization.open_shift_applications_need_approval:
        return _assign_application(app, None)
    return app


@transaction.atomic
def decide_application(actor, app_id, approve):
    app = OpenShiftApplication.objects.select_for_update().get(pk=app_id, organization=actor.organization)
    if app.status != RequestStatus.PENDING:
        raise Conflict("Application already decided.")
    if not approve:
        app.status, app.decided_by, app.decided_at = RequestStatus.REJECTED, actor, timezone.now()
        app.save()
        audit.record(actor, "application.reject", app)
        notify(_user_of(app.employee), "request_decision", "Open shift application rejected", "", f"app:{app.pk}:rejected")
        return app
    return _assign_application(app, actor)


def _assign_application(app, actor):
    shift = Shift.objects.select_for_update().get(pk=app.shift_id)
    if shift.employee_id:
        raise Conflict("Shift has already been filled.")
    issues = [i for i in validate_assignment(shift, app.employee) if i.severity == ERROR]
    if issues:
        raise Conflict("Assignment would create blocking conflicts.", [i.as_dict() for i in issues])
    shift.employee, shift.version, shift.modified_since_publish = app.employee, shift.version + 1, True
    shift.save()
    ShiftChange.objects.create(shift=shift, actor=actor, kind="open_shift_filled", before={"employee_id": None}, after={"employee_id": app.employee_id})
    now = timezone.now()
    app.status, app.decided_by, app.decided_at = RequestStatus.APPROVED, actor, now
    app.save()
    # Other applicants lose automatically.
    others = OpenShiftApplication.objects.filter(shift=shift, status="pending").exclude(pk=app.pk)
    for o in others.select_related("employee__user"):
        o.status, o.decided_by, o.decided_at = RequestStatus.REJECTED, actor, now
        o.save()
        notify(_user_of(o.employee), "request_decision", "Open shift was filled", "", f"app:{o.pk}:filled")
    audit.record(actor, "application.approve", app, shift=shift.pk)
    notify(_user_of(app.employee), "request_decision", "Open shift assigned to you", "", f"app:{app.pk}:approved")
    return app
