# ERP Source Analysis: Odoo 19 and ERPNext 16 (HR and Accounts)

**Status:** desk analysis from official documentation and source code (Milestone 2), **then checked
against local Odoo 19 and ERPNext 16 sandboxes in Milestone 3** (results in §7). DrukSmart's own ERP
instances have not been queried. Every claim is labelled with how it was verified:

| Label | Meaning |
|-------|---------|
| **source** | Read in the ERP's own source code on GitHub (branch named below) |
| **docs** | Stated in official documentation |
| **assumption** | Not yet verified. **Must be confirmed against a sandbox instance** before connectors rely on it |

Machine-readable versions of everything below: [`contracts/sources/odoo.yaml`](../../contracts/sources/odoo.yaml),
[`contracts/sources/erpnext.yaml`](../../contracts/sources/erpnext.yaml).

## 1. Versions analysed

| ERP | Version | Why this version | Evidence |
|-----|---------|------------------|----------|
| Odoo Community | **19.0** | Current major; the JSON-2 API (cited in the proposal) is "new in version 19.0" | docs: Odoo 19.0 External JSON-2 API page; source: `odoo/odoo` branch `19.0` |
| ERPNext | **v16** (latest tag v16.52.0, 21 Oct 2026) | Newest major; v15 is still maintained (v15.124.0) | source: `frappe/erpnext` branch `version-16`, GitHub releases page |
| Frappe HR (HRMS) | **v16** (v16.51.0) | Leave Application lives in the separate HRMS app since ERPNext v14 | source: `frappe/hrms` branch `version-16` |
| Frappe framework | v16 | REST API implementation | source: `frappe/frappe` branch `version-16` |

> **Version risk.** Field names below are only guaranteed for these versions. Odoo 19 moved
> several employee fields to the new `hr.version` model (see §3.1). DrukSmart's real instances
> may run older versions; the connector must check the server version and fail clearly on a
> mismatch rather than silently reading wrong fields.

## 2. API access

### 2.1 Odoo JSON-2 API (docs, source)

| Aspect | Finding | Level |
|--------|---------|-------|
| Call | `POST /json/2/<model>/<method>` (e.g. `/json/2/hr.employee/search_read`) | docs |
| Auth | `Authorization: bearer <api_key>`; `X-Odoo-Database` needed when a server hosts several DBs | docs |
| Arguments | Named JSON keys: `domain`, `fields`, `ids`, `context`, plus method parameters | docs |
| `limit`/`offset`/`order` | Parameters of `search_read` (passed as named keys) | source (partial) / **assumption** for JSON-2 usage |
| Response | Bare JSON value (array for `search_read`), HTTP 200; errors 4xx/5xx with `{name, message, arguments, context, debug}` | docs |
| Transactions | One transaction per call; cannot chain calls | docs |
| Permissions | Runs with the key owner's access rights, record rules and field access; dedicated bot users recommended | docs |
| API keys | Max 3 months lifetime; shown once | docs |
| Many2one values | `[id, "display name"]` with default `load`; empty = `false` | source (`odoo/orm/fields_relational.py`) |
| Empty values | ORM returns `false` for `None` | source (`odoo/orm/fields.py`) |
| Date / datetime JSON format | Assumed `"YYYY-MM-DD"` / `"YYYY-MM-DD HH:MM:SS"` (naive UTC). The JSON-2 controller does no serialisation itself | **assumption** |
| Archived records | `search_read` hides `active = false` records unless context `active_test: false` is passed | **assumption** (standard ORM behaviour, not re-read) |
| Old APIs | `/xmlrpc`, `/jsonrpc` deprecated; removal scheduled (Odoo 22 per docs page summary) | docs (wording to re-check) |
| Commercial note | External API access on Odoo Online needs a *Custom* plan; self-hosted Community has no such limit | docs |

### 2.2 Frappe / ERPNext REST API (source)

