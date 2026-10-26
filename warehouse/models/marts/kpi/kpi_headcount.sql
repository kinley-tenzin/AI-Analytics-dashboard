-- HR-01 Active employee headcount and HR-02 headcount by department (docs/data/KPI_CATALOGUE.md).
-- One row per snapshot date x instance x organisation x branch x department x employee category
-- x employment status. active_headcount and employee_records are additive across every column
-- except snapshot_date. The *_name columns are display labels for Superset (never join keys).
select
    f.snapshot_date,
    f.source_system,
    f.source_instance,
    f.organisation_key,
    o.organisation_name,
    f.branch_key,
    b.branch_name,
    f.department_key,
    d.department_name,
    f.employee_category,
    f.employment_status,
    sum(f.headcount) as active_headcount,
    count(*) as employee_records
from {{ ref('fct_headcount_snapshot') }} as f
left join {{ ref('dim_organisation') }} as o on o.organisation_key = f.organisation_key
left join {{ ref('dim_branch') }} as b on b.branch_key = f.branch_key
left join {{ ref('dim_department') }} as d on d.department_key = f.department_key
group by 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11
