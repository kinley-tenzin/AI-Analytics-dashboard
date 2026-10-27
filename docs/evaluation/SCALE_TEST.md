# Scale test: the pipeline with MEDIUM synthetic data (Part 1: fake API, Part 2: data inside the ERPs)

**Question asked:** the demo data has about 130 records; what happens with realistic volume?
**Answer (measured, 2026-10-27):** the pipeline ran end to end over **118,051 synthetic source records**
(about 900 times more) in **about 7 minutes**, and every checked KPI matched an independent
calculation, in the warehouse, in Superset and in the Django API.

> **All data is SYNTHETIC.** It shows how the platform behaves at volume on one laptop. It is not
> DrukSmart's data and says nothing about DrukSmart's real ERPs or servers.

## What was tested

| | |
|---|---|
| Data | `tests/fixtures/synthetic_medium/` (generated, git-ignored): 118,051 records, fixed seed, 2 ERPs |
| Path | fake Odoo/ERPNext APIs → **unchanged connectors** → raw → dbt → data tests → publish, **through the Airflow DAG** (two batches: 2026-09-30 full, 2026-10-31 incremental) |
| Database | the synthetic `druksmart_analytics_test` only; the live warehouse database was not touched |
| Tool | `python evaluation/scale_test.py generate / use medium / run --reset-test-db / verify` |
| Machine | the reference laptop: 12 CPUs, 7.4 GiB RAM for Docker, 113 GB free disk before the run |

### Data volume (source records)

| Entity (per ERP) | Records |
|---|---|
| Employees | 1,000 (2,000 in total) |
| Leave requests | 10,000 (20,000 in total) |
| Customers + suppliers | 500 (1,000 in total) |
| Invoices, bills and credit notes | about 25,000 (50,000 in total) |
| Payments | about 22,000 (44,000 in total) |

Spread over two years, with partial payments, split payments, credit notes, returns, drafts,
cancellations, USD/INR documents and unapplied advances. **34 deliberately invalid records**
(17 per ERP) must be rejected. Ageing is realistic: old invoices are mostly settled, recent ones more
often open. Payments, balances and returns are generated as dated events, so
`total − outstanding = payments + returns` holds on every document at both batch dates.

## Results

### Correctness: 20 of 20 checks passed

`python evaluation/scale_test.py verify` recomputes every KPI from the fixture records with the
independent oracle (`tests/support/kpi_reference.py`, no dbt) and compares it with the published marts:

- the rejected records equal the quarantined records (34);
- HR-01 headcount by instance, branch and department; HR-03 approved leave;
- AC-01 to AC-04 (outstanding, overdue, ageing) for receivables and payables at **both** snapshot dates;
- receivables by branch, unallocated advances, and payment-to-invoice reconciliation.

Evidence: `docs/evaluation/results/scale_medium_verify.json`.

### Speed (Airflow task durations, seconds)

| Task | Batch 1 (full, 30 Sep) | Batch 2 (incremental, 31 Oct) |
|---|---|---|
| ERPNext accounts extraction | 176 | 13 |
| Odoo accounts extraction | 58 | 6 |
| HR extractions (each ERP) | 17 | 3 |
| dbt staging + intermediate | 25 | 33 |
| dbt marts build | 19 | 24 |
| dbt data tests | 13 | 14 |
| Publish swap | 1.6 | 1.3 |
| **Whole DAG run** | **276** | **115** |

Evidence: `docs/evaluation/results/scale_medium_run.json` (also holds container memory).

### Size and resources

| | |
|---|---|
| Rows in raw (all versions) | 118,017 (+ 34 quarantined) |
| Marts | 50,109 accounting documents, 43,731 payments, 24,876 receivable/payable snapshot rows, 19,980 leave requests, 3,992 headcount snapshot rows, 1,996 employees |
| Database size | 230 MB (the whole `_test` database) |
| Memory (of 7.4 GiB) | fake ERP 400 MiB, Airflow scheduler 340-450 MiB, PostgreSQL 200-310 MiB |

### Superset, Django API and assistant on the same data (2026-10-27)

`python deploy/druksmart.py demo-data synthetic`, then `python evaluation/scale_test.py consumers`
(evidence: `docs/evaluation/results/scale_medium_consumers.json`).

**Values: 14 of 14 checks passed.** Superset and the Django KPI API return exactly the oracle's totals
(headcount 1,717; receivables 183,736,254; payables 111,428,642; overdue receivables 165,739,606; overdue
payables 103,642,836; approved leave 797 requests / 1,697.5 days).

| Median time | Small data (Milestone 8) | Medium data |
|---|---|---|
| Superset query: headcount | 197 ms | 217 ms |
| Superset query: receivables total | 207 ms | 380 ms |
| Superset query: ageing by ledger | 222 ms | 331 ms |
| Dashboard load in the browser: HR | 4.4 s | 4.3 s |
| Dashboard load in the browser: Accounts | 4.0 s | 4.9 s |
| Django KPI API (any KPI) | 43-122 ms | 43-122 ms |
| Assistant, deterministic rules only | about 55 ms | **181 ms** (p95 280 ms) |

The AI assistant measured **2-7 s (outliers up to 38 s)** in this run, but **that is not the data volume**:
the backend now has Gemini configured and Gemini answered **HTTP 429 (quota exceeded)**. Every question first
spends about 1.5 s on failed Gemini calls and then falls back to the deterministic rules, which is
labelled in the answer ("rules (fallback)"). Fixing it needs a Gemini key with quota (or the provider set
to `rules`); it is unrelated to scale. Timed on its own, the rules path takes 181 ms median.