| Aspect | Finding | Level |
|--------|---------|-------|
| List | `GET /api/resource/<DocType>?fields=[..]&filters=[..]&order_by=..&limit_start=..&limit_page_length=..` | source (`frappe/api/v1.py`, `frappe/client.py`) |
| One document | `GET /api/resource/<DocType>/<name>` | source |
| v2 | `GET /api/v2/document/<DocType>` (`start`, `limit`), response also has `has_next_page` | source (`frappe/api/v2.py`) |
| Envelope | `{"data": ...}` | source (`frappe/api/__init__.py`) |
| **Default page size** | **20 rows**: every call must set `limit_page_length` explicitly | source |
| Auth | `Authorization: token <api_key>:<api_secret>` (or `Basic base64(key:secret)`) | source (`frappe/auth.py`) |
| Permissions | List endpoint is permission-checked (role + user permissions of the key owner) | source |
| Child tables | Not in list results; fetch each document (e.g. Payment Entry `references`) | **assumption** (list fields are parent fields) |
| `docstatus` | 0 = Draft, 1 = Submitted, 2 = Cancelled | source (`frappe/model/docstatus.py`) |
| Standard fields | `name, owner, creation, modified, modified_by, docstatus, idx` on every DocType; `modified` filterable | source (`frappe/model/__init__.py`, `db_query.py`) |
| Datetime | Naive values in the site's time zone (System Settings), e.g. `2026-10-01 10:00:00.000000` | **assumption** |
| Empty values | `null` (Links, Dates) or `""` (Data fields) | **assumption** |

## 3. HR entities

### 3.1 Odoo 19

| Concept | Model | Key fields (type) | Notes |
|---------|-------|-------------------|-------|
| Organisation / branch | `res.company` | `id`, `name`, `parent_id` (m2o, branch → parent), `currency_id` | source. Branches are child companies; hierarchy cannot be changed after creation; branches share the root currency |
| Department | `hr.department` | `id`, `name`, `complete_name` (computed), `parent_id`, `company_id`, `manager_id`, `active` | source. `_parent_store` hierarchy |
| Employee | `hr.employee` | `id`, `name`, `active`, `company_id`, `parent_id` (manager), `write_date` | source |
| Employee (version fields) | `hr.version` via `_inherits` | `department_id`, `job_id`, `job_title`, `employee_type` ∈ {employee, worker, student, trainee, contractor, freelance}, `departure_date`, `departure_reason_id`, `contract_date_start/end`, `date_version` | source. **New in 19.** `employee_type`, `departure_date` need group `hr.group_hr_user`; contract dates need `hr.group_hr_manager` |
| Leave request | `hr.leave` | `id`, `employee_id`, `holiday_status_id` (leave type), `state` ∈ {confirm, refuse, validate1, validate, cancel} (default confirm; **no draft**), `request_date_from/to` (date), `date_from/to` (datetime, computed), `number_of_days`, `department_id`, `company_id` | source |

**Employment status in Odoo** is not one field: it is `active` (archived = left/inactive)
plus `departure_date`. There is no stored joining date on `hr.employee` that a read-only HR
officer can read (`contract_date_start` is manager-only), so **point-in-time historical
headcount cannot be reconstructed from Odoo** with the planned permissions. Headcount history
is built from periodic snapshots instead (see KPI catalogue).

### 3.2 ERPNext 16 / HRMS 16

| Concept | DocType | Key fields (type) | Notes |
|---------|---------|-------------------|-------|
| Organisation | `Company` | `name`, `abbr`, `default_currency` | `abbr`/`default_currency` **assumption** |
| Branch | `Branch` | `name` | Simple master; linked from Employee only |
| Department | `Department` | `name` (e.g. "Sales - DSV"), `department_name`, `parent_department`, `company` (reqd), `is_group`, `disabled` | source. Tree DocType |
| Employee | `Employee` | `name` (series `HR-EMP-`), `employee_name`, `status` ∈ {Active, Inactive, Suspended, Left}, `company` (reqd), `department`, `branch`, `designation`, `date_of_joining` (reqd), `relieving_date` (mandatory when Left), `reports_to` | source. `employment_type` **not found** in the v16 JSON |
| Leave request | `Leave Application` (HRMS) | `name` (`HR-LAP-.YYYY.-`), `employee`, `leave_type`, `status` ∈ {Open, Approved, Rejected, Cancelled}, `docstatus`, `from_date`, `to_date`, `total_leave_days`, `half_day`, `posting_date`, `company`, `department` | source. **Submittable**: a request is final only when `docstatus = 1` |

