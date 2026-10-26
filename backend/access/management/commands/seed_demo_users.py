"""Create DEMO users, one per role, for LOCAL testing only (idempotent).

They share the password in BACKEND_DEMO_USER_PASSWORD (.env). Never run this in a DrukSmart
deployment: create real users in the Django admin instead.
"""

import os

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from access.models import BranchScope

# Same usernames, roles and demo branch as the Superset demo users
# (superset/definitions/access.yml).
DEMO_USERS = [
    ("demo_hr", "DrukSmart HR Manager", []),
    ("demo_accounts", "DrukSmart Accounts Manager", []),
    ("demo_executive", "DrukSmart Executive", []),
    ("demo_branch", "DrukSmart Branch Manager", ["odoo:odoo-sandbox:1"]),
]
# Demo users of earlier milestones, removed if they still exist (ADR-044).
RETIRED_DEMO_USERS = ["demo_creator"]


class Command(BaseCommand):
    help = "Create local demo users (password from BACKEND_DEMO_USER_PASSWORD)."

    def handle(self, *args, **options):
        password = os.environ.get("BACKEND_DEMO_USER_PASSWORD", "").strip()
        if not password or password == "CHANGE_ME":
            raise CommandError("BACKEND_DEMO_USER_PASSWORD is not set in .env")
        call_command("seed_roles")
        for username in RETIRED_DEMO_USERS:
            if User.objects.filter(username=username).delete()[0]:
                self.stdout.write(f"removed retired demo user {username}")
        for username, role, branches in DEMO_USERS:
            user, created = User.objects.get_or_create(username=username)
            user.set_password(password)
            user.is_staff = False
            user.save()
            user.groups.set([Group.objects.get(name=role)])
            BranchScope.objects.filter(user=user).exclude(branch_key__in=branches).delete()
            for key in branches:
                BranchScope.objects.get_or_create(user=user, branch_key=key)
            extra = f", branches {branches}" if branches else ""
            self.stdout.write(f"{'created' if created else 'updated'} {username} -> {role}{extra}")
