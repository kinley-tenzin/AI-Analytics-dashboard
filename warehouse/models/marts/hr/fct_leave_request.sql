-- TRANSACTION fact (one event = one leave request).
-- Grain: one row per leave request per source instance, latest extracted version.
-- Measures: leave_days (additive), request_count = 1. Filter approval_status = 'approved' for
-- approved-leave KPIs. Leave is attributed to the period of its START date (DS-HR-03).
-- department_key is the employee's current department (leave records are not re-dated).

select
    l.leave_key,
    l.source_system,
    l.source_instance,
    l.source_leave_id,
    l.employee_key,
    e.department_key,
    e.branch_key,
    e.organisation_key,
    l.leave_type_name,
    l.approval_status,
    l.source_status,
    l.docstatus,
    to_char(l.start_date, 'YYYYMMDD')::integer as start_date_key,
    l.start_date,
    l.end_date,
    l.leave_days,
    l.is_half_day,
    1 as request_count
from {{ ref('int_leave_requests') }} as l
left join {{ ref('dim_employee') }} as e on e.employee_key = l.employee_key
