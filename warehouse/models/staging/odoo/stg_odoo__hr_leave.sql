with v as ({{ raw_versions('odoo', 'hr.leave') }})
select
    {{ version_columns() }},
    {{ source_key('v.source_id') }} as leave_key,
    v.source_id::integer as leave_id,
    {{ odoo_m2o_id('employee_id') }} as employee_id,
    {{ odoo_m2o_name('holiday_status_id') }} as leave_type_name,
    {{ odoo_text('state') }} as source_status,
    {{ odoo_text('request_date_from') }}::date as start_date,
    {{ odoo_text('request_date_to') }}::date as end_date,
    (v.payload ->> 'number_of_days')::numeric(10, 2) as leave_days,
    {{ odoo_m2o_id('department_id') }} as department_id
from v
