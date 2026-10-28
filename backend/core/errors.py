from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.http import Http404
from rest_framework.response import Response
from rest_framework.views import exception_handler


class Conflict(Exception):
    """Business-rule failure -> HTTP 409 with machine-readable issues."""

    def __init__(self, message, issues=None):
        super().__init__(message)
        self.message, self.issues = message, issues or []


def handler(exc, context):
    if isinstance(exc, Conflict):
        return Response({"detail": exc.message, "issues": exc.issues}, status=409)
    if isinstance(exc, ValidationError):
        return Response({"detail": exc.messages}, status=400)
    if isinstance(exc, (PermissionDenied, PermissionError)):
        return Response({"detail": "Forbidden."}, status=403)
    if isinstance(exc, (Http404, ObjectDoesNotExist)):
        return Response({"detail": "Not found."}, status=404)
    return exception_handler(exc, context)
