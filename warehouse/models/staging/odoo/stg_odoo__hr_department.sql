with v as ({{ raw_versions('odoo', 'hr.department') }})
select
    {{ version_columns() }},
    {{ source_key('v.source_id') }} as department_key,
    v.source_id::integer as department_id,
    {{ odoo_text('name') }} as department_name,
    {{ odoo_m2o_id('parent_id') }} as parent_department_id,
    {{ odoo_m2o_id('company_id') }} as company_id,
    (v.payload ->> 'active')::boolean as is_active
from v
