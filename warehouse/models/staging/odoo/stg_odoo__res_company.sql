with v as ({{ raw_versions('odoo', 'res.company') }})
select
    {{ version_columns() }},
    {{ source_key('v.source_id') }} as company_key,
    v.source_id::integer as company_id,
    {{ odoo_text('name') }} as company_name,
    {{ odoo_m2o_id('parent_id') }} as parent_company_id,
    {{ odoo_m2o_name('currency_id') }} as currency_code,
    coalesce((v.payload ->> 'active')::boolean, true) as is_active
from v
