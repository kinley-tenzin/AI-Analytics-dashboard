"""Scale test: run the REAL pipeline over the MEDIUM synthetic data and prove the marts are correct.

    python evaluation/scale_test.py generate                  # write tests/fixtures/synthetic_medium
    python evaluation/scale_test.py use medium|small          # which fixtures the synthetic-erp serves
    python evaluation/scale_test.py run --reset-test-db       # replay both batches through Airflow
    python evaluation/scale_test.py verify                    # marts == independent oracle (+ sizes)

What each step touches (docs/evaluation/SCALE_TEST.md):
  * generate  : local files only.
  * use       : recreates the `synthetic-erp` container (fictional ERP APIs). Nothing else.
  * run       : TRUNCATES the raw tables of `<analytics db>_test` (synthetic-only database, refuses any
                other name) so no earlier synthetic rows mix in, then triggers the DAG twice
                (as_of 2026-09-30 and 2026-10-31). The live warehouse database is never touched.
  * verify    : read-only queries; the oracle (tests/support/kpi_reference.py) recomputes every KPI
                straight from the fixture records, independent of dbt.
Results: docs/evaluation/results/scale_medium_run.json and scale_medium_verify.json.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "evaluation"))
sys.path.insert(0, str(REPO / "tests" / "support"))

FIXTURE_DIRS = {"small": "tests/fixtures/synthetic", "medium": "tests/fixtures/synthetic_medium"}
SEP, OCT = date(2026, 9, 30), date(2026, 10, 31)
REPLAYS = ("2026-09-30T17:30:00Z", "2026-10-31T17:30:00Z")
MIN_FREE_GB = 5


def say(msg: str) -> None:
    print(msg, flush=True)


# ------------------------------------------------------------------------------ steps
def cmd_generate(_args) -> int:
    proc = subprocess.run(
        [sys.executable, str(REPO / "tests" / "fixtures" / "synthetic_medium" / "generate_medium.py")],
        cwd=REPO,
    )
    return proc.returncode


def cmd_use(args) -> int:
    folder = FIXTURE_DIRS[args.which]
    if not (REPO / folder).is_dir():
        say(f"{folder} does not exist: run `python evaluation/scale_test.py generate` first")
        return 1
    env = {**os.environ, "DRUKSMART_SYNTHETIC_FIXTURES": folder}
    proc = subprocess.run(
        ["docker", "compose", "--profile", "airflow", "up", "-d", "--force-recreate", "synthetic-erp"],
        cwd=REPO,
        env=env,
    )
    if proc.returncode == 0:
        say(f"synthetic-erp now serves {folder} (reverts to the small set if recreated without this)")
    return proc.returncode


def _free_gb() -> float:
    return shutil.disk_usage(REPO).free / 1e9


def _reset_test_raw(conn) -> None:
    db = conn.execute("select current_database()").fetchone()[0]
    if not db.endswith("_test"):
        raise SystemExit(f"refusing to reset {db}: only the synthetic *_test database is allowed")
    conn.execute("TRUNCATE raw.quarantined_record, raw.extraction_checkpoint, raw.source_record, raw.extraction_run")
    say(f"raw tables of {db} truncated (synthetic data only)")


def _docker_memory() -> dict:
    out = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{.Name}}|{{.MemUsage}}|{{.CPUPerc}}"],
        capture_output=True,
        text=True,
    ).stdout
    keep = ("synthetic-erp", "postgres", "airflow-scheduler", "airflow-apiserver", "superset", "backend")
    return {
        line.split("|")[0]: line.split("|")[1]
        for line in out.splitlines()
        if any(k in line.split("|")[0] for k in keep) and "sandbox" not in line
    }


def cmd_run(args) -> int:
    from druksmart_common.config import load_settings
    from druksmart_common.db import connect

    import evaltools as et

    free = _free_gb()
    say(f"free disk: {free:.1f} GB")
    if free < MIN_FREE_GB:
        say(f"less than {MIN_FREE_GB} GB free: stopping")
        return 1
    if not args.reset_test_db:
        say("add --reset-test-db: the *_test raw tables must be emptied so old synthetic rows do not mix in")
        return 1
    with connect(load_settings().pipeline_test(), autocommit=True) as conn:
        _reset_test_raw(conn)

    paused = any(
        d["dag_id"] == et.DAG and str(d["is_paused"]).lower() == "true"
        for d in json.loads(et.airflow("dags", "list", "-o", "json") or "[]")
    )
    if paused:
        et.airflow("dags", "unpause", et.DAG)
    runs, started = [], time.monotonic()
    try:
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        for as_of in REPLAYS:
            say(f"replaying {as_of[:10]} through Airflow (this takes a while) ...")
            result = et.run_and_wait(
                f"scale_{as_of[:10]}_{stamp}",
                {"source_mode": "synthetic", "as_of": as_of},
                timeout_s=args.timeout,
            )
            result["docker_memory"] = _docker_memory()
            runs.append(result)
            say(f"  state={result['state']}  {result['observed_seconds']} s")
            for t in result["tasks"]:
                say(f"    {t['task']:32s} {t['state']:8s} {t['seconds']} s")
            if result["state"] != "success":
                break
    finally:
        if paused:
            et.airflow("dags", "pause", et.DAG)
    path = et.save_result(
        "scale_medium_run",
        {
            "fixtures": os.environ.get("DRUKSMART_SYNTHETIC_FIXTURES", "see synthetic-erp container"),
            "total_seconds": round(time.monotonic() - started, 1),
            "free_disk_gb_before": round(free, 1),
            "runs": runs,
        },
    )
    say(f"saved {path.relative_to(REPO)}")
    return 0 if runs and all(r["state"] == "success" for r in runs) else 1


# ----------------------------------------------------------------------------- verify
def _dict(conn, sql, *params) -> dict:
    return {k: (float(v) if not isinstance(v, int) else v) for k, v in conn.execute(sql, params).fetchall()}


def _close(a: dict, b: dict) -> bool:
    keys = set(a) | set(b)
    return all(abs(float(a.get(k, 0) or 0) - float(b.get(k, 0) or 0)) < 0.005 for k in keys)


def cmd_verify(_args) -> int:
    os.environ["DRUKSMART_SYNTHETIC_FIXTURES"] = FIXTURE_DIRS["medium"]
    import kpi_reference as ref
    from druksmart_common.config import load_settings
    from druksmart_common.db import connect

    import evaltools as et

    checks: list[dict] = []

    def check(name: str, want, got, equal=None) -> None:
        ok = equal(want, got) if equal else want == got
        checks.append({"check": name, "ok": bool(ok), "oracle": want, "warehouse": got})
        say(f"  {'PASS' if ok else 'FAIL'}  {name}")

    say("computing the independent oracle from the fixture records (about a minute) ...")
    with connect(load_settings().pipeline_test(), autocommit=True) as conn:
        say(f"database: {conn.execute('select current_database()').fetchone()[0]}")

        # rejected records
        want = {(s, e, i) for s, ents in ref.rejected_ids().items() for e, ids in ents.items() for i in ids}
        got = {tuple(r) for r in conn.execute(
            "select source_system, source_entity, source_id from raw.quarantined_record"
        ).fetchall()}  # fmt: skip
        check("rejected records == quarantined records", len(want), len(got), lambda a, b: want == got)

        # HR
        hc = ref.headcount(OCT)
        got_inst = _dict(conn, "select source_instance, sum(active_headcount)::int from marts.kpi_headcount "
                               "where snapshot_date = %s group by 1", OCT)  # fmt: skip
        check("HR-01 headcount by instance", hc["by_instance"], got_inst)
        got_branch = _dict(
            conn,
            "select branch_key, sum(active_headcount)::int from marts.kpi_headcount "
            "where snapshot_date = %s group by 1 having sum(active_headcount) > 0",
            OCT,
        )
        check("HR-01 headcount by branch", hc["by_branch"], got_branch)
        got_dept = _dict(conn, "select department_key, sum(active_headcount)::int from marts.kpi_headcount "
                               "where snapshot_date = %s group by 1 having sum(active_headcount) > 0", OCT)  # fmt: skip
        check("HR-02 headcount by department", hc["by_department"], got_dept)

        leave = ref.approved_leave(date(2026, 10, 1), OCT)
        rows = conn.execute(
            "select source_instance, count(*)::int, sum(leave_days)::float, count(distinct employee_key)::int "
            "from marts.fct_leave_request where approval_status = 'approved' "
            "and start_date between %s and %s group by 1",
            (date(2026, 10, 1), OCT),
        ).fetchall()
        got_leave = {i: {"requests": r, "days": d, "employees": e} for i, r, d, e in rows}
        check("HR-03 approved leave (Oct) by instance", leave["by_instance"], got_leave)

        # Accounts, both snapshot dates
        for day in (SEP, OCT):
            acc = ref.accounts_kpis(day)
            for ledger, kpi_bal, kpi_over in (
                ("receivable", "AC-01_outstanding_receivables", "AC-03_overdue_receivables"),
                ("payable", "AC-02_outstanding_payables", "AC-03_overdue_payables"),
            ):
                for column, kpi in (("outstanding_amount", kpi_bal), ("overdue_amount", kpi_over)):
                    got = _dict(conn, f"select source_instance, sum({column}) from marts.kpi_receivables_payables "
                                      "where snapshot_date = %s and ledger = %s group by 1", day, ledger)  # fmt: skip
                    got["total"] = sum(got.values())
                    check(f"{kpi} {day}", acc[kpi], got, _close)
                ageing_want = acc["AC-04_receivables_ageing" if ledger == "receivable" else "AC-04_payables_ageing"]
                ageing_got: dict = {}
                for inst, bucket, amount in conn.execute(
                    "select source_instance, ageing_bucket, sum(outstanding_amount) "
                    "from marts.kpi_receivables_payables "
                    "where snapshot_date = %s and ledger = %s group by 1, 2",
                    (day, ledger),
                ).fetchall():
                    ageing_got.setdefault(inst, dict.fromkeys(ref.BUCKETS, 0.0))[bucket] = float(amount)
                check(
                    f"AC-04 {ledger} ageing {day}", ageing_want, ageing_got,
                    lambda a, b: all(_close(a[k], b.get(k, {})) for k in a),
                )  # fmt: skip
        by_branch = _dict(conn, "select branch_key, sum(outstanding_amount) from marts.kpi_receivables_payables "
                                "where snapshot_date = %s and ledger = 'receivable' group by 1", OCT)  # fmt: skip
        check(
            "AC-01 receivables by branch (Oct)",
            ref.accounts_kpis(OCT)["AC-01_receivables_by_branch"],
            by_branch,
            _close,
        )
        adv = _dict(conn, "select source_instance, sum(unallocated_amount) from marts.fct_payment "
                          "where direction = 'received' and document_state = 'posted' group by 1")  # fmt: skip
        check("unallocated advances", ref.unallocated_advances(OCT), adv, _close)
        check("oracle: payments reconcile with invoices", [], ref.payment_reconciliation_differences(OCT))

        # volumes (after the checks, read-only)
        volumes: dict[str, int] = {}
        tables = conn.execute(
            "select table_schema, table_name from information_schema.tables "
            "where table_schema in ('raw','staging','intermediate','marts') and table_type = 'BASE TABLE' "
            "order by 1, 2"
        ).fetchall()
        for schema, table in tables:
            volumes[f"{schema}.{table}"] = conn.execute(f'select count(*) from "{schema}"."{table}"').fetchone()[0]
        size = conn.execute("select pg_database_size(current_database())").fetchone()[0]

    failed = [c for c in checks if not c["ok"]]
    out = {
        "fixtures": FIXTURE_DIRS["medium"],
        "checks_total": len(checks),
        "checks_failed": len(failed),
        "database_size_mb": round(size / 1e6, 1),
        "row_counts": volumes,
        "checks": checks,
    }
    path = et.save_result("scale_medium_verify", out)
    say(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed; database {out['database_size_mb']} MB")
    say(f"saved {path.relative_to(REPO)}")
    for c in failed:
        say(f"FAILED: {c['check']}\n  oracle   : {str(c['oracle'])[:400]}\n  warehouse: {str(c['warehouse'])[:400]}")
    return 1 if failed else 0


# --------------------------------------------------------------------------- consumers
def cmd_consumers(args) -> int:
    """Superset and Django/assistant on the medium data: same numbers as the oracle, and how fast."""
    os.environ["DRUKSMART_SYNTHETIC_FIXTURES"] = FIXTURE_DIRS["medium"]
    import kpi_reference as ref

    import evaltools as et
    import performance as perf
    import reconcile

    period = (date(2026, 10, 1), OCT)
    say("oracle (about a minute) ...")
    hc, acc, leave = ref.headcount(OCT), ref.accounts_kpis(OCT), ref.approved_leave(*period)
    want = {
        "headcount": hc["total"],
        "receivable": acc["AC-01_outstanding_receivables"]["total"],
        "payable": acc["AC-02_outstanding_payables"]["total"],
        "overdue_receivable": acc["AC-03_overdue_receivables"]["total"],
        "overdue_payable": acc["AC-03_overdue_payables"]["total"],
        "leave_requests": leave["total"]["requests"],
        "leave_days": leave["total"]["days"],
    }
    api = et.superset("admin")
    sup = reconcile.superset_layer(api, OCT, period)
    instances = [v for k, v in sup.items() if not k.startswith("_")]

    def total(key):
        return sum(v.get(key, 0) or 0 for v in instances)

    got_superset = {
        "headcount": total("headcount"),
        "receivable": total("receivable"),
        "payable": total("payable"),
        "overdue_receivable": total("overdue_receivable"),
        "overdue_payable": total("overdue_payable"),
        "leave_requests": sum((v.get("leave") or {}).get("requests", 0) for v in instances),
        "leave_days": sum((v.get("leave") or {}).get("days", 0) for v in instances),
    }
    dj = et.Django("demo_executive")
    layer = reconcile.django_layer(dj, OCT, period)
    dj.close()
    got_django = {
        "headcount": layer["headcount"],
        "receivable": layer["receivable"],
        "payable": layer["payable"],
        "overdue_receivable": layer["overdue_receivable"],
        "overdue_payable": layer["overdue_payable"],
        "leave_requests": layer["leave"]["requests"],
        "leave_days": layer["leave"]["days"],
    }
    checks = []
    for layer_name, got in (("Superset", got_superset), ("Django KPI API", got_django)):
        for key, value in want.items():
            ok = abs(float(got[key]) - float(value)) < 0.005
            checks.append({"check": f"{layer_name}: {key}", "ok": ok, "oracle": value, "layer": got[key]})
            say(f"  {'PASS' if ok else 'FAIL'}  {layer_name}: {key} = {got[key]}")

    say("== timings")
    out = {
        "fixtures": FIXTURE_DIRS["medium"],
        "checks": checks,
        "superset_query_ms": perf.superset_latency(args.samples),
        "dashboard_load_ms": perf.dashboard_loads(3),
        "django": perf.django_latency(args.samples),
    }
    path = et.save_result("scale_medium_consumers", out)
    failed = [c for c in checks if not c["ok"]]
    say(f"{len(checks) - len(failed)}/{len(checks)} value checks passed; saved {path.relative_to(REPO)}")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("generate")
    use = sub.add_parser("use")
    use.add_argument("which", choices=sorted(FIXTURE_DIRS))
    run = sub.add_parser("run")
    run.add_argument("--reset-test-db", action="store_true")
    run.add_argument("--timeout", type=int, default=3600, help="seconds per replay")
    sub.add_parser("verify")
    cons = sub.add_parser("consumers")
    cons.add_argument("--samples", type=int, default=20)
    args = parser.parse_args()
    return {"generate": cmd_generate, "use": cmd_use, "run": cmd_run, "verify": cmd_verify, "consumers": cmd_consumers}[
        args.cmd
    ](args)


if __name__ == "__main__":
    sys.exit(main())
