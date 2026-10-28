"""Server-side authorization. Every queryset served over the API goes through here."""
from rest_framework.permissions import BasePermission

from .models import Role


def org_scoped(qs, user):
    if not user.organization_id:
        return qs.none()
    return qs.filter(organization_id=user.organization_id)


def _scope_ids(user):
    return (
        set(user.managed_locations.values_list("id", flat=True)),
        set(user.managed_departments.values_list("id", flat=True)),
    )


def scope_rows(qs, user):
    """Scoped managers only see rows in their locations/departments (shifts etc.)."""
    if user.role != Role.MANAGER:
        return qs
    locs, depts = _scope_ids(user)
    if locs:
        qs = qs.filter(location_id__in=locs)
    if depts:
        qs = qs.filter(department_id__in=depts)
    return qs


def scope_employees(qs, user):
    if user.role != Role.MANAGER:
        return qs
    locs, depts = _scope_ids(user)
    if locs:
        qs = qs.filter(locations__id__in=locs).distinct()
    if depts:
        qs = qs.filter(department_id__in=depts)
    return qs


def can_manage_employee(user, employee):
    if not user.organization_id or user.organization_id != employee.organization_id:
        return False
    if user.at_least(Role.ADMIN):
        return True
    if user.role != Role.MANAGER:
        return False
    locs, depts = _scope_ids(user)
    if locs and not (locs & set(employee.locations.values_list("id", flat=True))):
        return False
    return not depts or employee.department_id in depts


def can_manage_row(user, obj):
    """For rows with organization/location/department (shifts)."""
    if not user.organization_id or user.organization_id != obj.organization_id:
        return False
    if user.at_least(Role.ADMIN):
        return True
    if user.role != Role.MANAGER:
        return False
    locs, depts = _scope_ids(user)
    return (not locs or obj.location_id in locs) and (not depts or obj.department_id in depts)


class MinRole(BasePermission):
    role = Role.EMPLOYEE

    def has_permission(self, request, view):
        u = request.user
        return bool(u.is_authenticated and u.organization_id and u.at_least(self.role))


class IsManager(MinRole):
    role = Role.MANAGER


class IsAdmin(MinRole):
    role = Role.ADMIN


class IsOwner(MinRole):
    role = Role.OWNER
