# Final engineering handover report

DrukSmart Analytics & AI Dashboard Platform. Group 8, CST. Handover after Milestone 9,
2026-10-25.

> **Verdict.**
> - **Working prototype:** a reproducibly deployable, extensively tested prototype for academic
>   demonstration and technical review.
> - **Not production-ready:** it is **not** enterprise-production-ready. It has only been verified
>   on local ERP sandboxes and synthetic data, on one laptop, without HTTPS, SSO, high availability,
>   load testing, a live LLM evaluation or a real-user study.

## 1. Fully implemented and verified

| Capability | Evidence (where to look) |
|---|---|
| Read-only Odoo 19 (JSON-2) and ERPNext 16 (REST) connectors with contracts, retries, paging and quarantine | live tests against the sandboxes (14); unit tests with fake APIs; `docs/connectors/` |
| Versioned, idempotent raw store with full source identity and extraction metadata | repeat runs add 0 versions (E2E); `ingestion/` |
| dbt warehouse: 43 models, Kimball star schemas with enforced grains, 164 data tests | every pipeline run; `docs/warehouse/WAREHOUSE.md` |
| KPIs HR-01..03 and AC-01..04 reproduce the **hand-calculated** synthetic results (both ERPs, every edge case) in dbt **and** the Django KPI service | `pytest -m warehouse` (19) |
| Airflow DAG: build–test–swap publication, retries, daily schedule, least-privilege container environment | 14 M8 runs + clean-start runs; `docs/orchestration/` |
| Superset dashboards (HR, Accounts): certified metrics, native filters, cross-filter, export, roles, branch RLS, freshness with age, configuration as code and asset export/import | `pytest -m superset` (44); browser checks per role; `docs/bi/SUPERSET.md` |
| Django KPI registry (8 functions) and bounded assistant with the **deterministic rules interpreter**: scope enforced before any query, no SQL path, stale and synthetic labelling, JSON error contract | `tests/backend` (128); evaluation 56/56 seen, **13/14 held-out**; `docs/backend/` |
| Cross-layer reconciliation: ERP figures = dbt = Superset = Django = AI result = AI answer text | 30/30 in every run, both stacks |
| End-to-end on the sandboxes with controlled business changes (hire/leave, partial and full payment, cancellations) | all deltas exact in 5 runs; EVALUATION_REPORT §4 |
| Reliability: ERP outage (temporary, permanent), broken model, failed data test, warehouse down, restarts, stale data | 8/8 scenarios; EVALUATION_REPORT §6 |
| Access control at the Superset, Django and database boundaries, incl. tampering | access matrix 115/115 |
| Compose deployment (profiles, health-checked order) and `deploy/druksmart.py` operations | unattended clean start in **515 s**; regression 12/12 on a fresh stack |
| Backup, restore-check and full restore | restore into a separate stack reproduced all counts, 30/30 |
| Synthetic fallback for demonstrations, labelled everywhere | values equal the hand-calculated fixtures; a no-ERP install falls back automatically (656 s) |
| Secrets handling | `.env` git-ignored; scan of 344 committable files found no secret values; container allowlists |

## 2. Implemented but incompletely tested

| Capability | What is missing |
|---|---|
| **Gemini** function-calling interpreter and LLM phrasing with number verification | Never called against the real API (no key). Only mocked-HTTP tests (16). Accuracy, latency and cost unknown |
| Dashboard Creator editing in Superset's native editor (save as, edit, new charts) | Permissions tested through the API; the drag/resize UI flow was not automated (manual checklist in `docs/bi/SUPERSET.md` §10) |
| Cross-filter clicks and CSV download through the UI | CSV download through the real UI automated once (usability walkthrough); cross-filter click not automated |
| Usability | Only an automated walkthrough (6/6 tasks feasible). **No participant sessions**: protocol and SUS sheet ready (`docs/evaluation/USABILITY.md`) |
| Performance | Measured on 126 source records on one laptop; **no load or concurrency tests** |
| Branch-manager access for ERPNext branches | ERPNext invoices have no branch (DS-AC-05), so Accounts is empty for them by design |

## 3. Simulated functionality (clearly labelled)

| Simulation | Purpose |
|---|---|
| Local **Odoo 19 / ERPNext 16 sandboxes** with synthetic companies, people and invoices | stand-in for DrukSmart's ERPs: real APIs and code paths, fictional data |
| **Synthetic fixtures** + `synthetic-erp` fake APIs (`source_mode=synthetic`, `druksmart_analytics_test`) | hand-calculated reference and demonstration fallback; labelled `synthetic` in Superset and in every answer |
| **Demo users** with shared local passwords | role testing only; never for a real deployment |
| **Controlled sandbox changes** (`evaluation/sandbox_changes.py`, tagged E2E-M8) | end-to-end evaluation; the sandboxes contain these extra records |

## 4. Not implemented

- Connection to **DrukSmart's real ERPs**, which needs their read-only API users and confirmation of the DS-… business decisions.
- **Production deployment features:**
  - HTTPS / reverse proxy and secure cookies;
  - single sign-on;
  - Django login throttling (D6), *since fixed in Milestone 10 Task 10.3*;
  - removing the unused broad `bi_reader` (D7);
  - separate or HA databases (D11);
  - scheduled off-site backups;
  - monitoring and alerting.
