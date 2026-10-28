from django.http import HttpResponse
from django.urls import include, path, re_path
from rest_framework.routers import DefaultRouter

from attendance.api import TimeViewSet
from core import api as core
from leave.api import LeaveTypeViewSet, LeaveViewSet
from notifications.api import list_notifications, mark_read
from people.api import (
    DepartmentViewSet,
    EmployeeViewSet,
    LocationViewSet,
    PositionViewSet,
    QualificationViewSet,
)
from reports.api import ReportView
from scheduling.api import ApplicationViewSet, ShiftViewSet, SwapViewSet, TemplateViewSet, WeekView

router = DefaultRouter()
router.register("employees", EmployeeViewSet, basename="employee")
router.register("locations", LocationViewSet, basename="location")
router.register("departments", DepartmentViewSet, basename="department")
router.register("positions", PositionViewSet, basename="position")
router.register("qualifications", QualificationViewSet, basename="qualification")
router.register("shifts", ShiftViewSet, basename="shift")
router.register("templates", TemplateViewSet, basename="template")
router.register("swaps", SwapViewSet, basename="swap")
router.register("applications", ApplicationViewSet, basename="application")
router.register("leave-types", LeaveTypeViewSet, basename="leavetype")
router.register("leave", LeaveViewSet, basename="leave")
router.register("time", TimeViewSet, basename="time")

api = [
    path("auth/csrf/", core.CsrfView.as_view()),
    path("auth/login/", core.LoginView.as_view()),
    path("auth/logout/", core.LogoutView.as_view()),
    path("auth/me/", core.MeView.as_view()),
    path("auth/accept-invite/", core.AcceptInviteView.as_view()),
    path("auth/password-reset/", core.PasswordResetRequestView.as_view()),
    path("auth/password-reset/confirm/", core.PasswordResetConfirmView.as_view()),
    path("organization/", core.OrgView.as_view()),
    path("invitations/", core.InviteView.as_view()),
    path("users/", core.UserListView.as_view()),
    path("users/<int:pk>/", core.UserDetailView.as_view()),
    path("audit/", core.AuditView.as_view()),
    path("notifications/", list_notifications),
    path("notifications/read/", mark_read),
    path("week/", WeekView.as_view()),
    path("reports/<str:name>/", ReportView.as_view()),
    path("", include(router.urls)),
]


def spa(request, *a, **kw):
    from django.conf import settings

    index = settings.FRONTEND_DIST / "index.html"
    if not index.exists():
        return HttpResponse("Frontend not built. Run `npm run build` in frontend/.", status=404)
    return HttpResponse(index.read_text(encoding="utf-8"))


urlpatterns = [
    path("api/", include(api)),
    re_path(r"^(?!api/|static/).*$", spa),
]
