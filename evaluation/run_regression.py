"""Repeatable regression suite for the whole platform (Milestone 8, Task 8).

    python evaluation/run_regression.py              # every stage whose prerequisites are up
    python evaluation/run_regression.py --quick      # lint + unit + frontend (no services needed)
    python evaluation/run_regression.py --with-e2e   # also the end-to-end test (CHANGES sandbox data)

Stages run in dependency order; a stage whose services are not running is SKIPPED (reported,
never silently passed). Writes docs/evaluation/results/regression.json and exits 1 if any stage
that ran failed.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import evaltools as et  # noqa: E402

PY = sys.executable
NPM = shutil.which("npm") or "npm"  # npm.cmd on Windows


def pg_up() -> bool:
    try:
        with et.warehouse() as conn:
            conn.execute("select 1")
        return True
    except Exception:
        return False


def sandboxes_up() -> bool:
    return et.service_up(f"{os.environ.get('ODOO_BASE_URL', '')}/web/login") and et.service_up(
        f"{os.environ.get('ERPNEXT_BASE_URL', '')}/api/method/ping"
    )


def superset_up() -> bool:
    return et.service_up(f"{et.SUPERSET_URL}/health")


def django_up() -> bool:
    return et.service_up(f"{et.DJANGO_URL}/health/")


def node_available() -> bool:
    return shutil.which("npm") is not None and (et.REPO / "frontend" / "node_modules").is_dir()


def airflow_up() -> bool:
    try:
        return et.run_state("__none__") is None
    except Exception:
        return False


# (name, what it covers, command, prerequisites)
STAGES = [
    ("lint", "ruff lint + format check", [PY, "-m", "ruff", "check", "."], []),
    ("format", "ruff format check", [PY, "-m", "ruff", "format", "--check", "."], []),
    (
        "unit",
        "contracts, connectors (fake APIs), ingestion logic, KPI oracle, DAG static checks, "
        "Superset definitions, Django registry/rules/Gemini(mocked)/API, consistency guards",
        [
            PY,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "tests/unit",
            "tests/backend",
            "-m",
            "not backend and not superset",
        ],
        [],
    ),
    (
        "frontend",
        "website (Milestone 10): TypeScript type check, ESLint, Vitest unit/routing/page tests",
        [NPM, "--prefix", "frontend", "run", "verify"],
        [node_available],
    ),
    (
        "database",
        "PostgreSQL roles/schemas, raw ingestion against the DB, publication swap/grants",
        [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-m", "smoke or db"],
        [pg_up],
    ),
    (
        "warehouse",
        "fixtures -> connectors -> raw -> dbt build + data tests -> hand-calculated KPIs; "
        "Django KPI service on the same marts",
        [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-m", "warehouse"],
        [pg_up],
    ),
    (
        "live_erp",
        "read-only connectivity, contracts and idempotent loading against the ERP sandboxes",
        [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-m", "live"],
        [pg_up, sandboxes_up],
    ),
    (
        "kpi_service",
        "Django KPI functions vs fact tables, scope, restricted DB account",
        [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-m", "backend and not superset"],
        [pg_up],
    ),
    (
        "superset",
        "Superset access boundary, RLS, CSV export, KPIs; Superset = KPI service",
        [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-m", "superset"],
        [pg_up, superset_up],
    ),
    (
        "dashboards_browser",
        "dashboards per role in headless Edge; KPI cards = warehouse",
        [PY, str(et.REPO / "superset/scripts/browser_check.py")],
        [pg_up, superset_up],
    ),
    (
        "reconciliation",
        "source ERPs = dbt = Superset = Django = AI answers (all KPIs, per ERP)",
        [PY, str(HERE / "reconcile.py"), "--name", "reconciliation_regression"],
        [pg_up, sandboxes_up, superset_up, django_up],
    ),
    (
        "access_matrix",
        "every role x resource at Superset, Django and database boundaries",
        [PY, str(HERE / "access_matrix.py")],
        [pg_up, superset_up, django_up],
    ),
    (
        "website_browser",
        "website in headless Edge: roles, sign-in, embedded dashboards = KPI service per user, "
        "Ask AI, reports, administration, WCAG 2.1 AA audit, 12-step user journey, layouts",
        [PY, str(et.REPO / "frontend/scripts/browser_check.py")],
        [pg_up, superset_up, django_up],
    ),
    (
        "assistant_eval",
        "AI assistant evaluation set (held-out set) against fact-table references",
        [
            PY,
            str(et.REPO / "backend/manage.py"),
            "evaluate_assistant",
            "--provider",
            "rules",
            "--questions",
            str(et.REPO / "backend/evaluation/questions_holdout.yml"),
        ],
        [pg_up],
    ),
]
E2E = (
    "end_to_end",
    "sandbox change -> Airflow -> all layers (modifies SANDBOX data)",
    [PY, str(HERE / "e2e.py"), "--post-fix"],
    [pg_up, sandboxes_up, superset_up, django_up, airflow_up],
)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--with-e2e", action="store_true")
    args = parser.parse_args(argv)
    stages = STAGES[:4] if args.quick else STAGES + ([E2E] if args.with_e2e else [])
    results = []
    for name, covers, cmd, prereqs in stages:
        missing = [p.__name__ for p in prereqs if not p()]
        if missing:
            results.append(
                {
                    "stage": name,
                    "covers": covers,
                    "status": "skipped",
                    "reason": f"not running: {', '.join(missing)}",
                }
            )
            print(f"[SKIP] {name:<20} ({', '.join(missing)})", flush=True)
            continue
        t = time.monotonic()
        proc = subprocess.run(cmd, cwd=et.REPO, capture_output=True, text=True)
        seconds = round(time.monotonic() - t, 1)
        status = "passed" if proc.returncode == 0 else "failed"
        # Keep enough output of a FAILED stage to diagnose it from regression.json alone.
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-(3 if status == "passed" else 40) :]
        results.append({"stage": name, "covers": covers, "status": status, "seconds": seconds, "summary": tail})
        print(f"[{status.upper()}] {name:<20} {seconds:>7} s  {tail[-1] if tail else ''}", flush=True)
    et.save_result("regression", {"run_at": datetime.now().isoformat(timespec="seconds"), "stages": results})
    failed = [r for r in results if r["status"] == "failed"]
    print(
        f"\n{len(results) - len(failed)}/{len(results)} stages without failure "
        f"({sum(r['status'] == 'skipped' for r in results)} skipped)"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
