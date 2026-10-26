"""Keep the API's JSON error contract when something below the views fails (Milestone 8, D10).

Example: the PostgreSQL server holding both the warehouse and Django's own sessions is down. The
session lookup then fails before any view code runs, and Django would answer with an HTML 500
page that the UI cannot interpret. API clients get a JSON 503 / 500 instead; no data is returned.
"""

from __future__ import annotations

import logging

from django.db import DatabaseError
from django.http import JsonResponse

log = logging.getLogger("druksmart.api")


class ApiErrorMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if not request.path.startswith("/api/"):
            return None  # pages keep Django's normal error handling
        if isinstance(exception, DatabaseError):
            log.error("database unavailable during %s: %s", request.path, type(exception).__name__)
            return JsonResponse(
                {
                    "status": "error",
                    "message": "The service's database is not reachable right now. "
                    "Try again later.",
                },
                status=503,
            )
        log.exception("unhandled error during %s", request.path)
        return JsonResponse({"status": "error", "message": "Internal error."}, status=500)
