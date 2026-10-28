from django.conf import settings
from django.db import models


class OrgOwned(models.Model):
    organization = models.ForeignKey("core.Organization", on_delete=models.CASCADE, related_name="+")

    class Meta:
        abstract = True


class Location(OrgOwned):
    name = models.CharField(max_length=120)
    address = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="uniq_location_name")]

    def __str__(self):
        return self.name


class Department(OrgOwned):
    name = models.CharField(max_length=120)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="uniq_department_name")]

    def __str__(self):
        return self.name


class Position(OrgOwned):
    name = models.CharField(max_length=120)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="uniq_position_name")]

    def __str__(self):
        return self.name


class Qualification(OrgOwned):
    name = models.CharField(max_length=120)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="uniq_qualification_name")]

    def __str__(self):
        return self.name


class EmploymentStatus(models.TextChoices):
    ACTIVE = "active"
    INACTIVE = "inactive"  # cannot log in, still schedulable history
    ARCHIVED = "archived"  # hidden from lists; history kept


class Employee(OrgOwned):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=16, choices=EmploymentStatus.choices, default=EmploymentStatus.ACTIVE)
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.PROTECT)
    position = models.ForeignKey(Position, null=True, blank=True, on_delete=models.PROTECT)
    locations = models.ManyToManyField(Location, blank=True)
    qualifications = models.ManyToManyField(Qualification, blank=True)
    contracted_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    hourly_rate = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "email"], name="uniq_employee_email")]
        ordering = ["name"]

    def __str__(self):
        return self.name


class Availability(models.Model):
    """Recurring weekly availability. Absence of rows means 'no stated restriction'."""

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="availability")
    weekday = models.PositiveSmallIntegerField()  # 0=Monday
    start_time = models.TimeField()
    end_time = models.TimeField()
    available = models.BooleanField(default=True)

    class Meta:
        indexes = [models.Index(fields=["employee", "weekday"])]
        constraints = [
            models.CheckConstraint(condition=models.Q(weekday__gte=0, weekday__lte=6), name="availability_weekday")
        ]
