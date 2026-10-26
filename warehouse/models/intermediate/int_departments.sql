-- Departments of both ERPs (current versions) + an explicit 'unassigned' member per instance.
-- Departments are NEVER merged across companies or ERPs, even with equal names (DS-ORG-01).
-- Grain: one row per department per source instance.

with org as (
    select * from {{ ref('int_organisation_units') }} where unit_type = 'branch'
),

odoo as (
    select d.source_system, d.source_instance, d.department_key, d.department_name,
           {{ source_key('d.parent_department_id', 'd') }} as parent_department_key,
           o.organisation_key, d.company_id::text as source_company,
           coalesce(d.is_active, true) as is_active, false as is_group
    from {{ ref('stg_odoo__hr_department') }} as d
    left join org as o on o.unit_key = d.source_system || ':' || d.source_instance || ':' || d.company_id
    where d.is_current
),

erp as (
    select d.source_system, d.source_instance, d.department_key, d.department_name,
           case when d.parent_department_id is not null
                then {{ source_key('d.parent_department_id', 'd') }} end as parent_department_key,
           case when d.company_name is not null
                then d.source_system || ':' || d.source_instance || ':' || d.company_name end,
           d.company_name, d.is_active, d.is_group
    from {{ ref('stg_erpnext__department') }} as d
    where d.is_current
),

departments as (
    select * from odoo
    union all
    select * from erp
)

select * from departments
union all
select distinct source_system, source_instance,
       source_system || ':' || source_instance || ':unassigned', 'Unassigned',
       null::text, null::text, null::text, true, false
from departments
