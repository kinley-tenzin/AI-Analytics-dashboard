# DrukSmart Analytics & AI Dashboard Platform: engineering evaluation report (Milestone 8)

Group 8, College of Science and Technology, Royal University of Bhutan. Industry partner:
DrukSmart. The evaluation was run on 2026-10-25.

> **Scope of the evidence.**
> - **Data:** all results come from the local prototype using **local ERP sandboxes (Odoo 19,
>   ERPNext 16) with synthetic data**, plus the hand-calculated synthetic fixtures. DrukSmart's
>   real ERPs, data and users were not involved.
> - **Not production-ready:** passing these tests shows that the prototype works as designed on
>   this data and machine. It does **not** show production readiness, scalability or real-user
>   acceptance (see §11).

## 1. Testing objectives

| # | Objective (milestone task) | Main evidence |
|---|---|---|
| O1 | Find integration gaps and defects across all components (T1) | [INTEGRATION_ASSESSMENT.md](INTEGRATION_ASSESSMENT.md) |
| O2 | Demonstrate the complete workflow ERP → raw → dbt → warehouse → Airflow → Superset → Django AI (T2) | §4 end-to-end runs |
| O3 | Verify KPI correctness against independently calculated results, across ERPs and edge cases, and reconcile every layer (T3) | §5 |
| O4 | Show safe failure and recovery; never present stale or invalid data as new (T4) | §6 |
| O5 | Verify role and scope restrictions at the Superset, database and Django boundaries (T5) | §7 |
| O6 | Measure prototype performance with recorded environment and volumes (T6) | §8 |
| O7 | Prepare and pre-check a usability evaluation (T7) | §9, [USABILITY.md](USABILITY.md) |
| O8 | Provide a repeatable regression suite (T8) | §10 |

## 2. Test environment

| Item | Value |
|---|---|
| Machine | Reference laptop (Windows 11 Home 10.0.26200); CPU, RAM and container memory as measured in §8 |
| Container runtime | Docker Desktop (WSL2). Other coursework containers were also running during the measurements |
| Warehouse | PostgreSQL 17.11 (Docker), 127.0.0.1:5433 |
| Pipeline | Python 3.14.3 (host), Airflow 3.3.2 (LocalExecutor, Python 3.12 image), dbt Core 1.12.0 + dbt-postgres 1.11.0 |
| BI | Apache Superset 6.1.0 (+ psycopg2 2.9.9), own metadata PostgreSQL |
| Backend | Django 5.2.18 LTS (development server, 127.0.0.1:8000), rules interpreter (no LLM) |
| ERPs | Local sandboxes: Odoo 19.0 (127.0.0.1:8069), ERPNext/HRMS 16 (127.0.0.1:8090), synthetic data |
| Browser automation | Playwright 1.64.1 driving the installed Microsoft Edge (headless) |
| Data | Sandbox ERPs (126 current source records, 138 raw versions at measurement time) and the synthetic fixture batches (124 records incl. 7 invalid) |

## 3. Method and independence of expected results

Expected values never come from the code under test:

| Source of truth | What it is | Used for |
|---|---|---|
| **Hand-calculated fixtures** | `tests/fixtures/synthetic/expected_kpis.json`, calculated by hand in Milestone 2 and re-derived by an independent Python oracle (`tests/support/kpi_reference.py`) | warehouse and KPI-service correctness incl. every edge case (`pytest -m warehouse`) |
| **Source oracle** | `evaluation/source_oracle.py` reads the ERPs' **own** figures through their APIs: Odoo `amount_residual_signed`, ERPNext `outstanding_amount`, employee status, leave state. It does not use the connectors, raw tables or dbt | live reconciliation of every layer (`evaluation/reconcile.py`) |
| **Changes by construction** | `evaluation/sandbox_changes.py` makes business changes whose effect is known in advance (e.g. invoice 6,000 with 2,500 paid gives +3,500 receivables) | end-to-end deltas (`evaluation/e2e.py`) |
| **Fact-table references** | `backend/evaluation/references.py` queries the dbt fact tables as the pipeline role, not the KPI views the backend reads | AI assistant evaluation |

## 4. End-to-end workflow (Task 2)

**Procedure** (`python evaluation/e2e.py`, then `--post-fix` after the defect fixes):
1. Reconcile all layers (baseline).
2. Change the **sandbox ERPs** as a business user would.
3. Run the **real Airflow DAG** (`druksmart_elt`, configured mode: extract → raw → dbt → tests → publish).
4. Reconcile all layers against the source oracle again.
5. Check that each KPI changed by exactly the expected amount.
6. Query Superset the way a dashboard does and compare with a forced fresh query.
7. Count raw versions (a repeat run must add none).

The changes and their expected effects:

| Phase | Business change in the sandbox ERPs | Edge case exercised | Expected effect |
|---|---|---|---|
| A | Odoo: new employee in Sales | new record | headcount +1, Sales +1 |
| A | Odoo: invoice 6,000 (due in 30 days), **partial payment** 2,500 | partial payment | receivables +3,500 (not yet due) |
| A | Odoo: invoice 1,500 posted, then **cancelled** | cancellation | no change |
| A | ERPNext: approved 1-day leave for an employee **already on leave this month** | distinct-employee count | requests +1, days +1, employees +0 |
| A | ERPNext: supplier bill 4,000 (overdue), partial payment 1,500 | partial payment, overdue | payables +2,500, overdue AP +2,500 |
| B | Odoo: that employee **leaves** (archived, departure date) | source change of an existing record | headcount −1 |
| B | Odoo: the invoice is **paid in full** | settlement | receivables −3,500 |
| B | ERPNext: the leave application is **cancelled** | cancellation of a submitted document | requests −1, days −1 |
| repeat | none (same extraction again) | duplicate extraction | nothing changes, 0 new raw versions |
| C / D (after fixes) | Odoo: one more hire, then that person leaves | post-fix check of the pipeline and Superset freshness | headcount +1, then −1, visible **immediately** in Superset |

