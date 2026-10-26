# Apache Superset: BI and reporting (Milestone 6)

Superset **is** the dashboard interface of the platform: no separate React/ECharts application exists.
It reads only the published, tested warehouse datasets. Dashboards are built and edited with Superset's
own native editor.

| | |
|---|---|
| Version | Apache Superset **6.1.0** (`apache/superset:6.1.0` + `psycopg2-binary==2.9.9`, image `druksmart/superset:6.1.0`) |
| URL | <http://127.0.0.1:8088> (port `SUPERSET_PORT`; bound to 127.0.0.1 only) |
| Metadata | Own PostgreSQL 17.11 container `superset-db` (volume `druksmart_superset_db`), never the warehouse |
| Warehouse account | `druksmart_superset_reader`: `SELECT` on the **4 approved datasets only** |
| Configuration as code | `superset/`: approved list, governed dataset definitions, access model, dashboard templates, exported assets |

Contents:
1. [Architecture](#1-architecture)
2. [Setup](#2-setup-windows)
3. [Database connection](#3-database-connection-and-account)
4. [Approved datasets](#4-approved-datasets-and-governed-metrics)
5. [Dashboards and KPI mapping](#5-dashboards-and-kpi-to-chart-mapping)
6. [Roles](#6-roles-and-access-matrix)
7. [Usage](#7-usage)
8. [Export, import and backup](#8-export-import-backup-and-restore)
9. [Verification](#9-verification-results)
10. [Manual test guide](#10-manual-test-guide)
11. [Limitations](#11-limitations)

## 1. Architecture

```mermaid
flowchart LR
    AF["Airflow publish step<br/>(warehouse/publish.py)"] -->|"GRANT SELECT on approved list"| MARTS
    subgraph PG["PostgreSQL · druksmart_analytics"]
        MARTS[("marts<br/>kpi_headcount · kpi_approved_leave_monthly<br/>kpi_receivables_payables · data_freshness")]
        OTHER[("raw · staging · intermediate<br/>marts dimensions & facts")]
    end
    SS["Superset 6.1.0<br/>roles · dataset permissions · RLS"] -->|"druksmart_superset_reader<br/>read-only sessions"| MARTS
    SS -. "no privileges" .-x OTHER
    SS --> SSDB[("superset-db<br/>users · charts · dashboards")]
    U["Browser users<br/>HR Manager · Accounts Manager · Executive · Branch manager"] --> SS
```

Access is enforced at two layers, and neither depends on the other:

| Layer | Enforced by | What it guarantees |
|---|---|---|
| Database account | PostgreSQL grants (`publish.py`), `default_transaction_read_only`, `statement_timeout` | Superset as a whole (even its Admin, SQL Lab included) can read only the 4 approved relations, and cannot write |
| Superset roles | Dataset permissions, dashboard roles (`DASHBOARD_RBAC`), row-level security | Each user queries only their domain's datasets, and only their branch's rows (branch managers). This applies equally to dashboards, Explore, drill-down and CSV export |

Django permissions are **not** involved: Superset runs every dashboard query itself (CLAUDE.md §2).

## 2. Setup (Windows)

Prerequisites: PostgreSQL running (`docker compose up -d`), with marts published by Airflow
(Milestone 5) or by a manual dbt build.

```powershell
# 1. Settings: adds SUPERSET_* and DRUKSMART_SUPERSET_READER_* with random passwords (never printed)
python infrastructure\scripts\create_local_env.py --add-missing

# 2. Create the Superset warehouse login (idempotent) and grant it the approved datasets
docker compose exec -T postgres bash /docker-entrypoint-initdb.d/01_init_databases_roles_schemas.sh
python warehouse\publish.py grant-superset      # Airflow does this at every publication

# 3. Build the image (adds the PostgreSQL driver) and start Superset (~2 GB RAM, ~1.5 GB disk)
docker compose --profile superset up -d --build --wait

# 4. Register the connection, datasets, roles, dashboards, RLS and demo users (safe to re-run)
python superset\scripts\bootstrap.py
```

Expected output:
- Step 3 shows `Container druksmart-superset-1 Healthy`.
- Step 4 ends with `bootstrap complete` after lines such as `[database] created 'DrukSmart Warehouse' … connection OK`, `[dataset] … certified metrics`, `[role] …`, `[dashboard] …` and `[users] …`.

Open <http://127.0.0.1:8088>. Log in with `SUPERSET_ADMIN_USER` and the password stored in your
local `.env` (`SUPERSET_ADMIN_PASSWORD`). Open the file in an editor to read it; never paste it into
chat or commit it.

**Security of the deployment:**
- The Superset containers get **only** their own settings, never the whole `.env` (no `env_file`).
- The warehouse password is entered once by `bootstrap.py` and stored encrypted with `SUPERSET_SECRET_KEY`. Changing that key makes stored passwords unreadable; re-run `bootstrap.py` afterwards.
- The admin password is passed to `superset fab create-admin` inside the container, not on the compose command line.
- Self-registration is off and there is no public role.

**Troubleshooting:**

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: psycopg2` | You are running the plain `apache/superset` image: use `--build` (the official image ships no DB drivers) |
| `bootstrap.py`: `permission denied for table …` in the connection test | Run step 2 (`publish.py grant-superset`) |
| `bootstrap.py`: `approved Superset datasets missing` (publication) | A dbt model in `approved_datasets.yml` was renamed/removed: fix the list or the model |
| `cannot log in to Superset … HTTP 401` | Admin password in `.env` differs from the one used at first start: `docker compose exec superset superset fab reset-password --username admin --password <new>` (type it yourself), then update `.env` |
| Port 8088 in use | Set `SUPERSET_PORT` in `.env`, then `docker compose --profile superset up -d` |

## 3. Database connection and account

| Setting | Value | Why |
|---|---|---|
| Name | `DrukSmart Warehouse` | |
| URI | `postgresql+psycopg2://druksmart_superset_reader:***@postgres:5432/druksmart_analytics` | Compose service name inside Docker |
| Session options | `default_transaction_read_only=on`, `statement_timeout=60000`, `connect_timeout=10` | Read-only even if a grant were wrong; no runaway queries |
| DML / CTAS / CVAS / file upload / async | all **off** | |
| Exposed in SQL Lab | yes, but only Admin has SQL Lab | Admin troubleshooting; same 4 relations |

The account is created by `infrastructure/postgres/init/01_init_databases_roles_schemas.sh`, with
CONNECT plus USAGE on `marts`. **`SELECT` is granted per relation** by `warehouse/publish.py` inside the
publication transaction, from `superset/approved_datasets.yml`. Because of that:
- a newly published table is **not** visible to Superset until someone approves it (unlike `bi_reader`, which reads all of `marts`);
- publication **fails** (and the old marts stay published) if an approved relation is missing.

## 4. Approved datasets and governed metrics

Source of truth: `superset/approved_datasets.yml` (what may be read) and
`superset/definitions/datasets.yml` (labels, date columns, filterable columns, metrics).

| Dataset (`marts.`) | Domain | Grain | Date column | Certified metrics |
|---|---|---|---|---|
| `kpi_headcount` | HR | snapshot date × instance × organisation × branch × department × category × employment status | `snapshot_date` | `active_headcount`, `employee_records`, `not_active_records` |
| `kpi_approved_leave_monthly` | HR | leave start month × instance × organisation × branch × department × leave type | `period_month` | `approved_requests`, `approved_leave_days` |
| `kpi_receivables_payables` | Accounts | as-of date × instance × ledger × organisation × branch × ageing bucket | `snapshot_date` | `outstanding_receivables`, `outstanding_payables`, `overdue_receivables`, `overdue_payables`, `outstanding_amount`, `open_documents` |
| `data_freshness` | shared | instance × domain | `published_at` | (none: shown as a table) |

Not approved (deliberately invisible to Superset):
- `dim_employee` (names), `dim_customer` and `dim_supplier`;
- the transaction facts `fct_*`;
- every `raw` / `staging` / `intermediate` relation.

Governance rules:
- **Metrics only re-aggregate the KPI columns dbt computes** (e.g. `SUM(active_headcount)`). No business rule is re-implemented in a chart. Unit tests check that every metric uses only its dataset's columns and that every chart uses only certified metrics.
- Metrics are **certified** ("DrukSmart data engineering (dbt)", with the KPI id). Point-in-time metrics carry a **warning** ("filter to ONE snapshot date").
- Datasets are flagged **managed externally**, so the UI does not offer to edit them. Change `datasets.yml` and re-run `bootstrap.py`. No DrukSmart role has dataset-write permission (tested).
- **Currency:** amounts are in each organisation's company currency (`currency_code` column). Metrics use Superset's `AUTO` currency with `currency_code_column`, so nothing hard-codes "BTN"; tables show `BTN 101,500.00`. A *Currency* filter exists because amounts of different currencies must never be added.
- **Labels:** the KPI views expose `organisation_name`, `branch_name`, `department_name` and `ageing_bucket_label` from the conformed dimensions. dbt `not_null` tests guarantee that every key resolves to a label.

## 5. Dashboards and KPI-to-chart mapping

Templates are defined in `superset/definitions/dashboards.py` and owned by the admin. Their URLs are
`/superset/dashboard/druksmart-hr/` and `/superset/dashboard/druksmart-accounts/`.

**Point-in-time rule.** Headcount and open balances must not be summed across snapshot dates. Each
dashboard therefore has a **required, single-value** date filter (*Snapshot date* / *As-of date*) that
defaults to the **latest available date**. That date is computed from the data, not hard-coded. Trend
charts are excluded from that filter and plot every date.

### DrukSmart HR Overview

| Chart | Type | Metric (dataset) | KPI |
|---|---|---|---|
| Active headcount | KPI card | `active_headcount` (kpi_headcount) | HR-01 |
| Not-active employee records | KPI card | `not_active_records` | HR-01 (comparison) |
| Approved leave days / Approved leave requests | KPI cards | `approved_leave_days` / `approved_requests` (kpi_approved_leave_monthly) | HR-03 |
| Active headcount by department | horizontal bar | `active_headcount` by `department_name` | HR-02 |
| Employee records by employment status (active vs not active) | donut | `employee_records` by `employment_status` | HR-01 comparison |
| Headcount by organisation and branch | table | active / not-active / all records | HR-01 |
| Active headcount trend (all snapshot dates) | line | `active_headcount` by organisation | HR-01 over time |
| Approved leave days by month and leave type | stacked bar | `approved_leave_days` | HR-03 |
| Approved leave by department and leave type | table | `approved_requests`, `approved_leave_days` | HR-03 |
| HR data freshness | table | `data_freshness` (domain = hr) | freshness |

Filters:
- *Snapshot date* (required, defaults to latest);
- *Leave period* (time range on the leave start month);
- *Organisation* → *Branch* → *Department* (cascading).

### DrukSmart Accounts Overview

| Chart | Type | Metric | KPI |
|---|---|---|---|
| Outstanding receivables / Outstanding payables | KPI cards | `outstanding_receivables` / `outstanding_payables` | AC-01 / AC-02 |
| Overdue receivables / Overdue payables | KPI cards | `overdue_receivables` / `overdue_payables` | AC-03 |
| Ageing of open balances by ledger | grouped bar | `outstanding_amount` by `ageing_bucket_label` × `ledger` | AC-04 |
| Outstanding balance trend by ledger (all as-of dates) | line | `outstanding_amount` by `ledger` | AC-01/02 over time |
| Open balances by organisation and branch | table | all five balance metrics + `open_documents`, with currency | AC-01..04 |
| Accounts data freshness | table | `data_freshness` (domain = accounts), incl. *Hours since publication* (computed at query time, M8) | freshness |

Filters:
- *As-of date* (required, defaults to latest);
- *Trend period*;
- *Organisation* → *Branch*;
- *Currency*.

Overdue amounts can exceed outstanding amounts for a branch. This is correct (AC-03): credit notes
reduce the outstanding total, while overdue counts only positive past-due balances.

**Interaction:**
- native filters;
- **cross-filtering** (click a bar or slice: the filter goes only to charts whose dataset has that column);
- *Drill by* on the governed datasets (right-click a value). *Drill to detail* (raw dataset rows) is
  **not** available to DrukSmart roles: none has `can_samples` (corrected in Milestone 10; earlier
  versions of this document listed it);
- *View as table*;
- **CSV/Excel export** from each chart menu (the same query, so RLS applies);
- *Explore* on a chart to analyse further.

Empty results show Superset's *No results were returned* message. Each dashboard's intro text explains
that this means the filters or the user's access rights leave no data.

## 6. Roles and access matrix

Defined in `superset/definitions/access.yml`. Every user has **one** DrukSmart role. `bootstrap.py` sets
each role's permissions to **exactly** that list, so manual drift is removed on the next run.

> **Changed in Milestone 10 (ADR-044):** the website is for managers and senior management. The HR
> and Accounts **Viewer** roles became **HR Manager** and **Accounts Manager**, who may also build
> dashboards with their own module's data. The separate Dashboard Creator role was retired (removed by
> `bootstrap.py`; `demo_creator` is deactivated). Earlier evidence in docs/evaluation/ refers to the old names.

| | Admin | HR Manager | Accounts Manager | Executive | Branch Manager |
|---|---|---|---|---|---|
| Superset role | `Admin` (built-in) | `DrukSmart HR Manager` | `DrukSmart Accounts Manager` | `DrukSmart Executive` | `DrukSmart Branch Manager` |
| HR datasets | ✅ | ✅ | ❌ (403) | ✅ | ✅ own branch (RLS) |
| Accounts dataset | ✅ | ❌ (403) | ✅ | ✅ | ✅ own branch (RLS) |
| Freshness | ✅ | ✅ | ✅ | ✅ | ✅ |
| Dashboards listed | all | HR + own | Accounts + own | HR, Accounts | HR, Accounts |
| Explore / CSV export | ✅ | ✅ (own data) | ✅ (own data) | ✅ | ✅ (own branch) |
| Create/edit charts & dashboards | ✅ | ✅ **own** objects, HR data only | ✅ **own** objects, Accounts data only | ❌ | ❌ |
| Edit default templates | ✅ (as code) | ❌ (403) | ❌ (403) | ❌ | ❌ |
| Edit datasets / metrics | via `datasets.yml` | ❌ (403) | ❌ (403) | ❌ | ❌ |
| Register new datasets | via `approved_datasets.yml` | ❌ (403) | ❌ (403) | ❌ | ❌ |
| SQL Lab | ✅ (4 relations only) | ❌ | ❌ | ❌ | ❌ |

A manager can technically save a chart that points at another module's dataset (Superset checks data
access when a chart is *queried*), but it returns no data (403, tested) and the website refuses to
publish a dashboard containing it.

Permission bases:
- **viewer** = Superset `Gamma` *minus* chart/dashboard/tag/theme write, definition export, cache invalidation, RLS-rule reading and self-registration.
- **creator** = `Gamma` *minus* RLS reading, theme write and self-registration. Used by the HR and Accounts Managers.

Neither base contains SQL Lab, database access or dataset write. Data access is then added per dataset
(`datasource_access`). Superset's built-in `Gamma`, `Alpha` and `sql_lab` roles are not given to users.

**Row-level security:**
- Rule *Branch manager - demo branch*, applied to the three KPI datasets: `branch_key IN ('odoo:odoo-sandbox:1')`.
- For a real deployment, set each manager's `branch_keys` (from `marts.dim_branch`) in `access.yml`. Use one RLS rule and role per branch, or a shared `group_key`.
- ERPNext invoices carry no branch (DS-AC-05), so ERPNext branch managers see HR data but an empty Accounts dashboard until DrukSmart decides how invoices map to branches.

**Demo users** (local testing only; created when `SUPERSET_DEMO_USER_PASSWORD` is set; they share that
password):
- `demo_hr` (HR Manager)
- `demo_accounts` (Accounts Manager)
- `demo_executive`
- `demo_branch`

To create real users, use *Settings → List Users*, and give each user exactly one DrukSmart role. Do
not create demo users in a DrukSmart deployment: leave the variable as `CHANGE_ME`.

## 7. Usage

- **Viewers:**
  - Open *Dashboards* and choose a dashboard.
  - Adjust the filters in the left bar and click **Apply filters**.
  - Click a bar or slice to cross-filter.
  - Use a chart's ⋮ menu for *Download → Export to .CSV* or *View as table*; right-click a value for *Drill by*.
- **HR and Accounts Managers** (building dashboards with their module's data):
  - **New chart:** *Charts → + Chart*, pick a dataset you have access to, choose a chart type, then use the certified metrics (✓ icon) and the labelled columns. Ad-hoc metrics you type in a chart stay in that chart and never change the governed definitions.
  - **New dashboard:** *Dashboards → + Dashboard*, add your charts, arrange them (*Edit dashboard*: drag, resize, markdown, native filters) and save. The official templates cannot be copied with *Save as* (Superset allows that only for their owner, the admin).
  - **Show it on the website:** in the website, *Manage dashboards* → publish it on your module's page, then switch it to *Visible*.
  - **Point-in-time metrics:** when you use one, keep a single-date filter on `snapshot_date` (the metric's warning says so).
- **Administrators:**
  - Change templates, datasets, roles or RLS in `superset/definitions/`, run `bootstrap.py`, then `assets.py export`, and commit.
  - Changes made only in the UI to the admin-owned templates are overwritten by the next `bootstrap.py`.
- **Filter panel layout:** *Apply filters / Clear all* sit directly under the last filter instead of pinned to the
  panel's bottom. This is CSS in `superset/docker/head_custom_extra.html`, mounted by `compose.yaml` over Superset's own
  (empty) customisation hook, so it applies to every Superset page and to the dashboards embedded in the website. It
  uses Superset's `data-test` hooks; re-check it after upgrading Superset.

## 8. Export, import, backup and restore

| What | Where | How |
|---|---|---|
| Dashboard definitions (templates **and** user-saved dashboards with their charts, datasets and connection) | `superset/assets/dashboards/` (YAML, committed) | `python superset\scripts\assets.py export` |
| Roles, RLS, demo users | `superset/definitions/access.yml` | applied by `bootstrap.py` |
| Everything (incl. users and passwords hashes) | metadata DB dump, **outside Git** | see below |

**Restore dashboards from Git** (overwrites objects with the same UUID):

```powershell
python superset\scripts\assets.py import
python superset\scripts\bootstrap.py   # roles, RLS, users (and re-applies the templates)
```

`assets.py import` imports **datasets, then charts, then dashboards**, each with overwrite. Superset's
dashboard import alone overwrites only the dashboard, not its charts (found while testing; see §9). The
warehouse password is taken from `.env`. The export contains it masked (`XXXXXXXXXX`).

**Full backup** of Superset's metadata database (contains password hashes, so store it like a secret):

```powershell
mkdir backups -Force
docker compose --profile superset exec -T superset-db pg_dump -U superset -d superset --format=custom > backups\superset_meta.dump
```

Restore into an empty `superset-db`: stop `superset`, then
`docker compose --profile superset exec -T superset-db pg_restore -U superset -d superset --clean --if-exists < backups\superset_meta.dump`,
then start `superset` again. The same `SUPERSET_SECRET_KEY` is required. `backups/` is git-ignored.

## 9. Verification results

All results below were produced on the reference machine on 2026-10-24/25, against the local ERP
sandboxes' data (synthetic, not DrukSmart's ERPs).

| Check | How | Result |
|---|---|---|
| Superset starts, init idempotent | `docker compose --profile superset up -d --wait`; re-ran `superset-init` | healthy; second init: `User already exists`, `superset-init done` |
| Connection works with the restricted account | `bootstrap.py` / `bootstrap.py --check` | `connection OK` |
| Bootstrap idempotent | ran 4×; counted objects | always 19 charts, 2 dashboards, 4 datasets, 1 RLS rule |
| Access boundary + KPI correctness (API, as each demo user) | `pytest -m superset` (35 tests) | **35 passed** |
| Definitions consistent with dbt models | `pytest tests/unit/test_superset_definitions.py` | 46 passed |
| Publication grants only approved relations; fails on missing ones | `pytest tests/integration/test_publish.py` | 7 passed |
| Real orchestrated publication grants Superset | Airflow runs `m6_superset_views_1/2` | `superset datasets granted: [...]` in the publish task log; both runs success |
| Dashboards render in a browser, per role, with correct KPI values | `python superset\scripts\browser_check.py` (headless Microsoft Edge) | 12/12 PASS: allowed dashboards render all charts with no errors; other-domain dashboards denied; every KPI card equals the value computed from the fact tables (branch manager: RLS values 7 employees, 101,500.00 receivables) |
| Interactive filter | browser script: Organisation = DTG Retail Pvt Ltd → Apply | receivables 166,700.00 → 101,500.00, payables 35,200.00 → 24,200.00 (= warehouse) |
| Saved changes persist | creator saved a dashboard; restarted `superset-db` + `superset` | dashboard still there (then deleted) |
| Restore from Git into an **empty** Superset | temporary instance on port 8089 with a new metadata DB: `assets.py import` + `bootstrap.py`, then `pytest -m superset` against it | 19 charts, 2 dashboards, 4 datasets, 1 RLS; 35/35 tests passed; temporary instance removed |
| Restore overwrites a changed chart | renamed a chart, ran `assets.py import` | name restored |
| Metadata backup | `pg_dump` custom format + `pg_restore --list` | 391 KB, 53 tables of data |
| No secrets in committed Superset files | scanned `superset/` and the tests for every `.env` secret value | none found |

What `pytest -m superset` proves, request by request through Superset's own API:

- **KPIs match the warehouse facts.** Headcount total and by department, AR/AP/overdue, approved leave and freshness all equal values computed independently from `fct_*`.
- **Dataset visibility per role is exact.** HR and Accounts users get **403** on the other domain, for both chart data and CSV export, and HR and Accounts users cannot open the other domain's dashboard.
- **SQL Lab is denied to all 5 DrukSmart roles.** Even the Admin's SQL Lab gets `permission denied` on `raw.source_record`, `staging.*`, `marts.dim_employee` and `marts.fct_leave_request`, and DML is refused.
- **RLS restricts the branch manager to their branch.** It also holds when they try to filter for other branches and in CSV export.
- **Viewers cannot create or modify anything.** Charts, dashboards and datasets all return 403.
- **The creator can build charts and dashboards, but not change governed objects.** Dataset metrics, the admin-owned templates and new datasets all return 403.

**Defects found and fixed during verification:**
1. **The latest-date filter was shown but not applied** (browser check): the KPI cards summed all three snapshot dates (48 instead of 16 employees). The cause was that native filters created via the API need `requiredFirst: true`. `bootstrap.py` now sets it, and `browser_check.py` compares every KPI card with the warehouse so that this cannot regress silently.
2. **ERPNext invoices had no organisation** (new dbt `not_null` label tests): organisation came only via the "Unassigned" branch. It is now taken from the invoice's own company (`int_accounting_document_versions`).
3. **Restore did not restore charts** (restore test): `assets.py` now imports datasets, charts and dashboards separately.
4. The official image has **no PostgreSQL driver**: added a 3-line derived image.

## 10. Manual test guide

The automated checks above already cover access and values. These manual checks confirm the
*experience* in your own browser. Record the results in the table.

| # | Steps | Expected | Result / date / tester |
|---|---|---|---|
| 1 | Log in as admin → *Dashboards* → *DrukSmart HR Overview* | All charts load. *Snapshot date* shows the latest date, and *Active headcount* equals the freshness table's latest data | |
| 2 | HR dashboard: Organisation = *DTG Retail Pvt Ltd* → **Apply filters** | Cards and charts change. The Branch filter only offers DTG Retail branches | |
| 3 | HR dashboard: click the *Sales* bar in *Active headcount by department* | Cross-filter chip appears. The other headcount charts show Sales only; the leave charts follow (same column) | |
| 4 | Chart ⋮ → *Download → Export to .CSV* on *Headcount by organisation and branch* | CSV opens with the same rows as the table | |
| 5 | Log out; log in as `demo_hr` (password: `SUPERSET_DEMO_USER_PASSWORD` in your `.env`) | Only the HR dashboard is listed. The *SQL* menu is absent. *Datasets* shows 3 datasets | |
| 6 | As `demo_hr`, open `http://127.0.0.1:8088/superset/dashboard/druksmart-accounts/` | Access denied / not found | |
| 7 | Log in as `demo_branch` → Accounts dashboard | Receivables 101,500.00, payables 24,200.00. The branch table shows only *DTG Retail Pvt Ltd (head office)*. Export CSV: only that branch | |
| 8 | Log in as `demo_hr` (HR Manager) → *Dashboards → + Dashboard* "My HR" → add an HR chart → resize it → **Save** | Copy saved. After a browser refresh (and after `docker compose --profile superset restart superset`) the change is still there | |
| 9 | As `demo_hr`, open a dataset (*Datasets* → kpi_headcount) | Metrics are certified (✓) and cannot be edited | |
| 10 | As `demo_executive`, open any chart → try *Save* | No save option / permission error | |

## 11. Limitations

- **Data.**
  - Verified only against the local sandboxes and synthetic data, not DrukSmart's ERPs or real users.
  - The sandbox balances are identical on all three snapshot dates, so trend lines are flat.
- **HR-03 distinct employees on leave** over a period cannot be re-aggregated from the monthly view, and employee-level data is deliberately not exposed to BI. The dashboard shows requests and days. The distinct count needs a dedicated KPI view (e.g. per period) if DrukSmart wants it.
- **Point-in-time metrics outside the templates.** A creator who explores `active_headcount` without a single-date filter gets a multi-date sum. Mitigations are the metric warning, documentation and a required date filter on the templates. A database-side guard would require changing the KPI view grain, which was not done.
- **KPI cards show the amount without the currency code** (Superset's AUTO currency is applied in tables). Each dashboard has a Currency filter, and both sandbox organisations use BTN.
- **ERPNext branches** have no Accounts data (invoices carry no branch; open decision DS-AC-05).
- **No Redis/Celery:**
  - chart-data caching is **off** since Milestone 8 (a 5-minute cache showed the previous publication after a refresh: defect D2); rate limiting is in memory;
  - async SQL Lab, alerts and scheduled reports are not configured (optional per the milestone);
  - a production deployment should add Redis and a worker.
- **RLS branch assignment is manual** configuration in `access.yml` (one rule per branch); there is no automatic user→branch mapping yet.
- **Single shared demo password** for the 5 demo users (local testing only).
- **UI changes to the default templates** are overwritten by `bootstrap.py`. They must go through `definitions/`, by design.
- **Interactive checks 3, 4, 8 and 9 in §10** (cross-filter click, CSV download via the UI, editor drag/resize, certified badge) were not automated. Their underlying permissions and queries are covered by the API tests.
