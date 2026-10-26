"""INDEPENDENT expected values for the evaluation set, from the dbt FACT tables.

Written separately from the KPI service (different relations, different SQL, pipeline role), so an
error in the service's views or registry shows up as a mismatch instead of being reproduced.
Each reference returns {"measure", "value"} or {"measure", "by", "values"}.
"""

from __future__ import annotations

import calendar

DEMO_BRANCH = "odoo:odoo-sandbox:1"  # access/management/commands/seed_demo_users.py


def _latest(conn, table: str):
    return conn.execute(f"select max(snapshot_date) from marts.{table}").fetchone()[0]


def _scalar(conn, sql: str, params=()):
    value = conn.execute(sql, params).fetchone()[0]
    return float(value) if value is not None else 0.0


def _headcount(conn, extra: str = "", params=(), as_of=None):
    d = as_of or _latest(conn, "fct_headcount_snapshot")
    return {
        "measure": "active_headcount",
        "value": _scalar(
            conn,
            "select count(*) from marts.fct_headcount_snapshot f "
            "where f.snapshot_date = %s and f.employment_status = 'active'" + extra,
            (d, *params),
        ),
    }


def _ledger_total(conn, ledger: str, extra: str = "", params=()):
    d = _latest(conn, "fct_receivable_payable_snapshot")
    return {
        "measure": "outstanding_amount",
        "value": _scalar(
            conn,
            "select sum(outstanding_company) from marts.fct_receivable_payable_snapshot "
            "where snapshot_date = %s and ledger = %s" + extra,
            (d, ledger, *params),
        ),
    }


def _leave(conn, start, end):
    return {
        "measure": "employees_on_leave",
        "value": _scalar(
            conn,
            "select count(distinct employee_key) from marts.fct_leave_request "
            "where approval_status = 'approved' and start_date between %s and %s",
            (start, end),
        ),
    }


def headcount_total(conn):
    return _headcount(conn)


def headcount_2026_10_23(conn):
    return _headcount(conn, as_of="2026-10-23")


def headcount_by_department(conn):
    d = _latest(conn, "fct_headcount_snapshot")
    rows = conn.execute(
        "select dd.department_name, count(*) from marts.fct_headcount_snapshot f "
        "join marts.dim_department dd using (department_key) "
        "where f.snapshot_date = %s and f.employment_status = 'active' group by 1",
        (d,),
    ).fetchall()
    return {
        "measure": "active_headcount",
        "by": ["department"],
        "values": {r[0]: float(r[1]) for r in rows},
    }


def headcount_sales(conn):
    return _headcount(
        conn,
        " and exists (select 1 from marts.dim_department d where d.department_key = "
        "f.department_key and d.department_name = %s)",
        ("Sales",),
    )


def headcount_dtg_retail(conn):
    return _headcount(
        conn,
        " and exists (select 1 from marts.dim_organisation o where o.organisation_key = "
        "f.organisation_key and o.organisation_name = %s)",
        ("DTG Retail Pvt Ltd",),
    )


def headcount_demo_branch(conn):
    return _headcount(conn, " and f.branch_key = %s", (DEMO_BRANCH,))


def employment_status(conn):
    d = _latest(conn, "fct_headcount_snapshot")
    rows = conn.execute(
        "select employment_status, count(*) from marts.fct_headcount_snapshot "
        "where snapshot_date = %s group by 1",
        (d,),
    ).fetchall()
    return {
        "measure": "employee_records",
        "by": ["employment_status"],
        "values": {r[0]: float(r[1]) for r in rows},
    }


def leave_oct_2026(conn):
    result = _leave(conn, "2026-10-01", "2026-10-31")
    result["also"] = {
        "approved_leave_days": _scalar(
            conn,
            "select sum(leave_days) from marts.fct_leave_request where approval_status = "
            "'approved' and start_date between '2026-10-01' and '2026-10-31'",
        )
    }
    return result


def leave_employees_latest_month(conn):
    latest = conn.execute(
        "select max(latest_snapshot_date) from marts.data_freshness where domain = 'hr'"
    ).fetchone()[0]
    last = calendar.monthrange(latest.year, latest.month)[1]
    return _leave(conn, latest.replace(day=1), latest.replace(day=last))


def receivables_total(conn):
    return _ledger_total(conn, "receivable")


def payables_total(conn):
    return _ledger_total(conn, "payable")


def receivables_demo_branch(conn):
    return _ledger_total(conn, "receivable", " and branch_key = %s", (DEMO_BRANCH,))


def overdue_by_ledger(conn):
    d = _latest(conn, "fct_receivable_payable_snapshot")
    rows = conn.execute(
        "select ledger, sum(outstanding_company) from marts.fct_receivable_payable_snapshot "
        "where snapshot_date = %s and is_overdue group by 1",
        (d,),
    ).fetchall()
    return {
        "measure": "overdue_amount",
        "by": ["ledger"],
        "values": {r[0]: float(r[1]) for r in rows},
    }


def overdue_receivable(conn):
    full = overdue_by_ledger(conn)
    return {"measure": "overdue_amount", "value": full["values"].get("receivable", 0.0)}


def overdue_by_ageing(conn):
    d = _latest(conn, "fct_receivable_payable_snapshot")
    labels = {
        "1_30": "1 1-30 days overdue",
        "31_60": "2 31-60 days overdue",
        "61_90": "3 61-90 days overdue",
        "91_plus": "4 Over 90 days overdue",
    }
    rows = conn.execute(
        "select ledger, ageing_bucket, sum(outstanding_company) "
        "from marts.fct_receivable_payable_snapshot where snapshot_date = %s and is_overdue "
        "group by 1, 2",
        (d,),
    ).fetchall()
    return {
        "measure": "overdue_amount",
        "by": ["ledger", "ageing"],
        "values": {f"{r[0]}|{labels[r[1]]}": float(r[2]) for r in rows},
    }


REFERENCES = {
    name: fn for name, fn in globals().items() if callable(fn) and not name.startswith("_")
}
REFERENCES.pop("REFERENCES", None)


def headcount_dtg_services(conn):
    return _headcount(
        conn,
        " and exists (select 1 from marts.dim_organisation o where o.organisation_key = "
        "f.organisation_key and o.organisation_name = %s)",
        ("DTG Services Pvt Ltd",),
    )


REFERENCES["headcount_dtg_services"] = headcount_dtg_services
