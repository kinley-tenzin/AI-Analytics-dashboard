# Integration assessment (Milestone 8, Task 1)

Assessed 2026-10-25 on the reference machine by inspecting the running system:
- container environments, grants, live database sessions and the DAG state;
- `pip check`;
- cross-layer reconciliation and end-to-end runs.

**ERPs:** "Live" means the local Odoo 19 / ERPNext 16 **sandboxes** with synthetic data.
DrukSmart's real ERPs have never been connected.

Legend: ✅ verified working · 🔧 defect found and fixed (verified) · ⚠️ open limitation · ⬜ not verified

## 1. Integration checklist

| # | Integration link | Status | Evidence |
|---|---|---|---|
| 1 | Odoo 19 → connector (JSON-2, read-only API key) | ✅ | `pytest -m live`; E2E runs extracted the sandbox changes |
| 2 | ERPNext 16 → connector (Frappe REST, read-only token) | ✅ | same |
| 3 | Connectors → raw (source identity, batch metadata, versioning, idempotency) | ✅ | E2E repeat run: raw versions 135 → 135; changed records only add versions |
| 4 | raw → dbt staging → intermediate → marts (+ data tests) | ✅ | 164 dbt data tests on 43 models (dbt `ls` count) pass in every DAG run; warehouse suite 19/19 |
| 5 | Build → test → **atomic publication** → consumer grants | ✅ | every run since M5; publication only after `dbt_test_marts`; grants for both consumers in the publish log |
| 6 | Airflow schedule and orchestration (daily 02:00, unpaused) | ✅ | `dags list`: paused = False; 14 Milestone 8 runs (11 success, 3 deliberate failure scenarios) |
| 7 | Airflow → pipeline secrets (least privilege) | 🔧 **D1** | All secrets were reachable in the containers, now restricted (§2) |
| 8 | Superset → warehouse (`superset_reader`, 4 approved datasets) | ✅ | `pg_stat_activity` (§3); access matrix |
| 9 | Superset dashboards show the **latest publication** | 🔧 **D2** | Stale cache after publication, now fixed |
| 10 | Django → warehouse (`kpi_reader`, 4 approved datasets) and → app DB (`app`) | ✅ | `pg_stat_activity`; readiness check |
| 11 | AI assistant → KPI service (same functions, same scope) | ✅ | reconciliation: AI answers = Django = Superset = dbt = source |
| 12 | Gemini provider | ⬜ | no API key; mocked tests only |
| 13 | KPI definitions identical across Superset and Django | ✅ | registry measures = certified Superset metrics (unit tests); 9 cross-system value tests |
| 14 | Data freshness visible and **staleness flagged** | 🔧 **D3** | Dates were shown, but old data was not flagged; now flagged |
| 15 | ERP sandboxes survive Docker restarts | 🔧 **D4** | No restart policy (the M5 incident cause); now set |
| 16 | Role definitions consistent between Superset and Django | 🔧 **D5** | Duplicated configuration; now guarded by tests |
| 17 | Python dependencies consistent | ✅ | `pip check`: No broken requirements found |
| 18 | All service ports bound to 127.0.0.1 | ✅ | `docker ps`: no 0.0.0.0 bindings |
| 19 | Authentication: Superset, Django, Airflow, ERPs | ⚠️ | 4 separate logins, no SSO; Django has no login throttling (D6, fixed in M10 Task 10.3) |
| 20 | Synthetic mode visible to consumers | ⚠️ by design | Synthetic runs write `druksmart_analytics_test`; Superset and Django read the dev DB only (D8) |
| 21 | Real DrukSmart ERPs | ⬜ | Never connected (credentials and versions unknown) |

## 2. Prioritised defect list

