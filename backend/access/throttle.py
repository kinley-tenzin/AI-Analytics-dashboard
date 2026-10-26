"""Sign-in throttling (closes Milestone 8 defect D6).

After MAX_FAILURES failed sign-ins for one username within WINDOW, that username is locked until
the oldest failure in the window expires. The check sits in the AUTHENTICATION BACKEND, so it
covers every sign-in path: the web app's JSON login, Django's sign-in form and /admin/.

Counted per username (normalised to lower case), not per IP address: behind Docker's port
mapping every browser arrives from the same gateway address, so an IP limit would lock out all
users at once. The trade-off (someone can deliberately lock a known username for 15 minutes) is
acceptable for this single-organisation prototype and documented in docs/web/AUTHENTICATION.md.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.core.exceptions import PermissionDenied
from django.dispatch import receiver
from django.utils import timezone

from .models import LoginFailure

log = logging.getLogger("druksmart.auth")

MAX_FAILURES = 5
WINDOW = timedelta(minutes=15)


def normalise(username: str | None) -> str:
    return (username or "").strip().lower()[:150]


def client_ip(request) -> str | None:
    return request.META.get("REMOTE_ADDR") if request is not None else None


def lockout_seconds(username: str | None) -> int:
    """Seconds until `username` may try again (0 = not locked)."""
    name = normalise(username)
    if not name:
        return 0
    since = timezone.now() - WINDOW
    recent = LoginFailure.objects.filter(username=name, created_at__gte=since).order_by(
        "created_at"
    )
    if recent.count() < MAX_FAILURES:
        return 0
    # Locked until enough failures have aged out of the window to drop below the limit.
    unlock_at = recent[recent.count() - MAX_FAILURES].created_at + WINDOW
    return max(1, int((unlock_at - timezone.now()).total_seconds()) + 1)


class ThrottledModelBackend(ModelBackend):
    """Django's username/password backend, refusing locked usernames before checking passwords."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(self._username_field())
        if lockout_seconds(username):
            log.warning("sign-in refused: username %r is locked", normalise(username))
            raise PermissionDenied  # stops authentication; Django records a failed attempt
        return super().authenticate(request, username=username, password=password, **kwargs)

    @staticmethod
    def _username_field() -> str:
        from django.contrib.auth import get_user_model

        return get_user_model().USERNAME_FIELD


@receiver(user_login_failed)
def record_failure(sender, credentials, request=None, **kwargs):
    name = normalise(credentials.get("username"))
    if not name:
        return
    LoginFailure.objects.filter(created_at__lt=timezone.now() - WINDOW).delete()
    LoginFailure.objects.create(username=name, ip_address=client_ip(request))
    log.info("sign-in failed for %r from %s", name, client_ip(request))


@receiver(user_logged_in)
def clear_failures(sender, request, user, **kwargs):
    LoginFailure.objects.filter(username=normalise(user.get_username())).delete()
    log.info("sign-in succeeded for %r", user.get_username())
