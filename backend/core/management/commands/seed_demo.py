"""Creates a clearly fictional demo organization for local development. Never run in production."""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import Organization, User
from people.models import Department, Employee, Location, Position
from scheduling.models import Shift

PASSWORD = "demo-password-123"


class Command(BaseCommand):
    help = "Create a fictional demo organization (DEBUG only)."

    def handle(self, *a, **kw):
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs with DEBUG=true.")
        if Organization.objects.filter(name="Demo Cafe").exists():
            raise CommandError("Demo data already exists.")
        org = Organization.objects.create(name="Demo Cafe", timezone="Europe/London")
        loc = Location.objects.create(organization=org, name="High Street")
        dept = Department.objects.create(organization=org, name="Front of house")
        pos = Position.objects.create(organization=org, name="Barista")
        for email, role, name in [("owner@demo.test", "owner", "Olivia Owner"), ("manager@demo.test", "manager", "Marcus Manager"),
                                  ("staff@demo.test", "employee", "Elena Employee")]:
            u = User.objects.create_user(email, PASSWORD, name=name, organization=org, role=role)
            e = Employee.objects.create(organization=org, user=u, name=name, email=email, department=dept, position=pos,
                                        contracted_hours=30)
            e.locations.add(loc)
        monday = (timezone.now() - timedelta(days=timezone.now().weekday())).replace(hour=9, minute=0, second=0, microsecond=0)
        staff = Employee.objects.get(email="staff@demo.test")
        for d in range(5):
            Shift.objects.create(organization=org, location=loc, department=dept, position=pos, employee=staff if d % 2 == 0 else None,
                                 start=monday + timedelta(days=d), end=monday + timedelta(days=d, hours=8), break_minutes=30)
        self.stdout.write(f"Created Demo Cafe. Log in as owner@demo.test / manager@demo.test / staff@demo.test, password: {PASSWORD}")
