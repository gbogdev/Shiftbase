import logging

from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Notification

log = logging.getLogger(__name__)


def notify(user, kind, title, body="", dedupe_key=None):
    """Create an in-app notification once per (user, dedupe_key); then try email.

    The in-app record is committed with the caller's transaction. Email is sent after commit and any
    failure is stored on the notification - it never rolls back or hides the underlying event.
    """
    if user is None or not user.is_active:
        return None
    key = dedupe_key or f"{kind}:{title}"
    try:
        with transaction.atomic():
            n = Notification.objects.create(user=user, kind=kind, title=title, body=body, dedupe_key=key)
    except IntegrityError:
        return None  # same event already notified
    org = user.organization
    if org and org.email_notifications:
        transaction.on_commit(lambda: send_email(n.pk))
    return n


def send_email(notification_id):
    n = Notification.objects.select_related("user").get(pk=notification_id)
    if n.email_sent_at:
        return
    try:
        send_mail(n.title, n.body or n.title, None, [n.user.email], fail_silently=False)
        n.email_sent_at = timezone.now()
        n.email_error = ""
    except Exception as exc:  # delivery problems must not lose the event
        log.warning("email delivery failed for notification %s: %s", n.pk, type(exc).__name__)
        n.email_error = type(exc).__name__
    n.save(update_fields=["email_sent_at", "email_error"])


def retry_failed_emails():
    """Run from cron / `manage.py retry_emails`; idempotent."""
    for n in Notification.objects.filter(email_sent_at__isnull=True).exclude(email_error=""):
        send_email(n.pk)
