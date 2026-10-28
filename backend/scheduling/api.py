from datetime import date, datetime, timedelta

from django.core.exceptions import ValidationError
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from core.access import IsManager, can_manage_row, org_scoped, scope_rows
from core.errors import Conflict
from core.models import Role
from people.models import Employee, Location, Qualification

from . import services
from .models import OpenShiftApplication, ScheduleTemplate, Shift, ShiftStatus, SwapRequest
from .validation import validate


class ShiftSerializer(serializers.ModelSerializer):
    required_qualifications = serializers.PrimaryKeyRelatedField(many=True, queryset=Qualification.objects.all(), required=False)
    hours = serializers.FloatField(read_only=True)

    class Meta:
        model = Shift
        fields = ["id", "location", "department", "position", "employee", "start", "end", "break_minutes", "notes",
                  "status", "published_at", "modified_since_publish", "required_qualifications", "series_id", "version", "hours"]
        read_only_fields = ["status", "published_at", "modified_since_publish", "series_id", "version"]


def _own_employee(user):
    return getattr(user, "employee", None)


class ShiftViewSet(viewsets.ModelViewSet):
    serializer_class = ShiftSerializer

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return super().get_permissions()
        return [IsManager()]

    def get_queryset(self):
        u = self.request.user
        qs = org_scoped(Shift.objects.prefetch_related("required_qualifications"), u)
        p = self.request.query_params
        if u.role == Role.EMPLOYEE:
            # Employees: published shifts only (their own + open ones + same-location colleagues' for swaps).
            qs = qs.filter(status=ShiftStatus.PUBLISHED)
        else:
            qs = scope_rows(qs, u)
        if p.get("start"):
            qs = qs.filter(end__gt=p["start"])
        if p.get("end"):
            qs = qs.filter(start__lt=p["end"])
        if p.get("location"):
            qs = qs.filter(location_id=p["location"])
        if p.get("employee"):
            qs = qs.filter(employee_id=p["employee"])
        if p.get("open") == "1":
            qs = qs.filter(employee__isnull=True)
        return qs

    def _save(self, request, instance=None):
        s = self.get_serializer(instance, data=request.data, partial=instance is not None)
        s.is_valid(raise_exception=True)
        d = dict(s.validated_data)
        if instance is None:
            shift = Shift()
        else:
            if not can_manage_row(request.user, instance):
                raise PermissionError
            shift = instance
        # Scope check for the target location/department of a manager with restrictions.
        probe = Shift(organization=request.user.organization, location=d.get("location", shift.location if instance else None),
                      department=d.get("department", getattr(shift, "department", None)))
        if not can_manage_row(request.user, probe):
            raise PermissionError
        saved = services.save_shift(request.user, shift, expected_version=request.data.get("version"), **d)
        issues = validate(request.user.organization, [saved])
        return Response({**ShiftSerializer(saved).data, "issues": [i.as_dict() for i in issues]},
                        status=200 if instance else 201)

    def create(self, request):
        return self._save(request)

    def update(self, request, *a, **kw):
        return self._save(request, self.get_object())

    partial_update = update

    def destroy(self, request, *a, **kw):
        shift = self.get_object()
        if not can_manage_row(request.user, shift):
            raise PermissionError
        services.delete_shift(request.user, shift)
        return Response(status=204)

    @action(detail=True, methods=["post"])
    def duplicate(self, request, pk=None):
        shift = self.get_object()
        if not can_manage_row(request.user, shift):
            raise PermissionError
        new = services.duplicate_shift(request.user, shift, days=int(request.data.get("days", 7)))
        return Response(ShiftSerializer(new).data, status=201)

    @action(detail=False, methods=["post"])
    def recurring(self, request):
        s = ShiftSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        weekdays = [int(w) for w in request.data.get("weekdays", [])]
        until = date.fromisoformat(request.data["until"])
        probe = Shift(organization=request.user.organization, location=s.validated_data["location"],
                      department=s.validated_data.get("department"))
        if not can_manage_row(request.user, probe):
            raise PermissionError
        made = services.create_recurring(request.user, dict(s.validated_data), weekdays, until)
        return Response(ShiftSerializer(made, many=True).data, status=201)

    @action(detail=False, methods=["post"])
    def validate(self, request):
        ids = request.data.get("ids", [])
        shifts = list(self.get_queryset().filter(pk__in=ids))
        return Response([i.as_dict() for i in validate(request.user.organization, shifts)])

    @action(detail=False, methods=["post"])
    def publish(self, request):
        loc = org_scoped(Location.objects.all(), request.user).get(pk=request.data["location"])
        probe = Shift(organization=request.user.organization, location=loc)
        if not can_manage_row(request.user, probe):
            raise PermissionError
        start = datetime.fromisoformat(request.data["start"])
        end = datetime.fromisoformat(request.data["end"])
        return Response(services.publish(request.user, loc, start, end))

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        shift = self.get_object()
        if request.user.role == Role.EMPLOYEE:
            return Response(status=403)
        return Response([{"at": c.at, "kind": c.kind, "actor": c.actor.email if c.actor else None, "before": c.before, "after": c.after}
                         for c in shift.changes.select_related("actor")])


class TemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScheduleTemplate
        fields = ["id", "name", "location", "shifts"]

    def validate_shifts(self, rows):
        for r in rows:
            if not (0 <= int(r["weekday"]) <= 6):
                raise serializers.ValidationError("weekday must be 0-6")
            for k in ("start", "end"):
                datetime.strptime(r[k], "%H:%M")
        return rows


class TemplateViewSet(viewsets.ModelViewSet):
    serializer_class = TemplateSerializer
    permission_classes = [IsManager]

    def get_queryset(self):
        return org_scoped(ScheduleTemplate.objects.all(), self.request.user)

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)

    @action(detail=True, methods=["post"])
    def apply(self, request, pk=None):
        t = self.get_object()
        monday = date.fromisoformat(request.data["week_start"])
        made = services.apply_template(request.user, t, monday)
        return Response(ShiftSerializer(made, many=True).data, status=201)


# ---- self-service ----

class SwapSerializer(serializers.ModelSerializer):
    class Meta:
        model = SwapRequest
        fields = ["id", "shift", "from_employee", "to_employee", "status", "decided_at", "note", "created_at"]


class SwapViewSet(viewsets.ViewSet):
    def list(self, request):
        u, qs = request.user, org_scoped(SwapRequest.objects.all(), request.user)
        me = _own_employee(u)
        if u.role == Role.EMPLOYEE or not u.at_least(Role.MANAGER):
            qs = qs.filter(from_employee=me) | qs.filter(to_employee=me) | qs.filter(to_employee__isnull=True, status="pending")
        return Response(SwapSerializer(qs.distinct().order_by("-id")[:200], many=True).data)

    def create(self, request):
        me = _own_employee(request.user)
        if not me:
            raise ValidationError("No employee profile.")
        shift = org_scoped(Shift.objects.all(), request.user).get(pk=request.data["shift"])
        to = Employee.objects.get(pk=request.data["to_employee"], organization=request.user.organization) if request.data.get("to_employee") else None
        return Response(SwapSerializer(services.request_swap(me, shift, to)).data, status=201)

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        me = _own_employee(request.user)
        if not me:
            raise ValidationError("No employee profile.")
        return Response(SwapSerializer(services.accept_swap(me, pk)).data)

    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        if not request.user.at_least(Role.MANAGER):
            return Response(status=403)
        req = org_scoped(SwapRequest.objects.select_related("shift"), request.user).get(pk=pk)
        if req.from_employee.user_id == request.user.pk or (req.to_employee and req.to_employee.user_id == request.user.pk):
            raise ValidationError("You cannot decide a request you are part of.")
        if not can_manage_row(request.user, req.shift):
            raise PermissionError
        return Response(SwapSerializer(services.decide_swap(request.user, pk, bool(request.data.get("approve")), request.data.get("note", ""))).data)


class ApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = OpenShiftApplication
        fields = ["id", "shift", "employee", "status", "decided_at", "created_at"]


class ApplicationViewSet(viewsets.ViewSet):
    def list(self, request):
        qs = org_scoped(OpenShiftApplication.objects.all(), request.user)
        if not request.user.at_least(Role.MANAGER):
            qs = qs.filter(employee=_own_employee(request.user))
        return Response(ApplicationSerializer(qs.order_by("-id")[:200], many=True).data)

    def create(self, request):
        me = _own_employee(request.user)
        if not me:
            raise ValidationError("No employee profile.")
        shift = org_scoped(Shift.objects.all(), request.user).get(pk=request.data["shift"])
        return Response(ApplicationSerializer(services.apply_open_shift(me, shift)).data, status=201)

    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        if not request.user.at_least(Role.MANAGER):
            return Response(status=403)
        app = org_scoped(OpenShiftApplication.objects.select_related("shift"), request.user).get(pk=pk)
        if not can_manage_row(request.user, app.shift):
            raise PermissionError
        return Response(ApplicationSerializer(services.decide_application(request.user, pk, bool(request.data.get("approve")))).data)


class WeekView(APIView):
    """Convenience: org-local week bounds so the client does not compute time zones."""

    def get(self, request):
        org = request.user.organization
        d = date.fromisoformat(request.query_params.get("date", date.today().isoformat()))
        monday = d - timedelta(days=(d.weekday() - org.week_start) % 7)
        lo = datetime.combine(monday, datetime.min.time(), tzinfo=org.tz)
        hi = datetime.combine(monday + timedelta(days=7), datetime.min.time(), tzinfo=org.tz)
        return Response({"start": lo, "end": hi, "week_start": monday})


__all__ = ["Conflict"]
