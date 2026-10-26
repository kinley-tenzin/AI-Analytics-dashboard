# Source-to-Target Mapping (Odoo / ERPNext → canonical HR and Accounts models)

Machine-readable rules: [`contracts/canonical/hr.yaml`](../../contracts/canonical/hr.yaml),
[`contracts/canonical/accounts.yaml`](../../contracts/canonical/accounts.yaml).
Raw envelope: [`contracts/raw_record.yaml`](../../contracts/raw_record.yaml).
These rules are executed by the test-only reference calculator (`tests/support/kpi_reference.py`)
and are the specification for the dbt `staging` / `intermediate` models.

## 1. Layers

```
ERP API response ──► raw (payload + provenance envelope) ──► staging (rename, cast, per ERP)
                 ──► intermediate (canonical model, value maps, verified identity) ──► marts
```

## 2. Provenance and identity rules

1. Every raw row stores `source_system`, `source_instance`, `source_entity`, `source_id`
   (text), `source_modified_at` (UTC), `extraction_batch_id`, `extracted_at` (UTC),
   `contract_version`, `payload`, `payload_sha256`.
2. **Canonical key** = `"{source_system}:{source_instance}:{source_id}"`. It is unique
   across ERPs and instances by construction.
3. **No automatic cross-ERP merging.** Equal names, ids, codes or tax numbers are *candidates*
   only. Two records are the same real-world entity **only** if listed in
   [`contracts/mappings/entity_mappings.yaml`](../../contracts/mappings/entity_mappings.yaml) with
   evidence, verifier and date. Unverified pairs stay separate.
4. Department, branch and customer **names are never join keys**.
5. Latest-version rule: as of date D, a record's state is its version from the latest batch
   extracted on or before D (incremental batches only contain changed records).
6. Records that fail a contract **error** are quarantined (not loaded to marts) and reported.
   **Warnings** are loaded and flagged (e.g. missing department becomes `unassigned`).

## 3. HR mappings

### Employee

| Canonical field | Odoo `hr.employee` | ERPNext `Employee` |
|-----------------|--------------------|--------------------|
| employee_key | `odoo:<inst>:<id>` | `erpnext:<inst>:<name>` |
| employee_name | `name` | `employee_name` |
| organisation_unit_key | root of `company_id` | `company` |
| branch_key | `company_id` (branch company) | `branch` or `unassigned` |
| department_key | `department_id[0]` or `unassigned` | `department` or `unassigned` |
| employee_category | `employee_type` | `unspecified` (no field in v16) |
| joined_on | not readable by read-only role | `date_of_joining` |
| left_on | `departure_date` | `relieving_date` |
| employment_status (as of D) | see rules | see rules |

**Status rules (as of date D)**

| Odoo | → | ERPNext | → |
|------|---|---------|---|
| `active` and (`departure_date` empty or > D) | active | `Active`, joined ≤ D, not relieved ≤ D | active |
| `active` and `departure_date` ≤ D | left | `Active` with `date_of_joining` > D | not yet joined |
| not `active`, `departure_date` set | left | `Left` | left |
| not `active`, no `departure_date` | inactive | `Inactive` | inactive |
| | | `Suspended` | suspended (not in headcount, DS-HR-02) |

### Leave request

| Canonical | Odoo `hr.leave` | ERPNext `Leave Application` |
|-----------|-----------------|-----------------------------|
| start_date / end_date | `request_date_from` / `request_date_to` | `from_date` / `to_date` |
| leave_days | `number_of_days` | `total_leave_days` |
| leave_type | `holiday_status_id[1]` | `leave_type` |

| approval_status | Odoo `state` | ERPNext (`docstatus`, `status`) |
|-----------------|--------------|----------------------------------|
| approved | `validate` | (1, Approved) |
| pending | `confirm`, `validate1` | (0, any status), (1, Open) |
| rejected | `refuse` | (1, Rejected) |
| cancelled | `cancel` | (2, any), (1, Cancelled) |

## 4. Accounts mappings

### Accounting document

| Canonical | Odoo `account.move` | ERPNext `Sales Invoice` / `Purchase Invoice` |
|-----------|---------------------|-----------------------------------------------|
| ledger, document_kind | `out_invoice` → receivable/invoice; `out_refund` → receivable/credit_note; `in_invoice` → payable/invoice; `in_refund` → payable/credit_note | Sales → receivable, Purchase → payable; `is_return` 0 → invoice, 1 → credit_note |
| document_state | `draft`/`posted`/`cancel` → draft/posted/cancelled | `docstatus` 0/1/2 → draft/posted/cancelled |
| counterparty_key | `partner_id[0]` | `customer` / `supplier` |
| branch_key | `company_id` | `unassigned` (DS-AC-05) |
| document_date | `invoice_date` | `posting_date` |
| due_date | `invoice_date_due` | `due_date` |
| currency_code | `currency_id[1]` | `currency` |
| amount_total_company | sign × \|`amount_total_signed`\| | sign × \|`base_grand_total`\| |
| outstanding_company | sign × \|`amount_residual_signed`\| | sign × \|`outstanding_amount`\| × F (F = 1 if party account currency = company currency; = `conversion_rate` if it equals the document currency; otherwise error) |
| payment_status | derived: 0 → paid; \|outstanding\| = \|total\| → unpaid; else partially_paid | same derivation |

`sign` = +1 for invoices, −1 for credit notes. Only `posted` documents count in balances.
Odoo `invoicing_legacy` documents are excluded (DS-AC-06). Source payment statuses are mapped
only for **consistency checks** (`not_paid`→unpaid, `partial`→partially_paid,
`paid`/`in_payment`/`reversed`→paid; ERPNext `Paid`/`Partly Paid`/`Unpaid`).

### Payment and allocation

| Canonical | Odoo `account.payment` | ERPNext `Payment Entry` |
|-----------|------------------------|--------------------------|
| direction | `inbound` → received, `outbound` → paid | `Receive` → received, `Pay` → paid, `Internal Transfer` → excluded |
| document_state | `draft` → draft; `in_process`, `paid` → posted; `canceled`, `rejected` → cancelled | `docstatus` |
| payment_date | `date` | `posting_date` |
| allocations | `reconciled_invoice_ids` / `reconciled_bill_ids` (links; exact amounts from `account.partial.reconcile`, deferred) | `references[].reference_name`, `allocated_amount` |
| unallocated advance | posted inbound payment without linked invoice | `unallocated_amount` |

## 5. Identity matching procedure (cross-ERP)

1. Generate **candidates** (e.g. equal normalised tax ID / TPN; equal name *and* TPN).
2. A DrukSmart user reviews each candidate and confirms or rejects it.
3. Confirmed pairs are added to `entity_mappings.yaml` with `evidence`, `verified_by`,
   `verified_on`. One member per source system per mapping.
4. Unified reporting (e.g. receivables of "Lhaki Traders" across both ERPs) uses the
   `unified_id`; everything else reports per canonical key.

Synthetic examples: Lhaki Traders (same TPN, verified) is unified. Norbu Hardware (same name,
different TPN) and employee Pema Wangmo (same name, no evidence) are **not**.

## 6. Data-quality rules that become dbt tests

| Rule | Severity |
|------|----------|
| Required field present, correct type, allowed selection value | error → quarantine |
| End date not before start date (leave, employment) | error |
| Record key unique within a batch | error |
| Expected field missing (department, branch, due date, draft number) | warning |
| Referenced department/company/partner exists | warning (later milestone) |
| Derived payment status consistent with source status | data-quality alert |
| total − outstanding = allocated payments (+ returns against) | reconciliation alert |
