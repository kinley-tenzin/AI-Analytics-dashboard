# Project evidence pack (for the final-year report and viva)

Material for Group 8 to explain the implementation to evaluators. It points to the real artefacts
in the repository. It is **not** the dissertation; each section is a starting point for the
corresponding report chapter.

## 1. Architecture summary (one paragraph for the abstract)

Read-only Python connectors extract HR and Accounts records from Odoo 19 (JSON-2 API) and ERPNext 16
(Frappe REST) into a versioned raw store in PostgreSQL, preserving source identity and extraction
metadata. dbt transforms them through staging and integration layers into Kimball star schemas and
governed KPI views; 164 data tests run on every build. Apache Airflow orchestrates a daily
build–test–publish cycle in which marts become visible to consumers only after every test has
passed. Apache Superset provides role-based dashboards with row-level security. A Django backend
answers bounded natural-language questions only through an allowlist of approved KPI functions. Both
consumers use dedicated read-only database accounts limited to the approved datasets. See
[TECHNICAL_DOCUMENTATION.md §3](../TECHNICAL_DOCUMENTATION.md).

## 2. Major technical contributions (what the team built, not configured)

1. **Contract-driven, read-only ERP connectors** with one interface for two very different APIs: keyset paging, incremental windows, retries, per-record contract validation and quarantine (`connectors/`, `contracts/`).
2. **Versioned, idempotent raw store.** Payload hashing keeps every distinct version and never duplicates; checkpoints make extraction restartable (`ingestion/`).
3. **Cross-ERP canonical model.** Explicit status, sign and currency rules, verified-only entity mapping, and documented grains, reproducing hand-calculated KPIs to the cent (`warehouse/`).
4. **Build–test–swap publication** with per-consumer least-privilege grants and a freshness/audit trail (`warehouse/publish.py`).
5. **Governed BI as code.** Certified metrics, roles, RLS and dashboards applied idempotently through Superset's API, with restorable assets (`superset/`).
6. **Bounded AI architecture.** A KPI function registry; the LLM only *proposes*; backend authorisation; numbers in LLM text verified against results; labelled deterministic fallback (`backend/`).
7. **Evaluation framework with independent oracles.** Source-ERP oracle, controlled sandbox changes, cross-layer reconciliation, fault injection and an access matrix (`evaluation/`).
8. **Reproducible deployment.** Offline image builds, ordered health-checked start-up, backup with restore verification, and a clean-start test (`deploy/`).

## 3. Data modelling justification

| Choice | Alternative considered | Why |
|---|---|---|
| Kimball star schemas with explicit grains | One wide table per KPI | Conformed dimensions serve both ERPs and both modules; grains are testable; BI-friendly |
| Periodic snapshot facts (headcount, open balances) | Reconstructing balances from transaction history | Exact "as of" figures using each ERP's own computed balance; no fabricated history (DS-AC-01) |
| Type 1 dimensions | Type 2 SCD | History needed only for KPIs, and the snapshot facts already carry the as-of attributes |
| Keys `system:instance:id`, never merged on names | Name matching | Same names in different ERPs are different entities (e.g. two "Sales" departments, "Pema Wangmo") |
| Company-currency amounts, split by currency | Converting everything to one currency | Avoids an invented exchange-rate policy (DS-AC-03/04) |
| KPI views + certified metrics | Formulas in each chart | One definition used by Superset and Django, tested equal |

## 4. Source-mapping examples (to show evaluators)

1. **Odoo customer invoice, partially paid.** Fields `move_type = out_invoice`, `state = posted`, `amount_residual_signed = 3,500` give ledger *receivable* with outstanding **+3,500** in company currency. After a full payment the residual is 0, so the document leaves the open-items snapshot. *Evidence:* end-to-end phases A/B in [EVALUATION_REPORT.md §4](../evaluation/EVALUATION_REPORT.md).
2. **ERPNext return (credit note).** Sales Invoice with `is_return = 1` maps to kind *credit note*, sign −1, and with an unapplied balance falls into the *unapplied credit* ageing bucket. *Evidence:* fixtures `RET-00001/00002`, `tests/warehouse`.
3. **Employee status.** Odoo `active = false` plus `departure_date` gives *left*. ERPNext `status = Active` but `date_of_joining` after D gives *not yet joined*. Neither counts in headcount. *Evidence:* HR-01 working in `tests/fixtures/synthetic/expected_kpis.json`.
4. **Cancelled leave.** ERPNext `docstatus = 2` is not approved, so it is excluded from HR-03. *Evidence:* end-to-end phase B (requests −1).

## 5. KPI validation examples

