"""Measure prototype performance on the LOCAL environment (Milestone 8, Task 6).

    python evaluation/performance.py [--runs 3] [--samples 30]

Measures (nothing is estimated):
  * environment and data volumes;
  * full-refresh pipeline runs (Airflow): per-task durations, total, per-entity extraction
    duration and record counts (raw.extraction_run);
  * Superset chart-data query latency (forced, no cache) and full dashboard load in a browser;
  * Django KPI API and AI assistant latency (rules interpreter; Gemini not configured).
Results: docs/evaluation/results/performance.json. Small synthetic/sandbox volumes: the numbers
describe THIS prototype on THIS machine and say nothing about enterprise scale.
"""

from __future__ import annotations

import argparse
import json
import os
import platform as py_platform
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import evaltools as et  # noqa: E402


def stats(values: list[float]) -> dict:
    v = sorted(values)
    return {
        "n": len(v),
        "min": round(v[0], 1),
        "p50": round(statistics.median(v), 1),
        "p95": round(v[max(0, int(round(0.95 * len(v))) - 1)], 1),
        "max": round(v[-1], 1),
        "mean": round(statistics.fmean(v), 1),
    }


def timed_ms(fn) -> float:
    t = time.perf_counter()
    fn()
    return (time.perf_counter() - t) * 1000


def environment() -> dict:
    info = {
        "os": py_platform.platform(),
        "python": py_platform.python_version(),
        "cpu": py_platform.processor(),
        "logical_cpus": os.cpu_count(),
    }
    try:
        out = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory; (Get-CimInstance Win32_Processor).Name",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout.split("\n")
        info["ram_gb"] = round(int(out[0].strip()) / 1024**3, 1)
        info["cpu"] = out[1].strip()
    except Exception:
        pass
    info["docker"] = subprocess.run(
        ["docker", "version", "--format", "{{.Server.Version}}"], capture_output=True, text=True
    ).stdout.strip()
    info["containers_running"] = len(
        subprocess.run(["docker", "ps", "-q"], capture_output=True, text=True).stdout.split()
    )
    mem = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.MemUsage}}"],
        capture_output=True,
        text=True,
    ).stdout
    info["druksmart_container_memory"] = [line for line in mem.splitlines() if line.startswith("druksmart")]
    return info


def volumes() -> dict:
    with et.warehouse() as conn:
        raw = conn.execute(
            "select source_system, source_entity, count(*) from raw.current_source_record group by 1, 2 order by 1, 2"
        ).fetchall()
        versions = conn.execute("select count(*) from raw.source_record").fetchone()[0]
        marts = {
            t: conn.execute(f"select count(*) from marts.{t}").fetchone()[0]
            for t in (
                "fct_headcount_snapshot",
                "fct_leave_request",
                "fct_accounting_document",
                "fct_payment",
                "fct_receivable_payable_snapshot",
                "kpi_headcount",
                "kpi_receivables_payables",
            )
        }
    return {
        "current_source_records": {f"{s}.{e}": n for s, e, n in raw},
        "current_source_records_total": sum(n for *_, n in raw),
        "raw_record_versions": versions,
        "mart_rows": marts,
    }


def pipeline_runs(n: int) -> dict:
    runs = []
    for i in range(n):
        run_id = f"m8_perf_full_{datetime.now():%H%M%S}_{i}"
        started = datetime.now().astimezone()
        r = et.run_and_wait(run_id, {"full_refresh": True}, timeout_s=2400)
        with et.warehouse() as conn:
            r["extraction"] = [
                {"entity": f"{s}.{e}", "records_fetched": f, "seconds": round(secs, 2)}
                for s, e, f, secs in conn.execute(
                    "select source_system, source_entity, records_fetched, "
                    "extract(epoch from finished_at - started_at) from raw.extraction_run "
                    "where started_at >= %s and status = 'succeeded' order by 1, 2",
                    (started,),
                ).fetchall()
            ]
        runs.append(r)
        print(f"   {run_id}: {r['state']} in {r['observed_seconds']} s", flush=True)
    by_task: dict[str, list[float]] = {}
    for r in runs:
        for t in r["tasks"]:
            if t["seconds"] is not None:
                by_task.setdefault(t["task"], []).append(t["seconds"])
    totals = []
    for r in runs:
        s, e = r["start_date"], r["end_date"]
        totals.append((datetime.fromisoformat(e) - datetime.fromisoformat(s)).total_seconds())
    return {
        "runs": runs,
        "run_total_seconds": stats(totals),
        "task_seconds": {k: stats(v) for k, v in sorted(by_task.items())},
    }


