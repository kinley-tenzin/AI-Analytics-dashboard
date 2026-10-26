"""Health checks: /health/ (process alive) and /health/ready/ (dependencies reachable).

Readiness reports only component states, never credentials or KPI values, so it may be called
without logging in (e.g. by a container health check).
"""

from __future__ import annotations

from datetime import UTC, datetime

from assistant.pipeline import provider_status
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from kpi import warehouse
from kpi.service import STALE_AFTER_HOURS


@require_GET
def live(request):
    return JsonResponse({"status": "ok"})


@require_GET
def ready(request):
    checks: dict[str, dict] = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["app_database"] = {"ok": True}
    except Exception as exc:
        checks["app_database"] = {"ok": False, "error": type(exc).__name__}
    try:
        with warehouse.connect() as conn:
            rows = conn.execute(
                "SELECT domain, max(latest_snapshot_date), max(published_at) "
                "FROM marts.data_freshness GROUP BY domain ORDER BY domain"
            ).fetchall()
        published = [r[2] for r in rows]
        age = (
            (datetime.now(UTC) - min(published)).total_seconds() / 3600
            if published and all(published)
            else None
        )
        stale = age is None or age > STALE_AFTER_HOURS
        checks["warehouse"] = {
            "ok": bool(rows) and not stale,
            "data_as_of": {r[0]: r[1].isoformat() for r in rows},
            "oldest_publication": min(published) if published and all(published) else None,
            "hours_since_publication": round(age, 1) if age is not None else None,
            "stale": stale,
            "stale_after_hours": STALE_AFTER_HOURS,
        }
    except Exception as exc:
        checks["warehouse"] = {"ok": False, "error": type(exc).__name__}
    checks["ai_provider"] = {"ok": True, **provider_status()}
    ok = all(c["ok"] for c in checks.values())
    return JsonResponse(
        {"status": "ok" if ok else "degraded", "checks": checks}, status=200 if ok else 503
    )
