"""Dashboards of the website and guest tokens for embedding them (Task 10.5).

Who may see which dashboard is decided HERE, from the Django user's scope (never from the
browser): the dashboard must be visible and belong to one of the user's modules; it may only
use datasets of that module; branch-restricted users get their branches as row-level security
rules inside the guest token and are refused any dashboard with a dataset that cannot be
branch-filtered. Superset then enforces the token (one dashboard, its charts only, the RLS).
"""

from __future__ import annotations

import logging

from access.scope import Scope, scope_for
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from kpi.http import api_login_required, error

from .models import PortalDashboard
from .superset import (
    DashboardInfo,
    DashboardNotFound,
    SupersetGateway,
    SupersetUnavailable,
    access_rules,
    branch_clause,
)

log = logging.getLogger("druksmart.portal")


class NotPermitted(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def can_author(scope: Scope) -> bool:
    """The HR / Accounts Managers (their module) and the administrator (both); ADR-044."""
    return bool(scope.author_domains)


def visible_dashboards(scope: Scope):
    return PortalDashboard.objects.filter(visible=True, domain__in=sorted(scope.domains))


def describe(d: PortalDashboard, scope: Scope) -> dict:
    data = {
        "key": d.key,
        "title": d.title,
        "description": d.description,
        "domain": d.domain,
        "kind": d.kind,
    }
    if scope.can_author(d.domain):
        # Native Superset editor (separate Superset sign-in; prototype limitation, ADR-040).
        public = settings.DRUKSMART_SUPERSET["PUBLIC_URL"]
        data["editor_url"] = f"{public}/superset/dashboard/{d.superset_ref}/"
    return data


def guest_rls(scope: Scope, d: PortalDashboard, info: DashboardInfo) -> list[dict]:
    """Check the dashboard's datasets and build the RLS rules for this user (fail closed)."""
    rules = access_rules()
    allowed = rules.domain_tables.get(d.domain, frozenset())
    outside = sorted(set(info.datasets) - allowed)
    if outside:
        log.warning("dashboard %s uses datasets outside %s: %s", d.key, d.domain, outside)
        raise NotPermitted(
            403,
            "dashboard_not_permitted",
            "This dashboard uses data outside its module and cannot be shown.",
        )
    if scope.branch_keys is None:
        return []
    if not scope.branch_keys:
        raise NotPermitted(403, "forbidden", "No branch is assigned to your account.")
    try:
        clause = branch_clause(scope.branch_keys)
    except ValueError:  # a malformed branch key in the user's scope: refuse, never pass it on
        log.error("invalid branch scope for %s", scope.username)
        raise NotPermitted(403, "forbidden", "Your branch assignment is invalid.") from None
    rls = []
    for table, dataset_id in sorted(info.datasets.items()):
        if table in rules.branch_filtered:
            rls.append({"dataset": dataset_id, "clause": clause})
        elif table not in rules.branch_neutral:
            raise NotPermitted(
                403,
                "dashboard_not_permitted",
                "This dashboard contains data that cannot be limited to your branch.",
            )
    return rls


@require_GET
@api_login_required
def list_dashboards(request):
    scope = scope_for(request.user)
    return JsonResponse(
        {
            "status": "ok",
            "dashboards": [describe(d, scope) for d in visible_dashboards(scope)],
            "can_author": can_author(scope),
            "author_domains": sorted(scope.author_domains),
            "superset_url": settings.DRUKSMART_SUPERSET["PUBLIC_URL"],
        }
    )


@require_POST
@never_cache
@api_login_required
def guest_token(request, key: str):
    scope = scope_for(request.user)
    dashboard = PortalDashboard.objects.filter(key=key, visible=True).first()
    if dashboard is None:
        return error(404, "not_found", "This dashboard does not exist or is hidden.")
    if not scope.allows(dashboard.domain):
        log.info("guest token refused: %s has no %s access", scope.username, dashboard.domain)
        return error(403, "forbidden", "Your role does not include this module.")
    gateway = SupersetGateway()
    try:
        info = gateway.dashboard(dashboard.superset_ref)
        rls = guest_rls(scope, dashboard, info)
        token = gateway.guest_token(info, scope.username, rls)
    except NotPermitted as exc:
        return error(exc.status, exc.code, exc.message)
    except DashboardNotFound:
        log.warning("dashboard %s (%s) not found in Superset", key, dashboard.superset_ref)
        return error(404, "not_found", "The dashboard is not available in Superset.")
    except SupersetUnavailable as exc:
        log.error("Superset unavailable for guest token: %s", exc)
        return error(503, "bi_unavailable", "The dashboard service is not reachable right now.")
    log.info("guest token: %s -> %s (%d RLS rules)", scope.username, dashboard.key, len(rls))
    return JsonResponse(
        {
            "status": "ok",
            "token": token,
            "embedded_id": info.embedded_id,
            "superset_url": settings.DRUKSMART_SUPERSET["PUBLIC_URL"],
            "expires_in": settings.DRUKSMART_SUPERSET["GUEST_TOKEN_SECONDS"],
            "branch_restricted": scope.branch_keys is not None,
        }
    )
