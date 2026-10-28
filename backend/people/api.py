from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core import audit
from core.access import IsAdmin, can_manage_employee, org_scoped, scope_employees
from core.models import Role

from .models import Availability, Department, Employee, EmploymentStatus, Location, Position, Qualification


def _check_same_org(user, *objs):
    for o in objs:
        if o is not None and o.organization_id != user.organization_id:
            raise serializers.ValidationError("Unknown reference.")


class OrgModelViewSet(viewsets.ModelViewSet):
    """Reads: any member of the org. Writes: admins. Organization is always taken from the session."""

    model = None
    write_permission = IsAdmin

    def get_permissions(self):
        return [self.write_permission()] if self.request.method not in ("GET", "HEAD", "OPTIONS") else super().get_permissions()

    def get_queryset(self):
        return org_scoped(self.model.objects.all(), self.request.user)

    def perform_create(self, serializer):
        obj = serializer.save(organization=self.request.user.organization)
        audit.record(self.request.user, f"{self.model.__name__.lower()}.create", obj)

    def perform_update(self, serializer):
        obj = serializer.save()
        audit.record(self.request.user, f"{self.model.__name__.lower()}.update", obj)

    def perform_destroy(self, instance):
        audit.record(self.request.user, f"{self.model.__name__.lower()}.delete", instance, name=str(instance))
        instance.delete()


def simple(model_cls, names):
    class S(serializers.ModelSerializer):
        class Meta:
            model = model_cls
            fields = ["id", *names]

    class V(OrgModelViewSet):
        model = model_cls
        serializer_class = S

    V.__name__ = model_cls.__name__ + "ViewSet"
    return V


LocationViewSet = simple(Location, ["name", "address"])
DepartmentViewSet = simple(Department, ["name"])
PositionViewSet = simple(Position, ["name"])
QualificationViewSet = simple(Qualification, ["name"])


class AvailabilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Availability
        fields = ["id", "weekday", "start_time", "end_time", "available"]

    def validate(self, d):
        if d["end_time"] <= d["start_time"]:
            raise serializers.ValidationError("End must be after start.")
        return d


class EmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = ["id", "name", "email", "phone", "status", "department", "position", "locations",
                  "qualifications", "contracted_hours", "hourly_rate", "start_date", "user", "archived_at"]
        read_only_fields = ["user", "archived_at"]

    def validate(self, d):
        u = self.context["request"].user
        _check_same_org(u, d.get("department"), d.get("position"))
        for loc in d.get("locations", []):
            _check_same_org(u, loc)
        for q in d.get("qualifications", []):
            _check_same_org(u, q)
        return d

    def to_representation(self, obj):
        data = super().to_representation(obj)
        u = self.context["request"].user
        # Pay data is only visible to admins and the employee themself.
        if not (u.at_least(Role.ADMIN) or obj.user_id == u.pk):
            data.pop("hourly_rate", None)
        return data


class EmployeeViewSet(viewsets.ModelViewSet):
    serializer_class = EmployeeSerializer

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return super().get_permissions()
        # availability does its own object-level check (own record or in-scope manager)
        return super().get_permissions() if self.action == "availability" else [IsAdmin()]

    def get_queryset(self):
        u = self.request.user
        qs = org_scoped(Employee.objects.prefetch_related("locations", "qualifications"), u)
        if u.role == Role.EMPLOYEE:
            # Employees see colleagues' names (for swaps) but the list stays minimal.
            qs = qs.filter(status=EmploymentStatus.ACTIVE)
        else:
            qs = scope_employees(qs, u)
        if self.request.query_params.get("archived") != "1":
            qs = qs.exclude(status=EmploymentStatus.ARCHIVED)
        return qs

    def retrieve(self, request, *a, **kw):
        obj = self.get_object()
        if request.user.role == Role.EMPLOYEE and obj.user_id != request.user.pk:
            return Response(self._minimal(obj))
        return super().retrieve(request, *a, **kw)

    def list(self, request, *a, **kw):
        if request.user.role == Role.EMPLOYEE:
            return Response([self._minimal(e) for e in self.get_queryset()])
        return super().list(request, *a, **kw)

    @staticmethod
    def _minimal(e):
        return {"id": e.id, "name": e.name, "position": e.position_id, "department": e.department_id}

    def perform_create(self, serializer):
        emp = serializer.save(organization=self.request.user.organization)
        audit.record(self.request.user, "employee.create", emp)

    def perform_update(self, serializer):
        emp = serializer.save()
        audit.record(self.request.user, "employee.update", emp, fields=list(self.request.data.keys()))

    def destroy(self, request, *a, **kw):
        raise ValidationError("Employees are archived, not deleted. Use the archive action.")

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def archive(self, request, pk=None):
        emp = Employee.objects.select_for_update().get(pk=self.get_object().pk)
        emp.status, emp.archived_at = EmploymentStatus.ARCHIVED, timezone.now()
        emp.save()
        if emp.user_id:
            emp.user.is_active = False
            emp.user.save(update_fields=["is_active"])
        audit.record(request.user, "employee.archive", emp)
        return Response(EmployeeSerializer(emp, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def deactivate(self, request, pk=None):
        emp = self.get_object()
        emp.status = EmploymentStatus.INACTIVE
        emp.save()
        if emp.user_id:
            emp.user.is_active = False
            emp.user.save(update_fields=["is_active"])
        audit.record(request.user, "employee.deactivate", emp)
        return Response(EmployeeSerializer(emp, context={"request": request}).data)

    @action(detail=True, methods=["get", "put"])
    def availability(self, request, pk=None):
        """Employees manage their own availability; managers can edit within their scope."""
        emp = self.get_object()
        u = request.user
        own = emp.user_id == u.pk
        if request.method == "GET":
            if not own and not can_manage_employee(u, emp):
                return Response(status=403)
            return Response(AvailabilitySerializer(emp.availability.all(), many=True).data)
        if not own and not can_manage_employee(u, emp):
            return Response(status=403)
        s = AvailabilitySerializer(data=request.data, many=True)
        s.is_valid(raise_exception=True)
        with transaction.atomic():
            emp.availability.all().delete()
            Availability.objects.bulk_create([Availability(employee=emp, **row) for row in s.validated_data])
        audit.record(u, "availability.update", emp)
        return Response(s.data)

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "request": self.request}

