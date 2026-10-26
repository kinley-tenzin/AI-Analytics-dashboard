-- Customer dimension. unified_customer_id groups the same customer across ERPs ONLY when a
-- verified mapping exists. Grain: one row per customer record per source instance.
select
    partner_key as customer_key,
    source_system,
    source_instance,
    partner_name as customer_name,
    tax_id,
    unified_partner_id as unified_customer_id,
    is_cross_erp_verified
from {{ ref('int_partners') }}
where partner_role = 'customer'
