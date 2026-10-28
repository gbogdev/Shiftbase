from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Organization, User


class Command(BaseCommand):
    help = "Create an organization and its owner. Password is read from the OWNER_PASSWORD environment variable."

    def add_arguments(self, p):
        p.add_argument("--name", required=True)
        p.add_argument("--owner-email", required=True)
        p.add_argument("--timezone", default="UTC")

    @transaction.atomic
    def handle(self, *a, **o):
        import os

        from django.contrib.auth.password_validation import validate_password

        pw = os.environ.get("OWNER_PASSWORD", "")
        validate_password(pw)
        org = Organization.objects.create(name=o["name"], timezone=o["timezone"])
        User.objects.create_user(o["owner_email"], pw, organization=org, role="owner", name="Owner")
        self.stdout.write(f"Created {org.name} with owner {o['owner_email']}")
