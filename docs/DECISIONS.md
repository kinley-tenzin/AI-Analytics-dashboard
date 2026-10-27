# Architecture Decision Records

Short records of significant decisions: context, decision, consequences. Add new ADRs at the end.
Never rewrite an accepted ADR. Supersede it with a new one.

The binding project-scope decisions (Odoo + ERPNext only, HR + Accounts only, Superset for BI,
Django for AI, one client per deployment, …) are listed in `CLAUDE.md` §2 and are not repeated here.

---

## ADR-001: Single repository with area-owned top-level directories
**Date:** 2026-10-21 · **Status:** accepted

**Context:** Four members work in parallel on integration, data engineering, BI and backend/AI.
**Decision:** One Git repository (`main` branch), with top-level directories per area (`connectors/`,
`ingestion/`, `warehouse/`, `orchestration/`, `superset/`, `backend/`) plus `infrastructure/`, `tests/`,
`docs/`. Shared Python code lives in one small package, `druksmart_common/`. `compose.yaml` stays at the
repository root so `docker compose` works without `-f` flags.
**Consequences:** Clear ownership, few merge conflicts, one place for docs and tests. Shared code must
stay small and stable, because changing it affects every area.

## ADR-002: PostgreSQL 17.11 in Docker Compose on host port 5433
**Date:** 2026-10-21 · **Status:** accepted

**Context:** The reference machine already runs a native PostgreSQL 18 service on port 5432. Team
members' machines differ.
**Decision:** Run `postgres:17.11-bookworm` (exact tag) via Docker Compose with a named volume
(`druksmart_pgdata`), published on `127.0.0.1:${DRUKSMART_PG_PORT:-5433}`. PostgreSQL 17 was chosen over
18 because it has had a longer stabilisation period and support from dbt, Superset and Airflow
tooling. Moving to 18 later is a documented dump/restore.
**Consequences:** Identical database version for all members, no clash with native installs, and the
database is unreachable from the network. Requires Docker Desktop to be running.

## ADR-003: Separate analytics and application databases
**Date:** 2026-10-21 · **Status:** accepted

**Decision:** `druksmart_analytics` holds ERP-derived data in layered schemas `raw → staging →
intermediate → marts`. `druksmart_app` holds Django application metadata. Airflow and Superset
metadata databases will be created in their own milestones rather than as empty placeholders now.
**Consequences:** Application data and analytical data have different owners, backups and access
rules. Cross-database joins are impossible by design.

## ADR-004: Least-privilege database roles, enforced in PostgreSQL
**Date:** 2026-10-21 · **Status:** accepted

**Context:** The proposal requires that BI and AI never touch raw ERP data, and that permissions are
enforced in the systems that actually query data.
**Decision:** Three login roles: `pipeline` (owns analytical schemas), `bi_reader` (USAGE/SELECT on
`marts` only, with default privileges for future dbt tables), `app` (owns `druksmart_app` only).
`PUBLIC` has no CONNECT on either database. The bootstrap superuser is never used by code.
**Consequences:** Even a mis-configured Superset dataset or AI KPI function cannot read `raw`.
Verified by `tests/smoke` and by negative tests (SQLSTATE 42501 on raw access).

## ADR-005: Host Python 3.12+ (verified 3.14); Airflow and Superset in containers; dbt pin
**Date:** 2026-10-21 · **Status:** accepted

**Context:** The reference machine has only Python 3.14.3. A wheel-only dry-run install showed that
**dbt-core 1.12.6 fails to resolve** because it requires a *pre-release* `dbt-core-experimental-parser`.
The cause is pip ignoring pre-releases, not the Python version: it also fails on 3.12/3.13. Letting pip
choose for `dbt-postgres==1.11.0` resolves **dbt-core 1.12.0** with prebuilt wheels on 3.12 and 3.14.
**Decision:** Require Python ≥ 3.12 on the host. Pin dbt-core 1.12.0 / dbt-postgres 1.11.0 when the
dbt project is created (re-verified then). Run Airflow and Superset from their official Docker images,
because Airflow does not support native Windows and the images bundle tested dependency sets.
**Consequences:** No extra Python install needed today. If a later dependency lacks 3.14 wheels, add
Python 3.12 alongside and record a new ADR.

## ADR-006: Configuration from environment variables, validated at startup
**Date:** 2026-10-21 · **Status:** accepted

