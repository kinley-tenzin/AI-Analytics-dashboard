with v as ({{ raw_versions('erpnext', 'Leave Application') }})
select
    {{ version_columns() }},
    {{ source_key('v.source_id') }} as leave_key,
    v.source_id as leave_id,
    {{ erp_text('employee') }} as employee_id,
    {{ erp_text('leave_type') }} as leave_type_name,
    {{ erp_text('status') }} as source_status,
    (v.payload ->> 'docstatus')::integer as docstatus,
    {{ erp_text('from_date') }}::date as start_date,
    {{ erp_text('to_date') }}::date as end_date,
    (v.payload ->> 'total_leave_days')::numeric(10, 2) as leave_days,
    coalesce((v.payload ->> 'half_day')::integer, 0) = 1 as is_half_day,
    {{ erp_text('company') }} as company_name,
    {{ erp_text('department') }} as department_id,
    {{ erp_text('posting_date') }}::date as posting_date
from v
