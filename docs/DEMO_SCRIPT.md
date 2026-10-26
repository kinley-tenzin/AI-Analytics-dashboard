# Final demonstration script (about 27 minutes)

Group 8 final-year evaluation: DrukSmart Analytics & AI Dashboard Platform.

**What is live and what is not (say this at the start):**
- **ERPs:** "ERP" in this demonstration means **local Odoo 19 and ERPNext 16 sandboxes with test
  data**, not DrukSmart's systems.
- **Assistant:** it uses the **deterministic rules interpreter**. Gemini is implemented but has never
  been run with a real key.
- **Fallback:** if the sandboxes are unavailable, follow §G. It uses the **synthetic** dataset, which
  is clearly labelled as such.

## 0. Preparation (the day before, and 30 minutes before)

| Step | Command / action | Expected |
|---|---|---|
| Services up | `python deploy\druksmart.py up` | every service `healthy` |
| ERP sandboxes | `python infrastructure\sandboxes\sandbox.py up odoo` and `... up erpnext` | Odoo 127.0.0.1:8069 and ERPNext 127.0.0.1:8090 respond |
| Full status | `python deploy\druksmart.py status` | `ERP sandboxes reachable OK`, consumers read LIVE data, DAG scheduled |
| Fresh data | `python deploy\druksmart.py run-pipeline` | `configured run ...: success` |
| Everything agrees | `python evaluation\reconcile.py` | `30/30 reconciliation checks passed` |
| Browser tabs | **Website 127.0.0.1:8000/app/** (`demo_executive`; a private window for `demo_branch`, another for `demo_hr`) · Airflow 127.0.0.1:8085 (admin) · Odoo 127.0.0.1:8069 (sandbox admin) · Superset 127.0.0.1:8088 only for the authoring step (`demo_hr` with the Superset demo password) | signed in |
| Website check (optional) | `python frontend\scripts\browser_check.py` | `161/161 checks passed` |
| Resources | close unrelated containers and apps; Docker Desktop has 7+ GB | — |

Passwords are in your local `.env` (`AIRFLOW_ADMIN_PASSWORD`, `SUPERSET_ADMIN_PASSWORD`,
`SUPERSET_DEMO_USER_PASSWORD`, `BACKEND_DEMO_USER_PASSWORD`, `ODOO_SANDBOX_ADMIN_PASSWORD`). **Never show
`.env` on the projector.**

## A. ERP integration (4 min)

1. Slide or diagram: `docs/TECHNICAL_DOCUMENTATION.md` §3 (architecture). Two ERPs, read-only API connectors, one common interface.
2. Run the connection checks:

   ```powershell
   python -m ingestion check --source odoo
   python -m ingestion check --source erpnext
   ```

   Expected: authenticated, version supported (Odoo 19.0 / Frappe 16), and all contracted fields readable.
3. **Point out:** the API users are **read-only**. The platform never writes to an ERP (contracts in `contracts/sources/*.yaml`).
4. *(Optional, live change)* In the Odoo sandbox: **Employees → New** → create "Demo Visitor" in *Sales*, then **Save**. This change is used again in parts C to E.

## B. Data engineering (5 min)

1. Raw layer: source identity and extraction metadata on every record:

   ```powershell
   docker compose exec postgres psql -U druksmart_admin -d druksmart_analytics -c "select source_system, source_instance, source_entity, source_id, contract_version, first_run_id, last_extracted_at, times_seen from raw.source_record order by last_extracted_at desc limit 8"
   ```

2. Show one dbt model:
   - `warehouse/models/marts/accounts/fct_receivable_payable_snapshot.sql` (grain comment, sign rules, ageing);
   - then the star-schema diagram in `docs/TECHNICAL_DOCUMENTATION.md` §8.
3. Data-quality checks: `python warehouse\run_dbt.py ls --resource-type test`. The log line reads *Found 43 models, 164 data tests …*. Open `warehouse/models/marts/_marts.yml` (grain and relationship tests).
4. **Say:**
   - Each fact table declares its grain, and the tests enforce it.
   - Cross-ERP entities are merged only through verified mappings.
   - Invalid records are quarantined, never loaded.

## C. Pipeline automation (4 min)

1. Airflow → **druksmart_elt** → *Graph*. Walk through: validate, migrate, extract (Odoo ∥ ERPNext), dbt staging, marts (hidden schema), tests, **publish**, report.
2. **Trigger DAG** (configured) and watch it turn green (about 65 s).
3. While it runs, explain:
   - **Build–test–swap:** marts are built in a hidden schema, tested, and only then swapped in atomically. A failed test means nothing is published.
   - **Retries** for temporary ERP outages.
4. Show the `publish_validated_marts` log: `Superset datasets granted …`, `KPI service datasets granted …`.

## D. The DrukSmart website: overview and dashboards (6 min)

Everything happens in **one website**, http://127.0.0.1:8000/app/, with one sign-in.

1. **Sign in** as `demo_executive`. Point out that the menu shows only the pages of the role.
2. **Overview:**
   - Active employees (+1 if you did A.4), departments, approved leave, receivables, payables and overdue amounts;
   - the department and ageing charts (switch one to *Table*);
   - the labels *Data as of* and *Refreshed … ago* (just published).
3. **HR Analytics:** the governed Superset dashboard **inside the website**.
   - The **Active headcount** equals the overview.
   - Filter **Organisation = DTG Retail Pvt Ltd → Apply filters**; click the *Sales* bar to cross-filter.
   - Right-click a value → **Drill by → Department**.
4. **Accounts Analytics:** outstanding and overdue receivables and payables, ageing, branch table. Then **⋮ → Download → Export to .CSV**.
5. **Access control** (private window, `demo_branch`):
   - the overview and the embedded Accounts dashboard show **only the head-office branch** (101,500.00 receivables), with *Limited to your branch*;
   - the CSV contains only that branch.
   - As `demo_hr`, **Accounts Analytics** is missing from the menu, and opening `/app/accounts` says *You do not have access*.
6. **Explain the security:** "Viewers never sign in to Superset. For every dashboard, Django checks the user's module and branch and asks Superset for a 5-minute guest token for that one dashboard, with the branch as row-level security. Superset enforces the token. Only this website may frame Superset."
7. **Authoring:**
   - as `demo_hr` (HR Manager), show **Edit in Superset (separate sign-in)**: managers build dashboards with their module's data in Superset's own editor (a known limitation: a second sign-in);
   - open **Manage dashboards**: the HR Manager publishes and shows/hides dashboards on the HR page only; the executive and the branch manager do not have this page.

## E. Ask AI and Reports (5 min)

**Ask AI** as `demo_executive` (click suggested questions or type):

| Ask | Expected |
|---|---|
| How many active employees are there? | the same headcount as the overview and the dashboard, as-of date stated |
| How many employees work in each department? | per-department chart and table, with *Explore in HR Analytics* |
| How much is overdue? | receivables and payables separately, BTN, as-of date |
| Show overdue balances by ageing category. | ageing buckets per ledger |
| What is the outstanding balance? | **Needs clarification**, with one-click options |
| What is the salary of the HR manager? | **Not supported** (personal data) |

- **Not authorised:** as `demo_hr`, ask *What is the outstanding receivables balance?*. Expected: **Not authorised**, and no query was run.
- **Honest labelling:** every answer says **"Deterministic rules, no language model"**, and the side panel explains how answers work.

**Reports** (`demo_branch`): *Outstanding receivables by branch* → **Preview** → **Download CSV**. Only the branch's rows are included.

**Administration** (optional; needs an administrator account): platform status, dashboard visibility, users with roles and branches.

## F. Verification (3 min)

1. Run live: `python evaluation\reconcile.py`, which gives **30/30**. Every KPI is identical across:
   - the ERPs' own figures;
   - dbt;
   - Superset;
   - the Django API;
   - the AI answer.

   The website check (`frontend\scripts\browser_check.py`, 161 checks) adds the embedded dashboards,
   the overview and the reports for each role.
2. Show `docs/evaluation/EVALUATION_REPORT.md`:
   - **§4:** end-to-end deltas;
   - **§6:** 8/8 failure scenarios;
   - **§7:** access matrix 115/115;
   - **§8:** measured performance;
   - **§11:** limitations.
3. Close with the limitations:
   - sandboxes, not DrukSmart's ERPs;
   - Gemini unverified;
   - no real-user study yet;
   - not production-ready.

## G. Fallback: synthetic dataset (if the ERP sandboxes are not available)

```powershell
python deploy\druksmart.py demo-data synthetic
```

This replays the two **fictional** extraction batches (2026-09-30 and 2026-10-31) through the real
connectors, raw store, dbt, tests and publication, into the separate `druksmart_analytics_test`
database. It then points Superset and the assistant at that database.

**Say clearly: "This is synthetic demonstration data."** It is labelled in the product:
- Superset's *Data freshness* shows `source_mode = synthetic` and the fictional instances `odoo-dtg-retail` / `erpnext-dtg-services`;
- every assistant answer ends with **"SYNTHETIC DATA: …"**;
- the website's overview shows a red **"FICTIONAL synthetic demonstration dataset"** banner, and report files are named `…_SYNTHETIC.csv`.

Expected figures (hand-calculated in `tests/fixtures/synthetic/expected_kpis.json`, as of 2026-10-31):

| KPI | Expected |
|---|---|
| Active headcount | 16 (Odoo 9, ERPNext 7) |
| Approved leave, Oct 2026 | 7 requests, 13.5 days, 5 employees |
| Outstanding receivables | 142,500 (Odoo) + 78,700 (ERPNext) = **221,200** |
| Outstanding payables | 33,200 + 30,000 = **63,200** |

Parts B, C (manual DAG runs in *synthetic* mode), D, E and F work the same way. Part A shows the
connector code and contracts instead of a live connection.

**After the demo, switch back:** `python deploy\druksmart.py demo-data live`.

**If Gemini is asked about:** "The provider is implemented with function calling and mocked tests. It
was not run against the real API (no key), so today's answers use the deterministic interpreter, as
the label shows."

## H. If something goes wrong

| Symptom | Quick fix |
|---|---|
| A service is not healthy | `python deploy\druksmart.py up` (waits for health); then `status` |
| ERP check fails after a laptop or Docker restart | `python infrastructure\sandboxes\sandbox.py up odoo` / `erpnext` (or switch to §G) |
| The DAG run fails | Open the red task's log in Airflow. The previous data stays published (show that as a feature) |
| *Data may be out of date* in the website | run `python deploy\druksmart.py run-pipeline` |
| An embedded dashboard says "not reachable" | `python deploy\druksmart.py up`, then *Try again* |
| Docker Desktop stuck | quit it, `wsl --shutdown`, start it, then `python deploy\druksmart.py up` |
