# tests/ — automated tests

| Folder | Needs | Run with |
|--------|-------|----------|
| `unit/` | nothing (pure Python) | `pytest tests/unit` |
| `smoke/` | running PostgreSQL (`docker compose up -d`) | `pytest -m smoke` |
| `unit/connectors/` | nothing (fake ERP APIs via httpx MockTransport) | `pytest tests/unit/connectors` |
| `integration/` | running PostgreSQL + `python -m ingestion migrate` | `pytest -m db` |
| `live/` | real ERPs configured in `.env` (e.g. the local sandboxes); **skipped otherwise** | `pytest -m live -v` |
| `warehouse/` | PostgreSQL + dbt; uses ONLY the isolated `_test` database | `pytest -m warehouse -v` |
| `backend/` | Django tests: unit/API need nothing (SQLite in memory); `-m backend` needs the published dev warehouse and the KPI reader; skipped otherwise | `pytest tests/backend -v` |
| `superset/` | running Superset + `bootstrap.py` (demo users); read-only against the dev warehouse (the authoring test creates and deletes 2 dashboards); **skipped otherwise** | `pytest -m superset -v` |
| `frontend/src/**/*.test.ts(x)` | Node + `npm ci` in `frontend/` | `npm --prefix frontend run verify` |
| `frontend/scripts/browser_check.py` | the whole running stack + Edge (`.[bi-test]`) | `python frontend/scripts/browser_check.py` |

DAG runs (retries, recovery, publication) are verified with real Airflow runs; see
`docs/orchestration/ORCHESTRATION.md` §8. `tests/unit/test_orchestration.py` covers the static parts.
| `fixtures/synthetic/` | Synthetic Odoo/ERPNext extraction batches + hand-calculated `expected_kpis.json` | used by unit tests |
| `support/` | Test-only helpers (importable via `pythonpath`), e.g. the independent KPI reference calculator | |

Run everything: `pytest` (from the repo root, with `.venv` activated), or the staged platform
regression with prerequisite checks: `python evaluation/run_regression.py` (`--quick` = no services).
Platform-level evaluation (end-to-end, reconciliation, reliability, access, performance): `evaluation/`.

Organise new tests by area to avoid merge conflicts, e.g. `tests/unit/connectors/`,
`tests/integration/ingestion/`. dbt data tests live in `warehouse/`, next to the models they test.