**Decision:** All settings and credentials come from environment variables. Locally they come from a
git-ignored `.env` created from `.env.example` by `infrastructure/scripts/create_local_env.py`, which
generates random passwords and never prints them. `druksmart_common.config.load_settings()` fails
fast, naming (never showing) missing or placeholder settings. Compose uses `${VAR:?}` so it refuses to
start with missing secrets. Default host is `127.0.0.1`, because `localhost` costs ~5 s per connection
on Windows (IPv6 fallback, measured).
**Consequences:** No secrets in source control. Every member generates their own credentials.

## ADR-007: pyproject.toml + venv + pip with exact pins
**Date:** 2026-10-21 · **Status:** accepted

**Decision:** One `pyproject.toml` with exactly pinned runtime dependencies and a `dev` extra
(pytest, ruff), installed editable into `.venv` with plain pip. Area-specific dependencies (dbt,
Django, connector HTTP clients) are added when those areas start. Poetry/uv were not adopted, to
keep the toolchain small for the team.
**Consequences:** Simple and reproducible. Transitive dependencies are not locked yet. Add a
constraints/lock file if drift causes problems.

## ADR-008: Target Odoo 19.0 (JSON-2) and ERPNext/HRMS 16 (Frappe REST v1)
**Date:** 2026-10-22 · **Status:** accepted (to be re-checked against DrukSmart's real versions)

**Context:** Field locations differ by version. Odoo 19 moved department, job, employee type and
departure date onto `hr.version`, and introduced JSON-2 while deprecating XML-RPC/JSON-RPC.
ERPNext v16 is the newest major line.
**Decision:** Contracts target Odoo 19.0 and ERPNext/HRMS 16. Connectors must read the server
version and refuse unsupported versions instead of reading wrong fields.
**Consequences:** Supporting older DrukSmart instances means a new contract version, not ad-hoc fixes.

## ADR-009: Data contracts as YAML plus a small in-house validator
**Date:** 2026-10-22 · **Status:** accepted

**Context:** Two ERPs have different empty-value conventions (Odoo `false`, ERPNext `null`/`""`),
reference shapes (`[id, name]` vs name string) and datetime zones. Generic JSON Schema cannot
express "false means empty except for boolean fields" cleanly.
**Decision:** Contracts live in `contracts/` as YAML (readable by all four members and reviewers).
`druksmart_common.contracts` validates payloads with ERP-specific empty rules, two severities
(error → quarantine, warning → load and flag) and a few cross-field checks. Unknown extra fields
are ignored so ERP upgrades that add fields do not break extraction.
**Consequences:** One small module to maintain (~300 lines, fully unit-tested). dbt tests will
mirror the same rules in the warehouse.

## ADR-010: Balances from snapshots of ERP-maintained residuals, not rebuilt from payments
**Date:** 2026-10-22 · **Status:** proposed default, pending DS-AC-01

**Context:** Rebuilding AR/AP as of a past date needs journal-item-level allocations
(Odoo `account.partial.reconcile` + `account.move.line`), which is complex and error-prone.
**Decision:** Outstanding amounts use each ERP's own residual (`amount_residual_signed`,
`outstanding_amount`) at extraction time. Month-end snapshots form the history (Kimball periodic
snapshot). Payment allocations are extracted for **reconciliation checks**, not as the KPI basis.
**Consequences:** Accurate, explainable figures from the first snapshot onwards; no history before
the platform starts extracting (documented limitation).

## ADR-011: Canonical keys include source system and instance; cross-ERP identity only via verified mappings
**Date:** 2026-10-22 · **Status:** accepted

**Decision:** Canonical keys are `source_system:source_instance:source_id`. Records are merged
across ERPs only through `contracts/mappings/entity_mappings.yaml` entries carrying evidence,
verifier and date. Names, codes and tax ids are only candidates for review.
**Consequences:** No accidental merging (tested with same-name employees and customers). Unified
customer reporting needs manual verification work by DrukSmart.

## ADR-012: Expected KPI results are hand-calculated and independently re-derived
**Date:** 2026-10-22 · **Status:** accepted

**Decision:** `expected_kpis.json` is written by hand from the fixture design (with working). A
test-only reference calculator re-derives every figure from the fixtures and canonical YAML; tests
require agreement. Mutation tests prove the checks can fail. Future dbt marts are tested against the
same expected file.
**Consequences:** Two independent derivations make silent errors in either unlikely. Any fixture change
requires updating the hand calculation.

## ADR-013: Connectors are database-agnostic; ingestion owns storage and checkpoints
**Date:** 2026-10-22 · **Status:** accepted

