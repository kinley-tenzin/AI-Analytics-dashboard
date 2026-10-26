"""Overview API of the web application (backend/portal/overview.py, Task 10.4)."""

from __future__ import annotations

import pytest
from backend_support import DEMO_BRANCH, warehouse_available
from kpi.service import KpiRequest, KpiResult, KpiService, NoData
from portal.overview import OVERVIEW_TILES

pytestmark = pytest.mark.django_db


def fake_result(function: str, domain: str, *, stale=False, synthetic=False) -> KpiResult:
    return KpiResult(
        function=function,
        kpi_ids=["X"],
        title=function,
        domain=domain,
        dataset="marts.x",
        as_of="2026-10-25",
        period=None,
        group_by=[],
        filters={},
        branch_restricted=False,
        columns=[{"name": "v", "label": "V", "unit": "count"}],
        rows=[{"v": 1}],
        freshness=[
            {
                "source_instance": "odoo-sandbox",
                "data_as_of": "2026-10-25",
                "published_at": "2026-10-25T00:00:00+00:00",
                "source_mode": "configured",
            }
        ],
        notes=[],
        hours_since_publication=3.0 if domain == "hr" else 5.0,
        stale=stale,
        synthetic=synthetic,
    )


@pytest.fixture
def fake_service(monkeypatch):
    calls: list[tuple[str, str]] = []

    def run(self, request: KpiRequest, scope):
        calls.append((request.function, scope.username))
        domain = "hr" if request.function.startswith("hr.") else "accounts"
        if request.function == "hr.approved_leave":
            raise NoData("No approved leave in the period.")
        return fake_result(request.function, domain, stale=request.function == "ac.ageing")

    monkeypatch.setattr(KpiService, "run", run)
    return calls


def test_overview_requires_sign_in(client):
    assert client.get("/api/v1/portal/overview/").status_code == 401


def test_hr_user_gets_only_hr_tiles(client, role_user, fake_service):
    role_user("ov_hr", "DrukSmart HR Manager")
    client.login(username="ov_hr", password="pw-for-tests")
    data = client.get("/api/v1/portal/overview/").json()
    assert data["domains"] == ["hr"]
    assert set(data["tiles"]) == {key for key, _ in OVERVIEW_TILES["hr"]}
    assert all(fn.startswith("hr.") for fn, _ in fake_service)


def test_accounts_user_gets_only_accounts_tiles(client, role_user, fake_service):
    role_user("ov_acc", "DrukSmart Accounts Manager")
    client.login(username="ov_acc", password="pw-for-tests")
    data = client.get("/api/v1/portal/overview/").json()
    assert set(data["tiles"]) == {key for key, _ in OVERVIEW_TILES["accounts"]}


def test_no_data_tile_is_reported_not_hidden(client, role_user, fake_service):
    role_user("ov_nodata", "DrukSmart Executive")
    client.login(username="ov_nodata", password="pw-for-tests")
    tiles = client.get("/api/v1/portal/overview/").json()["tiles"]
    assert tiles["leave"] == {"status": "no_data", "message": "No approved leave in the period."}
    assert tiles["headcount"]["status"] == "ok"


def test_summary_takes_the_most_cautious_freshness(client, role_user, fake_service):
    role_user("ov_sum", "DrukSmart Executive")
    client.login(username="ov_sum", password="pw-for-tests")
    summary = client.get("/api/v1/portal/overview/").json()["summary"]
    assert summary["stale"] is True  # one tile stale -> the overview says stale
    assert summary["hours_since_publication"] == 5.0
    assert {(f["domain"], f["source_instance"]) for f in summary["freshness"]} == {
        ("hr", "odoo-sandbox"),
        ("accounts", "odoo-sandbox"),
    }


def test_user_without_role_gets_nothing(client, role_user, fake_service):
    role_user("ov_none", None)
    client.login(username="ov_none", password="pw-for-tests")
    data = client.get("/api/v1/portal/overview/").json()
    assert data == {"status": "ok", "domains": [], "tiles": {}, "summary": None}
    assert fake_service == []


def test_warehouse_down_gives_json_503(client, role_user, monkeypatch):
    def broken(self, request, scope):
        raise OSError("connection refused")

    monkeypatch.setattr(KpiService, "run", broken)
    role_user("ov_down", "DrukSmart HR Manager")
    client.login(username="ov_down", password="pw-for-tests")
    response = client.get("/api/v1/portal/overview/")
    assert response.status_code == 503 and response.json()["status"] == "error"


# --- against the real published warehouse ------------------------------------------------------

live = pytest.mark.skipif(not warehouse_available(), reason="warehouse / KPI reader not available")


@pytest.mark.backend
@live
def test_overview_equals_the_kpi_service(client, role_user):
    """Every tile is exactly the registry function's result for the user."""
    from access.scope import scope_for

    user = role_user("ov_exec", "DrukSmart Executive")
    client.login(username="ov_exec", password="pw-for-tests")
    tiles = client.get("/api/v1/portal/overview/").json()["tiles"]
    for domain in ("hr", "accounts"):
        for key, params in OVERVIEW_TILES[domain]:
            direct = KpiService().run(KpiRequest.from_dict(params), scope_for(user)).to_dict()
            assert tiles[key]["result"]["rows"] == direct["rows"], key


@pytest.mark.backend
@live
def test_branch_manager_overview_is_limited_to_the_branch(client, role_user):
    role_user("ov_exec2", "DrukSmart Executive")
    role_user("ov_branch", "DrukSmart Branch Manager", branches=(DEMO_BRANCH,))
    client.login(username="ov_exec2", password="pw-for-tests")
    everyone = client.get("/api/v1/portal/overview/").json()["tiles"]
    client.login(username="ov_branch", password="pw-for-tests")
    branch = client.get("/api/v1/portal/overview/").json()["tiles"]

    def headcount(tiles):
        return tiles["headcount"]["result"]["rows"][0]["active_headcount"]

    assert branch["headcount"]["result"]["branch_restricted"] is True
    assert 0 < headcount(branch) < headcount(everyone)
