"""Creates a clearly fictional demo organization for local development. Never run in production."""
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from attendance.models import EntryStatus, TimeCorrection, TimeEntry
from core import audit
from core.models import Organization, User
from leave.models import LeaveRequest, LeaveStatus, LeaveType
from notifications.models import Notification
from people.models import Availability, Department, Employee, Location, Position, Qualification
from scheduling.models import OpenShiftApplication, Shift, ShiftChange, SwapRequest

PASSWORD = "demo-password-123"
TZ = ZoneInfo("Europe/London")

# name, department, position, qualifications, hourly rate
PEOPLE = [
    ("Employee 1", "Front of house", "Barista", [], 13.5),
    ("Employee 2", "Front of house", "Barista", [], 12.75),
    ("Employee 3", "Kitchen", "Cook", ["Food hygiene"], 15.0),
    ("Employee 4", "Kitchen", "Cook", ["Food hygiene"], 14.5),
    ("Employee 5", "Front of house", "Server", [], 12.5),
    ("Employee 6", "Front of house", "Server", ["First aid"], 12.5),
    ("Employee 7", "Kitchen", "Kitchen assistant", ["Food hygiene"], 11.8),
    ("Employee 8", "Front of house", "Barista", ["First aid"], 12.75),
    ("Employee 9", "Front of house", "Server", [], 12.5),
    ("Employee 10", "Kitchen", "Cook", ["Food hygiene", "First aid"], 15.5),
]
PATTERNS = {
    "Barista": [("07:00", "15:00"), ("12:00", "20:00")],
    "Server": [("11:00", "19:00"), ("16:00", "23:00")],
    "Cook": [("10:00", "18:00"), ("14:00", "22:00")],
    "Kitchen assistant": [("09:00", "17:00")],
}


def at(day, hm):
    h, m = map(int, hm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=TZ)


