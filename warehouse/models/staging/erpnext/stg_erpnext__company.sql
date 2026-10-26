with v as ({{ raw_versions('erpnext', 'Company') }})
select
    {{ version_columns() }},
    {{ source_key('v.source_id') }} as company_key,
    v.source_id as company_name,
    {{ erp_text('abbr') }} as company_abbreviation,
    {{ erp_text('default_currency') }} as default_currency
from v
