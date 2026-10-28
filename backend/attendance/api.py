from datetime import datetime

from django.core.exceptions import ValidationError
from django.http import HttpResponse
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.access import IsManager, can_manage_employee, org_scoped
from core.models import Role

from . import services
from .models import EntryStatus, TimeEntry


class EntrySerializer(serializers.ModelSerializer):
    worked_hours = serializers.FloatField(read_only=True)
    employee_name = serializers.CharField(source="employee.name", read_only=True)
    scheduled_hours = serializers.SerializerMethodField()

    class Meta:
        model = TimeEntry
        fields = ["id", "employee", "employee_name", "shift", "clock_in", "clock_out", "break_minutes",
                  "break_started_at", "status", "approved_at", "worked_hours", "scheduled_hours"]

    def get_scheduled_hours(self, e):
        return e.shift.hours if e.shift_id else None


def _me(request):
    me = getattr(request.user, "employee", None)
    if not me or me.status != "active":
        raise ValidationError("No active employee profile.")
    return me


class TimeViewSet(viewsets.ViewSet):
    def list(self, request):
        u = request.user
        qs = org_scoped(TimeEntry.objects.select_related("employee", "shift"), u)
        p = request.query_params
        if p.get("start"):
            qs = qs.filter(clock_in__gte=p["start"])
        if p.get("end"):
            qs = qs.filter(clock_in__lt=p["end"])
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if not u.at_least(Role.MANAGER):
            qs = qs.filter(employee__user=u)
        rows = qs.order_by("-clock_in")[:500]
        if u.role == Role.MANAGER:
            rows = [e for e in rows if can_manage_employee(u, e.employee) or e.employee.user_id == u.pk]
        return Response(EntrySerializer(rows, many=True).data)

    @action(detail=False, methods=["post"], url_path="clock-in")
    def clock_in(self, request):
        return Response(EntrySerializer(services.clock_in(_me(request))).data, status=201)

    @action(detail=False, methods=["post"], url_path="clock-out")
    def clock_out(self, request):
        return Response(EntrySerializer(services.clock_out(_me(request))).data)

    @action(detail=False, methods=["post"], url_path="break-start")
    def break_start(self, request):
        return Response(EntrySerializer(services.start_break(_me(request))).data)

    @action(detail=False, methods=["post"], url_path="break-end")
    def break_end(self, request):
        return Response(EntrySerializer(services.end_break(_me(request))).data)

    @action(detail=False, methods=["post"])
    def submit(self, request):
        return Response({"submitted": services.submit_entries(_me(request), request.data.get("ids", []))})

    @action(detail=False, methods=["post"])
    def approve(self, request):
        if not request.user.at_least(Role.MANAGER):
            return Response(status=403)
        return Response({"approved": services.approve_entries(request.user, request.data.get("ids", []))})

    @action(detail=True, methods=["post"])
    def correct(self, request, pk=None):
        if not request.user.at_least(Role.MANAGER):
            return Response(status=403)
        d = request.data
        parse = lambda k: datetime.fromisoformat(d[k]) if d.get(k) else None  # noqa: E731
        e = services.correct_entry(request.user, pk, d.get("reason", ""), parse("clock_in"), parse("clock_out"),
                                   d.get("break_minutes"))
        return Response(EntrySerializer(e).data)

    @action(detail=False, methods=["get"])
    def export(self, request):
        if not request.user.at_least(Role.MANAGER):
            return Response(status=403)
        qs = org_scoped(TimeEntry.objects.filter(status=EntryStatus.APPROVED), request.user)
        p = request.query_params
        if p.get("start"):
            qs = qs.filter(clock_in__gte=p["start"])
        if p.get("end"):
            qs = qs.filter(clock_in__lt=p["end"])
        ids = [e.pk for e in qs.select_related("employee") if can_manage_employee(request.user, e.employee)]
        from core import audit

        audit.record(request.user, "timesheet.export", count=len(ids))
        resp = HttpResponse(services.export_csv(request.user.organization, qs.filter(pk__in=ids)), content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="approved-timesheets.csv"'
        return resp


__all__ = ["IsManager"]
