-- Legal organisations (companies) and branches of both ERPs, current versions.
-- Odoo: a branch is a child company (parent_id); its organisation is the ROOT company.
--       The root company itself also acts as the head-office branch.
-- ERPNext: organisations are Companies; branches are the Branch master. Branch has no company
--       link, so a branch is attached to an organisation only when the instance has exactly one
--       company; otherwise organisation_key stays NULL (resolution = 'ambiguous').
-- Every instance also gets an explicit 'unassigned' branch for records without one.
-- Grain: one row per branch (unit_type = 'branch') or organisation (unit_type = 'organisation').

with recursive odoo_companies as (
    select * from {{ ref('stg_odoo__res_company') }} where is_current
),

odoo_roots (source_instance, company_id, root_company_id) as (
    select source_instance, company_id, company_id
    from odoo_companies where parent_company_id is null
    union all
    select c.source_instance, c.company_id, r.root_company_id
    from odoo_companies as c
    join odoo_roots as r
        on r.source_instance = c.source_instance and r.company_id = c.parent_company_id
),

erp_companies as (
    select * from {{ ref('stg_erpnext__company') }} where is_current
),

erp_single_company as (
    select source_instance, min(company_key) as company_key
    from erp_companies group by source_instance having count(*) = 1
),

units as (
    -- organisations
    select 'organisation' as unit_type, c.source_system, c.source_instance, c.company_key as unit_key,
           c.company_name as unit_name, c.company_key as organisation_key, c.currency_code,
           'source' as resolution
    from odoo_companies as c where c.parent_company_id is null
    union all
    select 'organisation', e.source_system, e.source_instance, e.company_key, e.company_name,
           e.company_key, e.default_currency, 'source'
    from erp_companies as e
    union all
    -- Odoo branches (every company, incl. the root as head office)
    select 'branch', c.source_system, c.source_instance, c.company_key,
           case when c.parent_company_id is null then c.company_name || ' (head office)' else c.company_name end,
           c.source_system || ':' || c.source_instance || ':' || r.root_company_id,
           c.currency_code, 'source'
    from odoo_companies as c
    join odoo_roots as r using (source_instance, company_id)
    union all
    -- ERPNext branches
    select 'branch', b.source_system, b.source_instance, b.branch_key, b.branch_name,
           s.company_key, null,
           case when s.company_key is null then 'ambiguous' else 'single_company_instance' end
    from {{ ref('stg_erpnext__branch') }} as b
    left join erp_single_company as s using (source_instance)
    where b.is_current
),

instances as (
    select distinct source_system, source_instance from units
)

select * from units
union all
-- explicit 'unassigned' branch per instance
select 'branch', i.source_system, i.source_instance,
       i.source_system || ':' || i.source_instance || ':unassigned', 'Unassigned', null, null, 'unassigned'
from instances as i