**Decision:** `connectors/` implements a common `SourceConnector` interface (connection check,
entity validation, paged fetch over an `ExtractionWindow`) and never imports database code.
`ingestion/` computes windows, validates records against the contracts, stores them and keeps
checkpoints through a `CheckpointStore`-compatible `RawStore`.
**Consequences:** Adapters can be tested with fake HTTP servers only, and a different storage target
(e.g. files) would not change the adapters. Airflow (later) will call the ingestion runner, not the adapters.

## ADR-014: Raw history = append-only versions keyed by payload hash
**Date:** 2026-10-22 · **Status:** accepted

**Context:** Re-running an extraction must not double-count, yet changes must stay auditable.
**Decision:** `raw.source_record` is unique on (system, instance, entity, source id, SHA-256 of the
payload). Identical re-extractions only update `last_*` columns and `times_seen`; changes add a version.
The current state is the version with the latest `last_extracted_at` (view `raw.current_source_record`).
Each page is committed separately; the checkpoint advances only after a fully successful run.
**Consequences:** Safe re-runs and crash recovery without cursor bookkeeping. Storage grows only with real
changes. Deletions are not detected (no API support).

## ADR-015: Keyset pagination with a bounded window and 10-minute overlap
**Date:** 2026-10-22 · **Status:** accepted

**Decision:** Pages are requested with `primary key > last key` (not offsets). The window upper bound is
the run start time; incremental runs start 10 minutes before the previous checkpoint.
**Consequences:** Records modified during a run cannot shift other records between pages. Late commits
and moderate clock skew are tolerated. Overlapping records are re-fetched and counted as `unchanged`.

## ADR-016: Read-only enforcement in two layers
**Date:** 2026-10-22 · **Status:** accepted (Odoo HR part pending DS-SEC-01)

**Decision:** (1) Code: the Odoo adapter can only call `search_read`, `search_count`, `fields_get` and
`context_get`; the ERPNext adapter only sends GET. (2) ERP: dedicated users with read permissions.
**Consequences:** ERPNext can be fully read-only at the ERP level. Odoo cannot, for the HR-officer fields
(no read-only HR group exists), so for those the code layer is the effective control.

## ADR-017: Local Odoo/ERPNext sandboxes as separate Compose projects
**Date:** 2026-10-22 · **Status:** accepted

**Decision:** `infrastructure/sandboxes/{odoo,erpnext}/compose.yaml` run Odoo 19 (`odoo:19.0` +
PostgreSQL 17.11) and ERPNext 16 (`frappe/erpnext:v16.52.0`, MariaDB 11.8, Redis 6.2), bound to
localhost, with their own databases and volumes. Seed scripts create synthetic data and the
read-only bot users; API keys go straight into `.env` without being displayed.
**Consequences:** Live tests are reproducible without DrukSmart's systems. Sandboxes need ~3 GB of RAM
and several GB of disk, so they are started only when needed.

## ADR-018: dbt project layout, schemas and materialisations
**Date:** 2026-10-22 · **Status:** accepted

**Decision:** One dbt project in `warehouse/` (profile `druksmart`, targets `dev` and `test`).
Models build into the existing schemas exactly (`generate_schema_name` override): staging = views,
intermediate = tables, marts = tables, `kpi_*` = views. Credentials only via `env_var()`; `run_dbt.py`
loads `.env`. No dbt packages (offline-friendly; one small `unique_combination` test macro instead).
**Consequences:** Schemas keep the M1 permissions (BI reads `marts` only). The committed `profiles.yml`
contains no secrets.

## ADR-019: Staging keeps every record version; snapshots only for extracted dates
**Date:** 2026-10-22 · **Status:** accepted

**Decision:** Staging exposes each raw version with `valid_from`/`valid_to`. Periodic snapshot facts
(headcount, AR/AP) are built only for local dates on which the domain's key entities were extracted
successfully (`int_snapshot_dates`); a record's state at date D is its version first extracted before
the end of D.
**Consequences:** No fabricated history. Trend granularity equals extraction frequency (Airflow will
make this daily). A→B→A reversions have a documented edge case.

## ADR-020: Mapping tables generated from contracts (single source of truth)
**Date:** 2026-10-22 · **Status:** accepted

**Decision:** Status, type, state, sign, payment and identity mappings are rendered from
`contracts/canonical/*.yaml` and `contracts/mappings/entity_mappings.yaml` into dbt seeds by
`warehouse/scripts/generate_seeds.py`; a unit test fails on drift. The Python reference calculator
(M2) and dbt therefore apply the same rules.

## ADR-021: Separate transaction facts from snapshot balances; Type 1 dimensions
**Date:** 2026-10-22 · **Status:** accepted

