with v as ({{ raw_versions('erpnext', 'Sales Invoice') }})
select
    {{ version_columns() }},
    {{ source_key('v.source_id') }} as document_key,
    v.source_id as invoice_id,
    'Sales Invoice' as doctype,
    {{ erp_text('customer') }} as party_id,
    {{ erp_text('company') }} as company_name,
    {{ erp_text('posting_date') }}::date as document_date,
    {{ erp_text('due_date') }}::date as due_date,
    {{ erp_text('currency') }} as currency_code,
    (v.payload ->> 'conversion_rate')::numeric(20, 9) as conversion_rate,
    {{ money("v.payload ->> 'grand_total'") }} as grand_total,
    {{ money("v.payload ->> 'base_grand_total'") }} as base_grand_total,
    {{ money("v.payload ->> 'outstanding_amount'") }} as outstanding_amount,
    {{ erp_text('party_account_currency') }} as party_account_currency,
    (v.payload ->> 'is_return')::integer as is_return,
    {{ erp_text('return_against') }} as return_against_id,
    -- NULL when the field was not extracted (contract < 1.1.0); v16 default is 1 (verified live)
    (v.payload ->> 'update_outstanding_for_self')::integer as update_outstanding_for_self,
    {{ erp_text('status') }} as source_status,
    (v.payload ->> 'docstatus')::integer as docstatus
from v
