"""DrukSmart ELT: Odoo + ERPNext -> raw -> dbt -> data tests -> publish validated marts.

All work is done by the project's own CLIs through orchestration/bin/run_step.sh; this file only
declares order, parallelism, retries, timeouts and parameters.
See docs/orchestration/ORCHESTRATION.md.
"""

from __future__ import annotations

import os
from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG, Param

REPO = os.environ.get("DRUKSMART_REPO", "/opt/druksmart")
STEP = f"bash {REPO}/orchestration/bin/run_step.sh"
DEFAULT_MODE = os.environ.get("DRUKSMART_SOURCE_MODE", "configured")
SCHEDULE = os.environ.get("DRUKSMART_ELT_SCHEDULE", "0 2 * * *").strip()
BUILD_SCHEMA = "marts_build"
DBT_VARS = f"--vars '{{marts_schema: {BUILD_SCHEMA}}}'"

# Values every task receives (templated per run). append_env keeps .env-provided settings.
RUN_ENV = {
    "DRUKSMART_SOURCE_MODE": "{{ params.source_mode }}",
    "AS_OF": "{{ params.as_of or '' }}",
    "FULL_REFRESH": "{{ params.full_refresh }}",
}

with DAG(
    dag_id="druksmart_elt",
    description="ERP (Odoo, ERPNext) -> raw -> dbt marts -> tests -> publish",
    schedule=None if SCHEDULE.lower() in ("", "none", "manual") else SCHEDULE,
    start_date=pendulum.datetime(2026, 10, 1, tz="Asia/Thimphu"),
    catchup=False,  # a missed day is caught up by the next run's incremental window
    max_active_runs=1,  # one run at a time: shared raw checkpoints and dbt target
    dagrun_timeout=timedelta(hours=2),
    default_args={
        "owner": "druksmart",
        "retries": 2,
        "retry_delay": timedelta(minutes=1),
        "retry_exponential_backoff": True,
        "max_retry_delay": timedelta(minutes=10),
        "execution_timeout": timedelta(minutes=30),
    },
    params={
        "source_mode": Param(
            DEFAULT_MODE,
            enum=["configured", "synthetic"],
            description="configured = .env ERPs; synthetic = fictional fixture APIs",
        ),
        "as_of": Param(
            None,
            type=["null", "string"],
            description="SYNTHETIC ONLY: replay time, e.g. 2026-10-31T17:30:00Z",
        ),
        "full_refresh": Param(False, type="boolean", description="ignore extraction checkpoints"),
    },
    tags=["druksmart", "elt", "hr", "accounts"],
    doc_md=__doc__,
) as dag:

    def step(task_id: str, command: str, **kwargs) -> BashOperator:
        return BashOperator(
            task_id=task_id,
            bash_command=f"{STEP} {command}",
            env=RUN_ENV,
            append_env=True,
            **kwargs,
        )

    # 1. Validate source configuration: connection, auth, version, contracted field access.
    validate = [
        step(f"validate_{s}_source", f"check {s}", execution_timeout=timedelta(minutes=5))
        for s in ("odoo", "erpnext")
    ]
    prepare_raw = step("prepare_raw_schema", "migrate", execution_timeout=timedelta(minutes=5))

    # 2-4. Extract + load (the runner stores each page in raw as it is fetched).
    #      One pool slot per ERP: never two concurrent extractions against the same ERP API;
    #      Odoo and ERPNext run in parallel (different systems, different raw rows).
    extracts = [
        step(f"extract_load_{s}_{m}", f"extract {s} {m}", pool=f"{s}_api", retries=3)
        for s in ("odoo", "erpnext")
        for m in ("hr", "accounts")
    ]

    # 5. Staging + intermediate (+ their data tests). Not visible to BI.
    dbt_staging = step(
        "dbt_staging_intermediate",
        "dbt build --select resource_type:seed path:models/staging path:models/intermediate",
        retries=1,
    )
    # 6. Marts into the HIDDEN build schema.
    dbt_marts = step("dbt_build_marts", f"dbt run --select path:models/marts {DBT_VARS}", retries=1)
    # 7. Data-quality tests on the build schema. Deterministic: no retry.
    dbt_tests = step(
        "dbt_test_marts", f"dbt test --select path:models/marts path:tests {DBT_VARS}", retries=0
    )
    # 8. Only after every test passed: atomic swap into `marts` + freshness stamp + audit log.
    publish = step(
        "publish_validated_marts", "publish {{ run_id }}", execution_timeout=timedelta(minutes=5)
    )
    report = step(
        "report_published_state", "report", retries=0, execution_timeout=timedelta(minutes=5)
    )

    validate >> prepare_raw >> extracts
    extracts >> dbt_staging >> dbt_marts >> dbt_tests >> publish >> report
