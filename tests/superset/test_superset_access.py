"""Superset access boundary and KPI correctness, against the RUNNING Superset (marker: superset).

    docker compose --profile superset up -d
    python superset/scripts/bootstrap.py
    pytest -m superset -v

Every request goes through Superset's REST API as a real demo user, i.e. through the same
security manager that serves dashboards, Explore and CSV export. Expected values are computed
independently from the dbt FACT tables (not the KPI views Superset reads), in the published
dev warehouse. Nothing here writes to the warehouse; the only Superset objects created (one chart,
one dashboard) are deleted again.
"""

from __future__ import annotations

import csv
import io
import os
import sys
from pathlib import Path

import httpx
import pytest
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "superset" / "scripts"))

from superset_api import SupersetClient  # noqa: E402

from druksmart_common.config import load_settings  # noqa: E402
from druksmart_common.db import connect  # noqa: E402

pytestmark = pytest.mark.superset

load_dotenv(REPO / ".env", override=False)
BASE_URL = f"http://127.0.0.1:{os.environ.get('SUPERSET_PORT', '8088')}"
DEMO_PASSWORD = os.environ.get("SUPERSET_DEMO_USER_PASSWORD", "")
BRANCH = "odoo:odoo-sandbox:1"  # superset/definitions/access.yml, demo branch manager

HR = {"kpi_headcount", "kpi_approved_leave_monthly", "data_freshness"}
ACCOUNTS = {"kpi_receivables_payables", "data_freshness"}
ALL = HR | ACCOUNTS


def _superset_up() -> bool:
    try:
        return httpx.get(f"{BASE_URL}/health", timeout=5).status_code == 200
    except httpx.HTTPError:
        return False


if not _superset_up() or not DEMO_PASSWORD or DEMO_PASSWORD == "CHANGE_ME":
    pytest.skip("Superset not running or demo users not configured", allow_module_level=True)


# ------------------------------------------------------------------------------- fixtures
@pytest.fixture(scope="module")
def clients():
    opened: dict[str, SupersetClient] = {}

    def get(username: str) -> SupersetClient:
        if username not in opened:
            if username == "admin":
                opened[username] = SupersetClient.login(
                    BASE_URL,
                    os.environ["SUPERSET_ADMIN_USER"],
                    os.environ["SUPERSET_ADMIN_PASSWORD"],
                )
            else:
                opened[username] = SupersetClient.login(BASE_URL, username, DEMO_PASSWORD)
        return opened[username]

    yield get
    for c in opened.values():
        c.http.close()


@pytest.fixture(scope="module")
def ids(clients) -> dict[str, int]:
    """Dataset ids by table name (as the admin sees them)."""
    return {d["table_name"]: d["id"] for d in clients("admin").list_all("dataset")}


@pytest.fixture(scope="module")
def warehouse():
    with connect(load_settings().pipeline(), autocommit=True) as conn:
        yield conn


@pytest.fixture(scope="module")
def hr_date(warehouse) -> str:
    return str(
        warehouse.execute("select max(snapshot_date) from marts.fct_headcount_snapshot").fetchone()[
            0
        ]
    )


@pytest.fixture(scope="module")
def ac_date(warehouse) -> str:
    return str(
        warehouse.execute(
            "select max(snapshot_date) from marts.fct_receivable_payable_snapshot"
        ).fetchone()[0]
    )


def chart_data(
    api: SupersetClient,
    dataset_id: int,
    *,
    metrics: list[str],
    columns=(),
    filters=(),
    fmt: str = "json",
) -> httpx.Response:
    payload = {
        "datasource": {"id": dataset_id, "type": "table"},
        "force": True,
        "queries": [
            {
                "metrics": metrics,
                "columns": list(columns),
                "filters": list(filters),
                "row_limit": 1000,
            }
        ],
        "result_format": fmt,
        "result_type": "full",
    }
    return api.request("POST", "/api/v1/chart/data", json=payload)


def rows(resp: httpx.Response) -> list[dict]:
    assert resp.status_code == 200, resp.text[:300]
    return resp.json()["result"][0]["data"]


def at(date: str) -> dict:
    return {"col": "snapshot_date", "op": "==", "val": date}


# ------------------------------------------------------------------------- KPI correctness
def test_headcount_matches_the_warehouse_facts(clients, ids, warehouse, hr_date):
    expected = warehouse.execute(
        "select count(*) from marts.fct_headcount_snapshot "
        "where snapshot_date = %s and employment_status = 'active'",
        (hr_date,),
    ).fetchone()[0]
    data = rows(
        chart_data(
            clients("admin"),
            ids["kpi_headcount"],
            metrics=["active_headcount"],
            filters=[at(hr_date)],
        )
    )
    assert data[0]["active_headcount"] == expected