## Findings

1. **Extraction is the slow part, dbt is not.** ERPNext accounts (25,000 documents plus 20,000 payments,
   200 per page) took about 3 minutes. The whole dbt marts build takes about 20 seconds. Incremental
   runs after the first load are fast (13 s), which is how the platform would normally run.
2. **No timeouts, no memory problem, no disk problem** at this size (limits: 30 min per extraction task,
   2 h per run, so there is a wide margin).
3. **A pre-existing defect was found and fixed.** `warehouse/models/marts/_marts.yml` called two dbt
   macros, `primary_key()` and `foreign_key()`, that did not exist, so every marts build failed
   (small or large data). They are now in `warehouse/macros/`. The keys make PostgreSQL itself refuse
   duplicate grain keys and orphan dimension references (ADR-045).
4. **A foreign key caught a flaw in my first fixtures:** a leave request pointing at an employee the
   warehouse had not seen yet. A real ERP always has the employee, so the generator was corrected.

## Limits of this test (be clear when presenting)

- Pipeline, warehouse, Superset queries, the two Superset dashboards, the Django KPI API and the rules
  assistant were measured on this data. **The website pages and Gemini-phrased answers were not.**
  Dashboard loads were 3 samples each.
- One laptop, synthetic APIs on the local network: real ERP servers add network latency and rate limits.
- "Medium" is about 118,000 records. Larger loads (the 500,000 and 2.4 million levels discussed earlier)
  were **not** run.
- The ERP extraction runs on the fake APIs, so ERP-side load is not measured.

## Part 2: the same test with data loaded INTO the ERPs (10 %, 2026-10-27)

Part 1 above used a fake ERP API. At the supervisor's request the data was then loaded into the real
**Odoo and ERPNext sandboxes** (10 % of the medium set) and extracted by the unchanged connectors
(`source_mode=configured`). Loaders: `infrastructure/sandboxes/scale/` (README there).

> A live ERP only has its current state, so this run has **one snapshot date (2026-10-27)** and the
> data went into the **live warehouse database** (sandbox data, as in Milestones 5-8), not `_test`.
> Only 10 % was loaded: the full set would take roughly 4 h (Odoo) and 5-8 h (ERPNext) on this laptop.

### Loading into the ERPs (through each ERP's own logic)

| | Odoo (ORM, one process) | ERPNext (REST, 3 workers) |
|---|---|---|
| People | 100 employees | 50 employees (49 refused: lock retries, fixed on a second pass) |
| Leave requests | about 990 | 454 + later passes (69 refused: overlap / inactive employee) |
| Invoices, bills, credit notes | 2,511 (0.05 s each) | 1,306 + passes (1 s each) |
| Payments | 2,265 (0.5 s each) | 2,054 + passes (0.4 s each) |
| Wall time (10 %) | about 28 min | about 29 min plus a 16 s second pass |

The ERPs refuse some records by their own business rules (overlapping leave, leave for inactive
employees, returns above the open balance). They are counted and skipped, never forced. Parallel
ERPNext workers hit `tabSeries` lock contention (retried, then a second idempotent pass).

### Extraction and transformation (Airflow, real connectors)

| | |
|---|---|
| Whole DAG run | **170 s**, all 12 tasks succeeded, data tests passed, published |
| ERPNext accounts / Odoo accounts extraction | 65 s / 13 s |
| dbt staging + intermediate / marts / tests | 30 s / 17 s / 17 s |
| Raw records read from the ERPs | 11,734 versions (includes the earlier small sandbox data), 0 quarantined |
| Marts | 4,991 accounting documents, 4,360 payments, 1,879 leave requests, 1,364 receivable/payable snapshot rows, 220 employees |
| Warehouse database | 33 MB |

### Correctness: 30 of 30 reconciliation checks passed

`python evaluation/reconcile.py --name scale_erp10_reconciliation` compares, for each KPI and **per ERP**,
the ERPs' own figures (read straight from the Odoo and ERPNext APIs by an independent client) with dbt,
Superset, the Django KPI API and the assistant's answer text: headcount (and by department), receivables,
payables, overdue and ageing, approved leave. All layers agree. Evidence:
`docs/evaluation/results/scale_erp10_run.json` and `scale_erp10_reconciliation.json`.

### What this part does not show

- The invalid-record rejection (quarantine) was not exercised, because the ERPs themselves refuse such records.
- Only 10 % of the medium volume, and a single snapshot date.
- Dashboard and API timings were measured on the Part 1 data, not repeated here.

## Repeat or switch back

```powershell
python tests\fixtures\synthetic_medium\generate_medium.py        # (re)generate, 3 seconds
python evaluation\scale_test.py use medium                      # the fake ERP serves the medium data
python evaluation\scale_test.py run --reset-test-db             # about 7 minutes
python evaluation\scale_test.py verify                          # about 2 minutes, 20 checks
```

**The synthetic `_test` database now holds the medium data.** To show the small demo data again:
`python evaluation\scale_test.py use small`, then
`python evaluation\scale_test.py run --reset-test-db` (it empties only the `_test` raw tables, then
replays the small batches). `python deploy/druksmart.py demo-data live` points Superset and the assistant
back at the live data. `pytest -m warehouse` also resets those raw tables, so run `verify`
**before** it. Recreating `synthetic-erp` without `use medium` (for example `deploy/druksmart.py up`)
serves the small data again.
