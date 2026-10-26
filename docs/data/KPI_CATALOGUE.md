# KPI Catalogue: HR and Accounts (initial set)

Version 1.0 · 2026-10-22 · Status: **draft for DrukSmart confirmation**.
Items marked **DS-…** need a DrukSmart business decision. The value shown is the platform's
*proposed default*, used in fixtures and tests until confirmed. The defaults are not DrukSmart policy.

Expected results for the synthetic fixtures: `tests/fixtures/synthetic/expected_kpis.json`.

## Common definitions

| Term | Definition |
|------|------------|
| As-of date (D) | Local calendar date (Asia/Thimphu) the KPI describes |
| Snapshot | State of each record from the latest extraction batch on or before D. **Balances are not reconstructed backwards from history** (DS-AC-01) |
| Valid record | Passes its source contract (no errors); quarantined records are excluded and reported |
| Organisation scope | Filters: source instance, legal company, branch, department. All KPIs are additive across instances **only** in the same currency |
| Reporting currency | Company currency (BTN for both reference companies) |

---

## HR-01 Active employee headcount

| Item | Specification |
|------|---------------|
| Business definition | Number of people employed by the organisation on date D |
| Formula | `COUNT(DISTINCT employee_key) WHERE employment_status(D) = 'active'` |
| Source data | Odoo `hr.employee` (`active`, `departure_date`, `company_id`, `department_id`, `employee_type`); ERPNext `Employee` (`status`, `date_of_joining`, `relieving_date`, `branch`, `department`) |
| Status rules | See SOURCE_TO_TARGET_MAPPING §3 (future joiners and people whose leaving date ≤ D are excluded) |
| Dimensions | Source instance, company, branch, department, employee category (Odoo only) |
| Reporting date | Snapshot at D (month-end for trends) |
| Aggregation | Count. Additive across departments and branches; **not** additive across time |
| Limitations | Odoo history cannot be rebuilt (no readable joining date), so trends start from the first snapshot. Same person in both ERPs counts twice unless a verified mapping exists |
| Decisions | **DS-HR-01** which Odoo employee types count (default: all; alternative employee+worker only is also computed). **DS-HR-02** suspended employees (default: excluded) |
| Validation | Reconcile per instance with the ERP's own employee list filtered the same way; fixture expected: 9 + 7 = 16 |

## HR-02 Headcount by department

| Item | Specification |
|------|---------------|
| Business definition | HR-01 broken down by the department each active employee belongs to on D |
| Formula | `COUNT(DISTINCT employee_key) GROUP BY department_key WHERE active` |
| Source data | HR-01 + Odoo `hr.department`, ERPNext `Department` |
| Dimensions | Department (per source; parent hierarchy), branch, company |
| Reporting date | Snapshot at D |
| Aggregation | Count; departments sum to HR-01 (including `unassigned`) |
| Limitations | Departments are **not** merged across companies or ERPs. Odoo has two different "Sales" departments in the fixtures. A group-level department taxonomy needs **DS-ORG-01** |
| Validation | Sum of departments = HR-01 for every instance (tested) |

## HR-03 Approved leave statistics

| Item | Specification |
|------|---------------|
| Business definition | Approved leave in a reporting period: number of requests, leave days and distinct employees |
| Formula | Over approved requests with `start_date` in [P_start, P_end]: `COUNT(*)`, `SUM(leave_days)`, `COUNT(DISTINCT employee_key)` |
| Approved | Odoo `state = validate`; ERPNext `docstatus = 1 AND status = 'Approved'` |
| Source data | Odoo `hr.leave`; ERPNext `Leave Application` |
| Dimensions | Period (month), leave type, department, branch, source instance |
| Reporting date | Period-based (default calendar month); uses latest state at period end |
| Aggregation | Requests and days additive; distinct employees **not** additive across periods/departments |
| Limitations | Days follow each ERP's own working-day calculation (holiday calendars may differ). Leave types are not harmonised across ERPs (DS-HR-04) |
| Decisions | **DS-HR-03** a request spanning two months: default counts the whole request in the start month (alternative: prorate days) |
| Validation | Compare with each ERP's leave report for the month; fixture expected: 7 requests, 13.5 days, 5 employees |

## AC-01 Outstanding accounts receivable