## 4. Accounts entities

### 4.1 Odoo 19 (`account` module)

| Concept | Model | Key fields | Notes |
|---------|-------|-----------|-------|
| Customer invoice / credit note / vendor bill / vendor credit note | `account.move` | `move_type` ∈ {out_invoice, out_refund, in_invoice, in_refund, (entry, out_receipt, in_receipt)}; `state` ∈ {draft, posted, cancel}; `payment_state` ∈ {not_paid, in_payment, paid, partial, reversed, blocked, invoicing_legacy}; `partner_id`; `invoice_date`; `invoice_date_due`; `currency_id`; `amount_total`, `amount_residual` (document currency); `amount_total_signed`, `amount_residual_signed` (company currency, signed); `reversed_entry_id`; `company_id` | source. All listed amounts are stored. `company_currency_id` is related, not stored |
| Payment | `account.payment` | `payment_type` ∈ {inbound, outbound}; `partner_type` ∈ {customer, supplier}; `state` ∈ {draft, in_process, paid, canceled, rejected}; `amount`; `currency_id`; `date`; `move_id`; `reconciled_invoice_ids`, `reconciled_bill_ids` (computed, not stored); `is_reconciled` | source. Payment states changed in Odoo 18+ |
| Allocation (exact amounts) | `account.partial.reconcile` | `debit_move_id`, `credit_move_id` (journal items), `amount` (company currency, positive), `debit/credit_amount_currency`, `max_date` | source. Needs `account.move.line` too; deferred |
| Partner | `res.partner` | `id`, `name`, `vat`, `customer_rank`, `supplier_rank` | **assumption** (standard fields, not re-read) |

Important behaviours (source):
- **`in_payment` vs `paid`**: Community returns `paid` as soon as an invoice is fully
  reconciled (`_get_invoice_in_payment_state` returns `'paid'`); the Accountant module returns
  `in_payment` until the bank statement is matched. Both mean the invoice balance is zero.
- `payment_state` is stored but computed from `amount_residual`, `move_type`, `state` and
  matched payments; `blocked` and `invoicing_legacy` are preserved values, never computed.
- **Sign convention** of `*_signed` amounts per move type was not verified. The canonical
  rules use `abs()` and a document sign, so they are independent of it.
- Instalment due dates live on `account.move.line.date_maturity`; `invoice_date_due` is the
  document-level (latest/main) due date.

### 4.2 ERPNext 16

| Concept | DocType | Key fields | Notes |
|---------|---------|-----------|-------|
| Customer invoice / credit note | `Sales Invoice` | `name` (`ACC-SINV-.YYYY.-`, returns `ACC-SINV-RET-.YYYY.-`), `customer`, `company`, `posting_date`, `due_date`, `currency`, `conversion_rate`, `grand_total`, `base_grand_total`, `outstanding_amount`, `is_return`, `return_against`, `status` (13 values incl. Overdue, Partly Paid, Return, Credit Note Issued), `docstatus` | source. Credit note = `is_return = 1` (negative totals) |
| Supplier bill / debit note | `Purchase Invoice` | as above with `supplier`, `bill_no`, `bill_date`; status set incl. *Debit Note Issued* | source |
| Payment | `Payment Entry` | `payment_type` ∈ {Receive, Pay, Internal Transfer}, `party_type`, `party`, `posting_date`, `paid_amount`, `received_amount`, `paid_from/to_account_currency`, `unallocated_amount`, `docstatus`, `references` (child) | source |
| Allocation | `Payment Entry Reference` (child) | `reference_doctype`, `reference_name`, `allocated_amount`, `outstanding_amount`, `total_amount`, `due_date` | source |
| Customer / Supplier | `Customer`, `Supplier` | `name`, `customer_name`/`supplier_name`, `tax_id`, `disabled` | **assumption** |

Important behaviours:
- `outstanding_amount` is in **`party_account_currency`** (the receivable/payable account's
  currency), not necessarily the company currency (source: field options).
- `status` is derived and time-dependent (an unpaid invoice becomes *Overdue* after its due
  date); it is used only for cross-checks, never as the basis of KPIs.
