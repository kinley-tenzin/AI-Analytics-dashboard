with v as ({{ raw_versions('erpnext', 'Department') }})
select
    {{ version_columns() }},
    {{ source_key('v.source_id') }} as department_key,
    v.source_id as department_id,
    {{ erp_text('department_name') }} as department_name,
    {{ erp_text('parent_department') }} as parent_department_id,
    {{ erp_text('company') }} as company_name,
    coalesce((v.payload ->> 'is_group')::integer, 0) = 1 as is_group,
    coalesce((v.payload ->> 'disabled')::integer, 0) = 0 as is_active
from v
