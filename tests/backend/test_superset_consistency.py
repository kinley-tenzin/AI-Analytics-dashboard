"""The Django KPI service and Superset return the SAME numbers (markers: superset, backend).

Superset is queried through its own chart-data API with its certified metrics; the KPI service
through its registry. Both read the same published KPI views with different restricted accounts.
Skipped when Superset or the warehouse is not running.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
import pytest
from backend_support import ADMIN, BRANCH, warehouse_available
from dotenv import load_dotenv
from kpi.service import KpiRequest, KpiService

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "superset" / "scripts"))
from superset_api import SupersetClient  # noqa: E402

load_dotenv(REPO / ".env", override=False)
BASE = f"http://127.0.0.1:{os.environ.get('SUPERSET_PORT', '8088')}"


def _superset_up() -> bool:
    try:
        return httpx.get(f"{BASE}/health", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = [
    pytest.mark.superset,
    pytest.mark.backend,
    pytest.mark.skipif(
        not (_superset_up() and warehouse_available()), reason="Superset or warehouse not running"
    ),
]


@pytest.fixture(scope="module")
def superset():
    clients = {}

    def get(user: str) -> SupersetClient:
        if user not in clients:
            if user == "admin":
                clients[user] = SupersetClient.login(
                    BASE, os.environ["SUPERSET_ADMIN_USER"], os.environ["SUPERSET_ADMIN_PASSWORD"]
                )
            else:
                clients[user] = SupersetClient.login(
                    BASE, user, os.environ["SUPERSET_DEMO_USER_PASSWORD"]
                )
        return clients[user]

    yield get
    for c in clients.values():
        c.http.close()


def superset_value(api, table, metric, *, filters=(), columns=()):
    ds = api.find_one("dataset", "table_name", table)
    resp = api.request(
        "POST",
        "/api/v1/chart/data",
        json={
            "datasource": {"id": ds["id"], "type": "table"},
            "queries": [
                {
                    "metrics": [metric],
                    "columns": list(columns),
                    "filters": list(filters),
                    "row_limit": 1000,
                }
            ],
            "result_type": "full",
            "force": True,
        },
    )
    assert resp.status_code == 200, resp.text[:300]
    return resp.json()["result"][0]["data"]


def at(d):
    return {"col": "snapshot_date", "op": "==", "val": d}


@pytest.mark.parametrize(
    ("function", "measure", "table", "metric"),
    [
        ("hr.active_headcount", "active_headcount", "kpi_headcount", "active_headcount"),
        (
            "ac.outstanding_receivables",
            "outstanding_amount",
            "kpi_receivables_payables",
            "outstanding_receivables",
        ),
        (
            "ac.outstanding_payables",
            "outstanding_amount",
            "kpi_receivables_payables",
            "outstanding_payables",
        ),
    ],
)
@pytest.mark.parametrize(("user", "scope"), [("admin", ADMIN), ("demo_branch", BRANCH)])
def test_totals_match_superset(superset, function, measure, table, metric, user, scope):
    result = KpiService().run(KpiRequest(function), scope)
    expected = superset_value(superset(user), table, metric, filters=[at(result.as_of)])
    assert sum(r[measure] for r in result.rows) == pytest.approx(expected[0][metric])


def test_headcount_by_department_matches_superset(superset):
    result = KpiService().run(KpiRequest("hr.active_headcount", group_by="department"), ADMIN)
    rows = superset_value(
        superset("admin"),
        "kpi_headcount",
        "active_headcount",
        filters=[at(result.as_of)],
        columns=["department_name"],
    )
    assert {r["department"]: r["active_headcount"] for r in result.rows} == {
        r["department_name"]: r["active_headcount"] for r in rows
    }


def test_overdue_matches_superset(superset):
    result = KpiService().run(KpiRequest("ac.overdue_balance"), ADMIN)
    api = superset("admin")
    for ledger, metric in (("receivable", "overdue_receivables"), ("payable", "overdue_payables")):
        expected = superset_value(
            api, "kpi_receivables_payables", metric, filters=[at(result.as_of)]
        )[0][metric]
        got = sum(r["overdue_amount"] for r in result.rows if r["ledger"] == ledger)
        assert got == pytest.approx(expected)


def test_leave_requests_and_days_match_superset_monthly_view(superset):
    result = KpiService().run(
        KpiRequest("hr.approved_leave", period_start="2026-10-01", period_end="2026-10-31"), ADMIN
    )
    month = {"col": "period_month", "op": "==", "val": "2026-10-01"}
    api = superset("admin")
    requests = superset_value(
        api, "kpi_approved_leave_monthly", "approved_requests", filters=[month]
    )
    days = superset_value(api, "kpi_approved_leave_monthly", "approved_leave_days", filters=[month])
    assert result.rows[0]["approved_requests"] == requests[0]["approved_requests"]
    assert result.rows[0]["approved_leave_days"] == pytest.approx(days[0]["approved_leave_days"])
