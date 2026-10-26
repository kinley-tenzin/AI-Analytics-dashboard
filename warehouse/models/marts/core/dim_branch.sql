-- Conformed branch dimension (Odoo companies incl. head office, ERPNext Branch master,
-- plus one 'Unassigned' member per instance). Grain: one row per branch per source instance.
select
    b.unit_key as branch_key,
    b.source_system,
    b.source_instance,
    b.unit_name as branch_name,
    b.organisation_key,
    o.unit_name as organisation_name,
    b.resolution as organisation_resolution
from {{ ref('int_organisation_units') }} as b
left join {{ ref('int_organisation_units') }} as o
    on o.unit_type = 'organisation' and o.unit_key = b.organisation_key
where b.unit_type = 'branch'