<!-- GENERATED:E2E -->
| Phase | Airflow run | State | Run time (s) | Raw versions | Reconciliation | Superset right after publish | Deltas as expected |
|---|---|---|---|---|---|---|---|
| phase_a | `m8_e2e_phase_a_0115` | success | 82.7 | 119 → 129 | 30/30 | STALE (previous values) | 8/8 |
| phase_b | `m8_e2e_phase_b_0115` | success | 81.3 | 129 → 135 | 30/30 | STALE (previous values) | 8/8 |
| repeat | `m8_e2e_repeat_0115` | success | 81.3 | 135 → 135 | 30/30 | current | 8/8 |

| KPI | phase_a | phase_b | repeat |
|---|---|---|---|
| headcount | 16 → 17 (exp +1, got +1) ✓ | 17 → 16 (exp -1, got -1) ✓ | 16 → 16 (exp +0, got +0) ✓ |
| receivable | 166,700.00 → 170,200.00 (exp +3500, got +3500) ✓ | 170,200.00 → 166,700.00 (exp -3500, got -3500) ✓ | 166,700.00 → 166,700.00 (exp +0, got +0) ✓ |
| payable | 35,200.00 → 37,700.00 (exp +2500, got +2500) ✓ | 37,700.00 → 37,700.00 (exp +0, got +0) ✓ | 37,700.00 → 37,700.00 (exp +0, got +0) ✓ |
| overdue_receivable | 149,700.00 → 149,700.00 (exp +0, got +0) ✓ | 149,700.00 → 149,700.00 (exp +0, got +0) ✓ | 149,700.00 → 149,700.00 (exp +0, got +0) ✓ |
| overdue_payable | 29,200.00 → 31,700.00 (exp +2500, got +2500) ✓ | 31,700.00 → 31,700.00 (exp +0, got +0) ✓ | 31,700.00 → 31,700.00 (exp +0, got +0) ✓ |
| approved_leave_requests | 6 → 7 (exp +1, got +1) ✓ | 7 → 6 (exp -1, got -1) ✓ | 6 → 6 (exp +0, got +0) ✓ |
| approved_leave_days | 11 → 12 (exp +1, got +1) ✓ | 12 → 11 (exp -1, got -1) ✓ | 11 → 11 (exp +0, got +0) ✓ |
| approved_leave_employees | 4 → 4 (exp +0, got +0) ✓ | 4 → 4 (exp +0, got +0) ✓ | 4 → 4 (exp +0, got +0) ✓ |
<!-- /GENERATED:E2E -->

**"STALE (previous values)"** in phases A and B is defect **D2**. Right after a successful
publication, the query a Superset dashboard uses still returned the previous publication's numbers
(16 instead of 17 employees, 166,700.00 instead of 170,200.00) because of its 5-minute data cache.
The warehouse, Django and the AI already showed the new values. The repeat run shows "current" only
because nothing changed.

**After the defect fixes (D1 restricted Airflow environment, D2 Superset cache off):**

<!-- GENERATED:E2E_POST_FIX -->
| Phase | Airflow run | State | Run time (s) | Raw versions | Reconciliation | Superset right after publish | Deltas as expected |
|---|---|---|---|---|---|---|---|
| phase_c | `m8_e2e_phase_c_0129` | success | 80.1 | 135 → 137 | 30/30 | current | 8/8 |
| phase_d | `m8_e2e_phase_d_0129` | success | 80.5 | 137 → 138 | 30/30 | current | 8/8 |

| KPI | phase_c | phase_d |
|---|---|---|
| headcount | 16 → 17 (exp +1, got +1) ✓ | 17 → 16 (exp -1, got -1) ✓ |
| receivable | 166,700.00 → 166,700.00 (exp +0, got +0) ✓ | 166,700.00 → 166,700.00 (exp +0, got +0) ✓ |
| payable | 37,700.00 → 37,700.00 (exp +0, got +0) ✓ | 37,700.00 → 37,700.00 (exp +0, got +0) ✓ |
| overdue_receivable | 149,700.00 → 149,700.00 (exp +0, got +0) ✓ | 149,700.00 → 149,700.00 (exp +0, got +0) ✓ |
| overdue_payable | 31,700.00 → 31,700.00 (exp +0, got +0) ✓ | 31,700.00 → 31,700.00 (exp +0, got +0) ✓ |
| approved_leave_requests | 6 → 6 (exp +0, got +0) ✓ | 6 → 6 (exp +0, got +0) ✓ |
| approved_leave_days | 11 → 11 (exp +0, got +0) ✓ | 11 → 11 (exp +0, got +0) ✓ |
| approved_leave_employees | 4 → 4 (exp +0, got +0) ✓ | 4 → 4 (exp +0, got +0) ✓ |
<!-- /GENERATED:E2E_POST_FIX -->

The approved natural-language questions were answered by the assistant in every phase with the
same values as every other layer (§5). Example answers after phase B: see
`docs/evaluation/results/e2e.json` → `ai_answers`.

## 5. Data correctness (Task 3)

### 5.1 Hand-calculated expected results (synthetic fixtures, both ERPs, two snapshot dates)

`pytest -m warehouse` (19 tests) replays the synthetic extraction batches through the **real
connectors and runner**, builds all dbt models and data tests, and compares them with the
hand-calculated expected results. Since this milestone it also runs the **Django KPI service** on
the same marts.

| KPI | Expected (hand-calculated) | Warehouse | Django KPI service |
|---|---|---|---|
| HR-01 active headcount 2026-10-31 | 16 (Odoo 9, ERPNext 7), plus by branch | ✓ equal | ✓ equal (16) |
| HR-01 alternative policy (employee/worker only) | Odoo 7 | ✓ | not applicable |
| HR-02 headcount by department (11 departments, same names kept apart) | per department key | ✓ | ✓ (totals) |
| HR-03 approved leave Oct 2026 | 7 requests, 13.5 days, 5 employees | ✓ | ✓ |
| AC-01 / AC-02 outstanding AR / AP, 2026-09-30 and 2026-10-31 | per instance and total | ✓ | ✓ |
| AC-03 overdue AR / AP, both dates | per instance | ✓ | ✓ |
| AC-04 ageing, every bucket incl. unapplied credit, both dates and ledgers | per bucket | ✓ | ✓ |
| Unallocated advances kept apart from receivables; invoice totals ≠ outstanding | | ✓ | not applicable |
| 7 invalid source records quarantined, never in marts; snapshots only for extracted dates | | ✓ | not applicable |