- A return **against** an invoice either keeps its own negative outstanding (field
  `update_outstanding_for_self = 1`, the v16 default) or reduces the original invoice's outstanding
  (`= 0`). A standalone return always carries its own negative outstanding (**verified live**, §7).
- Invoices have **no branch field** by default. Branch reporting needs a cost centre or
  accounting dimension (DrukSmart decision DS-AC-05).

## 5. Heterogeneity summary (why mapping is needed)

| Aspect | Odoo | ERPNext |
|--------|------|---------|
| Record id | Integer `id` | String `name` (naming series or the title itself) |
| References | `[id, "name"]` pair | Name string |
| Empty value | `false` | `null` / `""` |
| Datetime | Naive UTC (assumed) | Naive site-local time (assumed) |
| Approval finality | State value (`validate`, `posted`) | `docstatus = 1` **and** status |
| Employee status | `active` + `departure_date` | `status` enum + dates |
| Branch | Child company | `Branch` master on Employee only |
| Credit note | Separate `move_type` (`out_refund`) | `is_return = 1` on the same DocType |
| Outstanding currency | Document + signed company currency | Party account currency |
| Partial payment detail | `account.partial.reconcile` (journal-item level) | `Payment Entry Reference` rows |

## 6. Required access for read-only connectors

| ERP | Minimum | Why |
|-----|---------|-----|
| Odoo | Dedicated bot user, **Employees: Officer** (`hr.group_hr_user`), **Time Off: Officer/read**, **Invoicing: Billing (read)** or equivalent read-only access rights; API key | `employee_type`, `departure_date` are restricted to HR officers (source) |
| ERPNext | Dedicated user with read-only custom role on the listed DocTypes; API key + secret | REST list respects role permissions (source) |

A read-only role is enforced by the ERP's permission model. The connectors only *call* read
methods (`search_read`, `GET`), and the sandbox milestone must prove that a write attempt with the
same credentials is refused (DS-SEC-01: DrukSmart to approve the HR-officer requirement).

## 7. Items verified against live sandboxes (Milestone 3, 2026-10-22)

Sandboxes: Odoo `19.0-20261015` Community, ERPNext `16.52.0` + HRMS `16.52.0` (synthetic data).

| # | Item | Result |
|---|------|--------|
| 1 | Odoo JSON-2 date/datetime formats; `false` for empty fields | ✅ `"2026-11-15"`, `"2026-10-22 07:42:50"` (UTC); `false` for empty date and many2one |
| 2 | Odoo `active_test: false` returns archived employees | ✅ archived employee returned |
| 3 | Odoo sign of `*_signed` amounts | ✅ out_invoice +, out_refund −, in_invoice −, in_refund + (as assumed). E.g. USD 300 open on a USD 500 bill = −25,200 BTN |
| 4 | Odoo `search_read` accepts `limit`, `order`, `domain`, `context` as named keys | ✅ |
| 5 | ERPNext child tables via single GET; datetime format; time zone | ✅ `references` returned; `"2026-10-22 14:10:01.246700"`; site TZ `Asia/Thimphu` |
| 6 | ERPNext returns and the original's outstanding | ⚠️ **Assumption corrected.** Controlled by the per-return field `update_outstanding_for_self` (default **1** in v16): the return keeps its own negative outstanding and the original is unchanged. With 0, the return reduces the original. Totals are identical; ageing differs. Field added to the contract (v1.1.0) |
| 7 | Read-only credentials refuse writes | ✅ ERPNext role refuses create/update. ✅ Odoo bot refused on company and invoice writes. Odoo HR-officer rights still allow employee edits (DS-SEC-01) |
| 8 | Odoo `/web/version`, JSON-2 401 on a bad key | ✅ |
| 9 | ERPNext `/api/v2/doctype/<DocType>/meta` | ✅ available to the read-only user |
| 10 | ERPNext Department `company` always set | ⚠️ **Corrected.** The root "All Departments" has none → `expected`, not `required` |
| 11 | HRMS 16 holiday lists | New: a submitted **Holiday List Assignment** is required before leave applications can be created (relevant to DrukSmart data quality, not to extraction) |

Still unverified: behaviour of DrukSmart's real instances (versions, customisations, permissions,
data volumes); Odoo `account.partial.reconcile` (deferred).
