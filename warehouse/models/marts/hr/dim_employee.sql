-- Employee dimension, Type 1 (current attributes only).
-- Why not SCD Type 2: no requirement asks for an employee's attribute history on its own; the
-- point-in-time department/branch/status needed for KPIs is stored on fct_headcount_snapshot.
-- Grain: one row per employee per source instance. Names are display-only, never join keys.
select
    employee_key,
    source_system,
    source_instance,
    source_employee_id,
    employee_name,
    organisation_key,
    branch_key,
    department_key,
    employee_category,
    joined_on,
    left_on
from {{ ref('int_employee_versions') }}
where is_current
