"""Reliability and recovery scenarios on the LOCAL integrated platform (Milestone 8, Task 4).

    python evaluation/reliability.py [scenario ...]      # default: all, in order

Each scenario injects ONE fault into the local development environment (sandbox ERPs, the local
PostgreSQL container, temporary files in the dbt project), observes the platform, removes the
fault and verifies recovery. The key check everywhere: nothing invalid or stale is presented as
newly validated data (no new publication, freshness unchanged, consumers flag or refuse).
Results: docs/evaluation/results/reliability.json. Never touches real organisational systems.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import evaltools as et  # noqa: E402

REPO = et.REPO
ODOO = "druksmart-odoo-sandbox-odoo-1"
ERPNEXT = "druksmart-erpnext-sandbox-backend-1"
TEST_DJANGO_PORT = 8001
SUFFIX = datetime.now().strftime("%H%M")


def docker(*args: str) -> str:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=True).stdout


def publication_id() -> int | None:
    with et.warehouse() as conn:
        return et.publication(conn)["publication_id"]


def freshness() -> list:
    with et.warehouse() as conn:
        return et.publication(conn)["freshness"]


def wait_for(predicate, timeout_s: int, poll_s: float = 5) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if predicate():
                return True
        except Exception:
            pass
        time.sleep(poll_s)
    return False


def task(run_id: str, name: str) -> dict:
    return next((t for t in et.task_states(run_id) if t["task"] == name), {})


class DjangoServer:
    """A separate Django instance (port 8001) the scenarios may stop, restart or reconfigure."""

    def __init__(self, extra_env: dict | None = None):
        self.env = {**os.environ, **(extra_env or {})}
        self.proc = None

    def start(self) -> None:
        self.proc = subprocess.Popen(
            [
                sys.executable,
                str(REPO / "backend/manage.py"),
                "runserver",
                f"127.0.0.1:{TEST_DJANGO_PORT}",
                "--noreload",
            ],
            env=self.env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if not wait_for(lambda: et.service_up(f"{self.url}/health/"), 60, 1):
            raise RuntimeError("test Django server did not start")

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{TEST_DJANGO_PORT}"

    def stop(self) -> None:
        if self.proc:
            self.proc.terminate()
            self.proc.wait(30)
            self.proc = None


# ----------------------------------------------------------------------------- scenarios
def erp_temporary_failure() -> dict:
    """Odoo API down when the run starts, back before the retries are exhausted."""
    before = publication_id()
    run_id = f"m8_rel_erp_temporary_{SUFFIX}"
    docker("stop", ODOO)
    et.trigger_run(run_id)
    retried = wait_for(lambda: task(run_id, "validate_odoo_source").get("state") == "up_for_retry", 600)
    docker("start", ODOO)
    state = et.wait_run(run_id, 1800)
    t = task(run_id, "validate_odoo_source")
    after = publication_id()
    # The task-state JSON has no try number; the observed `up_for_retry` state is the evidence.
    passed = retried and state["state"] == "success" and t.get("state") == "success" and after != before
    return {
        "fault": "Odoo sandbox container stopped at run start; restarted after the first failed attempt",
        "expected": "validate_odoo_source fails, is retried automatically, run succeeds and publishes",
        "observed": {
            "up_for_retry_seen": retried,
            "run_state": state["state"],
            "validate_odoo_final_state": t.get("state"),
            "publication_before": before,
            "publication_after": after,
        },
        "passed": passed,
    }


def erp_outage_beyond_retries() -> dict:
    """ERPNext down for the whole run: the run must fail and publish NOTHING."""
    before, fresh_before = publication_id(), freshness()
    run_id = f"m8_rel_erp_outage_{SUFFIX}"
    docker("stop", ERPNEXT)
    try:
        state = et.run_and_wait(run_id, timeout_s=2400)
    finally:
        docker("start", ERPNEXT)
    after, fresh_after = publication_id(), freshness()
    tasks = {t["task"]: t["state"] for t in state["tasks"]}
    passed = (
        state["state"] == "failed"
        and after == before
        and fresh_after == fresh_before
        and tasks.get("publish_validated_marts") in ("upstream_failed", None)
    )
    wait_for(
        lambda: httpx.get(os.environ["ERPNEXT_BASE_URL"] + "/api/method/ping", timeout=5).status_code == 200,
        300,
    )
    return {
        "fault": "ERPNext sandbox backend stopped for the whole run",
        "expected": "run fails after retries; no publication; consumers keep the previous, correctly dated data",
        "observed": {
            "run_state": state["state"],
            "task_states": tasks,
            "publication_before": before,
            "publication_after": after,
            "freshness_unchanged": fresh_after == fresh_before,
        },
        "passed": passed,
    }


def _project_file_fault(run_id: str, path: Path, content: str, failing_task: str) -> dict:
    before, fresh_before = publication_id(), freshness()
    path.write_text(content, encoding="utf-8")
    try:
        state = et.run_and_wait(run_id, timeout_s=1800)
    finally:
        path.unlink(missing_ok=True)
    tasks = {t["task"]: t["state"] for t in state["tasks"]}
    after, fresh_after = publication_id(), freshness()
    return {
        "run_state": state["state"],
        "failing_task": failing_task,
        "failing_task_state": tasks.get(failing_task),
        "publish_state": tasks.get("publish_validated_marts"),
        "publication_unchanged": after == before,
        "freshness_unchanged": fresh_after == fresh_before,
        "passed": state["state"] == "failed"
        and tasks.get(failing_task) == "failed"
        and after == before
        and fresh_after == fresh_before,
    }


def failed_transformation() -> dict:
    obs = _project_file_fault(
        f"m8_rel_dbt_broken_{SUFFIX}",
        REPO / "warehouse/models/staging/zz_m8_broken_model.sql",
        "-- Milestone 8 reliability test: deliberately invalid SQL (removed automatically)\nselect from where\n",
        "dbt_staging_intermediate",
    )
    return {
        "fault": "a staging model with invalid SQL is added to the dbt project",
        "expected": "dbt_staging_intermediate fails; nothing downstream runs; no publication",
        "observed": obs,
        "passed": obs.pop("passed"),
    }


def failed_data_quality() -> dict:
    obs = _project_file_fault(
        f"m8_rel_dq_failure_{SUFFIX}",
        REPO / "warehouse/tests/zz_m8_failing_check.sql",
        "-- Milestone 8 reliability test: a data test that always finds a 'bad' row (removed automatically)\n"
        "select 1 as bad_row\n",
        "dbt_test_marts",
    )
    return {
        "fault": "a data-quality test that always fails is added",
        "expected": "marts are built in marts_build but dbt_test_marts fails; NOT published",
        "observed": obs,
        "passed": obs.pop("passed"),
    }


def recovery_run() -> dict:
    """After the faults: a normal run publishes again and every layer reconciles."""
    import reconcile

    before = publication_id()
    state = et.run_and_wait(f"m8_rel_recovery_{SUFFIX}")
    after = publication_id()
    report = reconcile.reconcile(reconcile.date.fromisoformat(freshness()[0]["data_as_of"]))
    return {
        "fault": "none (recovery after the previous scenarios)",
        "expected": "run succeeds, publishes, all layers reconcile",
        "observed": {
            "run_state": state["state"],
            "publication_before": before,
            "publication_after": after,
            "reconciliation": f"{report['passed']}/{report['total']}",
        },
        "passed": state["state"] == "success" and after != before and report["passed"] == report["total"],
    }


def database_unavailable() -> dict:
    """Warehouse PostgreSQL down: consumers must fail visibly, never show numbers; then recover."""
    server = DjangoServer()
    server.start()
    observed: dict = {}
    try:
        dj = et.Django("demo_executive", base=server.url)
        api = et.superset("admin")
        et.compose("stop", "postgres")
        ready = httpx.get(f"{server.url}/health/ready/", timeout=30)
        observed["django_ready_status"] = ready.status_code
        answer = dj.ask("How many active employees are there?")
        observed["django_answer_status"] = answer["status"]
        text = answer.get("answer") or answer.get("message", "")
        observed["django_answer_http_json"] = True
        observed["django_answer_text"] = text
        observed["django_answer_has_number"] = any(ch.isdigit() for ch in text)
        resp = et.superset_query(api, "kpi_headcount", ["active_headcount"])
        observed["superset_query_http"] = resp.status_code
        observed["superset_returned_data"] = resp.status_code == 200
        et.compose("start", "postgres")
        recovered = wait_for(lambda: dj.ask("How many active employees are there?")["status"] == "answered", 180)
        observed["django_recovered"] = recovered
        observed["superset_recovered"] = wait_for(
            lambda: et.superset_query(api, "kpi_headcount", ["active_headcount"]).status_code == 200,
            180,
        )
        dj.close()
    finally:
        et.compose("start", "postgres")
        wait_for(lambda: et.warehouse().close() is None, 180)
        server.stop()
    passed = (
        observed.get("django_ready_status") == 503
        and observed.get("django_answer_status") == "error"
        and not observed.get("superset_returned_data")
        and observed.get("django_recovered")
        and observed.get("superset_recovered")
    )
    return {
        "fault": "warehouse PostgreSQL container stopped while Superset and Django run",
        "expected": "Django readiness 503 and an explicit 'error' answer without numbers; Superset "
        "query error; both recover automatically when PostgreSQL is back",
        "observed": observed,
        "passed": passed,
    }


def service_restarts() -> dict:
    """Restart Superset, Airflow and Django: sessions/metadata persist, results unchanged."""
    import reconcile

    server = DjangoServer()
    server.start()
    dj = et.Django("demo_hr", base=server.url)
    before = dj.ask("How many active employees are there?")
    server.stop()
    server.start()  # same session cookie must still be valid (sessions live in druksmart_app)
    after = dj.ask("How many active employees are there?")
    server.stop()
    et.compose(
        "--profile",
        "superset",
        "--profile",
        "airflow",
        "restart",
        "superset",
        "airflow-scheduler",
        "airflow-apiserver",
        "airflow-dag-processor",
        timeout=900,
    )
    up = wait_for(lambda: et.service_up(f"{et.SUPERSET_URL}/health"), 300)
    airflow_ok = wait_for(lambda: et.run_state("m8_e2e_phase_a_0115") is not None, 300)
    report = reconcile.reconcile(reconcile.date.fromisoformat(freshness()[0]["data_as_of"]))
    passed = (
        after["status"] == "answered"
        and after["answer"] == before["answer"]
        and up
        and airflow_ok
        and report["passed"] == report["total"]
    )
    return {
        "fault": "restart of Django (new process), Superset and the Airflow services",
        "expected": "logged-in Django session survives; Superset/Airflow come back; reconciliation unchanged",
        "observed": {
            "django_session_survived": after["status"] == "answered",
            "same_answer": after["answer"] == before["answer"],
            "superset_healthy": up,
            "airflow_history_available": airflow_ok,
            "reconciliation": f"{report['passed']}/{report['total']}",
        },
        "passed": passed,
    }


def stale_data_flagged() -> dict:
    """A consumer whose data is older than the threshold must say so (threshold lowered)."""
    server = DjangoServer({"DRUKSMART_STALE_AFTER_HOURS": "0.001"})
    server.start()
    try:
        dj = et.Django("demo_executive", base=server.url)
        answer = dj.ask("How many active employees are there?")
        ready = httpx.get(f"{server.url}/health/ready/", timeout=30)
        dj.close()
    finally:
        server.stop()
    stale_flag = (answer.get("result") or {}).get("stale")
    passed = (
        stale_flag is True
        and "not current" in answer["answer"]
        and ready.status_code == 503
        and ready.json()["checks"]["warehouse"]["stale"]
    )
    return {
        "fault": "staleness threshold lowered to 3.6 s, so the current publication counts as old",
        "expected": "answer still shows the value but states it is not current; readiness 503 (stale)",
        "observed": {
            "result_stale": stale_flag,
            "answer": answer["answer"],
            "ready_status": ready.status_code,
            "ready_warehouse": ready.json()["checks"]["warehouse"],
        },
        "passed": passed,
    }


SCENARIOS = {
    "erp_temporary_failure": erp_temporary_failure,
    "erp_outage_beyond_retries": erp_outage_beyond_retries,
    "failed_transformation": failed_transformation,
    "failed_data_quality": failed_data_quality,
    "recovery_run": recovery_run,
    "database_unavailable": database_unavailable,
    "service_restarts": service_restarts,
    "stale_data_flagged": stale_data_flagged,
}


def main(argv: list[str]) -> int:
    names = argv or list(SCENARIOS)
    results = {}
    for name in names:
        print(f"== {name}", flush=True)
        started = time.monotonic()
        try:
            r = SCENARIOS[name]()
        except Exception as exc:  # a crashed scenario is a FAILED scenario, with the reason
            r = {"passed": False, "error": f"{type(exc).__name__}: {exc}"}
        r["seconds"] = round(time.monotonic() - started, 1)
        results[name] = r
        print(
            f"   {'PASS' if r['passed'] else 'FAIL'} ({r['seconds']} s): {r.get('observed', r.get('error'))}",
            flush=True,
        )
    existing = {}
    path = et.RESULTS_DIR / "reliability.json"
    if path.exists():
        import json

        existing = json.loads(path.read_text(encoding="utf-8"))
    existing.update(results)
    et.save_result("reliability", existing)
    return 0 if all(r["passed"] for r in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
