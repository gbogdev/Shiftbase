from datetime import datetime
from datetime import timezone as dtz

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from core.models import Organization, User
from people.models import Department, Employee, Location, Position

PW = "correct-horse-battery-1"


def utc(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=dtz.utc)


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()


class World:
    """Two organizations with one user per role in org A and an employee in org B."""

    def __init__(self):
        self.org = Organization.objects.create(name="Harbor Cafe", timezone="Europe/London")
        self.other = Organization.objects.create(name="Northside Bakery", timezone="America/New_York")
        self.loc = Location.objects.create(organization=self.org, name="Main St")
        self.loc2 = Location.objects.create(organization=self.org, name="Pier")
        self.dept = Department.objects.create(organization=self.org, name="Kitchen")
        self.dept2 = Department.objects.create(organization=self.org, name="Front")
        self.pos = Position.objects.create(organization=self.org, name="Cook")
        self.owner = self.user("owner@harbor.test", "owner", "Olive Owner")
        self.admin = self.user("admin@harbor.test", "admin", "Adam Admin")
        self.manager = self.user("manager@harbor.test", "manager", "Maya Manager")
        self.emp_user = self.user("ella@harbor.test", "employee", "Ella Employee")
        self.emp_user2 = self.user("sam@harbor.test", "employee", "Sam Staff")
        self.ella = self.employee(self.emp_user)
        self.sam = self.employee(self.emp_user2)
        self.ob_admin = User.objects.create_user("admin@north.test", PW, name="Nora Admin", organization=self.other, role="admin")
        self.ob_emp = Employee.objects.create(organization=self.other, name="Ned North", email="ned@north.test")
        self.ob_loc = Location.objects.create(organization=self.other, name="Dock")

    def user(self, email, role, name):
        return User.objects.create_user(email, PW, name=name, organization=self.org, role=role)

    def employee(self, user):
        e = Employee.objects.create(organization=self.org, user=user, name=user.name, email=user.email,
                                    department=self.dept, position=self.pos)
        e.locations.add(self.loc)
        return e

    def client(self, user):
        c = APIClient()
        c.force_login(user)
        return c


@pytest.fixture
def w(db):
    return World()


@pytest.fixture
def mk_shift(w):
    from scheduling.models import Shift

    def make(employee=None, start=None, end=None, status="draft", **kw):
        return Shift.objects.create(organization=w.org, location=kw.pop("location", w.loc), employee=employee,
                                    start=start or utc(2026, 3, 2, 9), end=end or utc(2026, 3, 2, 17),
                                    status=status, **kw)

    return make