def test_headcount_by_department_matches(clients, ids, warehouse, hr_date):
    expected = dict(
        warehouse.execute(
            "select d.department_name, count(*) from marts.fct_headcount_snapshot f "
            "join marts.dim_department d using (department_key) "
            "where f.snapshot_date = %s and f.employment_status = 'active' group by 1",
            (hr_date,),
        ).fetchall()
    )
    data = rows(
        chart_data(
            clients("admin"),
            ids["kpi_headcount"],
            metrics=["active_headcount"],
            columns=["department_name"],
            filters=[at(hr_date)],
        )
    )
    got = {r["department_name"]: r["active_headcount"] for r in data if r["active_headcount"]}
    assert got == expected


def test_receivables_payables_overdue_match(clients, ids, warehouse, ac_date):
    expected = warehouse.execute(
        "select sum(outstanding_company) filter (where ledger = 'receivable'), "
        "sum(outstanding_company) filter (where ledger = 'payable'), "
        "sum(outstanding_company) filter (where ledger = 'receivable' and is_overdue), "
        "sum(outstanding_company) filter (where ledger = 'payable' and is_overdue) "
        "from marts.fct_receivable_payable_snapshot where snapshot_date = %s",
        (ac_date,),
    ).fetchone()
    metrics = [
        "outstanding_receivables",
        "outstanding_payables",
        "overdue_receivables",
        "overdue_payables",
    ]
    data = rows(
        chart_data(
            clients("admin"),
            ids["kpi_receivables_payables"],
            metrics=metrics,
            filters=[at(ac_date)],
        )
    )[0]
    for metric, value in zip(metrics, expected, strict=True):
        assert data[metric] == pytest.approx(float(value or 0)), metric


def test_approved_leave_matches(clients, ids, warehouse):
    expected_requests, expected_days = warehouse.execute(
        "select count(*), sum(leave_days) from marts.fct_leave_request "
        "where approval_status = 'approved'"
    ).fetchone()
    data = rows(
        chart_data(
            clients("admin"),
            ids["kpi_approved_leave_monthly"],
            metrics=["approved_requests", "approved_leave_days"],
        )
    )[0]
    assert data["approved_requests"] == expected_requests
    assert data["approved_leave_days"] == pytest.approx(float(expected_days))


def test_freshness_matches_the_publication(clients, ids, warehouse):
    expected = warehouse.execute(
        "select count(*), min(latest_snapshot_date)::text from marts.data_freshness "
        "where published_at is not null"
    ).fetchone()
    resp = clients("admin").request(
        "POST",
        "/api/v1/chart/data",
        json={
            "datasource": {"id": ids["data_freshness"], "type": "table"},
            "queries": [{"columns": ["latest_snapshot_date", "published_at"], "row_limit": 100}],
            "result_type": "full",
        },
    )
    data = rows(resp)
    assert len(data) == expected[0] and all(r["published_at"] for r in data)


# ------------------------------------------------------------------------- dataset access
@pytest.mark.parametrize(
    ("user", "visible"),
    [
        ("demo_hr", HR),
        ("demo_accounts", ACCOUNTS),
        ("demo_executive", ALL),
        ("demo_branch", ALL),
    ],
)
def test_each_role_sees_only_its_datasets(clients, user, visible):
    assert {d["table_name"] for d in clients(user).list_all("dataset")} == visible


@pytest.mark.parametrize(
    ("user", "forbidden", "metric"),
    [
        ("demo_hr", "kpi_receivables_payables", "outstanding_receivables"),
        ("demo_accounts", "kpi_headcount", "active_headcount"),
        ("demo_accounts", "kpi_approved_leave_monthly", "approved_leave_days"),
    ],
)
def test_querying_an_unauthorised_dataset_is_denied(clients, ids, user, forbidden, metric):
    for fmt in ("json", "csv"):  # chart data AND CSV export
        resp = chart_data(clients(user), ids[forbidden], metrics=[metric], fmt=fmt)
        assert resp.status_code == 403, (fmt, resp.status_code, resp.text[:200])


@pytest.mark.parametrize(
    ("user", "dashboards"),
    [
        ("demo_hr", {"druksmart-hr"}),
        ("demo_accounts", {"druksmart-accounts"}),
        ("demo_executive", {"druksmart-hr", "druksmart-accounts"}),
    ],
)
def test_dashboards_visible_per_role(clients, user, dashboards):
    assert {d["slug"] for d in clients(user).list_all("dashboard")} == dashboards


