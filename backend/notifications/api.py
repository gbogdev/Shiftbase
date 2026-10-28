from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Notification


@api_view(["GET"])
def list_notifications(request):
    qs = Notification.objects.filter(user=request.user)[:100]  # always the caller's own rows
    return Response([{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "created_at": n.created_at,
                      "read": n.read_at is not None} for n in qs])


@api_view(["POST"])
def mark_read(request):
    Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
    return Response(status=204)