| Item | Specification |
|------|---------------|
| Business definition | Amount customers owe the organisation on date D |
| Formula | `SUM(outstanding_company)` over receivable documents with `document_state = posted` (invoices positive, credit notes negative) |
| Source data | Odoo `account.move` (out_invoice, out_refund); ERPNext `Sales Invoice` (`is_return` 0/1) |
| Document states | Draft and cancelled documents never count; `posted` / `docstatus = 1` only |
| Partial payments | Included via the residual / outstanding amount maintained by the ERP |
| Credit notes | Applied credit notes reduce the invoice's residual; **unapplied** credit notes are negative balances (shown in ageing as `unapplied_credit`), DS-AC-08 |
| Currency | Company currency at the document's own rate (no revaluation, DS-AC-04) |
| Dimensions | Instance, company, branch (Odoo only by default, DS-AC-05), customer (unified only via verified mapping), currency |
| Reporting date | Snapshot at D |
| Aggregation | Sum; additive across documents, customers, branches; not across dates |
| Limitations | Unallocated customer advances are reported separately, not netted (DS-AC-07). Odoo `invoicing_legacy` excluded (DS-AC-06) |
| Validation | Reconcile with the ERP's *Aged Receivable* report at D; check total − outstanding = allocations per invoice (tested) |

## AC-02 Outstanding accounts payable

As AC-01 for supplier documents: Odoo `in_invoice` / `in_refund`; ERPNext `Purchase Invoice`.
Positive = amount the organisation owes suppliers. Validation against the *Aged Payable* report.

## AC-03 Overdue balance

| Item | Specification |
|------|---------------|
| Business definition | Part of AR (or AP) whose due date has passed on D |
| Formula | `SUM(outstanding_company) WHERE outstanding_company > 0 AND due_date < D` |
| Due date | Document-level due date (Odoo `invoice_date_due`, ERPNext `due_date`), DS-AC-02 |
| Limitations | Instalment schedules (several due dates per invoice) are treated at document level |
| Validation | Equals the sum of all overdue ageing buckets (tested) |

## AC-04 Ageing distribution (receivables and payables)

| Bucket | Rule (days overdue = D − due_date) |
|--------|-------------------------------------|
| `not_due` | ≤ 0 |
| `1_30` | 1–30 |
| `31_60` | 31–60 |
| `61_90` | 61–90 |
| `91_plus` | ≥ 91 |
| `no_due_date` | posted document without due date (data-quality warning) |
| `unapplied_credit` | negative outstanding (credit notes not applied); not aged |

Buckets sum exactly to AC-01 / AC-02 (tested). Boundaries are the common 30-day convention
(DS-AC-02 to confirm).

## Effects on financial KPIs (summary)

| Factor | Treatment |
|--------|-----------|
| Duplicate entities | Same customer in two ERPs is two customers unless a verified mapping exists; amounts are never double-counted because each *document* exists in one ERP only |
| Document states | Only posted/submitted documents count; drafts and cancelled documents are excluded even if they show a non-zero balance (fixture: ERPNext SINV-00005) |
| Partial payments | Reflected through ERP-maintained residual; cross-checked against payment allocations |
| Credit notes | Applied: reduce the original invoice. Unapplied: negative balance in `unapplied_credit` |
| Reversed invoices (Odoo) | Invoice + reversing credit note both have zero residual → no effect |
| Currency | Company currency at document rate. ERPNext outstanding converted when the party account is in the document currency |
| Snapshot dates | Each figure is tied to D; month-end snapshots build the trend |

## Open decisions for DrukSmart

| ID | Question | Proposed default |
|----|----------|------------------|
| DS-HR-01 | Which Odoo employee types count in headcount? | All types |
| DS-HR-02 | Do suspended employees count? | No |
| DS-HR-03 | Leave spanning two periods: start month or prorated? | Whole request in start month |
| DS-HR-04 | Harmonised leave type list across ERPs? | Report source leave types |
| DS-ORG-01 | How do Odoo companies/branches and ERPNext company/branches roll up to DrukSmart's organisation and department structure? | Report per source structure |
| DS-AC-01 | Are month-end snapshots acceptable instead of reconstructed historical balances? | Yes |
| DS-AC-02 | Ageing by document due date and 30-day buckets? | Yes |
| DS-AC-03 | Group reporting currency if companies use different currencies | Not needed while all use BTN |
| DS-AC-04 | Revalue foreign-currency balances at D? | No (document rate) |
| DS-AC-05 | Branch for ERPNext invoices (cost centre / accounting dimension?) | `unassigned` |
| DS-AC-06 | Exclude Odoo `invoicing_legacy` documents? | Exclude |
| DS-AC-07 | Net unallocated advances against receivables/payables? | No, report separately |
| DS-AC-08 | Show unapplied credit notes netted (current) or separately only? | Netted in totals and shown as a bucket |
| DS-SEC-01 | Approve Odoo read-only API user with HR Officer rights (needed for employee_type, departure_date) | Yes, read-only |
