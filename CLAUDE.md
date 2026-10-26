# CLAUDE.md — DrukSmart Analytics & AI Dashboard Platform

Persistent engineering guidance for Claude Code sessions on this repository.
These rules stay active across every milestone. Read this file at the start of each session.

## 1. Project context

- **Project:** Analytics & AI Dashboard Platform (Industry Research Project, final year)
- **Industry partner:** DrukSmart (external guide: Associate Director, Technology & Application Dept.)
- **Institution:** College of Science and Technology (CST), Royal University of Bhutan, Computing Technologies Dept.
- **Team:** Group 8, four members
- **Source specification:** `Group8_DrukSmart.pdf` (project proposal), to be kept at
  `docs/reference/Group8_DrukSmart.pdf`. If it is missing, ask the user to add it before relying on
  proposal details. Where the proposal conflicts with Section 2 below, **Section 2 wins**.

Claude's role: Principal Software Architect, Senior Full-Stack Engineer, Data Engineering Lead, DevOps
Engineer, QA Engineer and Technical Mentor. The goal is a complete, technically sound, integrated,
demonstrable prototype. This is not a simple dashboard demo, CRUD app or tutorial project.

## 2. Confirmed implementation decisions (override older proposal text)

| Area | Decision |
|---|---|
| ERP sources | Odoo and ERPNext **only** |
| Business modules | Human Resources and Accounts **only** |
| ERP integration | Python, API-driven, **read-only** connectors (Odoo JSON-2 / external API; ERPNext Frappe REST) |
| Database | PostgreSQL |
| Transformations & data tests | dbt Core |
| Warehouse model | Kimball star schemas, explicit fact-table grains, conformed dimensions (Date, Organisation, Branch…); Type 2 SCD only where justified |
| Orchestration | Apache Airflow |
| BI / dashboards | Apache Superset (use its native authoring; **do not build a custom dashboard designer**) |
| Supporting backend & controlled AI | Django |
| AI | Bounded NL questions answered **only** through approved KPI functions over authorised analytical data |
| Deployment model | One client organisation per deployment; multiple ERP sources per client allowed |
| Future work (out of scope) | Multi-tenant SaaS, other ERPs (SAP, Oracle, Dynamics), Sales/Finance/Inventory modules |
| Optional (only after core is complete) | Forecasting (TimesFM), advanced notifications |

### Known proposal conflicts already resolved by the table above
- Proposal mentions a "Django backend and React dashboard" (Lit. Review) → dashboards are **Superset**; Django serves AI/supporting services only and does not proxy Superset chart queries.
- Phase Two schedule lists "Sales & Finance Extensions" and warehouse section lists Sales/Finance analytics → **out of scope**.
- Risk section says permissions are enforced "on the Django side" → dashboard/export access is enforced by **Superset** roles, dataset permissions and row-level security; Django enforces access for AI requests. Neither may bypass the other.
- Aim mentions "real-time" → implementation is **scheduled batch / near-real-time refresh** via Airflow, not streaming.

## 3. Required end-to-end architecture

```
Odoo / ERPNext
  → Python API connectors (read-only, common connector interface)
  → PostgreSQL raw data (source tagging + extraction metadata)
  → dbt staging & standardisation
  → integrated data models
  → dimensional analytical warehouse (star schemas)
  → validated HR & Accounts KPI datasets
  → Apache Superset dashboards  +  Django AI services
Apache Airflow orchestrates extraction, transformation, validation and publishing.
```

ERP systems remain the operational source of truth. **The platform must never modify ERP transactional records.**

## 4. Engineering standards

### Architecture
- Modular, maintainable codebase; clear separation of integration, transformation, orchestration, BI and AI.
- Documented service and data contracts.
- No unnecessary services or duplicated functionality.
- Prefer stable, compatible, pinned versions and reproducible development environments.

### Data engineering
- Preserve ERP source identity and extraction metadata on every raw record (source ERP, source instance, source id, extraction batch, extraction timestamp).
- Idempotent loading wherever possible.
- Prevent duplicates and incorrect cross-ERP entity merging (never merge entities across ERPs without a verified mapping).
- Document every KPI calculation and every fact-table grain.
- Reconcile warehouse results against known ERP records.
- Validate missing fields, references, dates, amounts and relevant status values.
- Financial facts must define as-of/valuation date and treatment of partial payments, cancellations, credit notes and currency consistently across both ERPs.

### Security
- Credentials via environment variables / local untracked config (`.env` never committed; provide `.env.example`).
- Essential authentication and role-based access (roles: HR, Accounts, Branch Manager, Executive, Admin).
- Enforce dataset and organisational restrictions in the systems that actually query data.
- External AI services get **no** unrestricted database access; send only aggregated, authorised KPI results — never individual employee records, bank details, ID documents or pay amounts.
- Do not expand into unnecessary enterprise-grade security engineering.