def test_dashboard_of_another_domain_is_denied(clients):
    assert clients("demo_hr").request(
        "GET", "/api/v1/dashboard/druksmart-accounts"
    ).status_code in (403, 404)
    assert clients("demo_accounts").request(
        "GET", "/api/v1/dashboard/druksmart-hr"
    ).status_code in (403, 404)


# ------------------------------------------------------------------------- SQL Lab / raw data
@pytest.mark.parametrize("user", ["demo_hr", "demo_accounts", "demo_executive", "demo_branch"])
def test_sql_lab_is_denied_to_every_druksmart_role(clients, user):
    resp = clients(user).request(
        "POST",
        "/api/v1/sqllab/execute/",
        json={"database_id": 1, "sql": "select 1", "schema": "marts", "runAsync": False},
    )
    assert resp.status_code in (401, 403), resp.text[:200]


def _admin_sql(clients, sql: str) -> httpx.Response:
    db_id = clients("admin").find_one("database", "database_name", "DrukSmart Warehouse")["id"]
    return clients("admin").request(
        "POST",
        "/api/v1/sqllab/execute/",
        json={
            "database_id": db_id,
            "sql": sql,
            "schema": "marts",
            "runAsync": False,
            "client_id": os.urandom(5).hex(),
        },
    )


@pytest.mark.parametrize(
    "sql",
    [
        "select count(*) from raw.source_record",  # raw ERP payloads
        "select count(*) from staging.stg_erpnext__employee",  # staging
        "select employee_name from marts.dim_employee limit 1",  # unapproved mart (names)
        "select count(*) from marts.fct_leave_request",
    ],  # unapproved employee-level fact
)
def test_even_admin_sql_lab_cannot_read_unapproved_relations(clients, sql):
    """The DATABASE ACCOUNT itself can only read the approved datasets."""
    resp = _admin_sql(clients, sql)
    assert resp.status_code != 200 and "permission denied" in resp.text.lower(), resp.text[:300]


def test_admin_sql_lab_reads_approved_dataset_but_cannot_write(clients):
    assert _admin_sql(clients, "select count(*) from marts.kpi_headcount").status_code == 200
    resp = _admin_sql(clients, "delete from marts.kpi_headcount")
    assert resp.status_code != 200, "DML must be refused"


# ------------------------------------------------------------------------- row-level security
def test_branch_manager_sees_only_their_branch(clients, ids, warehouse, hr_date, ac_date):
    api = clients("demo_branch")
    headcount = warehouse.execute(
        "select count(*) from marts.fct_headcount_snapshot "
        "where snapshot_date = %s and employment_status = 'active' and branch_key = %s",
        (hr_date, BRANCH),
    ).fetchone()[0]
    total = warehouse.execute(
        "select count(*) from marts.fct_headcount_snapshot "
        "where snapshot_date = %s and employment_status = 'active'",
        (hr_date,),
    ).fetchone()[0]
    assert headcount < total, "demo branch must not hold every employee, or the test proves nothing"
    data = rows(
        chart_data(api, ids["kpi_headcount"], metrics=["active_headcount"], filters=[at(hr_date)])
    )
    assert data[0]["active_headcount"] == headcount

    ar = warehouse.execute(
        "select coalesce(sum(outstanding_company), 0) from marts.fct_receivable_payable_snapshot "
        "where snapshot_date = %s and ledger = 'receivable' and branch_key = %s",
        (ac_date, BRANCH),
    ).fetchone()[0]
    data = rows(
        chart_data(
            api,
            ids["kpi_receivables_payables"],
            metrics=["outstanding_receivables"],
            filters=[at(ac_date)],
        )
    )
    assert data[0]["outstanding_receivables"] == pytest.approx(float(ar))


def test_branch_manager_cannot_filter_their_way_to_other_branches(clients, ids, hr_date):
    api = clients("demo_branch")
    data = rows(
        chart_data(
            api,
            ids["kpi_headcount"],
            metrics=["active_headcount"],
            columns=["branch_key"],
            filters=[at(hr_date)],
        )
    )
    assert {r["branch_key"] for r in data} == {BRANCH}
    other = {"col": "branch_key", "op": "NOT IN", "val": [BRANCH]}
    data = rows(
        chart_data(api, ids["kpi_headcount"], metrics=["active_headcount"], filters=[other])
    )
    assert not data or not data[0]["active_headcount"]


