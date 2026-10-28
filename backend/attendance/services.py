import csv
import io
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from core import audit
from core.access import can_manage_employee
from core.errors import Conflict
from notifications.services import notify
from scheduling.models import Shift, ShiftStatus

from .models import EntryStatus, TimeCorrection, TimeEntry

LATE_GRACE = timedelta(minutes=5)
MISSED_CLOCK_OUT_AFTER = timedelta(hours=16)


def _matching_shift(employee, now):
    return (
        Shift.objects.filter(employee=employee, status=ShiftStatus.PUBLISHED,
                             start__lte=now + timedelta(hours=2), end__gte=now - timedelta(hours=2))
        .order_by("start").first()
    )


@transaction.atomic
def clock_in(employee, now=None):
    now = now or timezone.now()
    shift = _matching_shift(employee, now)
    try:
        with transaction.atomic():
            entry = TimeEntry.objects.create(organization_id=employee.organization_id, employee=employee,
                                             shift=shift, clock_in=now)
    except IntegrityError:
        raise Conflict("You are already clocked in.") from None
    if shift and now > shift.start + LATE_GRACE:
        for u in _managers_for(employee):
            notify(u, "attendance_issue", "Late arrival", f"{employee.name} clocked in late.", f"late:{entry.pk}")
    return entry


def _managers_for(employee):
    from core.models import Role, User

    return [u for u in User.objects.filter(organization_id=employee.organization_id, role__in=[Role.MANAGER, Role.ADMIN, Role.OWNER], is_active=True)
            if can_manage_employee(u, employee)]


def _open_entry(employee):
    entry = TimeEntry.objects.select_for_update().filter(employee=employee, clock_out__isnull=True).first()
    if not entry:
        raise Conflict("You are not clocked in.")
    return entry


@transaction.atomic
def start_break(employee, now=None):
    entry = _open_entry(employee)
    if entry.break_started_at:
        raise Conflict("Break already started.")
    entry.break_started_at = now or timezone.now()
    entry.save(update_fields=["break_started_at"])
    return entry


@transaction.atomic
def end_break(employee, now=None):
    entry = _open_entry(employee)
    if not entry.break_started_at:
        raise Conflict("No break in progress.")
    now = now or timezone.now()
    entry.break_minutes += int((now - entry.break_started_at).total_seconds() // 60)
    entry.break_started_at = None
    entry.save(update_fields=["break_minutes", "break_started_at"])
    return entry


@transaction.atomic
def clock_out(employee, now=None):
    entry = _open_entry(employee)
    now = now or timezone.now()
    if entry.break_started_at:
        entry.break_minutes += int((now - entry.break_started_at).total_seconds() // 60)
        entry.break_started_at = None
    entry.clock_out = now
    entry.save()
    return entry


def flag_missed_clock_outs(now=None):
    """Cron-safe: notifies managers once per entry (dedupe key) about entries open too long."""
    now = now or timezone.now()
    n = 0
    for e in TimeEntry.objects.filter(clock_out__isnull=True, clock_in__lt=now - MISSED_CLOCK_OUT_AFTER).select_related("employee"):
        for u in _managers_for(e.employee):
            if notify(u, "attendance_issue", "Missed clock-out", f"{e.employee.name} has not clocked out.", f"missed-out:{e.pk}:{u.pk}"):
                n += 1
    return n


@transaction.atomic
def correct_entry(actor, entry_id, reason, clock_in=None, clock_out=None, break_minutes=None):
    if not reason or not reason.strip():
        raise ValidationError("An explanation is required.")
    entry = TimeEntry.objects.select_for_update(of=("self",)).select_related("employee").get(pk=entry_id, organization=actor.organization)
    if not can_manage_employee(actor, entry.employee):
        raise PermissionError
    if entry.status == EntryStatus.APPROVED:
        raise Conflict("Approved entries cannot be corrected. Ask an administrator to reopen it.")
    old = {"clock_in": entry.clock_in.isoformat(), "clock_out": entry.clock_out.isoformat() if entry.clock_out else None,
           "break_minutes": entry.break_minutes}
    if clock_in is not None:
        entry.clock_in = clock_in
    if clock_out is not None:
        entry.clock_out = clock_out
        entry.break_started_at = None
    if break_minutes is not None:
        entry.break_minutes = break_minutes
    if entry.clock_out and entry.clock_out < entry.clock_in:
        raise ValidationError("Clock-out is before clock-in.")
    entry.save()
    new = {"clock_in": entry.clock_in.isoformat(), "clock_out": entry.clock_out.isoformat() if entry.clock_out else None,
           "break_minutes": entry.break_minutes}
    TimeCorrection.objects.create(entry=entry, actor=actor, reason=reason.strip(), old_values=old, new_values=new)
    audit.record(actor, "timesheet.correct", entry, old=old, new=new, reason=reason.strip())
    notify(entry.employee.user, "attendance_issue", "Your time record was corrected", reason.strip(), f"correct:{entry.pk}:{entry.corrections.count()}")
    return entry


@transaction.atomic
def submit_entries(employee, ids):
    qs = TimeEntry.objects.select_for_update().filter(employee=employee, pk__in=ids, status=EntryStatus.OPEN, clock_out__isnull=False)
    return qs.update(status=EntryStatus.SUBMITTED)


@transaction.atomic
def approve_entries(actor, ids):
    entries = list(TimeEntry.objects.select_for_update(of=("self",)).select_related("employee").filter(
        pk__in=ids, organization=actor.organization, status=EntryStatus.SUBMITTED, clock_out__isnull=False))
    now, done = timezone.now(), 0
    for e in entries:
        if e.employee.user_id == actor.pk or not can_manage_employee(actor, e.employee):
            continue  # nobody approves their own time; out-of-scope entries are skipped
        e.status, e.approved_by, e.approved_at = EntryStatus.APPROVED, actor, now
        e.save(update_fields=["status", "approved_by", "approved_at"])
        audit.record(actor, "timesheet.approve", e)
        done += 1
    return done


def _csv_safe(v):
    s = str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s  # spreadsheet formula injection


def export_csv(org, entries):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["employee", "email", "date", "clock_in_utc", "clock_out_utc", "break_minutes", "worked_hours", "hourly_rate"])
    for e in entries.select_related("employee"):
        local = e.clock_in.astimezone(org.tz).date().isoformat()
        w.writerow([_csv_safe(e.employee.name), _csv_safe(e.employee.email), local, e.clock_in.isoformat(),
                    e.clock_out.isoformat(), e.break_minutes, f"{e.worked_hours:.2f}", e.employee.hourly_rate or ""])
    return buf.getvalue()
