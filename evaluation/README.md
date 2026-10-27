# evaluation/: platform-level integration and evaluation tools (Milestone 8)

**Owner:** all members. Report: [docs/evaluation/EVALUATION_REPORT.md](../docs/evaluation/EVALUATION_REPORT.md).

The scripts drive the **running** local platform and write evidence to
`docs/evaluation/results/*.json`. They use the local ERP **sandboxes** and synthetic data only.

| Script | What it does | Changes anything? |
|---|---|---|
| `run_regression.py` | The whole regression suite in dependency order (lint → unit → DB → warehouse → live ERP → KPI service → Superset → browser → reconciliation → access → assistant). Stages whose services are down are SKIPPED | no (`--with-e2e` changes sandbox data) |
| `reconcile.py` | Every KPI across source ERPs (oracle), dbt facts, Superset, Django API, AI answers (incl. answer text), per ERP | no |
| `source_oracle.py` | Independent KPI figures straight from the ERP APIs (read-only users) | no |
| `e2e.py` | Sandbox change → Airflow DAG → all layers; checks the expected deltas and Superset freshness | **sandbox ERP data** (idempotent) |
| `sandbox_changes.py` | The controlled business changes used by `e2e.py` (refuses non-sandbox ERPs) | **sandbox ERP data** |
| `reliability.py` | Fault injection: ERP down, warehouse down, broken dbt model, failing data test, restarts, stale data | stops and starts **local** containers; temporary files removed again |
| `access_matrix.py` | Every role × resource at the Superset, Django and database boundaries, incl. tampering | no |
| `performance.py` | Pipeline (full refresh), Superset, dashboard, Django and assistant timings with environment and volumes | runs 3 pipeline runs |
| `scale_test.py` | Pipeline over ~118,000 SYNTHETIC records (medium), then all KPIs vs the independent oracle ([SCALE_TEST.md](../docs/evaluation/SCALE_TEST.md)) | **truncates the synthetic `*_test` raw tables**; switches the `synthetic-erp` container |
| `usability_walkthrough.py` | The 6 user tasks through the real UIs (headless Edge); NOT a user study | no |
| `db_connections.py` | Which database account each component really uses | no |
| `report_tables.py` | Renders the results as Markdown: `python evaluation/report_tables.py --update docs/evaluation/EVALUATION_REPORT.md` | report file only |
| `evaltools.py` | Shared helpers (Airflow CLI, warehouse, Superset API, Django session client) | — |

Prerequisites:
- `docker compose --profile airflow --profile superset up -d`
- both sandboxes up (`python infrastructure/sandboxes/sandbox.py up odoo|erpnext`)
- Django running (`python backend/manage.py runserver 127.0.0.1:8000`) with the demo users seeded
- `pip install -e ".[dev,warehouse,backend,bi-test]"`

```powershell
python evaluation\run_regression.py --quick     # no services needed (lint + unit)
python evaluation\run_regression.py             # everything that is running
```
