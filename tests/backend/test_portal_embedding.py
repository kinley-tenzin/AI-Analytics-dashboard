"""Dashboard list and guest tokens for embedded Superset dashboards (portal, Task 10.5).

Superset is replaced by an httpx MockTransport that records what the backend asks for, so these
tests prove WHAT the backend requests (dashboard resource, RLS rules) for each user. The live
tests against the running Superset are in tests/superset/test_embedding_live.py.
"""

from __future__ import annotations

import httpx
import pytest
from django.test import Client
from fake_superset import FakeSuperset
from portal import dashboards as portal_dashboards
from portal.models import PortalDashboard
from portal.superset import AccessRules, SupersetGateway

pytestmark = pytest.mark.django_db

PASSWORD = "pw-for-tests"


@pytest.fixture
def superset(monkeypatch, settings):
    fake = FakeSuperset()
    settings.DRUKSMART_SUPERSET = {
        **settings.DRUKSMART_SUPERSET,
        "SERVICE_PASSWORD": "service-pw",
        "PUBLIC_URL": "http://127.0.0.1:8088",
    }
    transport = httpx.MockTransport(fake.handler)
    monkeypatch.setattr(portal_dashboards, "SupersetGateway", lambda: SupersetGateway(transport))
    SupersetGateway.forget()
    yield fake
    SupersetGateway.forget()


def signed_in(role_user, username, role, branches=()):
    role_user(username, role, branches=branches)
    client = Client()
    client.login(username=username, password=PASSWORD)
    return client


def token(client, key="hr"):
    return client.post(f"/api/v1/portal/dashboards/{key}/guest-token/")


# --- dashboard list ---------------------------------------------------------------------------


def test_dashboard_list_follows_the_users_modules(role_user, superset):
    client = signed_in(role_user, "em_exec_list", "DrukSmart Executive")
    data = client.get("/api/v1/portal/dashboards/").json()
    assert [d["key"] for d in data["dashboards"]] == ["accounts", "hr"]
    assert data["can_author"] is False and data["author_domains"] == []
    assert all("editor_url" not in d for d in data["dashboards"])


def test_module_managers_get_the_native_editor_link_for_their_module(role_user, superset):
    """ADR-044: the HR Manager authors HR dashboards (in Superset), nothing else."""
    client = signed_in(role_user, "em_hr", "DrukSmart HR Manager")
    data = client.get("/api/v1/portal/dashboards/").json()
    assert data["can_author"] is True and data["author_domains"] == ["hr"]
    editor = {d["key"]: d.get("editor_url") for d in data["dashboards"]}
    assert editor == {"hr": "http://127.0.0.1:8088/superset/dashboard/druksmart-hr/"}


def test_branch_managers_never_author(role_user, superset):
    client = signed_in(
        role_user, "em_branch_author", "DrukSmart Branch Manager", branches=("odoo:odoo-sandbox:1",)
    )
    data = client.get("/api/v1/portal/dashboards/").json()
    assert data["can_author"] is False
    assert all("editor_url" not in d for d in data["dashboards"])


def test_hidden_dashboards_are_not_listed_and_get_no_token(role_user, superset):
    PortalDashboard.objects.filter(key="hr").update(visible=False)
    client = signed_in(role_user, "em_hidden", "DrukSmart Executive")
    assert [d["key"] for d in client.get("/api/v1/portal/dashboards/").json()["dashboards"]] == [
        "accounts"
    ]
    assert token(client, "hr").status_code == 404
    assert superset.guest_requests == []


# --- authorisation ----------------------------------------------------------------------------


def test_guest_token_requires_sign_in_and_csrf(role_user, superset):
    assert Client().post("/api/v1/portal/dashboards/hr/guest-token/").status_code == 401
    role_user("em_csrf", "DrukSmart HR Manager")
    client = Client(enforce_csrf_checks=True)
    client.login(username="em_csrf", password=PASSWORD)
    assert token(client).status_code == 403
    assert client.get("/api/v1/portal/dashboards/hr/guest-token/").status_code == 405
    assert superset.guest_requests == []


def test_no_token_for_a_module_outside_the_role(role_user, superset):
    client = signed_in(role_user, "em_hr2", "DrukSmart HR Manager")
    response = token(client, "accounts")
    assert response.status_code == 403 and response.json()["status"] == "forbidden"
    assert superset.guest_requests == []


def test_no_token_for_a_user_without_role_or_unknown_dashboard(role_user, superset):
    client = signed_in(role_user, "em_none", None)
    assert token(client, "hr").status_code == 403
    assert token(client, "does-not-exist").status_code == 404
    assert superset.guest_requests == []