**Decision:** Transaction facts (`fct_accounting_document`, `fct_payment`, `fct_leave_request`) are
separate from periodic snapshots (`fct_receivable_payable_snapshot`, `fct_headcount_snapshot`).
Dimensions are Type 1; point-in-time attributes needed for KPIs live on the snapshot facts, so SCD2
is not justified by any current requirement.

## ADR-022: Isolated `_test` database for end-to-end warehouse tests
**Date:** 2026-10-22 · **Status:** accepted

**Decision:** The PostgreSQL init script also creates `<analytics db>_test` with the same schemas and
grants. The warehouse test truncates ITS raw tables, replays the synthetic extraction batches through
the real connectors (fake APIs) and runner, runs `dbt build --target test`, and compares the marts
with the hand-calculated `expected_kpis.json`.
**Consequences:** Development data (sandbox extractions) and test data never mix. The test refuses to
run against a database whose name does not end in `_test`.

## ADR-023: Airflow 3.3.2, LocalExecutor, separate metadata database
**Date:** 2026-10-22 · **Status:** accepted

**Context:** The official Compose file uses CeleryExecutor + Redis (4 GB+ recommended); the team
develops on 16 GB laptops already running PostgreSQL and ERP sandboxes.
**Decision:** Airflow 3.3.2 (Python 3.12 image) with LocalExecutor: api-server, scheduler and
dag-processor only (no triggerer: no deferrable tasks). Airflow metadata lives in its own
`airflow-db` PostgreSQL 17.11 container. All services sit behind the Compose profile `airflow`.
**Consequences:** About 1.5 GB of RAM. Tasks run as scheduler sub-processes (parallelism 4). A warehouse
outage does not stop Airflow from recording and retrying failures.

## ADR-024: DAG delegates to project CLIs via one step script; separate pipeline venv
**Date:** 2026-10-22 · **Status:** accepted

**Decision:** Every task runs `orchestration/bin/run_step.sh <step>`, which calls
`python -m ingestion`, `warehouse/run_dbt.py` or `warehouse/publish.py` from a dedicated venv in the
image (`/opt/druksmart-venv`). The repository is mounted read-only. The image installs packages
offline from pre-downloaded wheels.
**Consequences:** No business logic in the DAG; the same commands run on a laptop and in Airflow;
dbt/Airflow dependency conflicts are impossible. Image rebuilds are needed only when pins change.

## ADR-025: Build-test-swap publication of marts
**Date:** 2026-10-22 · **Status:** accepted

**Context:** Superset and AI read `marts` directly. Rebuilding tables in place and testing afterwards
would expose unvalidated KPIs whenever tests fail.
**Decision:** The DAG builds marts into the hidden schema `marts_build` (dbt var `marts_schema`),
runs all tests there, and only then `warehouse/publish.py` swaps it into `marts` in one transaction
(grants, renames, default privileges, freshness stamp, `raw.publication` audit row).
**Consequences:** Consumers only ever see a fully tested set of marts, or the previous one. Manual dev
builds (`run_dbt.py build`) still write to `marts` directly.

## ADR-026: Explicit synthetic source mode through the real code path
**Date:** 2026-10-22 · **Status:** accepted

**Decision:** `DRUKSMART_SOURCE_MODE=synthetic` (or the run parameter `source_mode`) points the real
connectors at the `synthetic-erp` service, which serves the fictional fixtures over the documented
Odoo/Frappe APIs, and writes to `<analytics db>_test`. Only this mode may use `--as-of` to replay the
fixture timeline. The fake API implementation is shared with the unit tests (`connectors/synthetic/`).
**Consequences:** The complete DAG can be demonstrated and tested without ERP sandboxes, and synthetic
data never mixes with configured-source data.

## ADR-027: Superset 6.1.0 in Docker with its own metadata database and a derived image
**Date:** 2026-10-24 · **Status:** accepted

**Context:** Superset 6.1.0 is the latest stable release (7.0 is a release candidate). The official
image ships no database drivers (verified: `import psycopg2` fails).
**Decision:** The image is `druksmart/superset:6.1.0` = official image + `psycopg2-binary==2.9.9` (the
version Superset itself pins). It runs in compose profile `superset` with its own PostgreSQL 17.11
metadata container, on 127.0.0.1 only. The containers receive only their own variables (no `env_file`).
There is no Redis/Celery: caching is in-process, and alerts/reports are not configured.
**Consequences:** Reproducible startup with two commands, and pipeline/ERP secrets never enter
Superset. Async queries and scheduled reports need Redis and a worker later.

## ADR-028: Dedicated Superset database account limited to an approved-dataset list
**Date:** 2026-10-24 · **Status:** accepted

