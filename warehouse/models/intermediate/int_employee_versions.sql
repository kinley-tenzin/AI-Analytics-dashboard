-- Canonical employee attributes for EVERY extracted version of every employee (both ERPs).
-- The status as of a date is derived later (fct_headcount_snapshot), because Odoo's status
-- depends on the date (departure_date) and ERPNext's on joining/relieving dates.
-- Grain: one row per employee record version.

select
    e.record_version_id,
    e.source_system,
    e.source_instance,
    e.employee_key,
    e.employee_id::text as source_employee_id,
    e.employee_name,
    b.organisation_key,
    {{ source_key('e.company_id', 'e') }} as branch_key,
    coalesce({{ source_key('e.department_id', 'e') }},
             e.source_system || ':' || e.source_instance || ':unassigned') as department_key,
    e.employee_type as employee_category,
    null::date as joined_on,                -- not readable by the read-only Odoo role
    e.departure_date as left_on,
    e.is_active as source_is_active,
    null::text as source_status,
    e.valid_from,
    e.valid_to,
    e.is_current
from {{ ref('stg_odoo__hr_employee') }} as e
left join {{ ref('int_organisation_units') }} as b
    on b.unit_type = 'branch' and b.unit_key = {{ source_key('e.company_id', 'e') }}

union all

select
    e.record_version_id,
    e.source_system,
    e.source_instance,
    e.employee_key,
    e.employee_id,
    e.employee_name,
    case when e.company_name is not null
         then e.source_system || ':' || e.source_instance || ':' || e.company_name end,
    coalesce({{ source_key('e.branch_name', 'e') }},
             e.source_system || ':' || e.source_instance || ':unassigned'),
    coalesce({{ source_key('e.department_id', 'e') }},
             e.source_system || ':' || e.source_instance || ':unassigned'),
    'unspecified',
    e.date_of_joining,
    e.relieving_date,
    null::boolean,
    e.source_status,
    e.valid_from,
    e.valid_to,
    e.is_current
from {{ ref('stg_erpnext__employee') }} as e
