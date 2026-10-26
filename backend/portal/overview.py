"""Overview page data (Task 10.4): a fixed set of APPROVED KPI functions run for the caller.

Nothing is calculated here. Each tile is an existing registry function (kpi/registry.py) run by
the KPI service with the caller's scope, so module and branch restrictions, the as-of logic,
staleness and synthetic labelling are exactly those of the KPI API, the assistant and (by the
consistency tests) Superset.
"""

from __future__ import annotations

import logging

from access.scope import scope_for
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from kpi.http import api_login_required, error
from kpi.service import KpiError, KpiRequest, KpiService

log = logging.getLogger("druksmart.portal")

# (tile key, KPI request) per module. Only modules in the caller's scope are run.
OVERVIEW_TILES: dict[str, list[tuple[str, dict]]] = {
    "hr": [
        ("headcount", {"function": "hr.active_headcount"}),
        ("headcount_by_department", {"function": "hr.active_headcount", "group_by": "department"}),
        ("leave", {"function": "hr.approved_leave"}),
    ],
    "accounts": [
        ("receivables", {"function": "ac.outstanding_receivables"}),
        ("payables", {"function": "ac.outstanding_payables"}),
        ("overdue", {"function": "ac.overdue_balance"}),
        ("ageing", {"function": "ac.ageing"}),
    ],
}


def _summary(results: list[dict]) -> dict:
    """Reporting dates and freshness across the tiles (the most cautious value wins)."""
    freshness = {}
    for r in results:
        for f in r["freshness"]:  # one row per source of the result's module
            freshness[(r["domain"], f["source_instance"])] = {"domain": r["domain"], **f}
    ages = [
        r["hours_since_publication"] for r in results if r["hours_since_publication"] is not None
    ]
    return {
        "as_of": sorted({r["as_of"] for r in results if r["as_of"]}),
        "freshness": sorted(freshness.values(), key=lambda f: (f["domain"], f["source_instance"])),
        "hours_since_publication": max(ages) if ages else None,
        "stale": any(r["stale"] for r in results),
        "synthetic": any(r["synthetic"] for r in results),
        "branch_restricted": any(r["branch_restricted"] for r in results),
    }


@require_GET
@api_login_required
def overview(request):
    scope = scope_for(request.user)
    service = KpiService()
    tiles: dict[str, dict] = {}
    results: list[dict] = []
    for domain in ("hr", "accounts"):
        if not scope.allows(domain):
            continue
        for key, params in OVERVIEW_TILES[domain]:
            try:
                result = service.run(KpiRequest.from_dict(params), scope).to_dict()
            except KpiError as exc:  # e.g. no_data for a branch without records
                tiles[key] = {"status": exc.status, "message": exc.message}
                continue
            except Exception:
                log.exception("overview tile %s failed", key)
                return error(
                    503, "error", "The warehouse is not reachable right now. Try again later."
                )
            tiles[key] = {"status": "ok", "result": result}
            results.append(result)
    return JsonResponse(
        {
            "status": "ok",
            "domains": sorted(scope.domains),
            "tiles": tiles,
            "summary": _summary(results) if results else None,
        }
    )