The fixture edge cases cover:
- active, left, archived, suspended and future joiners;
- same-name people across ERPs (not merged);
- duplicate department names;
- approved, pending, refused, cancelled, unsubmitted, half-day and month-spanning leave;
- paid, unpaid, **partially paid**, draft, **cancelled with a stale balance**, reversed and foreign-currency invoices;
- applied and unapplied credit notes;
- draft→posted and paid **between batches**;
- incremental batches without unchanged records.

### 5.2 Live reconciliation across all layers (sandbox ERPs)

`python evaluation/reconcile.py` compares, for the latest snapshot:
- the source ERPs;
- dbt facts;
- Superset certified metrics;
- the Django KPI API;
- the AI assistant's structured result;
- the number **written in the AI answer text**.

It covers 11 KPIs, plus per-ERP figures for both ERPs. Baseline before any change:

<!-- GENERATED:RECONCILIATION_BASELINE -->
As of 2026-10-25 (publication 7, run `m7_kpi_service_1`): **30/30 checks passed**.

| KPI | Source ERPs (oracle) | dbt facts | Superset | Django API | AI answer | Result |
|---|---|---|---|---|---|---|
| headcount | 16 | 16 | 16 | 16 | 16 | PASS |
| receivable | 166,700.00 | 166,700.00 | 166,700.00 | 166700 | 166700 | PASS |
| payable | 35,200.00 | 35,200.00 | 35,200.00 | 35200 | 35200 | PASS |
| overdue_receivable | 149,700.00 | 149,700.00 | 149,700.00 | 149700 | 149700 | PASS |
| overdue_payable | 29,200.00 | 29,200.00 | 29,200.00 | 29200 | 29200 | PASS |
| headcount_by_department | Administration: 1; Finance & Accounts: 3; Management: 1; Sales: 5; Warehouse: 1; Operations: 2; Accounts: 1; Human Resources: 1; Unassigned: 1 | Finance & Accounts: 3; Warehouse: 1; Operations: 2; Sales: 5; Administration: 1; Management: 1; Unassigned: 1; Human Resources: 1; Accounts: 1 | Accounts: 1; Operations: 2; Administration: 1; Human Resources: 1; Warehouse: 1; Management: 1; Unassigned: 1; Finance & Accounts: 3; Sales: 5 | Accounts: 1; Administration: 1; Finance & Accounts: 3; Human Resources: 1; Management: 1; Operations: 2; Sales: 5; Unassigned: 1; Warehouse: 1 | Accounts: 1; Administration: 1; Finance & Accounts: 3; Human Resources: 1; Management: 1; Operations: 2; Sales: 5; Unassigned: 1; Warehouse: 1 | PASS |
| approved_leave_employees | 4 | 4 | n/a | 4 | 4 | PASS |
| approved_leave_requests | 6 | 6 | 6 | 6 | 6 | PASS |
| approved_leave_days | 11 | 11 | 11 | 11 | 11 | PASS |
| ageing_all_buckets | payable|1_30: 29,200.00; payable|unapplied_credit: -1,000.00; receivable|1_30: 124,200.00; receivable|31_60: 18,000.00; receivable|91_plus: 7,500.00; receivable|unapplied_credit: -5,000.00; payable|not_due: 7,000.00; receivable|not_due: 22,000.00 | payable|1_30: 29,200.00; receivable|unapplied_credit: -5,000.00; receivable|91_plus: 7,500.00; payable|unapplied_credit: -1,000.00; receivable|31_60: 18,000.00; receivable|1_30: 124,200.00; receivable|not_due: 22,000.00; payable|not_due: 7,000.00 | receivable|not_due: 22,000.00; payable|not_due: 7,000.00; receivable|1_30: 124,200.00; payable|1_30: 29,200.00; receivable|31_60: 18,000.00; receivable|unapplied_credit: -5,000.00; payable|unapplied_credit: -1,000.00; receivable|91_plus: 7,500.00 | n/a | n/a | PASS |
| overdue_by_ageing | payable|1 1-30 days overdue: 29,200.00; receivable|1 1-30 days overdue: 124,200.00; receivable|2 31-60 days overdue: 18,000.00; receivable|4 Over 90 days overdue: 7,500.00 | payable|1 1-30 days overdue: 29,200.00; receivable|4 Over 90 days overdue: 7,500.00; receivable|2 31-60 days overdue: 18,000.00; receivable|1 1-30 days overdue: 124,200.00 | n/a | payable|1 1-30 days overdue: 29200; receivable|1 1-30 days overdue: 124200; receivable|2 31-60 days overdue: 18000; receivable|4 Over 90 days overdue: 7500 | payable|1 1-30 days overdue: 29200; receivable|1 1-30 days overdue: 124200; receivable|2 31-60 days overdue: 18000; receivable|4 Over 90 days overdue: 7500 | PASS |
| odoo-sandbox:headcount | 10 | 10 | 10 | n/a | n/a | PASS |
| odoo-sandbox:receivable | 101,500.00 | 101,500.00 | 101,500.00 | n/a | n/a | PASS |
| odoo-sandbox:payable | 24,200.00 | 24,200.00 | 24,200.00 | n/a | n/a | PASS |
| odoo-sandbox:overdue_receivable | 103,500.00 | 103,500.00 | 103,500.00 | n/a | n/a | PASS |
| odoo-sandbox:overdue_payable | 25,200.00 | 25,200.00 | 25,200.00 | n/a | n/a | PASS |
| odoo-sandbox:ageing | payable|1_30: 25,200.00; payable|unapplied_credit: -1,000.00; receivable|1_30: 88,000.00; receivable|31_60: 8,000.00; receivable|91_plus: 7,500.00; receivable|unapplied_credit: -2,000.00 | payable|1_30: 25,200.00; receivable|unapplied_credit: -2,000.00; receivable|91_plus: 7,500.00; payable|unapplied_credit: -1,000.00; receivable|31_60: 8,000.00; receivable|1_30: 88,000.00 | payable|1_30: 25,200.00; receivable|unapplied_credit: -2,000.00; payable|unapplied_credit: -1,000.00; receivable|31_60: 8,000.00; receivable|91_plus: 7,500.00; receivable|1_30: 88,000.00 | n/a | n/a | PASS |
| odoo-sandbox:leave_requests | 3 | 3 | 3 | n/a | n/a | PASS |
| erpnext-sandbox:headcount | 6 | 6 | 6 | n/a | n/a | PASS |
| erpnext-sandbox:receivable | 65,200.00 | 65,200.00 | 65,200.00 | n/a | n/a | PASS |
| erpnext-sandbox:payable | 11,000.00 | 11,000.00 | 11,000.00 | n/a | n/a | PASS |
| erpnext-sandbox:overdue_receivable | 46,200.00 | 46,200.00 | 46,200.00 | n/a | n/a | PASS |
| erpnext-sandbox:overdue_payable | 4,000.00 | 4,000.00 | 4,000.00 | n/a | n/a | PASS |
| erpnext-sandbox:ageing | payable|1_30: 4,000.00; payable|not_due: 7,000.00; receivable|1_30: 36,200.00; receivable|31_60: 10,000.00; receivable|not_due: 22,000.00; receivable|unapplied_credit: -3,000.00 | receivable|not_due: 22,000.00; receivable|1_30: 36,200.00; payable|1_30: 4,000.00; receivable|31_60: 10,000.00; payable|not_due: 7,000.00; receivable|unapplied_credit: -3,000.00 | receivable|not_due: 22,000.00; payable|not_due: 7,000.00; receivable|1_30: 36,200.00; payable|1_30: 4,000.00; receivable|31_60: 10,000.00; receivable|unapplied_credit: -3,000.00 | n/a | n/a | PASS |
| erpnext-sandbox:leave_requests | 3 | 3 | 3 | n/a | n/a | PASS |