def test_executive_token_is_for_one_dashboard_without_rls(role_user, superset):
    client = signed_in(role_user, "em_exec", "DrukSmart Executive")
    response = token(client, "accounts")
    assert response.status_code == 200
    data = response.json()
    assert data["token"] == "guest-token-abc"
    assert data["embedded_id"] == "uuid-druksmart-accounts"
    assert data["superset_url"] == "http://127.0.0.1:8088" and data["expires_in"] == 300
    (request,) = superset.guest_requests
    assert request["resources"] == [{"type": "dashboard", "id": "uuid-druksmart-accounts"}]
    assert request["rls"] == []
    assert request["user"]["username"] == "web:em_exec"


def test_branch_manager_token_filters_every_branch_dataset(role_user, superset):
    client = signed_in(
        role_user, "em_branch", "DrukSmart Branch Manager", branches=("odoo:odoo-sandbox:1",)
    )
    assert token(client, "hr").json()["branch_restricted"] is True
    assert token(client, "accounts").status_code == 200
    hr, accounts = superset.guest_requests
    clause = "branch_key IN ('odoo:odoo-sandbox:1')"
    assert hr["rls"] == [{"dataset": 2, "clause": clause}, {"dataset": 1, "clause": clause}]
    assert accounts["rls"] == [{"dataset": 3, "clause": clause}]


def test_branch_manager_without_branch_gets_no_token(role_user, superset):
    client = signed_in(role_user, "em_nobranch", "DrukSmart Branch Manager")
    response = token(client)
    assert response.status_code == 403
    assert superset.guest_requests == []


def test_malformed_branch_key_is_refused_not_passed_on(role_user, superset):
    client = signed_in(
        role_user, "em_inject", "DrukSmart Branch Manager", branches=("x') OR ('1'='1",)
    )
    assert token(client).status_code == 403
    assert superset.guest_requests == []


def test_dashboard_using_another_modules_data_is_refused_to_everyone(role_user, superset):
    """A creator added an Accounts chart to the HR dashboard: HR viewers must not see it."""
    superset.datasets["druksmart-hr"].append(("kpi_receivables_payables", 3))
    client = signed_in(role_user, "em_mixed", "DrukSmart Executive")
    response = token(client, "hr")
    assert response.status_code == 403 and response.json()["status"] == "dashboard_not_permitted"
    assert superset.guest_requests == []


def test_branch_user_is_refused_a_dataset_that_cannot_be_branch_filtered(
    role_user, superset, monkeypatch
):
    rules = AccessRules(
        domain_tables={"hr": frozenset({"kpi_headcount", "unfiltered"})},
        branch_filtered=frozenset({"kpi_headcount"}),
        branch_neutral=frozenset(),
    )
    monkeypatch.setattr(portal_dashboards, "access_rules", lambda: rules)
    superset.datasets["druksmart-hr"] = [("kpi_headcount", 1), ("unfiltered", 9)]
    branch = signed_in(role_user, "em_b2", "DrukSmart Branch Manager", branches=("odoo:x:1",))
    assert token(branch).status_code == 403
    executive = signed_in(role_user, "em_e2", "DrukSmart Executive")
    assert token(executive).status_code == 200  # not branch-restricted: no RLS needed


# --- failures ---------------------------------------------------------------------------------


def test_superset_down_gives_json_503(role_user, superset):
    superset.down = True
    client = signed_in(role_user, "em_down", "DrukSmart HR Manager")
    response = token(client)
    assert response.status_code == 503 and response.json()["status"] == "bi_unavailable"


def test_dashboard_missing_in_superset_gives_404(role_user, superset):
    PortalDashboard.objects.filter(key="hr").update(superset_ref="deleted-dashboard")
    client = signed_in(role_user, "em_gone", "DrukSmart HR Manager")
    assert token(client).status_code == 404


def test_service_account_signs_in_once_and_metadata_is_cached(role_user, superset):
    client = signed_in(role_user, "em_cache", "DrukSmart HR Manager")
    for _ in range(3):
        assert token(client).status_code == 200
    assert superset.logins == 1


def test_app_page_may_frame_only_superset(client, settings, tmp_path):
    (tmp_path / "index.html").write_text("<div id=root></div>", encoding="utf-8")
    settings.DRUKSMART_FRONTEND_DIST = tmp_path
    csp = client.get("/app/")["Content-Security-Policy"]
    assert f"frame-src {settings.DRUKSMART_SUPERSET['PUBLIC_URL']}" in csp
    assert "frame-ancestors 'none'" in csp


def test_access_rules_come_from_the_superset_definitions():
    from portal.superset import access_rules

    rules = access_rules()
    assert rules.domain_tables["hr"] == {
        "kpi_headcount",
        "kpi_approved_leave_monthly",
        "data_freshness",
    }
    assert rules.domain_tables["accounts"] == {"kpi_receivables_payables", "data_freshness"}
    assert rules.branch_filtered == {
        "kpi_headcount",
        "kpi_approved_leave_monthly",
        "kpi_receivables_payables",
    }
    assert rules.branch_neutral == {"data_freshness"}
