from datetime import date

from django.core.exceptions import ValidationError
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.access import IsAdmin, can_manage_employee, org_scoped
from core.models import Role
from people.api import OrgModelViewSet

from . import services
from .models import LeaveRequest, LeaveType


class LeaveTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveType
        fields = ["id", "name", "paid", "annual_allowance_days", "requires_approval"]


class LeaveTypeViewSet(OrgModelViewSet):
    model = LeaveType
    serializer_class = LeaveTypeSerializer
    write_permission = IsAdmin


class LeaveSerializer(serializers.ModelSerializer):
    days = serializers.IntegerField(read_only=True)

    class Meta:
        model = LeaveRequest
        fields = ["id", "employee", "leave_type", "start_date", "end_date", "reason", "status", "decided_at",
                  "decision_note", "days", "created_at"]


class LeaveViewSet(viewsets.ViewSet):
    def list(self, request):
        u = request.user
        qs = org_scoped(LeaveRequest.objects.select_related("employee"), u)
        if not u.at_least(Role.MANAGER):
            qs = qs.filter(employee__user=u)
        else:
            qs = [r for r in qs if can_manage_employee(u, r.employee) or r.employee.user_id == u.pk]
        return Response(LeaveSerializer(qs if isinstance(qs, list) else qs.order_by("-id")[:300], many=True).data)

    def create(self, request):
        me = getattr(request.user, "employee", None)
        if not me:
            raise ValidationError("No employee profile.")
        lt = org_scoped(LeaveType.objects.all(), request.user).get(pk=request.data["leave_type"])
        req = services.request_leave(me, lt, date.fromisoformat(request.data["start_date"]),
                                     date.fromisoformat(request.data["end_date"]), request.data.get("reason", ""))
        return Response(LeaveSerializer(req).data, status=201)

    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        if not request.user.at_least(Role.MANAGER):
            return Response(status=403)
        req, warnings, shifts = services.decide_leave(request.user, pk, bool(request.data.get("approve")),
                                                      request.data.get("note", ""))
        return Response({**LeaveSerializer(req).data, "staffing_warnings": warnings, "conflicting_shift_ids": shifts})

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        me = getattr(request.user, "employee", None)
        return Response(LeaveSerializer(services.cancel_leave(me, pk)).data)

    @action(detail=False, methods=["get"])
    def balances(self, request):
        me = getattr(request.user, "employee", None)
        if not me:
            return Response([])
        year = int(request.query_params.get("year", date.today().year))
        return Response([{"leave_type": t.name, "allowance": t.annual_allowance_days, "used": services.days_used(me, t, year)}
                         for t in org_scoped(LeaveType.objects.all(), request.user)])
