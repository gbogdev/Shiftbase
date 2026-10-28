from django.core.management.base import BaseCommand

from attendance.services import flag_missed_clock_outs
from notifications.services import retry_failed_emails


class Command(BaseCommand):
    help = "Retry failed emails and flag missed clock-outs. Safe to run repeatedly (e.g. every 5 minutes via cron)."

    def handle(self, *a, **kw):
        retry_failed_emails()
        self.stdout.write(f"flagged {flag_missed_clock_outs()} missed clock-outs")