**Context:** `bi_reader` can read all of `marts`, including employee and customer names (`dim_*`) and
transaction facts. Superset's Admin and SQL Lab would expose them.
**Decision:** Superset connects as `druksmart_superset_reader`. `warehouse/publish.py` grants it
`SELECT` on exactly the relations in `superset/approved_datasets.yml` (4 KPI/freshness relations),
inside the publication transaction, and fails the publication if one is missing. Sessions are forced
read-only with a statement timeout.
**Consequences:** No Superset user, Admin included, can reach unapproved data. Approving a new
dataset is an explicit, reviewed change.

## ADR-029: Configuration-as-code bootstrap through Superset's REST API
**Date:** 2026-10-24 · **Status:** accepted

**Decision:** The database connection, governed datasets (certified metrics, labels, currency via
`currency_code_column`, flagged *managed externally*), roles, RLS, demo users and the default
dashboard templates are defined in `superset/definitions/` and applied by the idempotent
`bootstrap.py` through the public REST API (no direct writes to Superset's metadata DB). Assets are
also exported in Superset's native YAML format to `superset/assets/`.
**Consequences:** A fresh Superset is rebuilt from Git and verified (restore test into an empty
instance). UI edits to admin-owned templates are overwritten on the next bootstrap; creators save
their own copies.

## ADR-030: One DrukSmart role per user, derived from Gamma, with exact permission sets
**Date:** 2026-10-24 · **Status:** accepted

**Decision:** Roles are HR Viewer, Accounts Viewer, Executive, Dashboard Creator and Branch Manager,
plus the built-in Admin. Each is a *viewer* or *creator* base derived from Gamma, minus write and
RLS-read permissions, plus `datasource_access` on its domain's datasets. Branch Manager adds RLS
(`branch_key IN (...)`). `DASHBOARD_RBAC` limits dashboards to roles. No role has SQL Lab, database
access or dataset write. `bootstrap.py` sets permissions to exactly the defined list and verifies them.
**Consequences:** The access matrix is reviewable in one file and enforced by Superset for
dashboards, Explore, drill-down and CSV export alike (tested per role).

## ADR-031: Point-in-time KPIs shown for one snapshot date selected by a required filter
**Date:** 2026-10-24 · **Status:** accepted

**Context:** Headcount and open balances are snapshot measures; summing across dates is wrong.
**Decision:** Dashboards have a required single-value date filter that defaults to the latest date
in the data (`defaultToFirstItem` + `requiredFirst`); trend charts are excluded from it. Point-in-time
metrics carry a warning text. KPI views gained display labels (names, sortable ageing label,
currency), employment status (HR) and organisation/branch (leave), without changing any KPI
definition.
**Consequences:** No hard-coded dates. The browser check found and now guards the case where the
default was displayed but not applied. Ad-hoc exploration without a date filter remains a
documented risk.

## ADR-032: Lightweight Django 5.2 LTS backend without a REST framework
**Date:** 2026-10-25 · **Status:** accepted

**Decision:** The backend uses Django 5.2.18 (LTS, supported until April 2028, Python 3.14), plain
JSON views, session authentication with CSRF, and Django templates plus a small vanilla-JS file for
the UI. Its metadata (users, groups, branch scopes, question log) lives in `druksmart_app` as the
`app` role. Tests use in-memory SQLite for Django's own tables, because the `app` role may not create
databases; warehouse access in tests stays real.
**Consequences:** There are few dependencies (Django, asgiref, pytest-django) and no frontend build.
A deployment still needs a WSGI server, HTTPS settings and static-file serving (deployment milestone).

## ADR-033: Approved KPI function registry as the only executable surface
**Date:** 2026-10-25 · **Status:** accepted

**Decision:** `kpi/registry.py` declares every operation: module, KPI ids, dataset, date parameter,
optional group-by, allowed filters, fixed conditions and aggregate expressions (equal to the certified
Superset metrics). `kpi/service.py` authorises the domain before connecting, validates every
parameter (filter values against the organisation structure, out-of-scope values → forbidden, dates
must be extracted snapshots), and composes SQL from registry constants with bound parameters, always
ANDing the user's branch scope. The API and the AI use the same service.
**Consequences:** There is no path from user or model text to SQL. Adding a KPI is a reviewed code change
plus tests. Numbers equal Superset's (tested).

## ADR-034: Dedicated KPI reader account and a request-grain leave view
**Date:** 2026-10-25 · **Status:** accepted

**Context:** HR-03 includes distinct employees on leave over a period, which cannot be re-aggregated
from the monthly view. `bi_reader` can read all marts, including employee names.
**Decision:** There is a new account `druksmart_kpi_reader`, with SELECT granted at publication on
`backend/approved_datasets.yml` only (`publish.py` generalised to consumers: Superset and the KPI
service), and a read-only, time-limited session. There is also a new dbt view `kpi_approved_leave_requests`
(approved requests with opaque `employee_key`, org labels, dates, days), approved for the backend
only. It is aggregated inside PostgreSQL and never returned or sent to an LLM.
**Consequences:** HR-03 is complete in the backend, and the employee-level grain stays out of Superset and
out of any response.

## ADR-035: LLM as a constrained proposer; deterministic rules as labelled default and fallback
**Date:** 2026-10-25 · **Status:** accepted

**Decision:** Interpreters only *propose* a registry function (or clarify / decline). Gemini is called
through its REST API (httpx; no SDK) with function declarations generated from the registry and
`functionCallingConfig.mode = ANY`. It receives organisational labels and aggregated results only, never
SQL, table names, keys, roles or credentials. Its wording is used only if every number in it occurs in
the result. The deterministic rules interpreter is the default when no key is configured, and the
fallback on any Gemini error. It is always labelled `rules` / `rules (fallback)` with `llm_used: false`.
**Consequences:** Permissions and numbers never depend on the model. Accuracy for unseen phrasings depends
on the interpreter (measured in docs/backend/EVALUATION.md). Gemini needs a key to be verified.

## ADR-036: Same role names in Superset and Django, separate accounts (no SSO yet)
**Date:** 2026-10-25 · **Status:** accepted

**Decision:** Django groups use the Superset role names and domains (HR Viewer, Accounts Viewer,
Executive, Dashboard Creator, Branch Manager), and branch scopes mirror Superset's RLS rule. Each
system enforces access on the queries it runs. Single sign-on is out of scope for the prototype.
**Consequences:** Administrators create a person in both systems with the same role, and branch
assignments are kept in sync by hand. This is documented as a limitation.

## ADR-037: Platform evaluation with independent oracles and controlled sandbox changes
**Date:** 2026-10-25 · **Status:** accepted

**Decision:** Platform-level evaluation lives in `evaluation/`. Expected values never come from the
code under test:
- hand-calculated fixtures (warehouse and KPI service);
- a source oracle reading the ERPs' own balances and statuses over their APIs (no connectors, no dbt);
- business changes made in the sandboxes whose effect is known by construction.

Every layer is reconciled per KPI and per ERP, including the number written in the AI answer.
**Consequences:** Discrepancies between layers are detected automatically (none found). The tools
change only sandbox data and refuse non-sandbox ERPs.

## ADR-038: Least-privilege pipeline environment; no Superset data cache; explicit staleness
**Date:** 2026-10-25 · **Status:** accepted

**Decision:**
- **D1:** Airflow containers receive an explicit allowlist of variables instead of `env_file: .env`, and the repository's `.env` is masked inside them.
- **D2:** Superset's chart-data cache is off (NullCache). At this volume, correctness beats a ~200 ms query.
- **D3:** KPI results carry `hours_since_publication` and `stale` (threshold `DRUKSMART_STALE_AFTER_HOURS`, default 30 h). Stale answers say so in their text, Django readiness returns 503, and Superset freshness tables show the age.
- **D10:** API errors stay JSON even when the database is down.

**Consequences:**
- A compromised pipeline task can no longer read BI, AI or admin secrets.
- Dashboards show a new publication immediately.
- Old data cannot be mistaken for current data.
- Re-enabling Superset caching later requires invalidation at publication.

## ADR-039: Single-machine Compose deployment driven by one operations script
**Date:** 2026-10-25 · **Status:** accepted

**Context:** The prototype must be deployable reproducibly on a student laptop (Windows, 15 GB RAM,
Docker VM 7.4 GB) for demonstration and handover, without Kubernetes-level complexity.
**Decision:**
- **Compose profiles.**
  - The Django backend becomes a Compose service (`druksmart/backend:5.2.18`, gunicorn, offline wheel build, explicit environment allowlist, masked `.env`), next to the existing `airflow` and `superset` profiles.
  - Health checks gate start-up order: PostgreSQL → Airflow → Superset → backend.
- **One operations script.** `deploy/druksmart.py` provides check, setup, up (`--minimal` without Airflow), status, run-pipeline, demo-data, backup, restore-check, restore and stop. `--env-file` selects another project and ports, which allows a fully isolated clean-start test.
- **Non-destructive by default.** No command deletes volumes; only `restore --yes` overwrites data.
- **Synthetic fallback.** `DRUKSMART_CONSUMER_DATA=synthetic` points Superset and the assistant at the synthetic database (`<db>_test`). The data stays labelled: `source_mode` in the freshness tables, and a "SYNTHETIC DATA" note in every assistant answer.

**Consequences:** One command per operation, verified by a clean-start deployment of a second stack.
This is not a production topology (single host, no HTTPS, no HA), which is documented as a limitation.

## ADR-040: One DrukSmart website: React + TypeScript app served by Django on one origin
**Date:** 2026-10-25 · **Status:** accepted (approved by the team, Milestone 10)

**Context:** The project's objective is ONE custom website that combines Superset's BI and the AI
assistant. Until Milestone 9, users moved between Superset (8088) and a small Django page (8000)
with separate logins. CLAUDE.md §2 forbids a custom dashboard designer.
**Decision:**
- **Frontend.** A React 19 + TypeScript single-page app (Vite) in `frontend/`. Exact pinned versions, `package-lock.json` committed.
- **Serving.** Django (`backend/portal`) serves the build under `/app/`, on the same origin as `/api/v1/`, so the app uses the Django session and CSRF. No tokens in the browser, no CORS.
- **Security headers on the app page.** A strict CSP (`'self'` only, no framing) and `X-Frame-Options: DENY`.
- **Login and authoring.**
  - Django is the website's identity. Viewers never use a Superset login.
  - Embedded dashboards will use per-user, per-dashboard guest tokens minted by Django (Task 10.5).
  - Dashboard Creators author in Superset's native editor with a separate Superset login. This is a documented prototype limitation; SSO is possible later.
- **Build.** The backend image builds the app in a pinned Node stage (`node:24.14.0-bookworm-slim`); the run-time container has no Node.
- **Transition.** The old assistant page stays until Task 10.9, then redirects to Ask AI.

**Consequences:**
- One product and one login for viewers, with the existing APIs reused unchanged.
- The Superset iframe remains a separate origin with its own access control (guest token plus RLS), which Task 10.5 must secure explicitly.
- A Node toolchain is needed for frontend development, but not to run the platform.

## ADR-041: Embedded dashboards with Django-minted guest tokens; branch RLS decided by Django
**Date:** 2026-10-25 · **Status:** accepted (Milestone 10, Task 10.5)

**Context:** The website must show the governed Superset dashboards to signed-in users without a
Superset login. Superset's role-based RLS does not apply to guest (embedded) users, and Superset's
default guest-token secret is public.
**Decision:**
- **Embedding.** Superset's official Embedded SDK with **guest tokens**.
  - Django (`portal/dashboards.py`) authorises each request from the user's Django scope: the dashboard must be visible, belong to one of the user's modules, and use only that module's datasets (`access.yml`).
  - Django then asks Superset, as a **portal service account** (viewer permissions plus `can_grant_guest_token` and `can_set_embedded`; no edits, no SQL Lab), for a token limited to **one dashboard**.
  - For branch managers, the token carries `branch_key IN (...)` RLS rules on every branch-filtered dataset. They are refused dashboards with unfilterable data and when no branch is assigned.
- **Tokens.** Lifetime 5 minutes, renewed by the SDK through Django. The secret comes from `.env` (`SUPERSET_GUEST_TOKEN_SECRET`; the container refuses to start without it).
- **Guest role.** "DrukSmart Embedded Guest": viewer permissions with no dataset access of its own, and nothing that leads into Superset itself (Explore, View query, share). Kept: CSV/Excel/image download, Drill by, View as table, cross-filtering.
- **Framing.** Superset sets `frame-ancestors 'self' <website>`. The embedded view checks the Referer, which the iframe sends origin-only. The website's CSP allows only Superset in `frame-src`.

**Consequences:**
- One sign-in for viewers. The branch restriction holds for aggregated charts, CSV exports and Drill by (verified in Edge, and against the KPI service per user).
- Forged, tampered and expired tokens are rejected (live tests).
- A token can outlive a sign-out or role change by up to 5 minutes.
- Creators still author in Superset with a separate sign-in (ADR-040).

## ADR-042: Reports and administration reuse the KPI registry and Django admin; no new engines
**Date:** 2026-10-25 · **Status:** accepted (Milestone 10, Task 10.7)

**Context:** The website needs reports, exports and basic administration (roles, modules, dashboard
visibility, status) without rebuilding a report engine or a user-management system.
**Decision:**
- **Reports.** A fixed catalogue of 9 reports, each one registry function with a fixed breakdown, run by the KPI service under the user's scope.
  - JSON preview and CSV download.
  - Spreadsheet-formula prefixes in text cells are neutralised; synthetic data is labelled in the file.
  - Ad-hoc exports stay in Superset's chart menus (also governed by the guest token).
- **Dashboards** are a small Django model (`PortalDashboard`: module, official/custom, visible).
  - The administrator shows or hides dashboards and publishes a Dashboard Creator's dashboard. Publishing enables embedding for the website's origin and refuses datasets outside the chosen module; the dashboard starts hidden.
- **Users and roles** stay in Django admin (groups = roles, BranchScope = branches). The website shows them read-only, with platform status.

**Consequences:**
- One definition per KPI across the overview, Ask AI, reports and (by tests) Superset. No second permission system.
- A known Superset rule (`DASHBOARD_RBAC`: only owners may "Save as") means creators build new dashboards rather than copy the official templates.

## ADR-043: The website replaces the old assistant page
**Date:** 2026-10-25 · **Status:** accepted (Decision 3; Milestone 10, Task 10.9)

**Context:** The team approved keeping the server-rendered assistant page until the website was
integrated and verified.
**Decision:** After the full verification (Edge journey, regression 14/14):
- `/` redirects to `/app/` and `/assistant/` to `/app/ask`;
- the old page's view, template and script are removed;
- `/api/v1/ask/` (used by Ask AI) is unchanged;
- Django's own sign-in page stays for the evaluation tools and as a fallback, and leads into the website.

**Consequences:** One user interface. The Milestone 8 usability walkthrough's assistant task now uses
the website's Ask AI page.

## ADR-044: The website is for managers; HR and Accounts Managers author their module's dashboards
**Date:** 2026-10-25 · **Status:** accepted (team decision after Milestone 10)

**Context:** The team clarified that the website is used by managers and senior management, not by
every HR or Accounts employee. The HR and Accounts users are the module managers and should be able
to customise dashboards for their area. Until now only a separate "Dashboard Creator" role could build
dashboards, and only the administrator could publish them.
**Decision:**
- **Roles:**
  - *HR Viewer* → **HR Manager** and *Accounts Viewer* → **Accounts Manager**, in both Superset and Django (a migration renames the Django groups, so members keep their access);
  - both managers use Superset's *creator* permission base with **their module's datasets only**: they build and edit their **own** dashboards and charts;
  - the official templates stay admin-owned and governed as code.
- **Publishing:** the managers publish, show and hide dashboards on **their own module's page** (new website page *Manage dashboards*, API `/api/v1/portal/manage/dashboards/`). The module check is unchanged: a dashboard with another module's data is refused. The administrator can do this for both modules.
- **View-only roles:**
  - the **Executive** stays view-only (team choice);
  - the **Branch Manager** stays view-only, because Superset cannot limit an author's new charts to one branch.
- **Retired:** the *Dashboard Creator* role. `bootstrap.py` removes it and the old viewer roles (`retired_roles`); `demo_creator` is removed in Django and deactivated in Superset, where it is still referenced by saved state.

**Consequences:**
- Managers customise without waiting for the administrator, but only for their module.
- The governed templates and KPI definitions stay protected.
- Superset lets a manager *save* a chart pointing at another module's dataset, but it returns no data (403, tested) and cannot be published.
- Evidence files from Milestones 6–8 use the old role names.

## ADR-045: Database-enforced primary and foreign keys on the marts (`primary_key`, `foreign_key` macros)
**Date:** 2026-10-27 · **Status:** accepted

**Context:** `warehouse/models/marts/_marts.yml` declared a `post_hook` on every dimension and fact that
called `primary_key([...])` and `foreign_key(column, parent, parent_column)`, but the macros were never
committed, so every marts build failed with "'primary_key' is undefined". The scale test (SCALE_TEST.md)
hit this first.
**Decision:** implement both macros in `warehouse/macros/` exactly as the hooks use them:
`alter table {{ this }} add primary key (...)` and
`add foreign key (...) references {{ ref(parent) }} (...)`. The parent goes through `ref()`, so it is in the
same (hidden build) schema and is built first. NULL keys stay allowed.
**Consequences:**
- PostgreSQL itself rejects duplicate grain keys and facts that point at missing dimension members, on top of the dbt `unique`, `not_null` and `relationships` tests. The first run with the constraints caught a real flaw in the new fixtures.
- The key indexes help joins as the tables grow.
- A genuine grain or referential problem now fails the marts build (and therefore blocks publication) instead of reaching dashboards. That is intended, and the failure message names the key.