- **Analytics gaps:**
  - multi-step or comparative AI questions (trends, "vs last month", percentages);
  - Superset KPI for distinct employees on leave over a period (only in Django).
- **Scope excluded by design:** multi-tenant SaaS; other ERPs (SAP, Oracle, Dynamics); Sales, Finance and Inventory modules; real-time streaming; forecasting (optional, not started).
- **Missing reference document:** the proposal PDF (`docs/reference/Group8_DrukSmart.pdf`) is not in the repository. Please add it.

## 5. Future enhancements (prioritised)

1. Connect DrukSmart's ERPs (read-only users), confirm DS-HR-01..04 / DS-AC-01..08 / DS-ORG-01 / DS-SEC-01, and re-run the reconciliation and evaluation suites on real data.
2. Run the usability study (5–8 participants) and iterate on wording and filters.
3. Production hardening: HTTPS, SSO (OIDC) for Superset and Django, login throttling, managed/HA PostgreSQL with scheduled backups, alerts on failed runs and stale data, `bi_reader` removal.
4. Evaluate Gemini (or another LLM) with `evaluate_assistant --provider gemini` before enabling it; add comparison and trend questions.
5. More KPIs (turnover, DSO/DPO, leave balances), then forecasting (TimesFM) against simple baselines.

## 6. Handover package contents

| Item | Location |
|---|---|
| Source code | `connectors/`, `ingestion/`, `warehouse/`, `orchestration/`, `superset/`, `backend/`, `druksmart_common/` |
| Database initialisation | `infrastructure/postgres/init/`, `ingestion/migrations/` |
| Docker configuration | `compose.yaml`, `orchestration/docker/`, `superset/docker/`, `backend/docker/` (wheels git-ignored; see DEPLOYMENT.md §3) |
| dbt models / Airflow DAG | `warehouse/` / `orchestration/dags/` |
| Superset configuration and dashboards | `superset/definitions/`, `superset/assets/dashboards/` |
| Django backend and AI service | `backend/` |
| Automated tests and evaluation tools | `tests/`, `evaluation/` |
| Synthetic demonstration dataset | `tests/fixtures/synthetic/` (+ `expected_kpis.json`), `connectors/synthetic/` |
| Deployment and operations | `deploy/`, `docs/DEPLOYMENT.md` |
| Documentation | `README.md`, `docs/TECHNICAL_DOCUMENTATION.md`, `docs/USER_GUIDE.md`, `docs/DEMO_SCRIPT.md`, component docs |
| Evaluation evidence | `docs/evaluation/` (report, assessment, usability protocol, `results/*.json`, screenshots) |
| Academic material | `docs/academic/PROJECT_EVIDENCE.md` |
| Secrets | **not included**: `.env` is created per machine by `create_local_env.py`; `.env.example` documents every key |

## 7. Readiness by acceptance criterion

| # | Criterion | Status |
|---|---|---|
| 1 | Full prototype deployable reproducibly | Met: unattended clean start (515 s), plus a no-ERP variant |
| 2 | Core services start successfully | Met: all health checks pass after `setup` and after `stop`/`up` |
| 3 | End-to-end demonstration works | Met: 5 E2E runs; demo script with live and synthetic paths |
| 4 | Documentation matches the implemented system | Met: rewritten from the code and from measured results; links checked |
| 5 | Tests and limitations clearly recorded | Met: EVALUATION_REPORT, INTEGRATION_ASSESSMENT, this report |
| 6 | No credentials in the repository | Met: secret scan clean; `.env` git-ignored |
| 7 | Ready for technical review | Met: uncommitted. The team should commit and push to the private repository |
| 8 | Demonstration possible with a fallback dataset | Met: `demo-data synthetic` tested on a fresh stack |

## 8. Addendum: Milestone 10, the unified DrukSmart website (2026-10-25)

After this handover, the team clarified that the product must be **one custom website**. Milestone 10
delivered it. Details: [PROGRESS.md](PROGRESS.md), [web/](web/), ADR-040…043.

| Area | Status |
|---|---|
| Website (React + TypeScript, served by Django at `/app/`): Overview, HR/Accounts Analytics, Ask AI, Reports, Administration | **Working**: Vitest 97/97; Edge check 161/161 incl. a 12-step journey per role and a WCAG 2.1 AA audit |
| One sign-in (Django session + CSRF), throttling (fixes D6) | **Working**: 24 API tests, live check |
| Superset embedded with guest tokens; branch RLS decided by Django; signing secret required; framing limited to the website | **Working**: 17 API tests, 10 live tests; embedded values = KPI service for 4 roles |
| Dashboard authoring | Superset's native editor with a **separate Superset sign-in** (approved limitation); publishing a creator's dashboard tested live (4 tests) |
| Old assistant page | Redirects to the website (Decision 3) |
| Regression | 14/14 stages (three consecutive full runs) |
| Clean-start deployment with the website | unattended `setup --build` in 595 s; website check 161/161 on the fresh stack |

Still open: SSO for creators; a usability study of the website with real users; everything in §4
above (DrukSmart's real ERPs, production hardening, Gemini evaluation).