| ID | Severity | Defect (how it was found) | Fix | Verification | Status |
|---|---|---|---|---|---|
| **D1** | High | Every Airflow container received **all** platform secrets. `env_file: .env` exposed the PostgreSQL superuser, Superset admin, Django secret, Gemini key and sandbox admin passwords, and the repository mount exposed `.env` again (found by inspecting the container environment). | Explicit allowlist of the pipeline's variables; repository `.env` masked by an empty file mount (`orchestration/docker/no-secrets.env`). | No forbidden variable left in the containers; `.env` inside them has 0 assignments; the post-fix E2E runs succeed with the reduced settings; regression test `test_d1_…` | fixed |
| **D2** | Medium | Superset's 5-minute chart-data cache served the **previous publication** right after a new one (measured in the E2E test: 16 instead of 17 employees, 166,700 instead of 170,200; the freshness table was affected too). | `DATA_CACHE_CONFIG = NullCache` (queries take milliseconds at this volume). | Post-fix E2E: dashboard value = fresh value immediately after both publications; test `test_d2_…` | fixed |
| **D3** | Medium | Consumers showed data *dates* but never warned when data was old (a failed schedule would look current). | Django: `stale` flag, age and warning in every KPI result and answer text, readiness 503 when stale (`DRUKSMART_STALE_AFTER_HOURS`, default 30). Superset: *Hours since publication* column in the freshness tables. | Reliability scenario `stale_data_flagged`; test `test_d3_…` | fixed |
| **D4** | Low | Odoo sandbox (and part of ERPNext) had no restart policy, so they stayed down after Docker Desktop restarted (the M5 scheduled-run incident). | `restart: unless-stopped` on all long-running sandbox services. | `docker inspect` restart policy; test `test_d4_…` | fixed |
| **D5** | Low | Roles/domains and the demo branch are declared separately for Superset and Django (no SSO), so they could drift. | Consistency tests (`tests/unit/test_platform_consistency.py`). | tests pass | mitigated |
| **D10** | Medium | With PostgreSQL down, the Django API answered with Django's **HTML** "Server Error (500)" page instead of its JSON error contract, so the UI could only say "unexpected response". Cause: Django's sessions live in `druksmart_app` on the **same PostgreSQL server** as the warehouse, so authentication fails before any view runs (found by reliability scenario `database_unavailable`). | `kpi.middleware.ApiErrorMiddleware`: any exception under `/api/` becomes JSON (503 for database errors, no data). | Scenario re-run: readiness 503, answer status `error` with a clear message and no numbers, automatic recovery; test `test_api_keeps_json_contract_when_the_database_fails` | fixed |
| **D11** | Info | The warehouse and Django's application database share one PostgreSQL server: a single point of failure for both BI and the assistant (by design for the prototype). | none in M8; separate servers or a managed HA database in deployment | — | open (deployment) |
| **D6** | Low | Django login has no brute-force throttling or lockout. Superset's FAB login has built-in rate limiting. | none in M8 (bound to 127.0.0.1; prototype) | **Fixed in M10 Task 10.3:** 5 failures per username in 15 min lock it (DB-backed, all sign-in paths); `tests/backend/test_auth_api.py` and a live check | fixed |
| **D7** | Info | `bi_reader` (SELECT on all marts) is no longer used by any consumer; only health checks and tests use it. | none | — | open: restrict or remove before deployment |
| **D8** | Info | Synthetic-mode data never reaches Superset or Django (different database). | by design (keeps fictional data apart); documented | — | accepted |
| **D9** | Info | Already-known limitations, carried over: Gemini unverified; no SSO; development servers; HR-03 distinct employees only in Django; ERPNext invoices have no branch (DS-AC-05). | — | — | open (documented in M6/M7) |

The defects found while running the reliability and evaluation tooling itself (scenario script
bugs, not platform defects) are listed in the evaluation report.

## 3. Database connections actually in use

Live `pg_stat_activity` snapshot of the analytics database while every service was running (see
`docs/evaluation/results/db_connections.json`). Each component connects as its intended account;
no component uses the PostgreSQL superuser.

| Component | Account actually used | How it was observed |
|---|---|---|
| Superset | `druksmart_superset_reader@druksmart_analytics` | Superset's registered connection (password masked). SQL Lab rejects `current_user` and `pg_backend_pid`, a Superset defence (`DISALLOWED_SQL_FUNCTIONS`) recorded as a positive finding |
| Django KPI service | `druksmart_kpi_reader@druksmart_analytics` | `select current_user` through `kpi.warehouse.connect()` |
| Airflow pipeline | `druksmart_pipeline@druksmart_analytics` | `select current_user` through `druksmart_common` inside the scheduler container |
| Django metadata | `druksmart_app_user@druksmart_app` (5 sessions) | `pg_stat_activity` |

No component connects as the PostgreSQL superuser.
