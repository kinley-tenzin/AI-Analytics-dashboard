"""Session sign-in API for the web application (Task 10.3).

The web app is served by Django on the same origin, so it signs in with an ordinary Django
SESSION (HttpOnly cookie) protected by CSRF; no token is ever given to the browser. Responses
follow the API's JSON contract `{"status": ..., "message": ...}` (kpi/http.py).
"""

from __future__ import annotations

from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from kpi.http import error, json_body

from .scope import scope_for
from .throttle import lockout_seconds

INVALID_CREDENTIALS = "Username or password is incorrect."
MAX_USERNAME = 150
MAX_PASSWORD = 4096


def _session_payload(request) -> dict:
    user = request.user
    if not user.is_authenticated:
        return {"status": "ok", "authenticated": False, "user": None}
    return {"status": "ok", "authenticated": True, "user": scope_for(user).as_dict()}


@require_GET
@never_cache
@ensure_csrf_cookie
def session(request):
    """Who is signed in. Always 200, so a signed-out visitor is a normal state, not an error."""
    return JsonResponse(_session_payload(request))


@require_POST
@never_cache
def sign_in(request):
    try:
        body = json_body(request)
    except ValueError as exc:
        return error(400, "invalid_request", str(exc))
    username, password = body.get("username"), body.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        return error(400, "invalid_request", "username and password must be text")
    username = username.strip()
    if not username or not password:
        return error(400, "invalid_request", "Enter your username and password.")
    if len(username) > MAX_USERNAME or len(password) > MAX_PASSWORD:
        return error(401, "invalid_credentials", INVALID_CREDENTIALS)

    wait = lockout_seconds(username)
    if wait:
        response = error(
            429,
            "throttled",
            "Too many failed sign-in attempts. Try again in "
            f"{max(1, round(wait / 60))} minute(s) or ask the administrator.",
            retry_after=wait,
        )
        response["Retry-After"] = str(wait)
        return response

    # Unknown user, wrong password and inactive account all give the SAME answer.
    user = authenticate(request, username=username, password=password)
    if user is None:
        return error(401, "invalid_credentials", INVALID_CREDENTIALS)
    login(request, user)  # new session id (no fixation) and a new CSRF token
    return JsonResponse(_session_payload(request))


@require_POST
@never_cache
def sign_out(request):
    logout(request)
    return JsonResponse({"status": "ok", "authenticated": False, "user": None})
