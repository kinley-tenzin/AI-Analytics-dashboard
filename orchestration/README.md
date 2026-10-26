# orchestration/: Apache Airflow DAGs and configuration

**Owner:** Member 2 · **Status:** working (Milestone 5)

| Path | Purpose |
|------|---------|
| `dags/druksmart_elt.py` | The ELT DAG: validate → extract/load (Odoo ∥ ERPNext) → dbt staging → dbt marts (hidden) → tests → publish → report |
| `bin/run_step.sh` | The only command the DAG runs: applies the source mode, then calls `python -m ingestion`, `warehouse/run_dbt.py` or `warehouse/publish.py` |
| `synthetic_mode.env` | Settings for the explicit SYNTHETIC source mode (fictional fixture data; not secrets) |
| `docker/Dockerfile` | Airflow 3.3.2 (Python 3.12) + separate pipeline venv with dbt, installed offline |
| `docker/requirements-pipeline.txt` | Pipeline pins (kept equal to `pyproject.toml` by a unit test) |
| `docker/wheels/` | Pre-downloaded Linux wheels (git-ignored) |

Services are defined in the root `compose.yaml` under the `airflow` profile:
`docker compose --profile airflow up -d`, then open http://127.0.0.1:8085.

Full guide (DAG, schedules, retries, publication, freshness, troubleshooting):
[docs/orchestration/ORCHESTRATION.md](../docs/orchestration/ORCHESTRATION.md).