def superset_latency(samples: int) -> dict:
    api = et.superset("admin")
    queries = {
        "headcount_total": ("kpi_headcount", ["active_headcount"], []),
        "headcount_by_department": ("kpi_headcount", ["active_headcount"], ["department_name"]),
        "receivables_total": ("kpi_receivables_payables", ["outstanding_receivables"], []),
        "ageing_by_ledger": (
            "kpi_receivables_payables",
            ["outstanding_amount"],
            ["ledger", "ageing_bucket_label"],
        ),
        "leave_by_month": ("kpi_approved_leave_monthly", ["approved_leave_days"], ["period_month"]),
    }
    out = {}
    for name, (table, metrics, cols) in queries.items():
        et.superset_query(api, table, metrics, columns=cols)  # warm-up (connection, metadata)
        out[name] = stats(
            [
                timed_ms(lambda t=table, m=metrics, c=cols: et.superset_query(api, t, m, columns=c).raise_for_status())
                for _ in range(samples)
            ]
        )
    return out


def dashboard_loads(samples: int) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"skipped": "playwright not installed (pip install -e .[bi-test])"}
    out = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.goto(f"{et.SUPERSET_URL}/login/")
        page.fill('input[name="username"], #username', os.environ["SUPERSET_ADMIN_USER"])
        page.fill('input[name="password"], #password', os.environ["SUPERSET_ADMIN_PASSWORD"])
        page.keyboard.press("Enter")
        page.wait_for_url(lambda u: "/login" not in u)
        for slug in ("druksmart-hr", "druksmart-accounts"):
            times = []
            for i in range(samples + 1):
                t = time.perf_counter()
                page.goto(f"{et.SUPERSET_URL}/superset/dashboard/{slug}/")
                page.wait_for_selector(".dashboard-component-chart-holder", timeout=60000)
                page.wait_for_load_state("networkidle", timeout=60000)
                page.wait_for_function(
                    "() => !document.querySelector('.loading, [data-test=\"loading-indicator\"]')",
                    timeout=60000,
                )
                if i:  # first load = warm-up
                    times.append((time.perf_counter() - t) * 1000)
            out[slug] = stats(times)
        browser.close()
    return out


def django_latency(samples: int) -> dict:
    dj = et.Django("demo_executive")
    kpis = {
        "hr.active_headcount": {},
        "hr.active_headcount by department": {"group_by": "department"},
        "hr.employment_status": {},
        "hr.approved_leave": {},
        "ac.outstanding_receivables": {},
        "ac.outstanding_payables": {},
        "ac.overdue_balance": {},
        "ac.overdue_by_ageing": {},
    }
    out: dict = {"kpi_api_ms": {}, "assistant_ms": {}}
    for label, params in kpis.items():
        fn = label.split()[0]
        dj.kpi(fn, **params)
        out["kpi_api_ms"][label] = stats(
            [timed_ms(lambda f=fn, p=params: dj.kpi(f, **p).raise_for_status()) for _ in range(samples)]
        )
    import reconcile

    for question in reconcile.ASK.values():
        dj.ask(question)
        out["assistant_ms"][question] = stats(
            [timed_ms(lambda q=question: dj.ask(q)) for _ in range(max(5, samples // 2))]
        )
    dj.close()
    out["interpreter"] = "rules (deterministic, no LLM); Gemini latency NOT measured (no API key)"
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--skip-pipeline", action="store_true")
    args = parser.parse_args(argv)
    result = {
        "measured_at": datetime.now().isoformat(timespec="seconds"),
        "environment": environment(),
        "volumes": volumes(),
    }
    print("environment + volumes recorded", flush=True)
    if not args.skip_pipeline:
        print("== pipeline (full refresh)", flush=True)
        result["pipeline_full_refresh"] = pipeline_runs(args.runs)
    print("== superset queries", flush=True)
    result["superset_query_ms"] = superset_latency(args.samples)
    print("== dashboards in browser", flush=True)
    result["dashboard_load_ms"] = dashboard_loads(5)
    print("== django", flush=True)
    result["django"] = django_latency(args.samples)
    path = et.save_result("performance", result)
    print(
        json.dumps(
            {k: v for k, v in result.items() if k not in ("pipeline_full_refresh",)},
            indent=1,
            default=str,
        )[:4000]
    )
    print(f"-> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
