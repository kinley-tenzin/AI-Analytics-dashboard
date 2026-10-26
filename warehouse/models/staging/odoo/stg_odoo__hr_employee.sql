with v as ({{ raw_versions('odoo', 'hr.employee') }})
select
    {{ version_columns() }},
    {{ source_key('v.source_id') }} as employee_key,
    v.source_id::integer as employee_id,
    {{ odoo_text('name') }} as employee_name,
    (v.payload ->> 'active')::boolean as is_active,
    {{ odoo_m2o_id('company_id') }} as company_id,
    {{ odoo_m2o_id('department_id') }} as department_id,
    {{ odoo_text('employee_type') }} as employee_type,
    {{ odoo_text('departure_date') }}::date as departure_date,
    {{ odoo_m2o_id('parent_id') }} as manager_employee_id
from v