### Quality
- Readable, maintainable, well-structured code.
- Appropriate unit, integration and data-quality tests; run them for real whenever possible.
- **Never fabricate implementation progress or test results.**
- Clearly label components as **working**, **simulated/stubbed**, or **incomplete**.
- Fix identified defects before moving on when feasible.
- No visually impressive interfaces without genuine backend functionality.

## 5. Working method — one milestone at a time

For each milestone:
1. Read the current codebase and project documentation.
2. Understand the milestone's dependencies.
3. Briefly explain the implementation plan.
4. Implement the required components.
5. Execute appropriate tests.
6. Fix failures where possible.
7. Update project documentation and `docs/PROGRESS.md`.
8. Summarise what is complete, incomplete, tested and untested.
9. **STOP and wait for permission before starting the next milestone.**

- If a milestone is too large, split it into checkpoints and confirm where necessary.
- Never silently skip requirements or claim success for unverified components.
- A milestone is complete only when its acceptance criteria are met **or** explicitly documented as blocked.

## 6. Beginner-friendly guidance (team are students)

- Teach while building: explain the *why*, not just the *what*.
- Assume a fresh Windows machine; do not assume Python, PostgreSQL, Git, Docker, WSL2, ERP servers etc. are installed. **Inspect the actual environment before configuring it.**
- For every manual step: explain why, give exact Windows-compatible instructions and commands, state the expected successful result, help diagnose errors, and wait for confirmation if it blocks further work.
- **Never ask for passwords, database credentials or API tokens in chat** — guide the user to set them locally.
- **No destructive commands without explicit permission.**
- The repo lives at `C:\Users\ASUS\FYP` (local, not OneDrive-synced). If it is ever moved into a synced folder (OneDrive, Google Drive), keep Docker volumes, database data directories, virtualenvs and `node_modules` out of the synced path.
- Git repository on branch `main` (initialised in Milestone 1). Commit only when the user asks.

### Verified environment facts (Milestone 1, reference machine)
- Python 3.14.3 host, project `.venv`; run tools as `.\.venv\Scripts\python.exe -m ...`.
- PostgreSQL runs in Docker (`postgres:17.11-bookworm`) on **127.0.0.1:5433**; a native PostgreSQL 18
  Windows service owns 5432, so do not use 5432. Use `127.0.0.1`, not `localhost` (~5 s IPv6 fallback per connection).
- Verify the database with `python -m druksmart_common.healthchecks` and `pytest`.
- Read passwords only from `.env` and never print them. Edit `.env` with in-place line replacement, never by displaying it.
- If `docker info` reports "Docker Desktop is unable to start": quit Docker Desktop, run `wsl --shutdown`, restart it.
- The machine also runs other coursework containers (kind clusters, DVWA). They are the user's; never stop or remove them.
- dbt: pin dbt-core 1.12.0 + dbt-postgres 1.11.0 (1.12.6 needs a pre-release dependency). See `docs/DECISIONS.md` ADR-005.

### Data contracts (Milestone 2)
- Targets: Odoo 19.0 (JSON-2) and ERPNext/HRMS 16 (Frappe REST). Contracts in `contracts/`;
  fields marked `verification: assumption` are unverified until checked against a sandbox.
- Cross-ERP identity only via `contracts/mappings/entity_mappings.yaml`. Never merge on names.
- `tests/fixtures/synthetic/expected_kpis.json` is hand-calculated and is the target every
  future warehouse/KPI implementation must reproduce. Edit fixtures via `generate_fixtures.py`, not by hand.
- Open business decisions DS-… are listed in `docs/data/KPI_CATALOGUE.md`. Do not invent policy for them.

### ERP integration (Milestone 3)
- Use `python -m ingestion …` for extraction; raw tables come from `ingestion/migrations/`.
- Local sandboxes: ALWAYS manage them with `python infrastructure/sandboxes/sandbox.py` (passes `-p`).
  Never run their compose files with `--env-file .env` alone: `.env` sets `COMPOSE_PROJECT_NAME=druksmart`.
