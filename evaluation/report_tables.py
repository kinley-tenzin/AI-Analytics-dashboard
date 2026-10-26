"""Render the recorded evaluation results as Markdown tables for the report (no numbers typed by hand).

    python evaluation/report_tables.py > docs/evaluation/_generated_tables.md

Reads docs/evaluation/results/*.json written by the evaluation scripts.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RESULTS = Path(__file__).resolve().parents[1] / "docs" / "evaluation" / "results"


def load(name: str):
    path = RESULTS / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:,.2f}" if not v.is_integer() or abs(v) >= 1000 else f"{v:,.0f}"
    if isinstance(v, dict):
        return "; ".join(f"{k}: {fmt(x)}" for k, x in v.items())
    return str(v)


def reconciliation(name: str) -> str:
    r = load(name)
    if not r:
        return f"_{name}: not run_\n"
    out = [
        f"As of {r['as_of']} (publication {r['publication']['publication_id']}, run "
        f"`{r['publication']['pipeline_run_id']}`): **{r['passed']}/{r['total']} checks passed**.\n",
        "| KPI | Source ERPs (oracle) | dbt facts | Superset | Django API | AI answer | Result |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in r["checks"]:
        layers = c["layers"]
        out.append(
            "| "
            + " | ".join(
                [c["kpi"]]
                + [
                    fmt(layers.get(k, "n/a")) if k in layers else "n/a"
                    for k in ("source", "dbt", "superset", "django", "ai")
                ]
            )
            + f" | {'PASS' if c['ok'] else 'FAIL'} |"
        )
    out.append(
        "\nAI answer text contains the source value: "
        + ", ".join(f"{k} {'✓' if v else '✗'}" for k, v in r["ai_answer_text_contains_source_number"].items())
    )
    return "\n".join(out) + "\n"


def e2e(name: str) -> str:
    r = load(name)
    if not r:
        return f"_{name}: not run_\n"
    out = [
        "| Phase | Airflow run | State | Run time (s) | Raw versions | Reconciliation "
        "| Superset right after publish | Deltas as expected |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for p in r["phases"]:
        cache = p["superset_cache_after_publish"]
        stale = any(v["stale"] for v in cache.values())
        deltas = sum(d["ok"] for d in p["deltas"].values())
        out.append(
            f"| {p['phase']} | `{p['airflow']['run_id']}` | {p['airflow']['state']} | "
            f"{p['airflow']['observed_seconds']} | {p['raw_versions']['before']} → {p['raw_versions']['after']} | "
            f"{p['reconciliation']['passed']}/{p['reconciliation']['total']} | "
            f"{'STALE (previous values)' if stale else 'current'} | {deltas}/{len(p['deltas'])} |"
        )
    out.append("")
    out.append("| KPI | " + " | ".join(p["phase"] for p in r["phases"]) + " |")
    out.append("|---|" + "---|" * len(r["phases"]))
    for k in r["phases"][0]["deltas"]:
        cells = []
        for p in r["phases"]:
            d = p["deltas"][k]
            cells.append(
                f"{fmt(d['before'])} → {fmt(d['after'])} (exp {d['expected_delta']:+g}, "
                f"got {d['actual_delta']:+g}) {'✓' if d['ok'] else '✗'}"
            )
        out.append(f"| {k} | " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def reliability() -> str:
    r = load("reliability")
    if not r:
        return "_reliability: not run_\n"
    out = ["| Scenario | Fault injected | Expected | Observed | Result |", "|---|---|---|---|---|"]
    for name, s in r.items():
        obs = s.get("observed", s.get("error"))
        out.append(
            f"| {name} | {s.get('fault', '')} | {s.get('expected', '')} | "
            f"{json.dumps(obs, default=str)[:400]} | {'PASS' if s['passed'] else 'FAIL'} |"
        )
    return "\n".join(out) + "\n"


def access() -> str:
    r = load("access_matrix")
    if not r:
        return "_access matrix: not run_\n"
    out = [
        f"**{r['passed']}/{r['total']} access checks behaved as the policy requires.**\n",
        "| User | Boundary | Resource | Attempt | Expected | Actual | Result |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in r["checks"]:
        out.append(
            f"| {c['user']} | {c['boundary']} | {c['resource']} | {c['attempt']} | "
            f"{c['expected']} | {c['actual']} | {'PASS' if c['pass'] else 'FAIL'} |"
        )
    return "\n".join(out) + "\n"


def performance() -> str:
    r = load("performance")
    if not r:
        return "_performance: not run_\n"
    env, vol = r["environment"], r["volumes"]
    out = [
        f"Measured {r['measured_at']}. Environment: {env.get('cpu')}, {env.get('logical_cpus')} "
        f"logical CPUs, {env.get('ram_gb')} GB RAM, {env.get('os')}, Docker {env.get('docker')}, "
        f"{env.get('containers_running')} containers running (incl. ERP sandboxes and unrelated "
        f"coursework containers).\n",
        f"Data volume: {vol['current_source_records_total']} current source records "
        f"({vol['raw_record_versions']} raw versions); mart rows: {fmt(vol['mart_rows'])}.\n",
    ]
    p = r.get("pipeline_full_refresh")
    if p:
        out += [
            "**Pipeline (full refresh, Airflow, seconds):**\n",
            "| Step | n | min | p50 | max |",
            "|---|---|---|---|---|",
            f"| **whole DAG run** | {p['run_total_seconds']['n']} | {p['run_total_seconds']['min']} | "
            f"{p['run_total_seconds']['p50']} | {p['run_total_seconds']['max']} |",
        ]
        for task, s in p["task_seconds"].items():
            out.append(f"| {task} | {s['n']} | {s['min']} | {s['p50']} | {s['max']} |")
        ex = p["runs"][-1]["extraction"]
        out += [
            "",
            "**Extraction per entity (last full-refresh run):**\n",
            "| Entity | Records | Seconds |",
            "|---|---|---|",
        ] + [f"| {e['entity']} | {e['records_fetched']} | {e['seconds']} |" for e in ex]
    out += [
        "",
        "**Query latency (ms):**\n",
        "| Request | n | p50 | p95 | max |",
        "|---|---|---|---|---|",
    ]
    for k, s in r["superset_query_ms"].items():
        out.append(f"| Superset chart data: {k} | {s['n']} | {s['p50']} | {s['p95']} | {s['max']} |")
    for k, s in (r.get("dashboard_load_ms") or {}).items():
        if isinstance(s, dict):
            out.append(
                f"| Superset dashboard full load in browser: {k} | {s['n']} | {s['p50']} | {s['p95']} | {s['max']} |"
            )
    for k, s in r["django"]["kpi_api_ms"].items():
        out.append(f"| Django KPI API: {k} | {s['n']} | {s['p50']} | {s['p95']} | {s['max']} |")
    for k, s in r["django"]["assistant_ms"].items():
        out.append(f"| AI assistant (rules): {k} | {s['n']} | {s['p50']} | {s['p95']} | {s['max']} |")
    return "\n".join(out) + "\n"


def usability() -> str:
    r = load("usability_walkthrough")
    if not r:
        return "_usability walkthrough: not run_\n"
    out = [
        "| Task | Role / UI | Expert-path user actions | Shown in UI | Expected | Completed |",
        "|---|---|---|---|---|---|",
    ]
    for t in r:
        out.append(
            f"| {t['task']} | {t.get('role', '')} · {t.get('ui', '')} | {t.get('actions', '')} | "
            f"{fmt(t.get('shown', t.get('error')))} | {fmt(t.get('expected', ''))} | "
            f"{'yes' if t['completed'] else 'NO'} |"
        )
    return "\n".join(out) + "\n"


def regression() -> str:
    r = load("regression")
    if not r:
        return "_regression: not run_\n"
    out = [
        f"Run {r['run_at']}.\n",
        "| Stage | Covers | Status | Seconds | Last output line |",
        "|---|---|---|---|---|",
    ]
    for s in r["stages"]:
        out.append(
            f"| {s['stage']} | {s['covers']} | {s['status']} | {s.get('seconds', '')} | "
            f"{(s.get('summary') or [s.get('reason', '')])[-1]} |"
        )
    return "\n".join(out) + "\n"


SECTIONS = {
    "RECONCILIATION_BASELINE": lambda: reconciliation("reconciliation_baseline"),
    "E2E": lambda: e2e("e2e"),
    "E2E_POST_FIX": lambda: e2e("e2e_post_fix"),
    "RELIABILITY": reliability,
    "ACCESS": access,
    "PERFORMANCE": performance,
    "USABILITY": usability,
    "REGRESSION": regression,
}


def update(path: Path) -> None:
    """Replace each <!-- GENERATED:KEY --> ... <!-- /GENERATED:KEY --> block with current tables."""
    import re

    text = path.read_text(encoding="utf-8")
    for key, render in SECTIONS.items():
        start, end = f"<!-- GENERATED:{key} -->", f"<!-- /GENERATED:{key} -->"
        block = f"{start}\n{render().rstrip()}\n{end}"
        text = re.sub(re.escape(start) + r".*?" + re.escape(end), lambda m, b=block: b, text, flags=re.S)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--update"]:
        update(Path(sys.argv[2]))
    else:
        for key in sys.argv[1:] or SECTIONS:
            print(f"<!-- {key} -->\n{SECTIONS[key]()}")
