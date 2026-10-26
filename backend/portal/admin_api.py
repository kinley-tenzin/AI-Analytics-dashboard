"""Administration and dashboard-management API (Tasks 10.7, ADR-044).

Administrator (Django superuser) only:
* Platform status: warehouse publication per module, Superset and service account, AI provider,
  consumer data mode. No KPI values.
* Users and roles: read-only list; accounts, roles and branches are edited in Django admin.

Dashboard management, for everyone who may AUTHOR dashboards (scope.author_domains: the HR /
Accounts Manager for their module, the administrator for both), always limited to those modules:
which dashboards a module page shows, and publishing a dashboard built in Superset (enables
embedding for the website's origin and checks that it uses only datasets of that module).
"""

from __future__ import annotations

import logging
import re
from functools import wraps

from access.models import BranchScope
from access.scope import ROLE_DOMAINS, scope_for
from assistant.pipeline import provider_status
from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_http_methods
from kpi import warehouse
from kpi.http import api_login_required, error, json_body
from kpi.service import KpiService

from .models import PortalDashboard
from .superset import DashboardNotFound, SupersetGateway, SupersetUnavailable, access_rules

log = logging.getLogger("druksmart.portal")

SUPERSET_REF = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def public_url() -> str:  # read at call time (tests override settings)
    return settings.DRUKSMART_SUPERSET["PUBLIC_URL"]


def admin_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if "Administrator" not in scope_for(request.user).roles:
            return error(403, "forbidden", "Only the administrator can use this page.")
        return view(request, *args, **kwargs)

    return api_login_required(wrapper)