- Sandbox ports: Odoo 127.0.0.1:8069, ERPNext 127.0.0.1:8090 (8080 is used by the user's WordPress stack).
- In PowerShell, piping a script into `docker exec` adds a BOM; use the Bash tool or `sandbox.py` instead.
- Live tests (`pytest -m live`) prove sandbox connectivity only, NOT DrukSmart's ERPs. Say so in reports.
- Milestone 3 stopped the user's coursework clusters (minikube, cte412-*, 4it-*); see docs/connectors/SANDBOXES.md to restore.

### Warehouse (Milestone 4)
- Run dbt only via `python warehouse/run_dbt.py …` (loads `.env`); targets `dev` and `test`
  (`druksmart_analytics_test`, used by `pytest -m warehouse`, which truncates ITS raw tables).
- Mapping seeds are GENERATED: edit `contracts/`, then `python warehouse/scripts/generate_seeds.py`.
- Snapshot facts exist only for dates with successful extractions; never fabricate history.
- Quote YAML values like `"1_30"` (YAML reads 1_30 as a number).
- dbt install needs `dbt-core-experimental-parser==2.0.0a4` (wheel). On slow networks download it
  with `curl -C -` and `pip install --find-links <dir>`.

### Orchestration (Milestone 5)
- Airflow: `docker compose --profile airflow up -d`; UI 127.0.0.1:8085; CLI via
  `docker compose exec -T airflow-scheduler airflow …`. DAG `druksmart_elt` only calls `orchestration/bin/run_step.sh`.
- The pipeline publishes marts ONLY via build (`marts_build`) → test → `warehouse/publish.py` swap. Never
  bypass it for consumer-facing data; manual `run_dbt.py build` writes `marts` directly (dev only).
- Synthetic mode (`source_mode=synthetic`) writes to `druksmart_analytics_test`; `as_of` only there.
- Image packages install offline from `orchestration/docker/wheels/` (git-ignored). Refresh them with
  `pip install --dry-run --report` + `curl -C -` when pins change (pip downloads stall on this network).
- `airflow … -o plain` tables shift columns for scheduled runs (logical_date filled); parse carefully.
- ERP sandboxes do not auto-restart after Docker Desktop restarts; scheduled configured runs then fail
  safely (nothing published) until `sandbox.py up` and the run is cleared.

### Superset (Milestone 6)
- Superset 6.1.0 runs as `docker compose --profile superset` (127.0.0.1:8088), image
  `druksmart/superset:6.1.0` (official image + psycopg2; the official one has NO DB driver).
- Superset reads the warehouse ONLY as `druksmart_superset_reader`, SELECT on `superset/approved_datasets.yml`
  (granted by `warehouse/publish.py`). Never point Superset at `bi_reader`/`pipeline` or approve `dim_*`/`fct_*`.
- Change datasets, roles, RLS and templates in `superset/definitions/`, run `python superset/scripts/bootstrap.py`,
  then `python superset/scripts/assets.py export`. Do not hand-edit `superset/assets/`.
- Native filters with "default to first value" need `requiredFirst: true`, or charts load unfiltered.
- Verify with `pytest -m superset` and `python superset/scripts/browser_check.py` (Edge, `.[bi-test]`).
  It must report KPI cards equal to the warehouse.
- Superset import of a dashboard does not overwrite its charts; `assets.py import` imports each type.
- Global Superset CSS lives only in `superset/docker/head_custom_extra.html` (mounted; filter-bar layout). Recreate
  the `superset` container after changing it.

### Django backend + AI (Milestone 7)
- Django 5.2.18 LTS in `backend/`: `python backend/manage.py runserver 127.0.0.1:8000`; metadata in
  `druksmart_app`; tests use `druksmart_backend.settings_test` (SQLite for Django tables only).
- KPIs are served ONLY through `backend/kpi/registry.py` + `service.py` as `druksmart_kpi_reader`
  (`backend/approved_datasets.yml`, granted by `publish.py grant-consumers`). Never let user/model text
  reach SQL; add a KPI = registry entry + tests (values must equal Superset).
- The AI may only PROPOSE a registry function; scope is decided in `access/scope.py`. Rules interpreter is
  the labelled default/fallback: never present it as an LLM. Gemini is unverified until run with a key.
- Evaluate with `python backend/manage.py evaluate_assistant` (needs `seed_demo_users`); keep the
  held-out set unseen when changing rules.
- Files saved by the Edit tool on Windows can get CRLF: shell scripts must stay LF (`sed -i 's/\r$//'`).

### Integration and evaluation (Milestone 8)
- Platform evaluation tools live in `evaluation/`; results in `docs/evaluation/results/`, report tables via
  `python evaluation/report_tables.py --update docs/evaluation/EVALUATION_REPORT.md`. Never type numbers by hand.
- `evaluation/e2e.py` and `sandbox_changes.py` CHANGE SANDBOX ERP data (idempotent, tagged E2E-M8) and refuse
  non-sandbox ERPs. `reliability.py` stops/starts local containers: never run it during a demo.
- Airflow containers get an explicit env allowlist (compose.yaml) and a masked `.env`; add new pipeline
  settings there. Superset chart-data cache is OFF (NullCache) on purpose (stale after publication).
- Django KPI results carry `stale`/`hours_since_publication`; keep API errors JSON (`ApiErrorMiddleware`).

### Deployment and handover (Milestone 9)
- Operate the platform ONLY with `python deploy/druksmart.py …` (check/setup/up/status/run-pipeline/demo-data/
  backup/restore-check/restore/stop). It never removes volumes; `restore --yes` is the only destructive command.
- Django runs as the Compose service `backend` (gunicorn, 127.0.0.1:8000). Do not also start `runserver` on 8000.
- `--env-file` with another COMPOSE_PROJECT_NAME/ports gives an isolated stack (clean-start tests); the project
  `druksmartclean` is a throwaway test stack.
- `DRUKSMART_CONSUMER_DATA=synthetic` (via `demo-data synthetic`) points Superset and the assistant at the
  labelled synthetic `_test` data; switch back with `demo-data live` after demos.
- Container env allowlists live in compose.yaml; backend reads only its own settings (kpi/warehouse.py).

### Unified website (Milestone 10)
- The website is `frontend/` (React 19 + TS 6.0, Vite 8), served by Django `backend/portal` at
  127.0.0.1:8000/app/ (same origin as /api/v1/). Plan: docs/web/WEB_APP_ARCHITECTURE.md; guide: docs/web/FRONTEND.md.
- Pages come from `frontend/src/navigation.ts` (one list). Menus are cosmetic; Django/guest tokens enforce access.
- Never show hardcoded KPI values: unfinished features use the labelled `PendingIntegration` panel.
- npm versions are exact (`save-exact`); TypeScript < 6.1 (typescript-eslint), jsdom 29 (Node 24.14 here).
- The running backend serves the frontend built INTO ITS IMAGE (`/opt/druksmart-frontend`): after frontend
  changes run `docker compose --profile backend build backend` + `deploy/druksmart.py up`.
- Verify with `npm run typecheck`, `npm run lint`, `npm test`, `pytest tests/backend/test_portal.py`,
  `python frontend/scripts/browser_check.py` (Edge, demo users).
- Website sign-in = Django session via `/api/v1/auth/{session,login,logout}/` (access/auth_api.py). Throttling lives
  in `access/throttle.py` (AUTHENTICATION_BACKENDS); never add a sign-in path that bypasses `authenticate()`.
- Browser checks use THROWAWAY usernames for wrong-password tests: 5 failures lock a demo user for 15 min.
- Website API = `backend/portal` (overview, dashboards + guest tokens, reports, assistant info, admin). Overview and
  reports only RUN registry functions; never add KPI arithmetic to portal/ or the frontend.
- Embedding: Superset needs SUPERSET_GUEST_TOKEN_SECRET (never the public default); guest role `DrukSmart Embedded
  Guest` has NO datasets; branch RLS rules come from Django (`portal/superset.py` reads superset/definitions/access.yml).
  A dashboard using datasets outside its module is refused. Docs: docs/web/EMBEDDING.md.
- The website verification is `python frontend/scripts/browser_check.py` (Edge, 161 checks, creates and deletes a
  temporary superuser); regression stages `frontend` + `website_browser`. Old `/` and `/assistant/` redirect to /app/.
- Roles (ADR-044): HR Manager / Accounts Manager (view + AUTHOR their module: Superset creator base with their module's
  datasets; publish on their page via /app/manage), Executive and Branch Manager (view only), Administrator. Retired:
  HR/Accounts Viewer, Dashboard Creator, demo_creator (listed in access.yml `retired_*`; bootstrap removes them).
- The Superset iframe is a separate origin: viewing uses Django-minted guest tokens with RLS added by Django
  (Superset role RLS does NOT apply to guests). Never trust branch/permission data sent by the browser.

## 7. Documentation to maintain

- `CLAUDE.md` — this file (persistent engineering guidance)
- `docs/PROJECT_ROADMAP.md` — development milestones
- `docs/PROGRESS.md` — completed work and next steps
- `docs/ARCHITECTURE.md` — the *actually implemented* architecture
- `docs/DECISIONS.md` — architecture decision records
- `docs/DEVELOPMENT_SETUP.md` — reproducible Windows setup and troubleshooting
- Technical docs for connectors, warehouse, KPI definitions, orchestration, dashboards, AI, deployment and tests

## 8. Team ownership (organise code to minimise conflicts)

| Member | Area |
|---|---|
| Member 1 | ERP integration and data extraction (connectors) |
| Member 2 | Data engineering: PostgreSQL, dbt, Airflow |
| Member 3 | Apache Superset, BI dashboards and reporting |
| Member 4 | Django backend, AI and system integration |

Keep each area in its own top-level directory with its own README and tests so members can work in parallel.

## 9. End-of-milestone report (required every milestone)

1. Components implemented
2. Important files created or changed
3. Architecture decisions
4. Tests executed and results (actual output, not assumed)
5. Manual work required from the user
6. Known issues and limitations
7. Current readiness of the system
8. Recommended next milestone

Then wait for approval before continuing.