| Validation | Example result |
|---|---|
| Hand-calculated fixtures | HR-01 16 (Odoo 9 + ERPNext 7); HR-03 7 requests / 13.5 days / 5 employees; AR 2026-10-31 = 142,500 + 78,700. Reproduced exactly by dbt **and** the Django KPI service |
| Source ERP oracle vs all layers | headcount 16, AR 166,700, AP 37,700, overdue AR 149,700, AP 31,700; identical in ERPs, dbt, Superset, Django, AI result and AI text (30/30) |
| Changes by construction | +1 hire then −1 departure; invoice 6,000 − 2,500 paid gives +3,500, then −3,500 when settled; cancelled invoice gives 0; extra leave for an already-absent employee gives requests +1, distinct employees +0 |

## 6. Test result summary

| Area | Result |
|---|---|
| pytest | 495 tests (unit, database, warehouse, live ERP, KPI service, Superset), all passing at handover |
| dbt data tests | 164 per run |
| Regression runner | 12/12 stages |
| End-to-end runs | 5/5 with exact deltas; reconciliation 30/30 each |
| Reliability | 8/8 fault scenarios |
| Access matrix | 115/115 |
| AI (rules) | 56/56 seen, 13/14 held-out, 0 permission violations |
| Usability | 6/6 tasks feasible (walkthrough); participant study **pending** |

Sources: [EVALUATION_REPORT.md](../evaluation/EVALUATION_REPORT.md) and `docs/evaluation/results/*.json`.

## 7. Performance observations

Measured on an AMD Ryzen 7 7445HS laptop (15.3 GB RAM, Docker VM 7.4 GB) with 126 source records:
- **Pipeline:** the full DAG run took ≈ 64 s, of which dbt was ≈ 51 s.
  - That time is **dominated by dbt start-up and Airflow task overhead** (≈ 1–1.5 s per task), not by data volume; extraction per entity was < 0.2 s.
- **Superset:** a chart query took ≈ 200 ms, mostly Superset's own processing; a full dashboard load took ≈ 4–4.4 s.
- **Django:** a KPI API call or assistant answer took ≈ 50–60 ms.
- **Memory:** the platform core (PostgreSQL, Superset, backend) uses ≈ 0.6 GB idle, plus Airflow ≈ 0.85 GB and both ERP sandboxes ≈ 0.65 GB.

**These numbers do not predict behaviour at enterprise volumes.** No load or concurrency tests were run.

## 8. Design decisions and trade-offs

| Decision | Benefit | Cost / trade-off |
|---|---|---|
| ELT with dbt in SQL | Transparent, tested, documented transformations | dbt start-up dominates small runs |
| Build–test–swap publication | Consumers never see untested data | Data is only as fresh as the last *successful* run (made visible by the stale flag) |
| Batch (daily) instead of streaming | Simple, reliable, enough for HR/finance KPIs | Not real-time (proposal's "real-time" interpreted as scheduled refresh) |
| Superset native authoring (no custom designer) | Mature features, no UI to maintain | Superset-specific concepts (e.g. "Apply filters") for users to learn |
| Registry-bounded AI | No SQL injection or hallucinated numbers; permissions outside the model | Only the questions the registry supports; the rules interpreter is phrasing-sensitive |
| Separate Superset and Django accounts | Each system enforces its own access | Two logins; roles kept in sync by tests |
| One PostgreSQL server | Simple on a laptop | Single point of failure (D11) |
| Superset cache off | Dashboards always current | ≈ 200 ms per query instead of a cache hit |
| Least-privilege containers and consumer accounts | Contained blast radius | More configuration to maintain |

Full records: [DECISIONS.md](../DECISIONS.md).

## 9. Limitations (state them honestly)

- **Data.** Sandboxes and synthetic data only; DrukSmart's real ERPs, data quality and volumes are untested.
- **AI.** Gemini is not verified; the deterministic interpreter's accuracy on new phrasings is 13/14 (small sample).
- **Users.** No real-user usability evaluation yet.
- **Security.** Prototype-grade: no HTTPS, no SSO, no login throttling at handover (D6, fixed in Milestone 10), the broad unused `bi_reader` (D7), and one database server (D11).
- **Business rules.** Open DrukSmart decisions DS-… use proposed defaults; ERPNext invoices have no branch (DS-AC-05).

## 10. Potential future enhancements

Listed in [TECHNICAL_DOCUMENTATION.md §16](../TECHNICAL_DOCUMENTATION.md):
- connect DrukSmart's ERPs;
- production hardening (HTTPS, SSO, HA database, scheduled backups, alerts);
- an LLM evaluation and multi-step questions;
- more KPIs;
- forecasting;
- a usability study;
- multi-tenancy.