def test_csv_export_respects_row_level_security(clients, ids, ac_date):
    resp = chart_data(
        clients("demo_branch"),
        ids["kpi_receivables_payables"],
        metrics=["outstanding_amount"],
        columns=["branch_key", "ledger"],
        filters=[at(ac_date)],
        fmt="csv",
    )
    assert resp.status_code == 200
    assert "csv" in resp.headers.get("content-type", "")
    # The export uses the governed column labels (datasets.yml) as headers.
    exported = list(csv.DictReader(io.StringIO(resp.text)))
    assert exported and {r["Branch key"] for r in exported} == {BRANCH}


# ------------------------------------------------------------------------- governed definitions
@pytest.mark.parametrize("user", ["demo_executive", "demo_branch"])
def test_viewers_cannot_create_or_change_anything(clients, ids, user):
    api = clients(user)
    chart = {
        "slice_name": "x",
        "viz_type": "table",
        "datasource_id": ids["data_freshness"],
        "datasource_type": "table",
        "params": "{}",
    }
    assert api.request("POST", "/api/v1/chart/", json=chart).status_code == 403
    assert (
        api.request("POST", "/api/v1/dashboard/", json={"dashboard_title": "x"}).status_code == 403
    )
    assert (
        api.request(
            "PUT", f"/api/v1/dataset/{ids['data_freshness']}", json={"description": "x"}
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    ("user", "other", "metric"),
    [
        ("demo_hr", "kpi_receivables_payables", "outstanding_receivables"),
        ("demo_accounts", "kpi_headcount", "active_headcount"),
    ],
)
def test_module_manager_gets_no_data_of_another_module(clients, ids, user, other, metric):
    """ADR-044: a module manager authors with THEIR module's data only.

    Superset checks data access when a chart is QUERIED, not when it is saved: a manager can save a
    chart that points at another module's dataset, but it never returns data (and the website
    refuses to publish a dashboard containing it). The test chart is removed by the admin, because
    Superset hides a chart from users without access to its data, even from its owner.
    """
    api = clients(user)
    assert other not in {d["table_name"] for d in api.list_all("dataset")}
    chart = api.request(
        "POST",
        "/api/v1/chart/",
        json={
            "slice_name": "pytest other module",
            "viz_type": "big_number_total",
            "datasource_id": ids[other],
            "datasource_type": "table",
            "params": f'{{"metric": "{metric}"}}',
        },
    )
    try:
        for fmt in ("json", "csv"):
            resp = chart_data(api, ids[other], metrics=[metric], fmt=fmt)
            assert resp.status_code == 403, (fmt, resp.status_code)
    finally:
        if chart.status_code == 201:
            clients("admin").request("DELETE", f"/api/v1/chart/{chart.json()['id']}")


def test_creator_can_build_charts_and_dashboards_but_not_change_governed_metrics(clients, ids):
    api = clients("demo_hr")  # the HR Manager (ADR-044)
    chart = api.request(
        "POST",
        "/api/v1/chart/",
        json={
            "slice_name": "pytest creator chart",
            "viz_type": "big_number_total",
            "datasource_id": ids["kpi_headcount"],
            "datasource_type": "table",
            "params": '{"metric": "active_headcount"}',
        },
    )
    dash = api.request(
        "POST", "/api/v1/dashboard/", json={"dashboard_title": "pytest creator dash"}
    )
    try:
        assert chart.status_code == 201, chart.text[:300]
        assert dash.status_code == 201, dash.text[:300]
        # Governed dataset metrics cannot be edited ...
        resp = api.request(
            "PUT",
            f"/api/v1/dataset/{ids['kpi_headcount']}",
            json={"metrics": [{"metric_name": "active_headcount", "expression": "COUNT(*)"}]},
        )
        assert resp.status_code == 403
        # ... nor can the admin-owned default dashboard templates (creators save their own copy).
        hr = clients("admin").find_one("dashboard", "slug", "druksmart-hr")
        resp = api.request(
            "PUT", f"/api/v1/dashboard/{hr['id']}", json={"dashboard_title": "hacked"}
        )
        assert resp.status_code == 403
    finally:
        if chart.status_code == 201:
            api.request("DELETE", f"/api/v1/chart/{chart.json()['id']}")
        if dash.status_code == 201:
            api.request("DELETE", f"/api/v1/dashboard/{dash.json()['id']}")


def test_creator_cannot_register_new_datasets(clients):
    db = clients("admin").find_one("database", "database_name", "DrukSmart Warehouse")
    resp = clients("demo_hr").request(
        "POST",
        "/api/v1/dataset/",
        json={"database": db["id"], "schema": "marts", "table_name": "dim_employee"},
    )
    assert resp.status_code == 403
