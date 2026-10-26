# Progress

Newest entries first. Each entry records what is **working**, **simulated/stubbed** or **incomplete**,
with real test results.

---

## Milestone 10: Unified DrukSmart web application (2026-10-25) · status: complete, awaiting review

- **Post-milestone change (ADR-044): managers author their module's dashboards.** The team clarified that the website is for managers and senior management.
  - **Roles:** HR Viewer → **HR Manager**, Accounts Viewer → **Accounts Manager**. Both build dashboards in Superset with their module's data only, and publish, show and hide them on their own page (new **Manage dashboards** page). Executive and Branch Manager stay view-only. The Dashboard Creator role is retired.
  - **Applied:** Superset re-bootstrapped (old roles removed, `demo_creator` deactivated because Superset still references it); Django migration renamed the groups; demo users re-seeded.
  - **Finding:** Superset lets a manager *save* a chart on another module's dataset but returns no data (403). The test was rewritten to check that, and the website refuses to publish such a dashboard. Three test charts left behind because the owner can't see them were removed as admin.
  - **Tests (all run):** backend + unit **512 passed**; Superset live **58 passed**; Vitest **103/103**; Edge browser check **154/154** (161 minus the demo_creator checks, plus manager checks); access matrix **95/95** (115 minus demo_creator's 20); full regression **14/14**.

- **Task 10.1 (audit and integration architecture):** done; architecture in
  [web/WEB_APP_ARCHITECTURE.md](web/WEB_APP_ARCHITECTURE.md), **approved** by the team (ADR-040):
  React + TypeScript served by Django; viewers use only the website login; creators author in native
  Superset with a separate login (prototype limitation); old assistant page kept until 10.9.
- **Task 10.2 (frontend foundation and navigation):** done (approved). Guide: [web/FRONTEND.md](web/FRONTEND.md).
  - **Working:**
    - `frontend/` (React 19.3, React Router 8.4, TypeScript 6.0, Vite 8.3): app shell, role-aware sidebar, top bar with user, role and sign-out;
    - routing for all six pages, access-denied, not-found and route-error pages;
    - session detection via `/api/v1/me/`; loading, empty and error components; design tokens; responsive layout with a mobile drawer.
    - Django `portal` app serves the build at `/app/` with a CSRF cookie, a strict CSP and no framing.
    - The backend image builds the frontend in a pinned Node stage.
  - **Interim:** sign-in hands over to Django's existing sign-in form and returns to the requested page (in-app form: 10.3).
  - **Labelled placeholders (no figures):** Overview KPIs (10.4), embedded dashboards (10.5), Ask AI (10.6), Reports and admin status (10.7).
  - **Tests (all run):**
    - frontend: typecheck and ESLint clean; Vitest **41/41**;
    - Django: `tests/backend` **150 passed** (22 new portal tests); quick regression 3/3 (401 unit tests);
    - browser: Edge check on the live stack **82/82** (five demo roles, three viewports, no console, CSP or unexpected HTTP errors).
  - **Defect found and fixed:** the menu and close buttons were visible on desktop (CSS specificity).
  - **Not tested in a browser:** the Administration page as an Administrator, because no Django superuser exists yet (covered by unit tests).
- **Proposal reviewed** (`docs/reference/Group8_DrukSmart.pdf` added by the team): it supports the Milestone 10 design (single interface, embedded Superset with signed access, Django for AI, role/organisation scope); no conflict. Notes in WEB_APP_ARCHITECTURE.md.
- **Task 10.3 (authentication and user access):** done. Details: [web/AUTHENTICATION.md](web/AUTHENTICATION.md).
  - **Working:**
    - JSON session API `/api/v1/auth/session|login|logout/`: CSRF-protected, one generic error message, new session id on sign-in;
    - in-app sign-in form (replaces the interim hand-over); sign-out through the API; return to sign-in when the session expires, keeping the page.
  - **Defect D6 fixed:** sign-in throttling (5 failures per username in 15 min, DB-backed so shared by all gunicorn workers, applied in the authentication backend, so it also covers `/accounts/login/` and `/admin/`).
  - **Tests (all run):**
    - `tests/backend` **174 passed** (24 new auth tests, incl. unlocking in admin); quick regression 3/3 (424 unit tests);
    - Vitest **53/53**, typecheck and ESLint clean;
    - Edge on the live stack **101/101**;
    - live throttle check: attempts 1–5 → 401, attempt 6 → 429, no CSRF → 403.
  - **Test fix:** one intermittent Vitest timeout seen once under load (not reproduced in 10 reruns). The wait for asynchronous UI was raised from 1 s to 5 s; no assertion changed.
  - **Limitations:**
    - Superset authoring still needs its own login (approved);
    - throttling is per username (a known username can be locked for 15 min);
    - the Administration page is still untested as an administrator in the browser (no superuser exists).
- **Tasks 10.4–10.9 (built together at the team's request, "build all task 10"), 2026-10-25:**
  - **10.4 Overview:** `/api/v1/portal/overview/` runs 7 existing registry functions under the user's scope (no new business rules). The page shows HR and Accounts tiles, a department chart, receivables/payables ageing charts, reporting date, refresh age and stale/synthetic/branch labels. Amounts are kept per currency. *Bug found by tests and fixed:* the ageing sort prefix was not removed from labels such as "1 1-30 days overdue".
  - **10.5 Secure Superset embedding:** Embedded SDK 0.4.0 with Django-minted guest tokens (ADR-041).
    - `EMBEDDED_SUPERSET`; **guest-token secret required** (Superset's default secret is public); 5-minute tokens; `frame-ancestors` = the website only.
    - Guest role without dataset access and without Explore/View query/share; portal service account (tokens + embedding only; cannot edit, no SQL Lab); branch RLS decided by Django per dataset.
    - The Referer is sent origin-only by the iframe (Superset checks it).
    - *Findings:* Superset role-RLS does not apply to guests (handled); Drill to detail needs `can_samples`, which no DrukSmart role has; the Milestone 6 documentation claiming it was corrected.
  - **10.6 Ask AI:** the conversation page on `/api/v1/ask/`, with suggestions from the registry (`/api/v1/portal/assistant/`), status labels, charts/tables, dashboard links and an honest interpreter label. *Fixed:* a duplicate accessible name.
  - **10.7 Reports and administration** (ADR-042):
    - 9 reports with preview and CSV (formula-injection safe; synthetic data labelled);
    - Administration: status, dashboard visibility, publishing a creator's dashboard (module check; starts hidden) and users/roles;
    - `PortalDashboard` model (official/custom).
    - *Finding:* with `DASHBOARD_RBAC`, creators cannot "Save as" the official templates (Superset owner rule); they build new dashboards (documented).
  - **10.8 Polish:**
    - responsive at 375/820/1440 px (no page-level horizontal scroll);
    - axe-core WCAG 2.1 A/AA audit of 8 pages: no violations, after fixing a label-in-name issue on the visibility toggles.
  - **10.9 Integration:**
    - `/` → `/app/` and `/assistant/` → `/app/ask`; old page view/template/JS removed (ADR-043);
    - regression runner gained `frontend` and `website_browser` stages (and keeps 40 lines of a failed stage);
    - deploy script requires the new secrets and reports the website;
    - documentation updated (USER_GUIDE, DEMO_SCRIPT, TECHNICAL_DOCUMENTATION, ARCHITECTURE, DEPLOYMENT, README, docs/web/*).
  - **Tests (all run, 2026-10-25):**
    - `tests/backend` **236 passed**; `pytest -m superset` **58 passed** (incl. 10 live embedding and 4 live authoring tests);
    - Vitest **97/97**, typecheck and ESLint clean;
    - **Edge browser check 161/161**: roles, sign-in/out, embedded big numbers = KPI service for 4 roles, branch values lower than the organisation's, Ask AI, Reports CSV, Administration (temporary admin), WCAG audit, the **12-step user journey** for an executive and a branch manager, layouts;
    - **full regression 14/14** (three times in a row). Two earlier full runs failed in `website_browser`; their output was masked by a Python SyntaxWarning in the check script. After the fixes (robust chart-menu step, random throwaway username so the sign-in throttle never triggers, warning removed), the website check passed in every run since (5 standalone, 3 full regressions).
  - **Clean-start deployment** of an isolated stack (`druksmartclean`, other ports): unattended `setup --build` in **595 s**; the website check on that fresh stack **161/161**; the throwaway stack was removed (its 4 volumes only).
  - **Limitations:**
    - creators still sign in separately to Superset to author;
    - a guest token can stay valid up to 5 minutes after sign-out;
    - creators cannot copy the official templates;
    - no real-user usability study of the website yet;
    - Superset's image lacks `service-worker.js` (harmless console 404 inside the iframe).

---

## Milestone 9: Deployment, documentation and handover (2026-10-25) · status: complete, awaiting review

Handover report: [HANDOVER_REPORT.md](HANDOVER_REPORT.md). Key documents:
[TECHNICAL_DOCUMENTATION.md](TECHNICAL_DOCUMENTATION.md), [DEPLOYMENT.md](DEPLOYMENT.md),
[USER_GUIDE.md](USER_GUIDE.md), [DEMO_SCRIPT.md](DEMO_SCRIPT.md),
[academic/PROJECT_EVIDENCE.md](academic/PROJECT_EVIDENCE.md).

### Working (verified)
- **Django backend as a Compose service** (`druksmart/backend:5.2.18`, gunicorn, built offline):
  explicit environment allowlist, masked `.env`, health check, migrations at start-up.
- **Operations script** `deploy/druksmart.py`:
  - check, setup, up (`--minimal`), status, run-pipeline, demo-data, backup, restore-check, restore, stop;
  - non-destructive by default.
- **Clean-start deployments of a separate stack** (empty volumes, other ports):
  - **Unattended `setup`:** 515 s to fully working; reconciliation 30/30; dashboards per role.
  - **First clean deployment:** the full regression ran 12/12 stages against it.
  - **No-ERP fallback:** a deployment without reachable ERPs comes up with the labelled synthetic dataset.
- **Backup and restore:**
  - backup of all four databases plus Superset assets;
  - restore-check into temporary databases;
  - full restore into the separate stack, which reproduced every count and reconciled 30/30.
- **Synthetic fallback** (`demo-data synthetic`): values equal the hand-calculated fixtures (16 employees, AR
  221,200.00, 13.5 leave days). The data is labelled in Superset (`source_mode`) and in every answer.
- **Documentation:** technical documentation (16 sections), user guide, deployment guide, demo script and academic
  evidence pack.

### Defects found and fixed
- A manual run of a paused DAG stayed queued (clean-start test). `run-pipeline` now unpauses temporarily.
- A restore with `--no-owner` locked the pipeline out of the warehouse (restore test). Ownership now comes from the dump.
- The `status` command read `is_paused` wrongly (the Airflow CLI returns text). Fixed.
- The backend needed the pipeline password through `load_settings`. The KPI connection now reads only its own settings.

### Not verified / open
- DrukSmart's real ERPs; Gemini; no participant usability study; no HTTPS/SSO/HA (prototype).
- D6, D7 and D11 from Milestone 8 remain open (documented).

---

## Milestone 8: System integration and evaluation (2026-10-25) · status: complete

Report: [evaluation/EVALUATION_REPORT.md](evaluation/EVALUATION_REPORT.md) · assessment:
[evaluation/INTEGRATION_ASSESSMENT.md](evaluation/INTEGRATION_ASSESSMENT.md) · tools: `evaluation/`.

### Working (verified)
- **End-to-end on the ERP sandboxes.** Controlled business changes (new hire and departure, partial
  payments, a cancelled invoice, approved and then cancelled leave) went through the real Airflow DAG to dbt,
  Superset, the Django API and the AI answers. Every expected delta was exact in 5 runs; a repeat run added
  0 raw versions.
- **Reconciliation 30/30 in every run.** Source ERPs (independent oracle) = dbt facts = Superset = Django =
  AI result = AI answer text, for 11 KPIs and per ERP. The Django KPI service also reproduces the
  hand-calculated fixture KPIs (new warehouse tests).
- **Reliability: 8/8 fault scenarios pass.**
  - Failures handled safely: ERP down temporarily (retried) or permanently (run fails, nothing published); broken dbt model; failing data test (not published).
  - Recovery: runs publish again and reconcile.
  - Warehouse down: consumers report errors without numbers and recover by themselves.
  - Service restarts: sessions and history survive.
  - Stale data: flagged.
- **Access matrix 115/115.** Roles × resources at the Superset, Django and database boundaries, including
  tampering. Each component connects with its intended account.
- **Usability walkthrough 6/6 tasks** completed through the real UIs with correct numbers. The participant
  protocol is ready.
- Performance measured (§8 of the report): DAG ~64 s for 126 source records; Superset query ~200 ms;
  dashboards ~4 s; Django ~50 ms.
- Regression runner `evaluation/run_regression.py` (12 stages, skips stages whose services are down).

### Defects found and fixed
- **D1 (high):** Airflow received every platform secret. Fixed with an explicit allowlist and the masked
  `.env`; verified.
- **D2:** Superset's cache showed the previous publication after a refresh (measured). Fixed by turning the
  cache off; verified.
- **D3:** stale data was not flagged. Fixed: Django flag, warning and readiness check, plus Superset's age column.
- **D4:** the sandboxes had no restart policy. Fixed.
- **D5:** duplicated role configuration. Now guarded by tests.
- **D10:** the API returned an HTML 500 page when the database was down. Fixed with JSON 503 middleware.
- Open: D6 (Django login throttling), D7 (unused broad `bi_reader`), D11 (one PostgreSQL server for the
  warehouse and the app).

### Not verified / incomplete
- DrukSmart's real ERPs; Gemini (no key); **no usability participants yet**; no load or concurrency
  testing; not production-ready.

### Next
- Deployment packaging and handover (Milestone 9 in the roadmap). The team runs the usability sessions.

---

## Milestone 7: Django backend and bounded AI analytics (2026-10-25) · status: complete

Details: [backend/BACKEND.md](backend/BACKEND.md) · evaluation: [backend/EVALUATION.md](backend/EVALUATION.md).

### Working (verified)
- **Django 5.2.18 LTS backend** (`backend/`). Apps: access, kpi, assistant, health. Metadata is in
  `druksmart_app` (migrated). There is session login with CSRF and JSON APIs (`/api/v1/me|kpis|kpis/run|ask`,
  `/health/`, `/health/ready/`).
- **Approved KPI registry**: 8 functions (HR-01..03, AC-01..04) with declared module, parameters,
  filters, dataset, aggregates and output. The service authorises before connecting, validates every
  parameter, and builds SQL from constants with bound parameters, plus the branch scope.
- **Restricted warehouse account** `druksmart_kpi_reader`, granted at publication from
  `backend/approved_datasets.yml` (`publish.py` now handles Superset and the KPI service as
  consumers). The new dbt view `kpi_approved_leave_requests` (backend only) completes HR-03's
  distinct employees.
- **Question workflow**: validate → scope → interpreter proposal → service → template answer (or LLM
  wording with every number verified) → `QuestionLog`. Explicit statuses for answered,
  clarification, unsupported, forbidden, invalid filter, no data and errors.
- **Deterministic rules interpreter**, the default and clearly labelled as having no LLM. **Gemini
  function-calling provider** implemented (REST via httpx, tools generated from the registry, mode ANY,
  number verification, labelled rules fallback).
- **UI**: Django template page with examples per role, loading/error states, a status badge, and a
  context panel (KPI, function, dataset, date, filters, scope, freshness, interpreter) and result table.
- Roles mirror Superset (5 groups + admin), with branch scope for Branch Manager. There are local demo users.

### Test results
- `pytest` → **482 passed** (355 before this milestone). The 127 new tests are all in `tests/backend`:
  registry 24, rules 37, mocked Gemini 16, API/auth/CSRF/pipeline 24, warehouse values vs fact
  tables 17, Superset consistency 9. `ruff check` / `ruff format --check` are clean.
- **KPI service = Superset**: 9 comparisons (headcount, AR, AP, overdue, by department, leave; admin and RLS
  branch manager) are equal.
- **Live HTTP**: all 7 brief questions were answered with values equal to the warehouse. The HR user was
  forbidden from Accounts and the Accounts user from HR. The branch manager got scoped values (7 employees,
  101,500.00 AR), and the Paro / DTG Services filters were forbidden.
- **Evaluation (rules interpreter)**: blind baseline 52/56 intents and 22/25 numbers; after fixes on the same
  set 56/56 and 25/25; **held-out 13/14 and 5/6**. **0 permission violations** in all runs.
- Browser (headless Edge): login, answer with context, clarification and forbidden all render correctly.
- Airflow run `m7_kpi_service_1` published the new view and granted both consumers.

### Defects found and fixed
- A filter for a real branch without rows in a dataset (Paro has no invoices) was reported as
  "unknown branch". Values are now validated against all governed datasets, giving `no_data`.
- The LLM number check captured trailing commas. The pattern was fixed (unit test).
- The init script lost line continuations, and a CRLF save broke it (`pipefail\r`). Both were fixed.
- The generated `DJANGO_SECRET_KEY` was too short (Django W009). `*SECRET_KEY` values are now 64 characters,
  and the local key was rotated in place.
- Evaluation run 1: 4 rule gaps (contractions, supplier and customer phrasings) were fixed. A held-out set
  was used to measure the effect honestly.

### Simulated / not verified
- **Gemini has not been called for real** (no API key). Only mocked-HTTP tests exist, and its accuracy is
  unknown until `evaluate_assistant --provider gemini` is run.
- The data is sandbox/synthetic. The demo users share one password.

### Incomplete / open
- No single sign-on between Superset and Django. Branch scopes are configured by hand.
- Development server only (no WSGI server, HTTPS or collectstatic).
- One KPI per question: no comparisons, trends or percentages.

### Next
- Milestone 8 (proposed): testing, evaluation and hardening across the platform (incl. a Gemini
  evaluation if a key is provided), then deployment packaging.

---

## Milestone 6: Apache Superset BI and reporting (2026-10-24 … 25) · status: complete

Full details and the role matrix: [bi/SUPERSET.md](bi/SUPERSET.md).

### Working (verified)
- Superset **6.1.0** (`docker compose --profile superset`) on 127.0.0.1:8088, with its own metadata
  PostgreSQL. A derived image adds the PostgreSQL driver, which the official image lacks. No pipeline
  or ERP secrets enter the Superset containers.
- Dedicated read-only warehouse account `druksmart_superset_reader`: SELECT on the **4 approved
  datasets** only (`superset/approved_datasets.yml`). It is granted at every Airflow publication, and
  publication fails if an approved dataset is missing. Sessions are read-only with a timeout.
- Governed datasets: labels, date and filter columns, **certified metrics** that only re-aggregate dbt
  KPI columns, AUTO currency from `currency_code`, locked as *managed externally*.
- Default **HR** (11 charts, 5 native filters) and **Accounts** (8 charts, 5 native filters)
  dashboards, each with a data-freshness table. A required "latest snapshot date" filter covers the
  point-in-time KPIs; cross-filtering, drill and CSV export are enabled.
- Roles: HR Viewer, Accounts Viewer, Executive, Dashboard Creator and Branch Manager (RLS), plus Admin.
  Each has an exact permission set, with no SQL Lab or dataset write for any DrukSmart role. Five
  demo users exist for local tests.
- Configuration as code (`superset/definitions/`, idempotent `bootstrap.py`), assets exported to
  `superset/assets/dashboards/` (Superset YAML), and a restore script.
- dbt KPI views gained display labels, `employment_status` (headcount) and org/branch (leave), with
  13 new grain/label tests. KPI definitions are unchanged.

### Test results
- `pytest` → **355 passed**:
  - 35 new `superset` access/KPI API tests;
  - 46 definition-consistency unit tests;
  - 3 new publication tests.

  `ruff check` / `ruff format --check` are clean.
- `browser_check.py` (headless Microsoft Edge, real login page) → **12/12 PASS**: the six users × two
  dashboards render or are denied as designed, and every KPI card equals the value computed from the
  fact tables, including the branch manager's RLS values.
- Interactive organisation filter in the browser: 166,700.00 → 101,500.00, matching the warehouse.
- Persistence across a restart of `superset` + `superset-db`: verified.
- Restore from Git into an **empty** Superset instance → identical object counts, and 35/35 tests
  pass against it.
- Airflow runs `m6_superset_views_1/2` succeeded, and the publish log shows the Superset grants.
- Secret scan of `superset/`: no `.env` value present. The exported DB URI is masked.

### Defects found and fixed
- Date filter default displayed but **not applied** (KPI cards summed 3 dates: 48 vs 16 employees).
  Fixed with `requiredFirst`, and now guarded by the browser check.
- ERPNext invoices had **no organisation** (M4 defect, found by the new label tests). The organisation
  now comes from the invoice's own company.
- Superset's dashboard import does not overwrite charts. Restore now imports datasets, charts and
  dashboards separately.
- The official image has no DB driver. Fixed with the derived image.

### Simulated / not verified
- Data comes from the local sandboxes (synthetic), not DrukSmart's ERPs. Demo users share one password.
- Not automated: cross-filter click, CSV download via the UI, editor drag/resize. The manual guide is
  in SUPERSET.md §10 and awaits the team's results.

### Incomplete / open
- HR-03 distinct employees on leave over a period is not exposed (needs a dedicated KPI view).
- No Redis/Celery: alerts and reports (optional) are not configured.
- ERPNext branches have no Accounts data (DS-AC-05). RLS branch assignment is manual configuration.

### Next
- Milestone 7 (proposed): Django backend with auth and a KPI function registry over the same governed
  datasets (numbers must equal Superset's).

---

## Milestone 5: Apache Airflow orchestration (2026-10-22 … 24) · status: complete

### Working (verified)
- Airflow **3.3.2** (Python 3.12) via `docker compose --profile airflow`: api-server (127.0.0.1:8085),
  scheduler (LocalExecutor), dag-processor, separate `airflow-db` metadata PostgreSQL, FAB admin user,
  pools `odoo_api` / `erpnext_api`. About 1 GB RAM in total (measured).
- Custom image with a separate pipeline venv (dbt 1.12.0, dbt-postgres 1.11.0), built **offline** from
  pre-downloaded Linux wheels (PyPI ran at 30–800 KB/s).
- DAG `druksmart_elt` (12 tasks): validate → migrate → extract/load (Odoo ∥ ERPNext, one per ERP at a
  time) → dbt staging/intermediate → marts in hidden `marts_build` → tests → **atomic publish** → report.
  No business logic in the DAG (`orchestration/bin/run_step.sh` calls the existing CLIs).
- Daily schedule (02:00 Asia/Thimphu, configurable), manual triggers with `source_mode`, `as_of`
  (synthetic only) and `full_refresh` params, retries with exponential backoff, timeouts.
- `marts.data_freshness` + `raw.publication` audit log; synthetic source mode (`synthetic-erp` service,
  `_test` database) through the identical code path.

### Test results
- `airflow dags list-import-errors` → none; 12 tasks listed.
- 13 real DAG runs (see docs/orchestration/ORCHESTRATION.md §8): 11 success, 2 deliberately failed
  (dbt failure, data-quality failure), and 1 real overnight failure that was recovered by clearing it.
  Recovery shown for ERP unavailable, warehouse DB down, broken dbt model, failing data test, and
  invalid source data (quarantined). Failed runs never published.
- Synthetic replay published marts that equal the hand-calculated KPIs; a full-refresh re-run added
  0 raw versions and left headcount/AR/AP unchanged.
- `pytest` → **271 passed** (new: orchestration static checks, synthetic HTTP service, publication
  swap/rollback/permissions). `ruff` clean.

### Defects found and fixed
- pip downloads stalled repeatedly: replaced by a `pip --dry-run --report` + resumable `curl` workflow.
- Default privileges are bound to the schema object: re-created by `publish.py` after each swap.
- Real incident: sandboxes do not auto-restart after a Docker Desktop restart. Documented the recovery
  (`sandbox.py up` + clear run). The pipeline itself behaved correctly.

### Simulated / not verified
- Live runs used the **local sandboxes** or the **synthetic** service, not DrukSmart's ERPs.

### Next
- Milestone 6 (proposed): Superset on the published marts (bi_reader), roles and row-level security, HR and Accounts dashboards.

---

## Milestone 4: Dimensional data warehouse and dbt (2026-10-22) · status: complete

> The milestone brief received was truncated in Task 5. Tasks 1–5 were implemented as written. The
> rest was inferred (with user approval): reconciliation to `expected_kpis.json`, KPI datasets for
> Superset/AI, tests, documentation.

### Working (verified)
- dbt Core 1.12.0 + dbt-postgres 1.11.0 project (`warehouse/`), env-var profile (`dev`, `test`),
  `run_dbt.py` loading `.env`, schema-exact naming, no external dbt packages.
- 18 staging views (every record version, typed, ERP empty values normalised, canonical keys,
  provenance), 8 intermediate tables (cross-ERP canonical models from **generated** mapping seeds),
  7 Type 1 dimensions, 5 facts (2 periodic snapshots, 3 transaction facts), 3 KPI views.
- Snapshot facts only for dates with real extractions (`int_snapshot_dates`): no fabricated history.
- Isolated `druksmart_analytics_test` database (init script) for end-to-end tests.
- Live sandbox data also builds cleanly in the dev database. KPIs are visible to `bi_reader` (marts only).

### Test results
- `dbt build` (dev, sandbox data): **PASS=192, ERROR=0** (8 seeds, 41 models, 143 data tests incl.
  ERPNext and Odoo payment reconciliation and the snapshot-vs-current consistency check).
- `pytest -m warehouse`: **16/16**. Synthetic fixtures → fake APIs → real ingestion → raw → dbt →
  marts reproduce every hand-calculated KPI (headcount, departments, policy alternative, leave,
  AR/AP/overdue/ageing at 2026-09-30 and 2026-10-31, branch, verified counterparty, advances).
- Mutation checks: including drafts/cancelled → dbt consistency test fails; ageing boundary 30→29 →
  exactly the two 30-day boundary cases fail.
- Full `pytest`: **256 passed**. `ruff`: clean.

### Defects found and fixed during the milestone
- `dbt-core-experimental-parser` 2.0.8 is source-only on Windows/Python 3.14. Pinned 2.0.0a4 (wheel).
  The slow network needed a resumable curl download.
- YAML parsed `1_30` as the number 130 in a test; values are quoted now.
- A macro alias error in `int_leave_requests`; seed column types now scoped per seed.

### Incomplete / open
- Business decisions DS-… still unconfirmed (defaults implemented and documented).
- ERPNext invoices have no branch (DS-AC-05); Odoo history starts at first snapshot.
- A→B→A reversion edge case (documented in docs/warehouse/WAREHOUSE.md §8).

### Next
- Milestone 5 (proposed): Airflow orchestration (extract → load → dbt build → publish) on a daily schedule.

---

## Milestone 3: ERP integration framework (2026-10-22) · status: complete

### Working (verified)
- `connectors/`: `SourceConnector` interface, `OdooConnector` (JSON-2), `ERPNextConnector` (Frappe REST),
  `ApiClient` with timeouts, retry/backoff and Retry-After handling, typed errors, read-only guards.
- `ingestion/`: raw migration (`raw.extraction_run`, `raw.source_record` versions, `raw.quarantined_record`,
  `raw.extraction_checkpoint`, view `raw.current_source_record`), `RawStore` (advisory lock, per-page
  commits), runner (windows, overlap, validation, quarantine, duplicates), CLI `python -m ingestion`.
- Local sandboxes: Odoo 19.0-20261015 + ERPNext 16.52.0 + HRMS 16.52.0 with synthetic data and
  read-only API users (`infrastructure/sandboxes/`). API keys are written to `.env` without being displayed.
- **Live extraction of all 7 Odoo and 10 ERPNext entities into raw** (62 + 53 records), idempotent re-run,
  and live incremental change detection (1 edited record → 1 new version per ERP).

### Test results
- `pytest` → **238 passed**: 15 Odoo + 12 ERPNext connector tests against controlled fake APIs,
  10 retry/backoff, 8 connector config, 10 PostgreSQL ingestion integration, **14 live**, plus the
  169 tests from Milestones 1–2 (still passing after the contract/fixture updates).
- Live (`pytest -m live`): 14/14 on both sandboxes, covering auth, version, field access, contract
  compliance of every real record, pagination, empty window, refused writes, end-to-end into raw.
- `ruff check` / `ruff format --check` → clean.

### Contract corrections found by live testing (ERPNext contract 1.0.0 → 1.1.0)
- Department `company` is missing on the root department → `expected` instead of `required`.
- Returns: `update_outstanding_for_self` (default 1 in v16) decides whether a return reduces the
  original invoice. Fixture returns now state `0` explicitly; KPI totals are unchanged.

### Defects found and fixed during the milestone
- Sandbox joined the platform's Compose project because `.env` sets `COMPOSE_PROJECT_NAME`.
  The wrong containers were removed (the warehouse was untouched), and `sandbox.py` now always passes `-p`.
- Fake servers derived schemas from data (false failures on empty tables). They now use the contract schema.
- Several sandbox seed issues (chart already loaded, country constraint, HRMS 16 Holiday List
  Assignment, leave limits, partial-run idempotency), all fixed in the seed scripts.

### Simulated / not verified
- **DrukSmart's real ERP instances were not accessed.** Live tests ran against local sandboxes.
- Retry, interruption and lock behaviour were verified with controlled failures, not induced live.
- Deletions are not detected (no API support), as documented.

### Incomplete / open
- DS-SEC-01: Odoo has no read-only HR group; the HR-officer bot can technically edit employees.
- Odoo exact payment allocations (`account.partial.reconcile`) deferred.
- HRMS must be re-installed if the ERPNext sandbox containers are recreated.

### Next
- Milestone 4 (proposed): dbt foundation, staging models over `raw.current_source_record`, conformed dimensions.

---

## Milestone 2: ERP data analysis & contracts (2026-10-22) · status: complete

### Working (verified by tests)
- ERP source analysis for Odoo 19.0 and ERPNext/HRMS 16 from official docs and source code
  (`docs/data/ERP_SOURCE_ANALYSIS.md`). Every claim is labelled source / docs / **assumption**.
- Version-controlled contracts: `contracts/raw_record.yaml`, `contracts/sources/{odoo,erpnext}.yaml`
  (7 + 10 entities), `contracts/canonical/{hr,accounts}.yaml`, `contracts/mappings/entity_mappings.yaml`.
- `druksmart_common.contracts`: contract loader, ERP-aware validator (error/warning), raw-record
  envelope builder (UTC times, SHA-256 payload hash, record keys), duplicate detection.
- KPI catalogue (HR-01..03, AC-01..04) with 14 flagged DrukSmart decisions (`docs/data/KPI_CATALOGUE.md`).
- Source-to-target mapping and identity-matching rules (`docs/data/SOURCE_TO_TARGET_MAPPING.md`).
- 22 synthetic fixture files (2 extraction batches, 2 ERPs), generated by a reviewed script.
  Seven deliberately invalid records, nine warning cases.
- Hand-calculated `expected_kpis.json`, independently re-derived by `tests/support/kpi_reference.py`.

### Test results
- `pytest` → **169 passed** (154 new in this milestone: contract unit tests, fixture tests,
  KPI expected-result tests, 3 mutation tests proving the checks can fail; plus the 15 from Milestone 1).
- Reference calculator and hand calculation agreed on the first comparison for all KPIs at both
  snapshot dates; payment reconciliation and source-status cross-checks found 0 differences.
- `ruff check` / `ruff format --check` → clean.

### Simulated / not verified
- **No live ERP was queried.** Fixtures imitate documented API shapes. Seven items are marked
  `assumption` and listed for verification in Milestone 3 (`ERP_SOURCE_ANALYSIS.md` §7).
- `kpi_reference.py` is a test oracle, not production code. Marts will be built in dbt.

### Incomplete / open
- 14 business decisions (DS-…) need DrukSmart confirmation; defaults are documented.
- Odoo exact allocation amounts (`account.partial.reconcile`) contracted but deferred.

### Next
- Milestone 3: ERP sandboxes & contract verification (awaiting approval).

---

## Milestone 1: Engineering foundation (2026-10-21) · status: complete

### Working (verified)
- Git repository (`main`), `.gitignore` / `.gitattributes` / `.editorconfig`. `.env` confirmed ignored
  (`git check-ignore`). **No commit made yet** (awaiting the team's go-ahead).
- PostgreSQL 17.11 via `compose.yaml`: healthy, named volume `druksmart_pgdata`, bound to `127.0.0.1:5433`.
- Databases `druksmart_analytics` (schemas `raw`, `staging`, `intermediate`, `marts`) and `druksmart_app`.
- Roles `pipeline`, `bi_reader` (marts read-only), `app` (app DB only); `PUBLIC` connect revoked.
- Init script is idempotent (re-run exit 0) and works on a fresh volume (throwaway project test, 5/5).
- Data persists across container restart.
- `druksmart_common`: settings validation, DB connect helper, health-check CLI.
- `create_local_env.py` generates `.env` with random passwords (never printed).

### Test results
- `python -m druksmart_common.healthchecks` → **5/5 checks passed**.
- `pytest` → **15 passed** in 0.64 s (10 unit, 5 smoke).
- Manual negative tests: bi_reader `SELECT raw.*` → denied (42501); bi_reader `INSERT` into marts →
  denied (42501); bi_reader reads a new pipeline-created marts table → OK (default privileges);
  app role → analytics DB refused (no CONNECT); wrong password → refused.
- `ruff check .` and `ruff format --check .` → clean.

### Defects found and fixed during the milestone
- Docker Desktop engine was stuck ("unable to start"). Fixed by restarting Docker Desktop and WSL.
- `localhost` connections took ~5 s each (IPv6 fallback). The default host is now `127.0.0.1`, and the test suite went from 25.5 s to 0.64 s.
- `create_local_env.py` wrote CRLF line endings on Windows. It now writes LF.

### Incomplete / not in scope
- No ERP, connector, dbt, Airflow, Superset or Django code (later milestones, by design).
- Airflow/Superset metadata databases are not created yet (added with those services).
- `docs/reference/Group8_DrukSmart.pdf` is not in the repo yet (manual step).

### Next
- Milestone 2: ERP sandboxes & source profiling (awaiting approval).