class Command(BaseCommand):
    help = "Create a fictional demo organization with 10 employees and a few weeks of activity (DEBUG only)."

    @transaction.atomic
    def handle(self, *a, **kw):
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs with DEBUG=true.")
        if Organization.objects.filter(name="Demo Cafe").exists():
            raise CommandError("Demo data already exists.")
        rng = random.Random(7)
        now = timezone.now()
        today = now.astimezone(TZ).date()
        monday = today - timedelta(days=today.weekday())

        org = Organization.objects.create(name="Demo Cafe", timezone="Europe/London")
        hs = Location.objects.create(organization=org, name="High Street", address="12 High Street")
        rv = Location.objects.create(organization=org, name="Riverside", address="3 Quay Walk")
        depts = {n: Department.objects.create(organization=org, name=n) for n in ("Front of house", "Kitchen")}
        poss = {n: Position.objects.create(organization=org, name=n) for n in PATTERNS}
        quals = {n: Qualification.objects.create(organization=org, name=n) for n in ("Food hygiene", "First aid")}
        annual = LeaveType.objects.create(organization=org, name="Annual leave", annual_allowance_days=25)
        sick = LeaveType.objects.create(organization=org, name="Sick leave", requires_approval=False)
        unpaid = LeaveType.objects.create(organization=org, name="Unpaid leave", paid=False)

        owner = User.objects.create_user("owner@demo.test", PASSWORD, name="Olivia Owner", organization=org, role="owner")
        manager = User.objects.create_user("manager@demo.test", PASSWORD, name="Marcus Manager", organization=org, role="manager")

        emps = []
        for i, (name, dept, pos, qs, rate) in enumerate(PEOPLE):
            email = name.replace(" ", "").lower() + "@demo.test"
            user = User.objects.create_user(email, PASSWORD, name=name, organization=org, role="employee")
            e = Employee.objects.create(organization=org, user=user, name=name, email=email, department=depts[dept],
                                        position=poss[pos], contracted_hours=[20, 24, 32, 36, 40][i % 5], hourly_rate=rate,
                                        start_date=today - timedelta(days=200 + 37 * i))
            e.locations.add(hs if i % 2 == 0 else rv)
            if i in (2, 5, 9):
                e.locations.add(rv if i % 2 == 0 else hs)
            e.qualifications.set([quals[q] for q in qs])
            emps.append(e)
        by_name = {e.name.split()[-1]: e for e in emps}

        # --- shifts: last week, this week, next week; 5 days each, one day-pair off per person ---
        shifts = {}  # (employee index, date) -> Shift
        for week in (-1, 0, 1):
            for i, e in enumerate(emps):
                loc = e.locations.order_by("id").first()
                pattern = PATTERNS[e.position.name]
                for d in range(7):
                    if d in (i % 7, (i + 1) % 7):
                        continue
                    day = monday + timedelta(days=7 * week + d)
                    s, t = pattern[(i + d) % len(pattern)]
                    published = week < 1 or d <= 3  # next week: Mon-Thu published, Fri-Sun still draft
                    sh = Shift.objects.create(
                        organization=org, location=loc, department=e.department, position=e.position, employee=e,
                        start=at(day, s), end=at(day, t), break_minutes=30, status="published" if published else "draft",
                        published_at=now - timedelta(days=3) if published else None)
                    if e.position.name == "Cook":
                        sh.required_qualifications.add(quals["Food hygiene"])
                    shifts[(i, day)] = sh
        next_mon = monday + timedelta(days=7)
        for day, s, t, loc, pos, status in [
            (next_mon + timedelta(days=2), "12:00", "20:00", hs, "Barista", "published"),
            (next_mon + timedelta(days=3), "16:00", "23:00", rv, "Server", "published"),
            (next_mon + timedelta(days=4), "10:00", "18:00", hs, "Cook", "draft"),
            (today + timedelta(days=2), "12:00", "20:00", rv, "Server", "published"),
        ]:
            Shift.objects.create(organization=org, location=loc, department=depts["Kitchen" if pos == "Cook" else "Front of house"],
                                 position=poss[pos], start=at(day, s), end=at(day, t), break_minutes=30, status=status,
                                 published_at=now - timedelta(days=2) if status == "published" else None)
        open_shifts = list(Shift.objects.filter(organization=org, employee__isnull=True, status="published", start__gt=now).order_by("start"))

        def nxt(name, skip=0):
            """First published shift next week for this person (their days off differ)."""
            i = [p[0].split()[-1] for p in PEOPLE].index(name)
            found = [shifts[(i, next_mon + timedelta(days=d))] for d in range(4) if (i, next_mon + timedelta(days=d)) in shifts]
            return found[skip] if len(found) > skip else None

        # one published shift edited after publishing (shows the "changed" flag and history)
        changed = nxt("10", 1)
        if changed:
            before = {"end": changed.end.isoformat()}
            changed.end += timedelta(hours=1)
            changed.version, changed.modified_since_publish = 2, True
            changed.save()
            ShiftChange.objects.create(shift=changed, actor=manager, kind="edited", before=before, after={"end": changed.end.isoformat()})

        # --- availability ---
        Availability.objects.create(employee=by_name["2"], weekday=2, start_time="16:00", end_time="23:59", available=False)
        Availability.objects.create(employee=by_name["5"], weekday=5, start_time="00:00", end_time="23:59", available=False)
        for wd in range(5):
            Availability.objects.create(employee=by_name["8"], weekday=wd, start_time="06:00", end_time="16:00", available=True)

        # --- leave ---
        def leave(emp, lt, d1, d2, status, reason="", note=""):
            r = LeaveRequest.objects.create(organization=org, employee=emp, leave_type=lt, start_date=d1, end_date=d2, reason=reason,
                                            status=status, decision_note=note)
            if status in (LeaveStatus.APPROVED, LeaveStatus.REJECTED) and lt.requires_approval:
                r.decided_by, r.decided_at = manager, now - timedelta(days=2)
                r.save()
            return r

        far = monday + timedelta(days=21)
        leave(by_name["3"], annual, far, far + timedelta(days=4), "approved", "Family holiday", "Enjoy!")
        leave(by_name["2"], annual, far + timedelta(days=1), far + timedelta(days=2), "pending", "Moving house")
        leave(by_name["9"], annual, far + timedelta(days=7), far + timedelta(days=13), "pending", "Trip abroad")
        leave(by_name["6"], unpaid, far + timedelta(days=2), far + timedelta(days=3), "rejected", "Concert", "Too many people already off that week.")
        chloe_off = monday - timedelta(days=7) + timedelta(days=4 % 7)  # a day she has no shift last week
        leave(by_name["5"], sick, chloe_off, chloe_off, "approved", "Migraine")
        leave(by_name["10"], annual, far + timedelta(days=3), far + timedelta(days=3), "pending", "Appointment")

        # --- swaps and open-shift applications (next week's published shifts) ---
        if (a := nxt("1")) and (b := by_name["2"]):
            SwapRequest.objects.create(organization=org, shift=a, from_employee=by_name["1"], to_employee=b)
        if a := nxt("3"):
            SwapRequest.objects.create(organization=org, shift=a, from_employee=by_name["3"])
        if a := nxt("4"):
            SwapRequest.objects.create(organization=org, shift=a, from_employee=by_name["4"], to_employee=by_name["10"], status="accepted")
        if len(open_shifts) >= 2:
            for who, sh in [("8", open_shifts[0]), ("9", open_shifts[0]), ("7", open_shifts[1])]:
                OpenShiftApplication.objects.create(organization=org, shift=sh, employee=by_name[who])

        # --- time entries for shifts that have started ---
        skip_today = by_name["9"]
        for (i, day), sh in sorted(shifts.items(), key=lambda kv: kv[1].start):
            if sh.status != "published" or sh.start > now:
                continue
            e = emps[i]
            late = rng.random() < 0.12
            cin = sh.start + timedelta(minutes=rng.randint(10, 25) if late else rng.randint(-4, 3))
            in_progress = sh.end > now
            if in_progress and e == skip_today:
                continue
            if in_progress:
                TimeEntry.objects.create(organization=org, employee=e, shift=sh, clock_in=min(cin, now - timedelta(minutes=1)))
                continue
            cout = sh.end + timedelta(minutes=rng.randint(-5, 12))
            if e == skip_today and day == today - timedelta(days=1):
                TimeEntry.objects.create(organization=org, employee=e, shift=sh, clock_in=cin)  # forgot to clock out
                continue
            last_week = day < monday
            entry = TimeEntry.objects.create(
                organization=org, employee=e, shift=sh, clock_in=cin, clock_out=cout, break_minutes=30,
                status=EntryStatus.APPROVED if last_week else (EntryStatus.SUBMITTED if rng.random() < 0.7 else EntryStatus.OPEN),
                approved_by=manager if last_week else None, approved_at=now - timedelta(days=1) if last_week else None)
            if not last_week and entry.status == EntryStatus.SUBMITTED and not TimeCorrection.objects.exists():
                old = {"clock_in": cin.isoformat(), "clock_out": cout.isoformat(), "break_minutes": 30}
                entry.break_minutes = 45
                entry.save()
                TimeCorrection.objects.create(entry=entry, actor=manager, reason="Employee reported a longer lunch break",
                                              old_values=old, new_values={**old, "break_minutes": 45})
                audit.record(manager, "timesheet.correct", entry, old=old, reason="Employee reported a longer lunch break")

        # --- notifications and audit trail ---
        for i, e in enumerate(emps):
            Notification.objects.create(user=e.user, kind="schedule_published", title="New schedule published",
                                        body="Your shifts for next week are published.", dedupe_key="seed-publish",
                                        read_at=now if i % 3 == 0 else None)
        for key, title, body in [("seed-l", "Late arrival", "A team member clocked in late."),
                                 ("seed-m", "Missed clock-out", "Employee 9 has not clocked out."),
                                 ("seed-p", "Leave request", "3 leave requests are waiting for a decision.")]:
            Notification.objects.create(user=manager, kind="attendance_issue", title=title, body=body, dedupe_key=key)
        audit.record(manager, "schedule.publish", hs, count=35)
        audit.record(owner, "org.settings", org, changed=["max_weekly_hours"])

        self.stdout.write(f"Created Demo Cafe: 10 employees, {Shift.objects.count()} shifts, {LeaveRequest.objects.count()} leave requests, "
                          f"{SwapRequest.objects.count()} swaps, {TimeEntry.objects.count()} time entries.")
        self.stdout.write(f"Logins (password {PASSWORD}): owner@demo.test, manager@demo.test, and employees such as employee1@demo.test, employee2@demo.test.")
