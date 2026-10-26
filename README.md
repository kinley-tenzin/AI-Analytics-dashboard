# DrukSmart Analytics & AI Dashboard Platform

Final-year Industry Research Project, Group 8, College of Science and Technology (Royal University
of Bhutan), with industry partner **DrukSmart**.

The platform integrates **Human Resources** and **Accounts** data from **Odoo** and **ERPNext**
through read-only APIs into a PostgreSQL analytical warehouse (dbt, Kimball star schemas).
**Apache Airflow** refreshes and publishes validated KPIs daily. Users work in **one DrukSmart
website** (React + TypeScript, served by **Django**): an overview of authorised KPIs, the **Apache
Superset** dashboards embedded with per-user guest tokens and row-level security, a bounded **Ask AI**
assistant that answers only through approved KPI functions, downloadable reports and administration.

> **Status: prototype complete (Milestones 1–10), including the unified website (Milestone 10).**
> - **Verified:** end to end on **local ERP sandboxes and synthetic data**, with KPIs reconciled
>   across every layer, failure and recovery tested, access tested and performance measured
>   ([evaluation report](docs/evaluation/EVALUATION_REPORT.md)).
> - **Not connected:** DrukSmart's real ERPs; Gemini was never called with a real key.
> - **No real-user study yet.**
> - **Not production-ready:** see [the limitations](docs/TECHNICAL_DOCUMENTATION.md#16-known-limitations-and-future-enhancements).

## Quick start (Windows, PowerShell)

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,warehouse,backend,bi-test]"
python deploy\druksmart.py check            # Docker, RAM, disk, ports
python deploy\druksmart.py setup --build    # everything: .env, images, databases, services, data
python deploy\druksmart.py status
```

Then open (local machine only):
- **The DrukSmart website:** <http://127.0.0.1:8000/app/>. Overview, HR and Accounts Analytics, Ask AI, Reports and Administration, with one sign-in.
- **Superset** (dashboard authoring by the HR and Accounts Managers, administration): <http://127.0.0.1:8088>
- **Airflow:** <http://127.0.0.1:8085>

Passwords are in your local `.env`. Never commit it or share it.

To use live ERP data locally, start the sandboxes first
([docs/connectors/SANDBOXES.md](docs/connectors/SANDBOXES.md)). Without them, `setup` loads the
clearly labelled **synthetic** dataset.

## Documentation

| For | Read |
|---|---|
| Everyone: system overview | [docs/TECHNICAL_DOCUMENTATION.md](docs/TECHNICAL_DOCUMENTATION.md) · handover status: [docs/HANDOVER_REPORT.md](docs/HANDOVER_REPORT.md) |
| Business users | [docs/USER_GUIDE.md](docs/USER_GUIDE.md) |
| The website (frontend, sign-in, embedding) | [docs/web/FRONTEND.md](docs/web/FRONTEND.md), [docs/web/AUTHENTICATION.md](docs/web/AUTHENTICATION.md), [docs/web/EMBEDDING.md](docs/web/EMBEDDING.md), [docs/web/WEB_APP_ARCHITECTURE.md](docs/web/WEB_APP_ARCHITECTURE.md) |
| Installing, operating, backup, troubleshooting | [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md), [docs/DEVELOPMENT_SETUP.md](docs/DEVELOPMENT_SETUP.md) |
| Final demonstration | [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) |
| Evaluation evidence | [docs/evaluation/EVALUATION_REPORT.md](docs/evaluation/EVALUATION_REPORT.md), [docs/evaluation/INTEGRATION_ASSESSMENT.md](docs/evaluation/INTEGRATION_ASSESSMENT.md), [docs/evaluation/USABILITY.md](docs/evaluation/USABILITY.md) |
| Academic report material | [docs/academic/PROJECT_EVIDENCE.md](docs/academic/PROJECT_EVIDENCE.md) |
| Design decisions, progress, roadmap | [docs/DECISIONS.md](docs/DECISIONS.md), [docs/PROGRESS.md](docs/PROGRESS.md), [docs/PROJECT_ROADMAP.md](docs/PROJECT_ROADMAP.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Components | [connectors](docs/connectors/CONNECTORS.md) · [data analysis & mappings](docs/data/SOURCE_TO_TARGET_MAPPING.md) · [KPI catalogue](docs/data/KPI_CATALOGUE.md) · [warehouse](docs/warehouse/WAREHOUSE.md) · [orchestration](docs/orchestration/ORCHESTRATION.md) · [Superset](docs/bi/SUPERSET.md) · [backend & AI](docs/backend/BACKEND.md) |

## Repository layout

| Path | Purpose | Owner |
|------|---------|-------|
| `connectors/` | Read-only Odoo / ERPNext API adapters (+ synthetic fake APIs) | Member 1 |
| `ingestion/` | Extraction runs, versioned raw store, quarantine, checkpoints | Member 1 / 2 |
| `contracts/` | Source contracts, canonical models, verified identity mappings | Member 1 / 2 |
| `warehouse/` | dbt project (staging → intermediate → marts), publication script | Member 2 |
| `orchestration/` | Airflow DAG, step script, Airflow image | Member 2 |
| `superset/` | Superset image/config, governed definitions, dashboard assets, bootstrap | Member 3 |
| `backend/` | Django KPI service, AI assistant, website API (`portal`, `access`), backend image, evaluation set | Member 4 |
| `frontend/` | The DrukSmart website (React + TypeScript, Vite), built into the backend image | Members 3 + 4 |
| `deploy/` | `druksmart.py` operations: check, setup, up, status, backup, restore | everyone |
| `evaluation/` | Platform evaluation: end-to-end, reconciliation, reliability, access, performance, regression | everyone |
| `infrastructure/` | PostgreSQL init script, env generator, ERP sandboxes | Member 2 |
| `druksmart_common/` | Shared settings, DB helper, health checks, contract validation | shared |
| `tests/` | pytest suites (unit, DB, warehouse, live ERP, backend, Superset) + synthetic fixtures | everyone |
| `docs/` | All documentation | everyone |
| `compose.yaml` | Docker Compose deployment (profiles `airflow`, `superset`, `backend`) | Member 2 |

## Tests

```powershell
python evaluation\run_regression.py --quick   # lint + unit + frontend tests, no services needed
python evaluation\run_regression.py           # every stage whose services are running
pytest                                        # all pytest suites (service-dependent ones skip)
```

## Ground rules

- The platform **never writes to an ERP**; ERP API users are read-only.
- Secrets live only in `.env` (git-ignored). Each container receives only the settings it needs.
- Superset and the assistant read **only** approved KPI datasets, through dedicated read-only accounts.
- Website viewers never sign in to Superset: Django mints a 5-minute guest token per user and dashboard, with the user's branch as row-level security.
- Synthetic (fictional) data is always labelled as such.
