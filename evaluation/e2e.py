"""End-to-end workflow test on the LOCAL ERP SANDBOXES (Milestone 8, Task 2).

    python evaluation/e2e.py [--skip-phase-b]

ERP change (sandbox_changes.py) -> Airflow DAG (extract, raw, dbt, tests, publish) -> warehouse
-> Superset -> Django KPI API -> AI answer, for two phases of controlled changes plus a repeat run
without changes. After each run:
  * every KPI is reconciled across all layers against the independent source oracle;
  * the change in each KPI must equal the change expected BY CONSTRUCTION;
  * Superset is queried both as a dashboard would (cached) and forced, to detect stale cache;
  * raw record versions are counted (a repeat run must add none).
Results: docs/evaluation/results/e2e.json. Uses LOCAL SANDBOX data, not DrukSmart's ERPs.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import evaltools as et  # noqa: E402
import reconcile  # noqa: E402

# Expected change of each KPI per phase (see sandbox_changes.py).
EXPECTED_DELTAS = {
    "phase_a": {
        "headcount": 1,
        "receivable": 3500,
        "payable": 2500,
        "overdue_receivable": 0,
        "overdue_payable": 2500,
        "approved_leave_requests": 1,
        "approved_leave_days": 1,
        "approved_leave_employees": 0,
    },
    "phase_b": {
        "headcount": -1,
        "receivable": -3500,
        "payable": 0,
        "overdue_receivable": 0,
        "overdue_payable": 0,
        "approved_leave_requests": -1,
        "approved_leave_days": -1,
        "approved_leave_employees": 0,
    },
    "phase_c": {
        "headcount": 1,
        "receivable": 0,
        "payable": 0,
        "overdue_receivable": 0,
        "overdue_payable": 0,
        "approved_leave_requests": 0,
        "approved_leave_days": 0,
        "approved_leave_employees": 0,
    },
    "phase_d": {
        "headcount": -1,
        "receivable": 0,
        "payable": 0,
        "overdue_receivable": 0,
        "overdue_payable": 0,
        "approved_leave_requests": 0,
        "approved_leave_days": 0,
        "approved_leave_employees": 0,
    },
    "repeat": {
        k: 0
        for k in (
            "headcount",
            "receivable",
            "payable",
            "overdue_receivable",
            "overdue_payable",
            "approved_leave_requests",
            "approved_leave_days",
            "approved_leave_employees",
        )
    },
}


def kpis(report: dict) -> dict:
    return {c["kpi"]: c["layers"]["source"] for c in report["checks"] if ":" not in c["kpi"]}


def raw_versions(conn) -> int:
    return conn.execute("select count(*) from raw.source_record").fetchone()[0]


def dashboard_vs_forced(api, as_of: str) -> dict:
    """What a dashboard (cached) shows vs a forced fresh query, for two KPI metrics."""
    at = {"col": "snapshot_date", "op": "==", "val": as_of}
    out = {}
    for table, metric in (
        ("kpi_headcount", "active_headcount"),
        ("kpi_receivables_payables", "outstanding_receivables"),
    ):
        cached = et.superset_rows(api, table, [metric], filters=[at], force=False)[0][metric]
        fresh = et.superset_rows(api, table, [metric], filters=[at], force=True)[0][metric]
        out[metric] = {"dashboard_cached": cached, "fresh": fresh, "stale": cached != fresh}
    return out


def phase(name: str, change: str | None, previous: dict, as_of: str, run_suffix: str) -> dict:
    result: dict = {"phase": name, "started": datetime.now().isoformat(timespec="seconds")}
    if change:
        t0 = time.monotonic()
        proc = subprocess.run(
            [sys.executable, str(HERE / "sandbox_changes.py"), change],
            capture_output=True,
            text=True,
        )
        result["sandbox_change"] = {
            "returncode": proc.returncode,
            "output": proc.stdout.strip(),
            "seconds": round(time.monotonic() - t0, 1),
        }
        if proc.returncode:
            raise SystemExit(proc.stdout + proc.stderr)
    with et.warehouse() as conn:
        raw_before = raw_versions(conn)
    api = et.superset("admin")
    dashboard_vs_forced(api, as_of)  # a dashboard viewer loads the page before the refresh
    run = et.run_and_wait(f"m8_e2e_{name}_{run_suffix}")
    result["airflow"] = run
    result["superset_cache_after_publish"] = dashboard_vs_forced(api, as_of)
    with et.warehouse() as conn:
        result["raw_versions"] = {"before": raw_before, "after": raw_versions(conn)}
    report = reconcile.reconcile(reconcile.date.fromisoformat(as_of))
    result["reconciliation"] = {
        "passed": report["passed"],
        "total": report["total"],
        "failed": [c for c in report["checks"] if not c["ok"]],
        "ai_answers": report["ai_answers"],
    }
    now = kpis(report)
    deltas = {}
    for k, expected in EXPECTED_DELTAS[name].items():
        actual = round(float(now[k]) - float(previous[k]), 2)
        deltas[k] = {
            "before": previous[k],
            "after": now[k],
            "expected_delta": expected,
            "actual_delta": actual,
            "ok": abs(actual - expected) < 0.005,
        }
    result["deltas"] = deltas
    result["passed"] = (
        run["state"] == "success" and report["passed"] == report["total"] and all(d["ok"] for d in deltas.values())
    )
    result["kpis"] = now
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-phase-b", action="store_true")
    parser.add_argument(
        "--post-fix",
        action="store_true",
        help="phases C/D only; also require Superset to show fresh data (defect D2)",
    )
    parser.add_argument("--suffix", default=datetime.now().strftime("%H%M"))
    args = parser.parse_args(argv)
    with et.warehouse() as conn:
        as_of = str(conn.execute("select max(snapshot_date) from marts.fct_headcount_snapshot").fetchone()[0])
    baseline = reconcile.reconcile(reconcile.date.fromisoformat(as_of))
    if baseline["passed"] != baseline["total"]:
        print("baseline reconciliation is not clean; fix that first")
        return 1
    out = {"as_of": as_of, "baseline": kpis(baseline), "phases": []}
    previous = kpis(baseline)
    plan = [("phase_a", "phase-a"), ("phase_b", "phase-b"), ("repeat", None)]
    if args.skip_phase_b:
        plan = plan[:1]
    if args.post_fix:
        plan = [("phase_c", "phase-c"), ("phase_d", "phase-d")]
    for name, change in plan:
        print(f"== {name}")
        r = phase(name, change, previous, as_of, args.suffix)
        out["phases"].append(r)
        print(
            f"   run {r['airflow']['run_id']}: {r['airflow']['state']} in {r['airflow']['observed_seconds']}s; "
            f"reconciliation {r['reconciliation']['passed']}/{r['reconciliation']['total']}; "
            f"raw versions {r['raw_versions']['before']} -> {r['raw_versions']['after']}"
        )
        for k, d in r["deltas"].items():
            print(
                f"   [{'PASS' if d['ok'] else 'FAIL'}] {k:<26} {d['before']} -> {d['after']} "
                f"(expected {d['expected_delta']:+}, actual {d['actual_delta']:+})"
            )
        print(f"   superset cache after publish: {r['superset_cache_after_publish']}")
        if args.post_fix and any(v["stale"] for v in r["superset_cache_after_publish"].values()):
            r["passed"] = False
            print("   [FAIL] Superset still served pre-publication data")
        previous = r["kpis"]
    out["passed"] = all(p["passed"] for p in out["phases"])
    path = et.save_result("e2e_post_fix" if args.post_fix else "e2e", out)
    print(f"END-TO-END: {'PASSED' if out['passed'] else 'FAILED'} -> {path}")
    return 0 if out["passed"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
