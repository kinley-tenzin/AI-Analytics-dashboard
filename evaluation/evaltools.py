"""Shared helpers for platform-level evaluation (Milestone 8): drive and read every layer.

    Airflow   : trigger the DAG, wait, read task states and durations (CLI in the scheduler container)
    Warehouse : read the published marts (pipeline role, read-only queries)
    Superset  : certified-metric queries through its chart-data API, as a given user
    Django    : KPI API and the AI assistant over HTTP, as a given user (session + CSRF)

Credentials come from .env and are never printed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "superset" / "scripts"))
load_dotenv(REPO / ".env", override=False)

from druksmart_common.config import load_settings  # noqa: E402
from druksmart_common.db import connect  # noqa: E402
from superset_api import SupersetClient  # noqa: E402

SUPERSET_URL = f"http://127.0.0.1:{os.environ.get('SUPERSET_PORT', '8088')}"
DJANGO_URL = os.environ.get("DRUKSMART_BACKEND_URL", "http://127.0.0.1:8000")
DAG = "druksmart_elt"
RESULTS_DIR = REPO / "docs" / "evaluation" / "results"


# ---------------------------------------------------------------------------- generic
def save_result(name: str, data) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    return path


def compose(*args: str, check: bool = True, timeout: int = 600) -> subprocess.CompletedProcess:
    """`docker compose` in the main project (never the sandboxes')."""
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=check,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------- Airflow
def airflow(*args: str) -> str:
    return compose("exec", "-T", "airflow-scheduler", "airflow", *args).stdout


def trigger_run(run_id: str, conf: dict | None = None) -> None:
    args = ["dags", "trigger", DAG, "--run-id", run_id]
    if conf:
        args += ["-c", json.dumps(conf)]
    airflow(*args)


def run_state(run_id: str) -> dict | None:
    runs = json.loads(airflow("dags", "list-runs", DAG, "-o", "json") or "[]")
    return next((r for r in runs if r["run_id"] == run_id), None)


def wait_run(run_id: str, timeout_s: int = 1200, poll_s: int = 10) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        state = run_state(run_id)
        if state and state["state"] in ("success", "failed"):
            return state
        time.sleep(poll_s)
    raise TimeoutError(f"run {run_id} did not finish within {timeout_s}s")


def task_states(run_id: str) -> list[dict]:
    rows = json.loads(airflow("tasks", "states-for-dag-run", DAG, run_id, "-o", "json") or "[]")
    out = []
    for r in rows:
        start, end = r.get("start_date"), r.get("end_date")
        seconds = None
        if start and end and start != "None" and end != "None":
            seconds = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
        out.append(
            {
                "task": r["task_id"],
                "state": r["state"],
                "seconds": seconds,
                "try_number": r.get("try_number"),
            }
        )
    return sorted(out, key=lambda t: t["task"])


def run_and_wait(run_id: str, conf: dict | None = None, timeout_s: int = 1200) -> dict:
    trigger_run(run_id, conf)
    started = time.monotonic()
    state = wait_run(run_id, timeout_s)
    return {
        "run_id": run_id,
        "state": state["state"],
        "start_date": state.get("start_date"),
        "end_date": state.get("end_date"),
        "observed_seconds": round(time.monotonic() - started, 1),
        "tasks": task_states(run_id),
    }


# ---------------------------------------------------------------------------- warehouse
def warehouse():
    return connect(load_settings().pipeline(), autocommit=True)


def publication(conn) -> dict:
    row = conn.execute(
        "SELECT publication_id, pipeline_run_id, published_at FROM raw.publication ORDER BY publication_id DESC LIMIT 1"
    ).fetchone()
    fresh = conn.execute(
        "SELECT source_instance, domain, latest_snapshot_date, published_at FROM marts.data_freshness"
    ).fetchall()
    return {
        "publication_id": row[0] if row else None,
        "pipeline_run_id": row[1] if row else None,
        "published_at": row[2].isoformat() if row else None,
        "freshness": [
            {"instance": r[0], "domain": r[1], "data_as_of": str(r[2]), "published_at": str(r[3])} for r in fresh
        ],
    }


# ---------------------------------------------------------------------------- Superset
def superset(user: str = "admin") -> SupersetClient:
    if user == "admin":
        return SupersetClient.login(
            SUPERSET_URL, os.environ["SUPERSET_ADMIN_USER"], os.environ["SUPERSET_ADMIN_PASSWORD"]
        )
    return SupersetClient.login(SUPERSET_URL, user, os.environ["SUPERSET_DEMO_USER_PASSWORD"])


def superset_query(
    api: SupersetClient,
    table: str,
    metrics: list[str],
    *,
    columns=(),
    filters=(),
    force: bool = True,
    fmt: str = "json",
) -> httpx.Response:
    ds = api.find_one("dataset", "table_name", table)
    return api.request(
        "POST",
        "/api/v1/chart/data",
        json={
            "datasource": {"id": ds["id"], "type": "table"},
            "queries": [
                {
                    "metrics": metrics,
                    "columns": list(columns),
                    "filters": list(filters),
                    "row_limit": 10000,
                }
            ],
            "result_type": "full",
            "result_format": fmt,
            "force": force,
        },
    )


def superset_rows(api, table, metrics, **kw) -> list[dict]:
    resp = superset_query(api, table, metrics, **kw)
    resp.raise_for_status()
    return resp.json()["result"][0]["data"]


# ---------------------------------------------------------------------------- Django
class Django:
    """Session client for the Django backend (login form + CSRF), as one user."""

    def __init__(self, username: str, password: str | None = None, base: str = DJANGO_URL):
        self.http = httpx.Client(base_url=base, timeout=60)
        self.http.get("/accounts/login/")
        resp = self.http.post(
            "/accounts/login/",
            data={
                "username": username,
                "password": password or os.environ["BACKEND_DEMO_USER_PASSWORD"],
                "csrfmiddlewaretoken": self.http.cookies["csrftoken"],
            },
            headers={"Referer": f"{base}/accounts/login/"},
        )
        if resp.status_code != 302:
            raise RuntimeError(f"Django login failed for {username}: HTTP {resp.status_code}")
        self.base = base

    def post(self, path: str, payload: dict) -> httpx.Response:
        return self.http.post(
            path,
            json=payload,
            headers={"X-CSRFToken": self.http.cookies["csrftoken"], "Referer": self.base + "/"},
        )

    def kpi(self, function: str, **params) -> httpx.Response:
        return self.post("/api/v1/kpis/run/", {"function": function, **params})

    def ask(self, question: str) -> dict:
        return self.post("/api/v1/ask/", {"question": question}).json()

    def close(self) -> None:
        self.http.close()


def service_up(url: str) -> bool:
    try:
        return httpx.get(url, timeout=5).status_code == 200
    except httpx.HTTPError:
        return False
