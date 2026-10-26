-- Supplier dimension (same identity rules as dim_customer).
-- Grain: one row per supplier record per source instance.
select
    partner_key as supplier_key,
    source_system,
    source_instance,
    partner_name as supplier_name,
    tax_id,
    unified_partner_id as unified_supplier_id,
    is_cross_erp_verified
from {{ ref('int_partners') }}
where partner_role = 'supplier'
