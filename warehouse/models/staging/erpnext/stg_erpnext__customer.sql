with v as ({{ raw_versions('erpnext', 'Customer') }})
select
    {{ version_columns() }},
    {{ source_key('v.source_id') }} as partner_key,
    v.source_id as customer_id,
    {{ erp_text('customer_name') }} as customer_name,
    {{ erp_text('tax_id') }} as tax_id,
    coalesce((v.payload ->> 'disabled')::integer, 0) = 0 as is_active
from v
