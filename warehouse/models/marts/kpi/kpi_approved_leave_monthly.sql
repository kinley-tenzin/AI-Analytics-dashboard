-- HR-03 Approved leave statistics per calendar month of the leave START date (DS-HR-03).
-- approved_requests and approved_leave_days are additive. employees_on_leave is a DISTINCT count:
-- do not sum it across months, departments, branches or instances (use fct_leave_request for that).
-- Organisation / branch / department are the employee's CURRENT ones (see fct_leave_request).
select
    date_trunc('month', l.start_date)::date as period_month,
    l.source_system,
    l.source_instance,
    l.organisation_key,
    o.organisation_name,
    l.branch_key,
    b.branch_name,
    l.department_key,
    d.department_name,
    l.leave_type_name,
    count(*) as approved_requests,
    sum(l.leave_days) as approved_leave_days,
    count(distinct l.employee_key) as employees_on_leave
from {{ ref('fct_leave_request') }} as l
left join {{ ref('dim_organisation') }} as o on o.organisation_key = l.organisation_key
left join {{ ref('dim_branch') }} as b on b.branch_key = l.branch_key
left join {{ ref('dim_department') }} as d on d.department_key = l.department_key
where l.approval_status = 'approved'
group by 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
