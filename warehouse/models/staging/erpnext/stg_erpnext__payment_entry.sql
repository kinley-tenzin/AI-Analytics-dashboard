with v as ({{ raw_versions('erpnext', 'Payment Entry') }})
select
    {{ version_columns() }},
    {{ source_key('v.source_id') }} as payment_key,
    v.source_id as payment_id,
    {{ erp_text('payment_type') }} as payment_type,
    {{ erp_text('party_type') }} as party_type,
    {{ erp_text('party') }} as party_id,
    {{ erp_text('posting_date') }}::date as payment_date,
    {{ money("v.payload ->> 'paid_amount'") }} as amount,
    {{ erp_text('paid_from_account_currency') }} as currency_code,
    {{ money("coalesce(v.payload ->> 'unallocated_amount', '0')") }} as unallocated_amount,
    (v.payload ->> 'docstatus')::integer as docstatus
from v
