"""Embedded dashboards against the RUNNING Superset (marker: superset; Task 10.5).

Guest tokens are minted by the real backend code (portal.superset / portal.dashboards) with the
real portal service account, then used against Superset exactly as the Embedded SDK uses them
(header X-GuestToken). Proves: a token opens ONLY its dashboard; forged, tampered and expired
tokens are rejected (so the public default signing secret is not in use); only the website may
frame Superset and load the embedded page. That the RLS rules filter every chart is checked in
the browser by frontend/scripts/browser_check.py (iframe values vs the warehouse).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from pathlib import Path

import httpx
import pytest
from dotenv import dotenv_values

pytestmark = [pytest.mark.superset, pytest.mark.django_db]

REPO = Path(__file__).resolve().parents[2]
ENV = dotenv_values(REPO / ".env")
BASE = f"http://127.0.0.1:{ENV.get('SUPERSET_PORT') or '8088'}"
WEB_ORIGIN = (ENV.get("DRUKSMART_WEB_ORIGIN") or "http://127.0.0.1:8000").rstrip("/")
PUBLIC_DEFAULT_SECRET = "test-guest-secret-change-me"  # Superset's built-in default


def _ready() -> bool:
    try:
        up = httpx.get(f"{BASE}/health", timeout=5).status_code == 200
    except httpx.HTTPError:
        return False
    return up and bool(ENV.get("SUPERSET_PORTAL_SERVICE_PASSWORD"))


if not _ready():
    pytest.skip(
        "Superset not running or the portal service account is not configured",
        allow_module_level=True,
    )


@pytest.fixture(scope="module")
def gateway():
    from portal.superset import SupersetGateway

    SupersetGateway.forget()
    return SupersetGateway()


@pytest.fixture(scope="module")
def dashboards(gateway):
    return {
        key: gateway.dashboard(ref)
        for key, ref in (("hr", "druksmart-hr"), ("accounts", "druksmart-accounts"))
    }


def as_guest(token: str, path: str) -> httpx.Response:
    return httpx.get(f"{BASE}{path}", headers={"X-GuestToken": token}, timeout=20)


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def sign(claims: dict, secret: str) -> str:
    head = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = b64(json.dumps(claims).encode())
    mac = hmac.new(secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{b64(mac)}"


def claims_of(token: str) -> dict:
    body = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


# --- tokens -----------------------------------------------------------------------------------


def test_token_opens_its_own_dashboard_only(gateway, dashboards):
    hr, accounts = dashboards["hr"], dashboards["accounts"]
    token = gateway.guest_token(hr, "live_test", [])
    assert as_guest(token, f"/api/v1/dashboard/{hr.id}/charts").status_code == 200
    other = as_guest(token, f"/api/v1/dashboard/{accounts.id}/charts")
    assert other.status_code in (403, 404), other.status_code


def test_token_lists_only_charts_of_its_dashboard(gateway, dashboards):
    hr = dashboards["hr"]
    token = gateway.guest_token(hr, "live_test", [])
    charts = as_guest(token, f"/api/v1/dashboard/{hr.id}/charts").json()["result"]
    names = {c["slice_name"] for c in charts}
    assert "Active headcount" in names
    assert not any("receivable" in n.lower() or "payable" in n.lower() for n in names)


def test_branch_rls_is_carried_in_the_signed_token(gateway, dashboards):
    from access.scope import Scope
    from portal.dashboards import guest_rls
    from portal.models import PortalDashboard

    scope = Scope(
        "live_branch",
        ("DrukSmart Branch Manager",),
        frozenset({"hr"}),
        frozenset({"odoo:odoo-sandbox:1"}),
    )
    rls = guest_rls(scope, PortalDashboard.objects.get(key="hr"), dashboards["hr"])
    token = gateway.guest_token(dashboards["hr"], "live_branch", rls)
    rules = claims_of(token)["rls_rules"]
    assert {r["dataset"] for r in rules} == {
        dashboards["hr"].datasets["kpi_headcount"],
        dashboards["hr"].datasets["kpi_approved_leave_monthly"],
    }
    assert all(r["clause"] == "branch_key IN ('odoo:odoo-sandbox:1')" for r in rules)
    assert claims_of(token)["exp"] - time.time() <= 300 + 5


def test_token_signed_with_the_public_default_secret_is_rejected(gateway, dashboards):
    hr = dashboards["hr"]
    real = claims_of(gateway.guest_token(hr, "live_test", []))
    forged = sign(real, PUBLIC_DEFAULT_SECRET)
    assert as_guest(forged, f"/api/v1/dashboard/{hr.id}/charts").status_code in (401, 403)


def test_tampered_token_is_rejected(gateway, dashboards):
    """Removing the RLS rules (or changing the dashboard) breaks the signature."""
    hr, accounts = dashboards["hr"], dashboards["accounts"]
    token = gateway.guest_token(hr, "live_test", [{"dataset": 1, "clause": "1 = 0"}])
    head, _, mac = token.split(".")
    claims = claims_of(token)
    claims["rls_rules"] = []
    claims["resources"] = [{"type": "dashboard", "id": accounts.embedded_id}]
    tampered = f"{head}.{b64(json.dumps(claims).encode())}.{mac}"
    assert as_guest(tampered, f"/api/v1/dashboard/{accounts.id}/charts").status_code in (401, 403)


def test_expired_token_is_rejected(gateway, dashboards):
    hr = dashboards["hr"]
    secret = ENV.get("SUPERSET_GUEST_TOKEN_SECRET")
    if not secret:
        pytest.skip("SUPERSET_GUEST_TOKEN_SECRET not in .env")
    claims = claims_of(gateway.guest_token(hr, "live_test", []))
    valid = sign(claims, secret)  # control: our signature is accepted
    assert as_guest(valid, f"/api/v1/dashboard/{hr.id}/charts").status_code == 200
    expired = sign({**claims, "iat": time.time() - 900, "exp": time.time() - 600}, secret)
    assert as_guest(expired, f"/api/v1/dashboard/{hr.id}/charts").status_code in (401, 403)


def test_service_account_cannot_change_dashboards_or_use_sql_lab(gateway):
    client = httpx.Client(base_url=BASE, timeout=20)
    headers = gateway._bearer(client)
    csrf = client.get("/api/v1/security/csrf_token/", headers=headers).json()["result"]
    write = client.put(
        "/api/v1/dashboard/druksmart-hr",
        json={"dashboard_title": "changed by test"},
        headers={**headers, "X-CSRFToken": csrf, "Referer": BASE},
    )
    assert write.status_code == 403
    assert client.get("/api/v1/sqllab/", headers=headers).status_code == 403


# --- framing ----------------------------------------------------------------------------------


def test_embedded_page_loads_only_from_the_website(dashboards):
    path = f"{BASE}/embedded/{dashboards['hr'].embedded_id}"
    assert httpx.get(path, headers={"Referer": f"{WEB_ORIGIN}/"}, timeout=20).status_code == 200
    assert (
        httpx.get(path, headers={"Referer": "http://evil.example/"}, timeout=20).status_code == 403
    )
    assert httpx.get(path, timeout=20).status_code == 403  # no Referer at all


def test_only_the_website_may_frame_superset():
    response = httpx.get(f"{BASE}/login/", timeout=20)
    csp = response.headers["Content-Security-Policy"]
    ancestors = next(p for p in csp.split(";") if "frame-ancestors" in p).split()[1:]
    assert ancestors == ["'self'", WEB_ORIGIN]


def test_embedding_is_unknown_for_dashboards_not_enabled(dashboards):
    assert (
        httpx.get(
            f"{BASE}/embedded/00000000-0000-0000-0000-000000000000",
            headers={"Referer": f"{WEB_ORIGIN}/"},
            timeout=20,
        ).status_code
        == 404
    )
