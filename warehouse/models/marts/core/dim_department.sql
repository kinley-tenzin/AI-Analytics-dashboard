-- Conformed department dimension. Same-named departments in different companies or ERPs stay
-- separate rows. Grain: one row per department per source instance (+ 'Unassigned').
select
    department_key,
    source_system,
    source_instance,
    department_name,
    parent_department_key,
    organisation_key,
    is_active,
    is_group
from {{ ref('int_departments') }}
