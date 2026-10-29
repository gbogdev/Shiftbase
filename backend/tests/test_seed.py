import pytest
from django.core.management import CommandError, call_command
from django.test import override_settings

from attendance.models import TimeEntry
from core.models import User
from leave.models import LeaveRequest
from people.models import Employee
from scheduling.models import OpenShiftApplication, Shift, SwapRequest

pytestmark = pytest.mark.django_db


@override_settings(DEBUG=True)
def test_seed_demo_populates_everything():
    call_command("seed_demo")
    assert Employee.objects.count() == 10
    assert User.objects.filter(role="employee").count() == 10
    assert Shift.objects.filter(status="draft").exists() and Shift.objects.filter(status="published").exists()
    assert Shift.objects.filter(employee__isnull=True).exists()
    assert LeaveRequest.objects.filter(status="pending").exists() and SwapRequest.objects.exists()
    assert OpenShiftApplication.objects.exists() and TimeEntry.objects.exists()
    with pytest.raises(CommandError):
        call_command("seed_demo")  # refuses to run twice
