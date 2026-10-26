-- HR-03 approved leave at REQUEST grain, for the Django KPI service only (backend/approved_datasets.yml).
-- Needed because COUNT(DISTINCT employee_key) over an arbitrary period cannot be re-aggregated from
-- kpi_approved_leave_monthly. The backend returns only aggregates (counts, days): employee_key is an
-- opaque warehouse key (no names) and never leaves the backend. NOT approved for Superset.
-- Grain: one row per approved leave request per source instance. Period attribution by START date
-- (DS-HR-03); organisation / branch / department are the employee's current ones.
select
    l.leave_key,
    l.source_system,
    l.source_instance,
    l.employee_key,
    l.organisation_key,
    o.organisation_name,
    l.branch_key,
    b.branch_name,
    l.department_key,
    d.department_name,
    l.leave_type_name,
    l.start_date,
    l.end_date,
    l.leave_days
from {{ ref('fct_leave_request') }} as l
left join {{ ref('dim_organisation') }} as o on o.organisation_key = l.organisation_key
left join {{ ref('dim_branch') }} as b on b.branch_key = l.branch_key
left join {{ ref('dim_department') }} as d on d.department_key = l.department_key
where l.approval_status = 'approved'
