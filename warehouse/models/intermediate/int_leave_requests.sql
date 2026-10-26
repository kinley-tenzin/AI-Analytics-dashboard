-- Canonical leave requests (current version) with approval status from the documented map
-- (seed map_leave_approval_status, generated from contracts/canonical/hr.yaml).
-- Grain: one row per leave request per source instance.

with leaves as (
    select source_system, source_instance, leave_key, leave_id::text as source_leave_id,
           {{ source_key('employee_id') }} as employee_key, leave_type_name, source_status,
           null::integer as docstatus, start_date, end_date, leave_days, false as is_half_day,
           record_version_id
    from {{ ref('stg_odoo__hr_leave') }} as v
    where is_current
    union all
    select source_system, source_instance, leave_key, leave_id,
           {{ source_key('employee_id') }}, leave_type_name, source_status,
           docstatus, start_date, end_date, leave_days, is_half_day, record_version_id
    from {{ ref('stg_erpnext__leave_application') }} as v
    where is_current
)

select
    l.*,
    coalesce(m.approval_status, 'unmapped') as approval_status
from leaves as l
left join {{ ref('map_leave_approval_status') }} as m
    on m.source_system = l.source_system
   and m.source_status = l.source_status
   and coalesce(m.docstatus, -1) = coalesce(l.docstatus, -1)
