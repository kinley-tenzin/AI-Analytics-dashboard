"""JSON helpers shared by the API views (no REST framework needed for a few endpoints)."""

from __future__ import annotations

import json
from functools import wraps

from django.http import JsonResponse

MAX_BODY_BYTES = 16 * 1024


def error(status: int, code: str, message: str, **extra) -> JsonResponse:
    return JsonResponse({"status": code, "message": message, **extra}, status=status)


def api_login_required(view):
    """Like login_required, but answers API clients with 401 JSON instead of a redirect."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return error(401, "unauthenticated", "Log in first (session authentication).")
        return view(request, *args, **kwargs)

    return wrapper


def json_body(request) -> dict:
    """Parse a small JSON object body or raise ValueError with a user-safe message."""
    if len(request.body) > MAX_BODY_BYTES:
        raise ValueError("request body too large")
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        raise ValueError("request body must be JSON") from None
    if not isinstance(data, dict):
        raise ValueError("request body must be a JSON object")
    return data
