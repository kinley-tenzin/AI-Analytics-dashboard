-- Business partners (customers and suppliers) of both ERPs, current versions, with the
-- cross-ERP unified id taken ONLY from verified mappings (seed verified_entity_mappings).
-- Unmapped partners keep their own key as unified id: equal names or tax ids never merge.
-- Grain: one row per partner per role (customer / supplier).

with partners as (
    select source_system, source_instance, partner_key, partner_name, tax_id, 'customer' as partner_role
    from {{ ref('stg_odoo__res_partner') }} where is_current and customer_rank > 0
    union all
    select source_system, source_instance, partner_key, partner_name, tax_id, 'supplier'
    from {{ ref('stg_odoo__res_partner') }} where is_current and supplier_rank > 0
    union all
    select source_system, source_instance, partner_key, customer_name, tax_id, 'customer'
    from {{ ref('stg_erpnext__customer') }} where is_current
    union all
    select source_system, source_instance, partner_key, supplier_name, tax_id, 'supplier'
    from {{ ref('stg_erpnext__supplier') }} where is_current
),

mapping as (
    select member_key, unified_id from {{ ref('verified_entity_mappings') }}
    where entity = 'business_partner'
)

select
    p.*,
    coalesce(m.unified_id, p.partner_key) as unified_partner_id,
    m.unified_id is not null as is_cross_erp_verified
from partners as p
left join mapping as m on m.member_key = p.partner_key
