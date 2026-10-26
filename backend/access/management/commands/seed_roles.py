"""Create the DrukSmart role groups (idempotent). Users are then added to ONE group each."""

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from access.scope import ROLE_DOMAINS


class Command(BaseCommand):
    help = "Create the DrukSmart role groups used by the KPI service and the AI assistant."

    def handle(self, *args, **options):
        for name in ROLE_DOMAINS:
            _, created = Group.objects.get_or_create(name=name)
            self.stdout.write(f"{'created' if created else 'exists '} group {name}")
