-- TRANSACTION fact: invoices, vendor bills and credit notes (all states), latest version.
-- Grain: one row per accounting document per source instance.
-- amount_total_company is the DOCUMENT VALUE (not an outstanding balance). Current outstanding
-- is included for drill-down; dated balances come from fct_receivable_payable_snapshot.

select
    d.document_key,
    d.source_system,
    d.source_instance,
    d.source_document_id,
    d.document_number,
    d.source_document_type,
    d.ledger,
    d.document_kind,
    d.document_state,
    d.source_payment_status,
    d.counterparty_key,
    d.branch_key,
    d.organisation_key,
    to_char(d.document_date, 'YYYYMMDD')::integer as document_date_key,
    d.document_date,
    to_char(d.due_date, 'YYYYMMDD')::integer as due_date_key,
    d.due_date,
    d.currency_code,
    d.amount_total_document,
    d.amount_total_company,
    d.outstanding_company as current_outstanding_company,
    case
        when d.outstanding_company = 0 then 'paid'
        when abs(d.outstanding_company) = abs(d.amount_total_company) then 'unpaid'
        else 'partially_paid'
    end as payment_status,
    d.return_against_key,
    d.currency_resolution,
    d.is_excluded_legacy
from {{ ref('int_accounting_document_versions') }} as d
where d.is_current