def author_required(view):
    """Signed-in users who may author dashboards for at least one module."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not scope_for(request.user).author_domains:
            return error(403, "forbidden", "Your role does not include managing dashboards.")
        return view(request, *args, **kwargs)

    return api_login_required(wrapper)


def dashboard_dict(d: PortalDashboard) -> dict:
    return {
        "key": d.key,
        "title": d.title,
        "description": d.description,
        "domain": d.domain,
        "kind": d.kind,
        "superset_ref": d.superset_ref,
        "visible": d.visible,
        "position": d.position,
        "editor_url": f"{public_url()}/superset/dashboard/{d.superset_ref}/",
    }


# ------------------------------------------------------------------------------- status
@require_GET
@admin_required
def status(request):
    service = KpiService()
    modules = []
    warehouse_ok = True
    for domain in ("hr", "accounts"):
        try:
            modules.append(service.freshness(domain))
        except Exception:
            log.exception("status: freshness of %s failed", domain)
            warehouse_ok = False
            modules.append({"domain": domain, "error": "warehouse not reachable"})
    gateway = SupersetGateway()
    superset_ok = gateway.ping()
    service_ok = False
    if superset_ok:
        try:
            gateway.dashboard(PortalDashboard.objects.filter(kind="official").first().superset_ref)
            service_ok = True
        except (SupersetUnavailable, DashboardNotFound, AttributeError) as exc:
            log.warning("status: service account check failed: %s", exc)
    users = get_user_model().objects.all()
    return JsonResponse(
        {
            "status": "ok",
            "warehouse": {"reachable": warehouse_ok, "consumer_data": warehouse.consumer_data()},
            "modules": modules,
            "superset": {
                "reachable": superset_ok,
                "service_account": service_ok,
                "public_url": settings.DRUKSMART_SUPERSET["PUBLIC_URL"],
            },
            "assistant": provider_status(),
            "counts": {
                "users": users.count(),
                "active_users": users.filter(is_active=True).count(),
                "dashboards": PortalDashboard.objects.count(),
                "visible_dashboards": PortalDashboard.objects.filter(visible=True).count(),
            },
        }
    )


# --------------------------------------------------------------------------- dashboards
@require_http_methods(["GET", "POST"])
@author_required
def dashboards(request):
    scope = scope_for(request.user)
    if request.method == "GET":
        mine = PortalDashboard.objects.filter(domain__in=sorted(scope.author_domains))
        return JsonResponse(
            {
                "status": "ok",
                "dashboards": [dashboard_dict(d) for d in mine],
                "author_domains": sorted(scope.author_domains),
            }
        )
    try:
        body = json_body(request)
    except ValueError as exc:
        return error(400, "invalid_request", str(exc))
    ref = str(body.get("superset_ref", "")).strip()
    domain = body.get("domain")
    if not SUPERSET_REF.match(ref):
        return error(400, "invalid_request", "Enter the Superset dashboard's slug or numeric id.")
    if domain not in ("hr", "accounts"):
        return error(400, "invalid_request", "Choose the module: hr or accounts.")
    if not scope.can_author(domain):
        return error(403, "forbidden", f"You cannot publish dashboards on the {domain} page.")
    if PortalDashboard.objects.filter(superset_ref=ref).exists():
        return error(409, "exists", "This Superset dashboard is already registered.")
    gateway = SupersetGateway()
    try:
        gateway.set_embedded(ref, [settings.DRUKSMART_SUPERSET["WEB_ORIGIN"]])
        info = gateway.dashboard(ref)
    except DashboardNotFound:
        return error(404, "not_found", "No Superset dashboard with this slug or id is visible.")
    except SupersetUnavailable:
        return error(503, "bi_unavailable", "Superset is not reachable right now.")
    allowed = access_rules().domain_tables[domain]
    outside = sorted(set(info.datasets) - allowed)
    if not info.datasets:
        return error(400, "invalid_dashboard", "The dashboard has no charts yet.")
    if outside:
        return error(
            400,
            "invalid_dashboard",
            f"The dashboard uses data outside the {domain} module: {', '.join(outside)}.",
        )
    title = str(body.get("title") or info.title).strip()[:120] or ref
    key = slugify(f"{domain}-{title}")[:64] or slugify(ref)
    if PortalDashboard.objects.filter(key=key).exists():
        key = f"{key[:55]}-{info.id}"
    dashboard = PortalDashboard.objects.create(
        key=key,
        title=title,
        description=str(body.get("description") or "")[:300],
        domain=domain,
        kind=PortalDashboard.CUSTOM,
        superset_ref=ref,
        visible=bool(body.get("visible", False)),
    )
    log.info("dashboard %s registered by %s (%s)", key, request.user.get_username(), ref)
    return JsonResponse({"status": "ok", "dashboard": dashboard_dict(dashboard)}, status=201)


@require_http_methods(["PATCH", "DELETE"])
@author_required
def dashboard(request, key: str):
    d = PortalDashboard.objects.filter(key=key).first()
    if d is None or not scope_for(request.user).can_author(d.domain):
        # Dashboards of another module look the same as unknown ones.
        return error(404, "not_found", "Unknown dashboard.")
    if request.method == "DELETE":
        if d.kind == PortalDashboard.OFFICIAL:
            return error(400, "invalid_request", "Official dashboards can be hidden, not removed.")
        d.delete()
        log.info("dashboard %s unregistered by %s", key, request.user.get_username())
        return JsonResponse({"status": "ok"})
    try:
        body = json_body(request)
    except ValueError as exc:
        return error(400, "invalid_request", str(exc))
    unknown = set(body) - {"visible", "title", "description", "position"}
    if unknown:
        return error(400, "invalid_request", f"Cannot change: {', '.join(sorted(unknown))}.")
    if "visible" in body:
        if not isinstance(body["visible"], bool):
            return error(400, "invalid_request", "visible must be true or false.")
        d.visible = body["visible"]
    if "title" in body:
        title = str(body["title"]).strip()
        if not title:
            return error(400, "invalid_request", "The title cannot be empty.")
        d.title = title[:120]
    if "description" in body:
        d.description = str(body["description"])[:300]
    if "position" in body:
        try:
            d.position = max(0, min(32767, int(body["position"])))
        except (TypeError, ValueError):
            return error(400, "invalid_request", "position must be a number.")
    d.save()
    log.info("dashboard %s changed by %s: %s", key, request.user.get_username(), sorted(body))
    return JsonResponse({"status": "ok", "dashboard": dashboard_dict(d)})


# -------------------------------------------------------------------------------- users
@require_GET
@admin_required
def users(request):
    branches: dict[int, list[str]] = {}
    for b in BranchScope.objects.all():
        branches.setdefault(b.user_id, []).append(b.branch_key)
    rows = []
    for u in get_user_model().objects.prefetch_related("groups").order_by("username"):
        scope = scope_for(u) if u.is_active else None
        rows.append(
            {
                "username": u.username,
                "active": u.is_active,
                "administrator": u.is_superuser,
                "roles": sorted(g.name for g in u.groups.all()),
                "modules": sorted(scope.domains) if scope else [],
                "branches": sorted(branches.get(u.id, [])),
                "last_login": u.last_login.isoformat() if u.last_login else None,
            }
        )
    return JsonResponse(
        {
            "status": "ok",
            "users": rows,
            "roles": [{"role": r, "modules": sorted(d)} for r, d in ROLE_DOMAINS.items()],
            "manage_url": "/admin/auth/user/",
        }
    )
