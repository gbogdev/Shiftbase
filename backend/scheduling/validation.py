"""Scheduling validation. Rules are plain functions registered in RULES.

A rule takes a Context and yields Issue objects. severity "error" blocks publishing;
"warning" is shown but does not block. To add an org- or country-specific rule, write a
function and append it to RULES (or wrap RULES per organization later).
"""
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta

from leave.models import LeaveRequest, LeaveStatus

from .models import Shift

ERROR, WARNING = "error", "warning"


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    message: str
    shift_id: int | None = None
    employee_id: int | None = None

    def as_dict(self):
        return asdict(self)


class Context:
    def __init__(self, org, shifts, extra_shifts_for=None):
        self.org = org
        self.shifts = list(shifts)
        self._by_emp = {}
        self._extra = extra_shifts_for

    def neighbours(self, shift):
        """All of the employee's other shifts that could interact (+-8 days) - published or draft."""
        key = shift.employee_id
        if key not in self._by_emp:
            self._by_emp[key] = list(
                Shift.objects.filter(
                    employee_id=key,
                    start__gte=shift.start - timedelta(days=8),
                    start__lte=shift.end + timedelta(days=8),
                ).order_by("start")
            )
        return [s for s in self._by_emp[key] if s.pk != shift.pk]


def overlap(ctx):
    for s in ctx.shifts:
        if not s.employee_id:
            continue
        for o in ctx.neighbours(s):
            if o.start < s.end and s.start < o.end:
                yield Issue(ERROR, "overlap", "Overlaps another shift for this employee.", s.pk, s.employee_id)
                break


def leave_conflict(ctx):
    tz = ctx.org.tz
    for s in ctx.shifts:
        if not s.employee_id:
            continue
        d1, d2 = s.start.astimezone(tz).date(), s.end.astimezone(tz).date()
        if LeaveRequest.objects.filter(
            employee_id=s.employee_id, status=LeaveStatus.APPROVED, start_date__lte=d2, end_date__gte=d1
        ).exists():
            yield Issue(ERROR, "leave", "Employee has approved leave on this date.", s.pk, s.employee_id)


def qualifications(ctx):
    for s in ctx.shifts:
        if not s.employee_id:
            continue
        need = set(s.required_qualifications.values_list("id", flat=True))
        have = set(s.employee.qualifications.values_list("id", flat=True))
        if need - have:
            yield Issue(ERROR, "qualification", "Employee lacks a required qualification.", s.pk, s.employee_id)


def availability(ctx):
    """Checks the shift's start day only (overnight shifts are checked up to midnight)."""
    tz = ctx.org.tz
    sev = ERROR if ctx.org.availability_blocks_publish else WARNING
    for s in ctx.shifts:
        if not s.employee_id:
            continue
        ls, le = s.start.astimezone(tz), s.end.astimezone(tz)
        t0 = ls.time().replace(tzinfo=None)
        t1 = le.time().replace(tzinfo=None) if le.date() == ls.date() else time.max
        rows = [r for r in s.employee.availability.all() if r.weekday == ls.weekday()]
        blocked = any(not r.available and r.start_time < t1 and t0 < r.end_time for r in rows)
        windows = [r for r in rows if r.available]
        outside = bool(windows) and not any(r.start_time <= t0 and t1 <= r.end_time for r in windows)
        if blocked or outside:
            yield Issue(sev, "unavailable", "Employee is marked unavailable at this time.", s.pk, s.employee_id)


def rest_period(ctx):
    need = timedelta(hours=float(ctx.org.min_rest_hours))
    for s in ctx.shifts:
        if not s.employee_id:
            continue
        for o in ctx.neighbours(s):
            gap = (s.start - o.end) if o.end <= s.start else (o.start - s.end) if s.end <= o.start else None
            if gap is not None and gap < need:
                yield Issue(WARNING, "rest", f"Less than {ctx.org.min_rest_hours}h rest between shifts.", s.pk, s.employee_id)
                break


def weekly_hours(ctx):
    seen = set()
    limit = float(ctx.org.max_weekly_hours)
    tz = ctx.org.tz
    ws = ctx.org.week_start
    for s in ctx.shifts:
        if not s.employee_id:
            continue
        local = s.start.astimezone(tz)
        monday = (local - timedelta(days=(local.weekday() - ws) % 7)).date()
        if (s.employee_id, monday) in seen:
            continue
        seen.add((s.employee_id, monday))
        lo = datetime.combine(monday, datetime.min.time(), tzinfo=tz)
        hi = datetime.combine(monday + timedelta(days=7), datetime.min.time(), tzinfo=tz)
        total = sum(
            x.hours for x in Shift.objects.filter(employee_id=s.employee_id, start__gte=lo, start__lt=hi)
        )
        if total > limit:
            yield Issue(WARNING, "weekly_hours", f"{total:.1f}h scheduled this week (limit {limit:g}h).", s.pk, s.employee_id)


def open_shifts(ctx):
    for s in ctx.shifts:
        if not s.employee_id:
            yield Issue(WARNING, "unstaffed", "Shift has no employee assigned (open shift).", s.pk)


RULES = [overlap, leave_conflict, qualifications, availability, rest_period, weekly_hours, open_shifts]


def validate(org, shifts):
    ctx = Context(org, shifts)
    return [i for rule in RULES for i in rule(ctx)]


def validate_assignment(shift, employee):
    """Dry-run: issues if `employee` were assigned to `shift` (not saved)."""
    original = shift.employee_id
    shift.employee = employee
    try:
        return validate(shift.organization, [shift])
    finally:
        shift.employee_id = original