AI answer text contains the source value: headcount ✓, receivable ✓, payable ✓, overdue_receivable ✓, leave_employees ✓
<!-- /GENERATED:RECONCILIATION_BASELINE -->

Every one of the 5 subsequent DAG runs (phases A, B, repeat, C, D) reconciled 30/30 (§4).
**No discrepancy was found between layers.** The only data-display discrepancy was Superset's cache
(D2, §4), which concerned *when* new values appear, not *what* they are; it was fixed.

## 6. Reliability and recovery (Task 4)

`python evaluation/reliability.py` injects one fault at a time into the local environment:
- stops sandbox containers or the warehouse;
- adds a broken dbt model or a failing data test as a temporary file;
- restarts services;
- lowers the stale threshold.

It then removes the fault and checks recovery. Earlier pipeline-only scenarios from Milestone 5
(malformed and quarantined records, failing relationship test, repeated runs) are in
[ORCHESTRATION.md §8](../orchestration/ORCHESTRATION.md). The duplicate-extraction check is part of §4.

<!-- GENERATED:RELIABILITY -->
| Scenario | Fault injected | Expected | Observed | Result |
|---|---|---|---|---|
| erp_temporary_failure | Odoo sandbox container stopped at run start; restarted after the first failed attempt | validate_odoo_source fails, is retried automatically, run succeeds and publishes | {"up_for_retry_seen": true, "run_state": "success", "validate_odoo_final_state": "success", "publication_before": 14, "publication_after": 15} | PASS |
| erp_outage_beyond_retries | ERPNext sandbox backend stopped for the whole run | run fails after retries; no publication; consumers keep the previous, correctly dated data | {"run_state": "failed", "task_states": {"dbt_build_marts": "upstream_failed", "dbt_staging_intermediate": "upstream_failed", "dbt_test_marts": "upstream_failed", "extract_load_erpnext_accounts": "upstream_failed", "extract_load_erpnext_hr": "upstream_failed", "extract_load_odoo_accounts": "upstream_failed", "extract_load_odoo_hr": "upstream_failed", "prepare_raw_schema": "upstream_failed", "publis | PASS |
| failed_transformation | a staging model with invalid SQL is added to the dbt project | dbt_staging_intermediate fails; nothing downstream runs; no publication | {"run_state": "failed", "failing_task": "dbt_staging_intermediate", "failing_task_state": "failed", "publish_state": "upstream_failed", "publication_unchanged": true, "freshness_unchanged": true} | PASS |
| failed_data_quality | a data-quality test that always fails is added | marts are built in marts_build but dbt_test_marts fails; NOT published | {"run_state": "failed", "failing_task": "dbt_test_marts", "failing_task_state": "failed", "publish_state": "upstream_failed", "publication_unchanged": true, "freshness_unchanged": true} | PASS |
| recovery_run | none (recovery after the previous scenarios) | run succeeds, publishes, all layers reconcile | {"run_state": "success", "publication_before": 13, "publication_after": 14, "reconciliation": "30/30"} | PASS |
| database_unavailable | warehouse PostgreSQL container stopped while Superset and Django run | Django readiness 503 and an explicit 'error' answer without numbers; Superset query error; both recover automatically when PostgreSQL is back | {"django_ready_status": 503, "django_answer_status": "error", "django_answer_http_json": true, "django_answer_text": "The service's database is not reachable right now. Try again later.", "django_answer_has_number": false, "superset_query_http": 400, "superset_returned_data": false, "django_recovered": true, "superset_recovered": true} | PASS |
| service_restarts | restart of Django (new process), Superset and the Airflow services | logged-in Django session survives; Superset/Airflow come back; reconciliation unchanged | {"django_session_survived": true, "same_answer": true, "superset_healthy": true, "airflow_history_available": true, "reconciliation": "30/30"} | PASS |
| stale_data_flagged | staleness threshold lowered to 3.6 s, so the current publication counts as old | answer still shows the value but states it is not current; readiness 503 (stale) | {"result_stale": true, "answer": "There are 16 active employees as of 25 October 2026. WARNING: this data is not current. The last validated publication was 0 hours ago; the scheduled refresh may have failed.", "ready_status": 503, "ready_warehouse": {"ok": false, "data_as_of": {"accounts": "2026-10-25", "hr": "2026-10-25"}, "oldest_publication": "2026-10-24T19:53:10.541Z", "hours_since_publicatio | PASS |
<!-- /GENERATED:RELIABILITY -->

## 7. Access control (Task 5)

`python evaluation/access_matrix.py` attempts every access path for every demo role at the three
boundaries:
- **Superset:** datasets, chart data, CSV export, RLS, SQL Lab, registering datasets.
- **Django:** KPI API and AI per domain, tampered parameters, attempts to widen the branch scope.
- **Database:** the consumer accounts directly against raw, staging and dimension tables, plus writes.

The pytest suites cover the same boundaries in more depth: `-m superset` (44 tests), `tests/backend` (128), `-m db`.

<!-- GENERATED:ACCESS -->
**115/115 access checks behaved as the policy requires.**

| User | Boundary | Resource | Attempt | Expected | Actual | Result |
|---|---|---|---|---|---|---|
| demo_hr | Superset | kpi_headcount | dataset listed | True | True | PASS |
| demo_hr | Superset | kpi_headcount | chart data | allowed | allowed | PASS |
| demo_hr | Superset | kpi_headcount | CSV export | allowed | allowed | PASS |
| demo_hr | Superset | kpi_approved_leave_monthly | dataset listed | True | True | PASS |
| demo_hr | Superset | kpi_approved_leave_monthly | chart data | allowed | allowed | PASS |
| demo_hr | Superset | kpi_approved_leave_monthly | CSV export | allowed | allowed | PASS |
| demo_hr | Superset | kpi_receivables_payables | dataset listed | False | False | PASS |
| demo_hr | Superset | kpi_receivables_payables | chart data | denied | denied | PASS |
| demo_hr | Superset | kpi_receivables_payables | CSV export | denied | denied | PASS |
| demo_hr | Superset | SQL Lab | execute SQL | denied | denied | PASS |
| demo_hr | Superset | marts.dim_employee | register new dataset | denied | denied | PASS |
| demo_hr | Django | hr KPI API | run KPI function | allowed | allowed | PASS |
| demo_hr | Django | hr AI question | ask | answered | answered | PASS |
| demo_hr | Django | accounts KPI API | run KPI function | denied | denied | PASS |
| demo_hr | Django | accounts AI question | ask | forbidden | forbidden | PASS |
| demo_hr | Django | KPI API | tampered: SQL in a parameter | rejected | rejected | PASS |
| demo_hr | Django | KPI API | tampered: unknown function | rejected | rejected | PASS |
| demo_hr | Django | KPI API | tampered: filter on a non-filter column | rejected | rejected | PASS |
| demo_hr | Django | KPI API | tampered: SQL injection in a filter value | rejected | rejected | PASS |
| demo_hr | Django | KPI API | tampered: as_of injection | rejected | rejected | PASS |
| demo_accounts | Superset | kpi_headcount | dataset listed | False | False | PASS |
| demo_accounts | Superset | kpi_headcount | chart data | denied | denied | PASS |
| demo_accounts | Superset | kpi_headcount | CSV export | denied | denied | PASS |
| demo_accounts | Superset | kpi_approved_leave_monthly | dataset listed | False | False | PASS |
| demo_accounts | Superset | kpi_approved_leave_monthly | chart data | denied | denied | PASS |
| demo_accounts | Superset | kpi_approved_leave_monthly | CSV export | denied | denied | PASS |
| demo_accounts | Superset | kpi_receivables_payables | dataset listed | True | True | PASS |
| demo_accounts | Superset | kpi_receivables_payables | chart data | allowed | allowed | PASS |
| demo_accounts | Superset | kpi_receivables_payables | CSV export | allowed | allowed | PASS |
| demo_accounts | Superset | SQL Lab | execute SQL | denied | denied | PASS |
| demo_accounts | Superset | marts.dim_employee | register new dataset | denied | denied | PASS |
| demo_accounts | Django | hr KPI API | run KPI function | denied | denied | PASS |
| demo_accounts | Django | hr AI question | ask | forbidden | forbidden | PASS |
| demo_accounts | Django | accounts KPI API | run KPI function | allowed | allowed | PASS |
| demo_accounts | Django | accounts AI question | ask | answered | answered | PASS |
| demo_accounts | Django | KPI API | tampered: SQL in a parameter | rejected | rejected | PASS |
| demo_accounts | Django | KPI API | tampered: unknown function | rejected | rejected | PASS |
| demo_accounts | Django | KPI API | tampered: filter on a non-filter column | rejected | rejected | PASS |
| demo_accounts | Django | KPI API | tampered: SQL injection in a filter value | rejected | rejected | PASS |
| demo_accounts | Django | KPI API | tampered: as_of injection | rejected | rejected | PASS |
| demo_executive | Superset | kpi_headcount | dataset listed | True | True | PASS |
| demo_executive | Superset | kpi_headcount | chart data | allowed | allowed | PASS |
| demo_executive | Superset | kpi_headcount | CSV export | allowed | allowed | PASS |
| demo_executive | Superset | kpi_approved_leave_monthly | dataset listed | True | True | PASS |
| demo_executive | Superset | kpi_approved_leave_monthly | chart data | allowed | allowed | PASS |
| demo_executive | Superset | kpi_approved_leave_monthly | CSV export | allowed | allowed | PASS |
| demo_executive | Superset | kpi_receivables_payables | dataset listed | True | True | PASS |
| demo_executive | Superset | kpi_receivables_payables | chart data | allowed | allowed | PASS |
| demo_executive | Superset | kpi_receivables_payables | CSV export | allowed | allowed | PASS |
| demo_executive | Superset | SQL Lab | execute SQL | denied | denied | PASS |
| demo_executive | Superset | marts.dim_employee | register new dataset | denied | denied | PASS |
| demo_executive | Django | hr KPI API | run KPI function | allowed | allowed | PASS |
| demo_executive | Django | hr AI question | ask | answered | answered | PASS |
| demo_executive | Django | accounts KPI API | run KPI function | allowed | allowed | PASS |
| demo_executive | Django | accounts AI question | ask | answered | answered | PASS |
| demo_executive | Django | KPI API | tampered: SQL in a parameter | rejected | rejected | PASS |
| demo_executive | Django | KPI API | tampered: unknown function | rejected | rejected | PASS |
| demo_executive | Django | KPI API | tampered: filter on a non-filter column | rejected | rejected | PASS |
| demo_executive | Django | KPI API | tampered: SQL injection in a filter value | rejected | rejected | PASS |
| demo_executive | Django | KPI API | tampered: as_of injection | rejected | rejected | PASS |
| demo_creator | Superset | kpi_headcount | dataset listed | True | True | PASS |
| demo_creator | Superset | kpi_headcount | chart data | allowed | allowed | PASS |
| demo_creator | Superset | kpi_headcount | CSV export | allowed | allowed | PASS |
| demo_creator | Superset | kpi_approved_leave_monthly | dataset listed | True | True | PASS |
| demo_creator | Superset | kpi_approved_leave_monthly | chart data | allowed | allowed | PASS |
| demo_creator | Superset | kpi_approved_leave_monthly | CSV export | allowed | allowed | PASS |
| demo_creator | Superset | kpi_receivables_payables | dataset listed | True | True | PASS |
| demo_creator | Superset | kpi_receivables_payables | chart data | allowed | allowed | PASS |
| demo_creator | Superset | kpi_receivables_payables | CSV export | allowed | allowed | PASS |
| demo_creator | Superset | SQL Lab | execute SQL | denied | denied | PASS |
| demo_creator | Superset | marts.dim_employee | register new dataset | denied | denied | PASS |
| demo_creator | Django | hr KPI API | run KPI function | allowed | allowed | PASS |
| demo_creator | Django | hr AI question | ask | answered | answered | PASS |
| demo_creator | Django | accounts KPI API | run KPI function | allowed | allowed | PASS |
| demo_creator | Django | accounts AI question | ask | answered | answered | PASS |
| demo_creator | Django | KPI API | tampered: SQL in a parameter | rejected | rejected | PASS |
| demo_creator | Django | KPI API | tampered: unknown function | rejected | rejected | PASS |
| demo_creator | Django | KPI API | tampered: filter on a non-filter column | rejected | rejected | PASS |
| demo_creator | Django | KPI API | tampered: SQL injection in a filter value | rejected | rejected | PASS |
| demo_creator | Django | KPI API | tampered: as_of injection | rejected | rejected | PASS |
| demo_branch | Superset | kpi_headcount | dataset listed | True | True | PASS |
| demo_branch | Superset | kpi_headcount | chart data | allowed | allowed | PASS |
| demo_branch | Superset | kpi_headcount | rows limited to own branch (RLS) | True | True | PASS |
| demo_branch | Superset | kpi_headcount | CSV export | allowed | allowed | PASS |
| demo_branch | Superset | kpi_approved_leave_monthly | dataset listed | True | True | PASS |
| demo_branch | Superset | kpi_approved_leave_monthly | chart data | allowed | allowed | PASS |
| demo_branch | Superset | kpi_approved_leave_monthly | CSV export | allowed | allowed | PASS |
| demo_branch | Superset | kpi_receivables_payables | dataset listed | True | True | PASS |
| demo_branch | Superset | kpi_receivables_payables | chart data | allowed | allowed | PASS |
| demo_branch | Superset | kpi_receivables_payables | rows limited to own branch (RLS) | True | True | PASS |
| demo_branch | Superset | kpi_receivables_payables | CSV export | allowed | allowed | PASS |
| demo_branch | Superset | SQL Lab | execute SQL | denied | denied | PASS |
| demo_branch | Superset | marts.dim_employee | register new dataset | denied | denied | PASS |
| demo_branch | Django | hr KPI API | run KPI function | allowed | allowed | PASS |
| demo_branch | Django | hr AI question | ask | answered | answered | PASS |
| demo_branch | Django | accounts KPI API | run KPI function | allowed | allowed | PASS |
| demo_branch | Django | accounts AI question | ask | answered | answered | PASS |
| demo_branch | Django | KPI API | tampered: SQL in a parameter | rejected | rejected | PASS |
| demo_branch | Django | KPI API | tampered: unknown function | rejected | rejected | PASS |
| demo_branch | Django | KPI API | tampered: filter on a non-filter column | rejected | rejected | PASS |
| demo_branch | Django | KPI API | tampered: SQL injection in a filter value | rejected | rejected | PASS |
| demo_branch | Django | KPI API | tampered: as_of injection | rejected | rejected | PASS |
| demo_branch | Django | branch scope | widen scope via other branch | denied | denied | PASS |
| demo_branch | Django | branch scope | widen scope via other organisation | denied | denied | PASS |
| demo_branch | Django | branch scope | group by branch shows only own branch | True | True | PASS |
| superset_reader | Database | raw.source_record | select | denied | denied | PASS |
| superset_reader | Database | staging.stg_odoo__hr_employee | select | denied | denied | PASS |
| superset_reader | Database | marts.dim_employee | select | denied | denied | PASS |
| superset_reader | Database | marts.dim_customer | select | denied | denied | PASS |
| superset_reader | Database | marts.data_freshness | insert | denied | denied | PASS |
| kpi_reader | Database | raw.source_record | select | denied | denied | PASS |
| kpi_reader | Database | staging.stg_odoo__hr_employee | select | denied | denied | PASS |
| kpi_reader | Database | marts.dim_employee | select | denied | denied | PASS |
| kpi_reader | Database | marts.dim_customer | select | denied | denied | PASS |
| kpi_reader | Database | marts.data_freshness | insert | denied | denied | PASS |
<!-- /GENERATED:ACCESS -->

Where each protection is enforced:

| Protection | Superset | Django | Database |
|---|---|---|---|
| Domain (HR / Accounts) separation | dataset permissions per role, `DASHBOARD_RBAC` | scope check before any query | — |
| Branch restriction | RLS rule (`branch_key IN …`), also on CSV export | `branch_key = ANY(%s)` always added; out-of-scope filters forbidden | — |
| No raw / personal data | only 4 approved datasets registered | registry allowlist; aggregates only | `superset_reader` / `kpi_reader` SELECT on approved relations only |
| No writes, no arbitrary SQL | no SQL Lab for DrukSmart roles; DML off | no SQL path; parameters bound | read-only sessions; no INSERT grants |

## 8. Performance (Task 6)

`python evaluation/performance.py` gives the following measured values. Small data; local machine
shared with other containers.

<!-- GENERATED:PERFORMANCE -->
Measured 2026-10-25T02:03:43. Environment: AMD Ryzen 7 7445HS w/ Radeon 740M Graphics, 12 logical CPUs, 15.3 GB RAM, Windows-11-10.0.26200-SP0, Docker 29.7.2, 22 containers running (incl. ERP sandboxes and unrelated coursework containers).

Data volume: 126 current source records (138 raw versions); mart rows: fct_headcount_snapshot: 82; fct_leave_request: 13; fct_accounting_document: 25; fct_payment: 12; fct_receivable_payable_snapshot: 57; kpi_headcount: 68; kpi_receivables_payables: 48.

**Pipeline (full refresh, Airflow, seconds):**

| Step | n | min | p50 | max |
|---|---|---|---|---|
| **whole DAG run** | 3 | 64.3 | 64.4 | 66.5 |
| dbt_build_marts | 3 | 16.1 | 16.4 | 16.7 |
| dbt_staging_intermediate | 3 | 21.6 | 22.1 | 22.1 |
| dbt_test_marts | 3 | 12.3 | 12.7 | 12.8 |
| extract_load_erpnext_accounts | 3 | 1.6 | 1.7 | 2.5 |
| extract_load_erpnext_hr | 3 | 1.5 | 1.5 | 1.6 |
| extract_load_odoo_accounts | 3 | 1.5 | 1.5 | 1.5 |
| extract_load_odoo_hr | 3 | 1.5 | 1.5 | 1.6 |
| prepare_raw_schema | 3 | 1.1 | 1.1 | 1.5 |
| publish_validated_marts | 3 | 1.1 | 1.3 | 1.6 |
| report_published_state | 3 | 1.9 | 2.0 | 2.1 |
| validate_erpnext_source | 3 | 1.6 | 1.7 | 1.7 |
| validate_odoo_source | 3 | 1.5 | 1.5 | 1.6 |

**Extraction per entity (last full-refresh run):**

| Entity | Records | Seconds |
|---|---|---|
| erpnext.Branch | 2 | 0.03 |
| erpnext.Company | 1 | 0.04 |
| erpnext.Customer | 3 | 0.05 |
| erpnext.Department | 14 | 0.04 |
| erpnext.Employee | 9 | 0.04 |
| erpnext.Leave Application | 7 | 0.03 |
| erpnext.Payment Entry | 6 | 0.17 |
| erpnext.Purchase Invoice | 4 | 0.03 |
| erpnext.Sales Invoice | 8 | 0.04 |
| erpnext.Supplier | 2 | 0.03 |
| odoo.account.move | 13 | 0.05 |
| odoo.account.payment | 6 | 0.07 |
| odoo.hr.department | 6 | 0.04 |
| odoo.hr.employee | 13 | 0.06 |
| odoo.hr.leave | 6 | 0.04 |
| odoo.res.company | 2 | 0.04 |
| odoo.res.partner | 24 | 0.07 |

**Query latency (ms):**

| Request | n | p50 | p95 | max |
|---|---|---|---|---|
| Superset chart data: headcount_total | 30 | 197.1 | 216.9 | 303.9 |
| Superset chart data: headcount_by_department | 30 | 206.9 | 258.0 | 539.0 |
| Superset chart data: receivables_total | 30 | 207.0 | 321.6 | 345.9 |
| Superset chart data: ageing_by_ledger | 30 | 222.3 | 301.5 | 331.7 |
| Superset chart data: leave_by_month | 30 | 216.3 | 267.0 | 504.9 |
| Superset dashboard full load in browser: druksmart-hr | 5 | 4417.7 | 4914.5 | 4914.5 |
| Superset dashboard full load in browser: druksmart-accounts | 5 | 3970.4 | 4124.9 | 4124.9 |
| Django KPI API: hr.active_headcount | 30 | 55.7 | 71.7 | 75.1 |
| Django KPI API: hr.active_headcount by department | 30 | 52.7 | 67.1 | 71.2 |
| Django KPI API: hr.employment_status | 30 | 44.6 | 66.4 | 69.5 |
| Django KPI API: hr.approved_leave | 30 | 49.9 | 59.3 | 62.9 |
| Django KPI API: ac.outstanding_receivables | 30 | 47.5 | 63.1 | 64.0 |
| Django KPI API: ac.outstanding_payables | 30 | 53.8 | 75.3 | 81.8 |
| Django KPI API: ac.overdue_balance | 30 | 53.9 | 67.4 | 91.3 |
| Django KPI API: ac.overdue_by_ageing | 30 | 51.9 | 66.0 | 66.8 |
| AI assistant (rules): How many active employees are there? | 15 | 53.9 | 69.7 | 82.8 |
| AI assistant (rules): How many employees work in each department? | 15 | 53.9 | 62.4 | 74.9 |
| AI assistant (rules): How many employees are on approved leave? | 15 | 55.0 | 74.0 | 75.1 |
| AI assistant (rules): What is the outstanding receivables balance? | 15 | 58.2 | 66.0 | 70.1 |
| AI assistant (rules): What is the outstanding payables balance? | 15 | 47.0 | 66.7 | 81.0 |
| AI assistant (rules): How much is overdue? | 15 | 54.4 | 63.6 | 69.8 |
| AI assistant (rules): Show overdue balances by ageing category. | 15 | 61.9 | 110.9 | 116.9 |
<!-- /GENERATED:PERFORMANCE -->

## 9. Usability (Task 7)

Method, task cards, questionnaire and recording sheet are in [USABILITY.md](USABILITY.md).
**No participant sessions have been run.** The automated walkthrough below only shows that each task
can be completed through the real UI by the intended role, and that the user would see the correct
number:

<!-- GENERATED:USABILITY -->
| Task | Role / UI | Expert-path user actions | Shown in UI | Expected | Completed |
|---|---|---|---|---|---|
| T1 Find the current HR headcount | HR Viewer · Superset HR dashboard | 5 | 16 | 16 | yes |
| T2 Filter employees by department (Sales) | HR Viewer · Superset HR dashboard, Department filter | 9 | 5 | 5 | yes |
| T3 View outstanding receivables | Accounts Viewer · Superset Accounts dashboard | 5 | 166,700.00 | 166,700.00 | yes |
| T4 Identify overdue invoice categories | Accounts Viewer · Superset ageing chart | 5 | ageing chart rendered | 3 overdue buckets in the data | yes |
| T5 Export permitted analytical results (CSV) | Accounts Viewer · Superset chart menu -> Download -> Export to .CSV | 9 | 3 CSV lines | header + rows of the permitted table | yes |
| T6 Ask an AI question and read the answer | Executive · Django assistant | 6 | Overdue balances as of 25 October 2026: payables BTN 31,700.00; receivables BTN 149,700.00. | overdue receivables BTN 149,700.00 | yes |
<!-- /GENERATED:USABILITY -->

## 10. Automated regression suite (Task 8)

| Command | Needs | Covers |
|---|---|---|
| `python evaluation/run_regression.py --quick` | nothing | lint, format, all unit tests (connectors with fake APIs, ingestion logic, contracts, KPI oracle, DAG, Superset definitions, Django registry/rules/Gemini(mocked)/API, consistency guards) |
| `python evaluation/run_regression.py` | the services that are running | + database, warehouse (fixtures → dbt → hand-calculated KPIs), live ERP connectivity, KPI service, Superset boundary, dashboards in a browser, cross-layer reconciliation, access matrix, assistant evaluation. Stages whose services are down are reported as SKIPPED |
| `python evaluation/run_regression.py --with-e2e` | everything | + end-to-end test (modifies **sandbox** data) |
| `pytest` | as above | all pytest suites (marker-based skips) |

Latest full regression run:

<!-- GENERATED:REGRESSION -->
Run 2026-10-25T04:10:25.

| Stage | Covers | Status | Seconds | Last output line |
|---|---|---|---|---|
| lint | ruff lint + format check | passed | 0.3 | All checks passed! |
| format | ruff format check | passed | 0.3 | 163 files already formatted |
| unit | contracts, connectors (fake APIs), ingestion logic, KPI oracle, DAG static checks, Superset definitions, Django registry/rules/Gemini(mocked)/API, consistency guards | passed | 11.3 | 379 passed, 26 deselected in 8.41s |
| database | PostgreSQL roles/schemas, raw ingestion against the DB, publication swap/grants | passed | 9.2 | 22 passed, 473 deselected in 6.91s |
| warehouse | fixtures -> connectors -> raw -> dbt build + data tests -> hand-calculated KPIs; Django KPI service on the same marts | passed | 29.3 | 19 passed, 476 deselected in 26.88s |
| live_erp | read-only connectivity, contracts and idempotent loading against the ERP sandboxes | passed | 14.6 | 14 passed, 481 deselected in 12.12s |
| kpi_service | Django KPI functions vs fact tables, scope, restricted DB account | passed | 5.7 | 17 passed, 478 deselected in 3.29s |
| superset | Superset access boundary, RLS, CSV export, KPIs; Superset = KPI service | passed | 24.2 | 44 passed, 451 deselected in 21.70s |
| dashboards_browser | dashboards per role in headless Edge; KPI cards = warehouse | passed | 151.4 | browser check: all passed |
| reconciliation | source ERPs = dbt = Superset = Django = AI answers (all KPIs, per ERP) | passed | 7.3 | 30/30 reconciliation checks passed -> C:\Users\ASUS\FYP\docs\evaluation\results\reconciliation_regression.json |
| access_matrix | every role x resource at Superset, Django and database boundaries | passed | 49.8 | access matrix: 115/115 checks as expected |
| assistant_eval | AI assistant evaluation set (held-out set) against fact-table references | passed | 2.8 | } |
<!-- /GENERATED:REGRESSION -->

## 11. Defects, corrections and remaining limitations

Defects found and fixed in this milestone are listed in
[INTEGRATION_ASSESSMENT.md §2](INTEGRATION_ASSESSMENT.md):
- D1, Airflow secrets exposure (high);
- D2, stale Superset cache (medium);
- D3, no staleness signal (medium);
- D4, sandbox restart policy (low);
- D5, duplicated role configuration (low);
- D10, HTML 500 instead of JSON when the database is down (medium).

Defect found by the reliability tests and fixed: **D10**, where the API returned an HTML 500 page instead of JSON while the database was down (medium).

Defects in the evaluation tooling itself, found while running it (fixed, no platform impact):
- **Retry check:** the reliability script read a `try_number` that Airflow's task-state JSON does not contain. The scenario was re-run with the observed `up_for_retry` state as evidence.
- **Error field:** the database-outage scenario expected an `answer` field in the JSON error. It now accepts `message`.
- **Restart timing:** the next scenario started before PostgreSQL was ready. The script now waits for readiness.
- **Identity probe:** the database-account probe used `current_user` in Superset SQL Lab, which Superset rejects (a defence). The configured connection is recorded instead.

Remaining limitations (honest status):

| Area | Limitation |
|---|---|
| Data | Only local sandboxes and synthetic data; DrukSmart's ERPs, volumes, data quality and versions are untested |
| Scale | Hundreds of records. The timings in §8 do not predict behaviour at enterprise volumes; no load or concurrency testing |
| AI | Rules interpreter only; Gemini is implemented but **never called for real** (no key). Held-out phrasing accuracy was 13/14 (Milestone 7) |
| Usability | No real participants yet; SUS and task results pending |
| Security | Development servers (no HTTPS); Django login without throttling (D6); 4 separate logins (no SSO); `bi_reader` unused but still broad (D7); demo users share passwords |
| Operations | No monitoring or alerting beyond Airflow's UI; no backups scheduled (manual procedures exist for Superset metadata) |
| Business rules | Open DrukSmart decisions (DS-HR-01…, DS-AC-01…) use proposed defaults; ERPNext invoices have no branch (DS-AC-05) |

**Conclusion:**
- **Works end to end on sandbox data.** The integrated prototype runs end to end on the local sandboxes, and its KPI values agree exactly across every layer and with two independent references.
- **Fails safely.** It fails without publishing bad or stale data as current, and it enforces the role and branch restrictions at every boundary tested.
- **Not production-ready.** It is a validated **prototype**: production use needs DrukSmart's real ERPs, real-user evaluation, a live LLM evaluation if Gemini is to be used, and the deployment hardening listed above.
