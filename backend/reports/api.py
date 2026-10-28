import csv
from collections import defaultdict
from datetime import datetime

from django.http import HttpResponse
from rest_framework.response import Response
from rest_framework.views import APIView

from attendance.models import TimeEntry
from core import audit
from core.access import IsManager, can_manage_employee, org_scoped, scope_rows
from leave.models import LeaveRequest, LeaveStatus
from scheduling.models import Shift, ShiftStatus

DISCREPANCY_MINUTES = 15


def _csv_safe(v):
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


class ReportView(APIView):
    permission_classes = [IsManager]

    def get(self, request, name):
        fn = REPORTS.get(name)
        if fn is None:
            return Response({"detail": "Unknown report."}, status=404)
        u, p = request.user, request.query_params
        if not (p.get("start") and p.get("end")):
            return Response({"detail": "start and end are required."}, status=400)
        start, end = datetime.fromisoformat(p["start"]), datetime.fromisoformat(p["end"])
        cols, rows = fn(u, start, end, p)
        if p.get("export") == "csv":
            audit.record(u, "report.export", report=name)
            resp = HttpResponse(content_type="text/csv")
            resp["Content-Disposition"] = f'attachment; filename="{name}.csv"'
            w = csv.writer(resp)
            w.writerow(cols)
            for r in rows:
                w.writerow([_csv_safe(v) for v in r])
            return resp
        return Response({"columns": cols, "rows": rows})


def _shifts(u, start, end, p):
    qs = scope_rows(org_scoped(Shift.objects.select_related("employee", "location", "department"), u), u)
    qs = qs.filter(start__gte=start, start__lt=end)
    for key, field in (("employee", "employee_id"), ("department", "department_id"), ("location", "location_id")):
        if p.get(key):
            qs = qs.filter(**{field: p[key]})
    return qs


def _visible_entries(u, start, end, p):
    qs = org_scoped(TimeEntry.objects.select_related("employee", "shift"), u).filter(
        clock_in__gte=start, clock_in__lt=end, clock_out__isnull=False)
    if p.get("employee"):
        qs = qs.filter(employee_id=p["employee"])
    if p.get("department"):
        qs = qs.filter(employee__department_id=p["department"])
    if p.get("location"):
        qs = qs.filter(employee__locations__id=p["location"]).distinct()
    return [e for e in qs if can_manage_employee(u, e.employee)]


def scheduled_hours(u, start, end, p):
    tot = defaultdict(float)
    for s in _shifts(u, start, end, p).filter(employee__isnull=False):
        tot[s.employee.name] += s.hours
    return ["employee", "scheduled_hours"], [[k, round(v, 2)] for k, v in sorted(tot.items())]


def worked_hours(u, start, end, p):
    tot = defaultdict(float)
    for e in _visible_entries(u, start, end, p):
        tot[e.employee.name] += e.worked_hours
    return ["employee", "worked_hours"], [[k, round(v, 2)] for k, v in sorted(tot.items())]


def absences(u, start, end, p):
    qs = org_scoped(LeaveRequest.objects.select_related("employee", "leave_type"), u).filter(
        status=LeaveStatus.APPROVED, start_date__lte=end.date(), end_date__gte=start.date())
    if p.get("employee"):
        qs = qs.filter(employee_id=p["employee"])
    if p.get("department"):
        qs = qs.filter(employee__department_id=p["department"])
    return ["employee", "type", "from", "to", "days"], [
        [r.employee.name, r.leave_type.name, r.start_date.isoformat(), r.end_date.isoformat(), r.days]
        for r in qs if can_manage_employee(u, r.employee)]


def overtime(u, start, end, p):
    limit = float(u.organization.max_weekly_hours)
    weeks = defaultdict(float)
    tz = u.organization.tz
    for s in _shifts(u, start, end, p).filter(employee__isnull=False):
        iso = s.start.astimezone(tz).isocalendar()
        weeks[(s.employee.name, f"{iso[0]}-W{iso[1]:02d}")] += s.hours
    return ["employee", "week", "scheduled_hours", "limit"], [
        [k[0], k[1], round(v, 2), limit] for k, v in sorted(weeks.items()) if v > limit]


def open_shifts(u, start, end, p):
    return ["date", "location", "start", "end", "status"], [
        [s.start.astimezone(u.organization.tz).date().isoformat(), s.location.name, s.start.isoformat(), s.end.isoformat(), s.status]
        for s in _shifts(u, start, end, p).filter(employee__isnull=True)]


def discrepancies(u, start, end, p):
    out = []
    for e in _visible_entries(u, start, end, p):
        if not e.shift_id:
            out.append([e.employee.name, e.clock_in.date().isoformat(), "unscheduled", round(e.worked_hours, 2), None])
            continue
        late = (e.clock_in - e.shift.start).total_seconds() / 60
        diff = e.worked_hours - e.shift.hours
        if late > 5 or abs(diff) * 60 > DISCREPANCY_MINUTES:
            out.append([e.employee.name, e.clock_in.date().isoformat(), f"late {late:.0f}m" if late > 5 else "hours differ",
                        round(e.worked_hours, 2), round(e.shift.hours, 2)])
    return ["employee", "date", "issue", "worked_hours", "scheduled_hours"], out


def coverage(u, start, end, p):
    days = defaultdict(lambda: [0, 0])
    tz = u.organization.tz
    for s in _shifts(u, start, end, p).filter(status=ShiftStatus.PUBLISHED):
        d = (s.location.name, s.start.astimezone(tz).date().isoformat())
        days[d][0 if s.employee_id else 1] += 1
    return ["location", "date", "staffed_shifts", "open_shifts"], [[k[0], k[1], v[0], v[1]] for k, v in sorted(days.items())]


def labor_cost(u, start, end, p):
    if not u.at_least("admin"):  # pay rates are admin-only
        return ["detail"], [["Labor cost reports require an administrator."]]
    tot = defaultdict(float)
    for e in _visible_entries(u, start, end, p):
        if e.employee.hourly_rate is not None:
            tot[e.employee.name] += e.worked_hours * float(e.employee.hourly_rate)
    return ["employee", "labor_cost"], [[k, round(v, 2)] for k, v in sorted(tot.items())]


REPORTS = {
    "scheduled-hours": scheduled_hours, "worked-hours": worked_hours, "absences": absences, "overtime": overtime,
    "open-shifts": open_shifts, "attendance-discrepancies": discrepancies, "coverage": coverage, "labor-cost": labor_cost,
}
