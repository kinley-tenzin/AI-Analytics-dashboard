-- PERIODIC SNAPSHOT fact.
-- Grain: one row per employee per HR snapshot date per source instance, for every employee
-- record known at that date (all statuses). Snapshot dates come from int_snapshot_dates, i.e.
-- only dates with a successful employee extraction: history is never fabricated.
-- Attributes (department, branch, status) are as of the snapshot date.
-- Measure: headcount (1 when employment_status = 'active', else 0): additive across employees,
-- departments and branches; NOT additive across snapshot dates.

with snapshots as (
    select * from {{ ref('int_snapshot_dates') }} where domain = 'hr'
),

at_date as (
    select s.snapshot_date, v.*
    from snapshots as s
    join {{ ref('int_employee_versions') }} as v
        on v.source_instance = s.source_instance
       and v.valid_from < s.snapshot_cutoff
       and (v.valid_to is null or v.valid_to >= s.snapshot_cutoff)
),

with_status as (
    select
        a.*,
        case
            when a.source_system = 'odoo' then
                case
                    when a.source_is_active and (a.left_on is null or a.left_on > a.snapshot_date) then 'active'
                    when a.source_is_active then 'left'
                    when a.left_on is not null then 'left'
                    else 'inactive'
                end
            else
                case
                    when m.employment_status = 'active' and a.joined_on > a.snapshot_date then 'not_yet_joined'
                    when m.employment_status = 'active' and a.left_on <= a.snapshot_date then 'left'
                    else coalesce(m.employment_status, 'unmapped')
                end
        end as employment_status
    from at_date as a
    left join {{ ref('map_erpnext_employee_status') }} as m on m.source_status = a.source_status
)

select
    to_char(snapshot_date, 'YYYYMMDD')::integer as snapshot_date_key,
    snapshot_date,
    employee_key,
    source_system,
    source_instance,
    organisation_key,
    branch_key,
    department_key,
    employee_category,
    employment_status,
    case when employment_status = 'active' then 1 else 0 end as headcount,
    record_version_id
from with_status
