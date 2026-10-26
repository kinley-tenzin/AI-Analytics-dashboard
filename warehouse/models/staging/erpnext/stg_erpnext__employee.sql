with v as ({{ raw_versions('erpnext', 'Employee') }})
select
    {{ version_columns() }},
    {{ source_key('v.source_id') }} as employee_key,
    v.source_id as employee_id,
    {{ erp_text('employee_name') }} as employee_name,
    {{ erp_text('status') }} as source_status,
    {{ erp_text('company') }} as company_name,
    {{ erp_text('department') }} as department_id,
    {{ erp_text('branch') }} as branch_name,
    {{ erp_text('date_of_joining') }}::date as date_of_joining,
    {{ erp_text('relieving_date') }}::date as relieving_date
from v
