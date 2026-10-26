"""KPI API: list the caller's approved functions and run one with validated parameters."""

from __future__ import annotations

import logging

from access.scope import scope_for
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from . import registry
from .http import api_login_required, error, json_body
from .service import KpiError, KpiRequest, KpiService

log = logging.getLogger("druksmart.kpi")

HTTP_STATUS = {"unsupported": 404, "forbidden": 403, "invalid_filter": 400, "no_data": 404}


@require_GET
@api_login_required
def me(request):
    return JsonResponse({"status": "ok", "scope": scope_for(request.user).as_dict()})


@require_GET
@api_login_required
def list_kpis(request):
    scope = scope_for(request.user)
    return JsonResponse(
        {
            "status": "ok",
            "functions": [registry.describe(f) for f in registry.functions_for(scope.domains)],
        }
    )


@require_POST
@api_login_required
def run_kpi(request):
    try:
        kpi_request = KpiRequest.from_dict(json_body(request))
    except ValueError as exc:
        return error(400, "invalid_request", str(exc))
    except KpiError as exc:
        return error(400, exc.status, exc.message, **exc.details)
    scope = scope_for(request.user)
    try:
        result = KpiService().run(kpi_request, scope)
    except KpiError as exc:
        log.info("kpi %s by %s -> %s", kpi_request.function, scope.username, exc.status)
        return error(HTTP_STATUS.get(exc.status, 500), exc.status, exc.message, **exc.details)
    except Exception:
        log.exception("kpi %s failed", kpi_request.function)
        return error(503, "error", "The warehouse is not reachable right now. Try again later.")
    return JsonResponse({"status": "ok", "result": result.to_dict()})
