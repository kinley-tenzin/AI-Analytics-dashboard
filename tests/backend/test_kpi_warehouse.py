"""KPI service against the PUBLISHED dev warehouse, as the restricted KPI reader (marker: backend).

Expected values are computed independently from the dbt FACT tables as the pipeline role (not
from the KPI views the service reads). Read-only; skipped when the warehouse or the KPI reader
is not configured.
"""

from __future__ import annotations

import psycopg
import pytest
from backend_support import ADMIN, BRANCH, DEMO_BRANCH, warehouse_available
from kpi.service import Forbidden, KpiRequest, KpiService, NoData

from druksmart_common.config import load_settings
from druksmart_common.db import connect

pytestmark = [
    pytest.mark.backend,
    pytest.mark.skipif(not warehouse_available(), reason="warehouse / KPI reader not available"),
]


@pytest.fixture(scope="module")
def facts():
    with connect(load_settings().pipeline(), autocommit=True) as conn:
        yield conn


@pytest.fixture(scope="module")
def latest(facts):
    hr = facts.execute("select max(snapshot_date) from marts.fct_headcount_snapshot").fetchone()[0]
    ac = facts.execute(
        "select max(snapshot_date) from marts.fct_receivable_payable_snapshot"
    ).fetchone()[0]
    return hr, ac


def run(function, scope=ADMIN, **kw):
    return KpiService().run(KpiRequest(function, **kw), scope)


def one(sql, facts, *params):
    return facts.execute(sql, params).fetchone()[0]


def test_active_headcount(facts, latest):
    expected = one(
        "select count(*) from marts.fct_headcount_snapshot where snapshot_date = %s "
        "and employment_status = 'active'",
        facts,
        latest[0],
    )
    result = run("hr.active_headcount")
    assert result.as_of == latest[0].isoformat()
    assert result.rows == [{"active_headcount": expected}]


def test_headcount_by_department(facts, latest):
    expected = dict(
        facts.execute(
            "select d.department_name, count(*) filter (where f.employment_status = 'active') "
            "from marts.fct_headcount_snapshot f "
            "join marts.dim_department d using (department_key) "
            "where f.snapshot_date = %s group by 1",
            (latest[0],),
        ).fetchall()
    )
    rows = run("hr.active_headcount", group_by="department").rows
    assert {r["department"]: r["active_headcount"] for r in rows} == expected


def test_employment_status(facts, latest):
    expected = dict(
        facts.execute(
            "select employment_status, count(*) from marts.fct_headcount_snapshot "
            "where snapshot_date = %s group by 1",
            (latest[0],),
        ).fetchall()
    )
    rows = run("hr.employment_status").rows
    assert {r["employment_status"]: r["employee_records"] for r in rows} == expected


def test_approved_leave_distinct_employees_over_a_period(facts):
    expected = facts.execute(
        "select count(distinct employee_key), count(*), sum(leave_days) "
        "from marts.fct_leave_request "
        "where approval_status = 'approved' and start_date between %s and %s",
        ("2026-10-01", "2026-10-31"),
    ).fetchone()
    row = run("hr.approved_leave", period_start="2026-10-01", period_end="2026-10-31").rows[0]
    assert (row["employees_on_leave"], row["approved_requests"]) == expected[:2]
    assert row["approved_leave_days"] == pytest.approx(float(expected[2]))


@pytest.mark.parametrize(
    ("function", "where"),
    [
        ("ac.outstanding_receivables", "ledger = 'receivable'"),
        ("ac.outstanding_payables", "ledger = 'payable'"),
    ],
)
def test_outstanding_balances(facts, latest, function, where):
    expected = one(
        f"select sum(outstanding_company) from marts.fct_receivable_payable_snapshot "
        f"where snapshot_date = %s and {where}",
        facts,
        latest[1],
    )
    rows = run(function).rows
    assert len(rows) == 1 and rows[0]["outstanding_amount"] == pytest.approx(float(expected))


def test_overdue_by_ledger_and_by_ageing(facts, latest):
    expected = dict(
        facts.execute(
            "select ledger, sum(outstanding_company) from marts.fct_receivable_payable_snapshot "
            "where snapshot_date = %s and is_overdue group by 1",
            (latest[1],),
        ).fetchall()
    )
    rows = run("ac.overdue_balance").rows
    assert {r["ledger"]: r["overdue_amount"] for r in rows} == pytest.approx(
        {k: float(v) for k, v in expected.items()}
    )
    by_bucket = run("ac.overdue_by_ageing").rows
    assert sum(r["overdue_amount"] for r in by_bucket) == pytest.approx(
        float(sum(expected.values()))
    )
    assert all(r["overdue_amount"] != 0 for r in by_bucket)


def test_branch_scope_restricts_every_result(facts, latest):
    expected = one(
        "select count(*) from marts.fct_headcount_snapshot where snapshot_date = %s "
        "and employment_status = 'active' and branch_key = %s",
        facts,
        latest[0],
        DEMO_BRANCH,
    )
    assert run("hr.active_headcount", BRANCH).rows == [{"active_headcount": expected}]
    rows = run("hr.active_headcount", BRANCH, group_by="branch").rows
    assert len(rows) == 1


@pytest.mark.parametrize("filters", [{"branch": "Paro"}, {"organisation": "DTG Services Pvt Ltd"}])
def test_filters_cannot_widen_the_branch_scope(filters):
    with pytest.raises(Forbidden):
        run("hr.active_headcount", BRANCH, filters=filters)


def test_snapshot_dates_are_never_invented():
    with pytest.raises(NoData) as exc:
        run("ac.outstanding_receivables", as_of="2025-01-01")
    assert exc.value.details["available_dates"]


def test_no_matching_rows_is_no_data():
    with pytest.raises(NoData):  # ERPNext invoices carry no branch (DS-AC-05)
        run("ac.outstanding_receivables", filters={"branch": "Paro"})


@pytest.mark.parametrize(
    "query",
    [
        "select count(*) from marts.dim_employee",
        "select count(*) from marts.fct_leave_request",
        "select count(*) from raw.source_record",
        "select count(*) from marts.kpi_approved_leave_monthly",
    ],
)
def test_kpi_reader_cannot_read_unapproved_relations(query):
    from kpi import warehouse

    with warehouse.connect() as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(query)


def test_kpi_reader_sessions_are_read_only():
    from kpi import warehouse

    with warehouse.connect() as conn, pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        conn.execute("create temporary table t (x int)")
