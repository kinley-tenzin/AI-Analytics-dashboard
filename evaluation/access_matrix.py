"""Access-control matrix across ALL enforcement boundaries (Milestone 8, Task 5).

    python evaluation/access_matrix.py

For every demo role, attempts each access path and compares the outcome with the policy:
  Superset  : datasets visible, chart data and CSV export per dataset, SQL Lab, dashboards
  Django    : KPI API per domain, AI questions per domain, tampered parameters, scope widening
  Database  : the consumer accounts directly (Superset reader, KPI reader) on unapproved relations
Results: docs/evaluation/results/access_matrix.json. Local demo users only.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from druksmart_common.config import load_settings  # noqa: E402

import evaltools as et  # noqa: E402

DOMAIN_DATASETS = {
    "hr": ["kpi_headcount", "kpi_approved_leave_monthly"],
    "accounts": ["kpi_receivables_payables"],
}
METRIC = {
    "kpi_headcount": "active_headcount",
    "kpi_approved_leave_monthly": "approved_requests",
    "kpi_receivables_payables": "outstanding_receivables",
}
ROLES = {  # user -> (domains, branch restricted)
    "demo_hr": ({"hr"}, False),
    "demo_accounts": ({"accounts"}, False),
    "demo_executive": ({"hr", "accounts"}, False),
    "demo_branch": ({"hr", "accounts"}, True),
}
DEMO_BRANCH = "odoo:odoo-sandbox:1"
QUESTIONS = {
    "hr": "How many active employees are there?",
    "accounts": "What is the outstanding receivables balance?",
}
KPI_FUNCTION = {"hr": "hr.active_headcount", "accounts": "ac.outstanding_receivables"}

rows: list[dict] = []


def record(user, boundary, resource, attempt, expected, actual, detail=""):
    rows.append(
        {
            "user": user,
            "boundary": boundary,
            "resource": resource,
            "attempt": attempt,
            "expected": expected,
            "actual": actual,
            "pass": expected == actual,
            "detail": str(detail)[:200],
        }
    )


def superset_checks(user: str, domains: set, branch: bool) -> None:
    api = et.superset(user)
    visible = {d["table_name"] for d in api.list_all("dataset")}
    for domain, tables in DOMAIN_DATASETS.items():
        for table in tables:
            allowed = domain in domains
            record(user, "Superset", table, "dataset listed", allowed, table in visible)
            for fmt in ("json", "csv"):
                ds = et.superset("admin").find_one("dataset", "table_name", table)
                resp = api.request(
                    "POST",
                    "/api/v1/chart/data",
                    json={
                        "datasource": {"id": ds["id"], "type": "table"},
                        "queries": [
                            {
                                "metrics": [METRIC[table]],
                                "columns": ["branch_key"] if table != "kpi_approved_leave_monthly" else [],
                                "row_limit": 100,
                            }
                        ],
                        "result_format": fmt,
                        "result_type": "full",
                        "force": True,
                    },
                )
                ok = resp.status_code == 200
                record(
                    user,
                    "Superset",
                    table,
                    "chart data" if fmt == "json" else "CSV export",
                    "allowed" if allowed else "denied",
                    "allowed" if ok else "denied",
                    resp.status_code,
                )
                if ok and branch and fmt == "json" and table != "kpi_approved_leave_monthly":
                    keys = {r["branch_key"] for r in resp.json()["result"][0]["data"]}
                    record(
                        user,
                        "Superset",
                        table,
                        "rows limited to own branch (RLS)",
                        True,
                        keys <= {DEMO_BRANCH},
                        keys,
                    )
    resp = api.request(
        "POST",
        "/api/v1/sqllab/execute/",
        json={"database_id": 1, "sql": "select 1", "runAsync": False},
    )
    record(
        user,
        "Superset",
        "SQL Lab",
        "execute SQL",
        "denied",
        "allowed" if resp.status_code == 200 else "denied",
        resp.status_code,
    )
    resp = api.request(
        "POST",
        "/api/v1/dataset/",
        json={"database": 1, "schema": "marts", "table_name": "dim_employee"},
    )
    record(
        user,
        "Superset",
        "marts.dim_employee",
        "register new dataset",
        "denied",
        "allowed" if resp.status_code in (200, 201) else "denied",
        resp.status_code,
    )


def django_checks(user: str, domains: set, branch: bool) -> None:
    dj = et.Django(user)
    for domain in ("hr", "accounts"):
        allowed = domain in domains
        resp = dj.kpi(KPI_FUNCTION[domain])
        record(
            user,
            "Django",
            f"{domain} KPI API",
            "run KPI function",
            "allowed" if allowed else "denied",
            "allowed" if resp.status_code == 200 else "denied",
            resp.status_code,
        )
        answer = dj.ask(QUESTIONS[domain])
        record(
            user,
            "Django",
            f"{domain} AI question",
            "ask",
            "answered" if allowed else "forbidden",
            answer["status"],
            answer["answer"],
        )
    tampering = [
        (
            "SQL in a parameter",
            {"function": "hr.active_headcount", "sql": "select * from raw.source_record"},
        ),
        ("unknown function", {"function": "raw.dump"}),
        (
            "filter on a non-filter column",
            {"function": "hr.active_headcount", "filters": {"employee_key": "x"}},
        ),
        (
            "SQL injection in a filter value",
            {"function": "hr.active_headcount", "filters": {"department": "x' or '1'='1"}},
        ),
        (
            "as_of injection",
            {"function": "hr.active_headcount", "as_of": "2026-10-25'; drop table x;--"},
        ),
    ]
    for name, payload in tampering:
        resp = dj.post("/api/v1/kpis/run/", payload)
        record(
            user,
            "Django",
            "KPI API",
            f"tampered: {name}",
            "rejected",
            "rejected" if resp.status_code in (400, 403, 404) else f"HTTP {resp.status_code}",
            resp.json().get("status"),
        )
    if branch:
        for name, filters in (
            ("other branch", {"branch": "Paro"}),
            ("other organisation", {"organisation": "DTG Services Pvt Ltd"}),
        ):
            resp = dj.kpi("hr.active_headcount", filters=filters)
            record(
                user,
                "Django",
                "branch scope",
                f"widen scope via {name}",
                "denied",
                "denied" if resp.status_code == 403 else f"HTTP {resp.status_code}",
            )
        resp = dj.kpi("hr.active_headcount", group_by="branch")
        branches = [r["branch"] for r in resp.json()["result"]["rows"]]
        record(
            user,
            "Django",
            "branch scope",
            "group by branch shows only own branch",
            True,
            branches == ["DTG Retail Pvt Ltd (head office)"],
            branches,
        )
    dj.close()


def database_checks() -> None:
    settings = load_settings()
    accounts = {
        "superset_reader": (
            os.environ.get("DRUKSMART_SUPERSET_READER_USER"),
            os.environ.get("DRUKSMART_SUPERSET_READER_PASSWORD"),
        ),
        "kpi_reader": (settings.kpi_reader_user, settings.kpi_reader_password),
    }
    probes = [
        "select 1 from raw.source_record limit 1",
        "select 1 from staging.stg_odoo__hr_employee limit 1",
        "select 1 from marts.dim_employee limit 1",
        "select 1 from marts.dim_customer limit 1",
        "insert into marts.data_freshness (source_instance) values ('x')",
    ]
    for name, (user, password) in accounts.items():
        for sql in probes:
            try:
                with psycopg.connect(
                    host=settings.pg_host,
                    port=settings.pg_port,
                    dbname=settings.analytics_db,
                    user=user,
                    password=password,
                    connect_timeout=5,
                    autocommit=True,
                ) as conn:
                    conn.execute(sql)
                actual = "allowed"
            except psycopg.Error as exc:
                actual = "denied"
                detail = type(exc).__name__
            else:
                detail = ""
            record(
                name,
                "Database",
                sql.split(" from ")[-1].split(" ")[0] if "from" in sql else "marts.data_freshness",
                sql.split(" ")[0],
                "denied",
                actual,
                detail,
            )


def main() -> int:
    for user, (domains, branch) in ROLES.items():
        superset_checks(user, domains, branch)
        django_checks(user, domains, branch)
    database_checks()
    failures = [r for r in rows if not r["pass"]]
    et.save_result("access_matrix", {"checks": rows, "passed": len(rows) - len(failures), "total": len(rows)})
    for r in failures:
        print("FAIL", r)
    print(f"access matrix: {len(rows) - len(failures)}/{len(rows)} checks as expected")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
