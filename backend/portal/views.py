"""Serves the DrukSmart web application (the React build in frontend/dist) under /app/.

Django serves it on the SAME ORIGIN as /api/v1/, so the app uses Django's session cookie and
CSRF protection directly (no tokens in the browser, no CORS). The app's data always comes from
the authenticated API endpoints; the files served here contain no data and no secrets.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.http import Http404, HttpResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_safe
from django.views.static import serve

ASSET_MAX_AGE = 365 * 24 * 3600


def content_security_policy() -> str:
    """Strict policy for the app page: only its own scripts, styles, fonts and API calls; frames
    only from Superset (embedded dashboards); the app itself can never be framed."""
    superset = settings.DRUKSMART_SUPERSET["PUBLIC_URL"]
    return "; ".join(
        [
            "default-src 'self'",
            "script-src 'self'",
            "style-src 'self'",
            "font-src 'self'",
            "img-src 'self' data:",
            "connect-src 'self'",
            f"frame-src {superset}",
            "frame-ancestors 'none'",
            "form-action 'self'",
            "base-uri 'self'",
            "object-src 'none'",
        ]
    )


MISSING_BUILD = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>DrukSmart Analytics: not built</title></head><body style="font-family:sans-serif">
<h1>The DrukSmart web application has not been built</h1>
<p>Build it with <code>npm ci</code> and <code>npm run build</code> in the <code>frontend</code>
folder (docs/web/FRONTEND.md), or rebuild the backend image.</p></body></html>"""


def dist_dir() -> Path:
    return Path(settings.DRUKSMART_FRONTEND_DIST)


def _serve_file(request, path: str, root: Path):
    try:
        return serve(request, path, document_root=root)
    except SuspiciousFileOperation:  # "../" outside the build directory
        raise Http404 from None


@require_safe
@never_cache
@ensure_csrf_cookie
def index(request):
    """The app shell for every client-side route; sets the CSRF cookie the app sends back."""
    index_file = dist_dir() / "index.html"
    if not index_file.is_file():
        return HttpResponse(MISSING_BUILD, status=503)
    response = HttpResponse(index_file.read_bytes(), content_type="text/html; charset=utf-8")
    response["Content-Security-Policy"] = content_security_policy()
    return response


@require_safe
def asset(request, path: str):
    response = _serve_file(request, path, dist_dir() / "assets")
    response["Cache-Control"] = f"public, max-age={ASSET_MAX_AGE}, immutable"
    return response


@require_safe
def root_file(request, path: str):
    if path == "index.html":  # always through `index` (CSRF cookie, no caching)
        raise Http404
    response = _serve_file(request, path, dist_dir())
    response["Cache-Control"] = "public, max-age=3600"
    return response
