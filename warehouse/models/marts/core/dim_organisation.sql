-- Conformed legal-organisation dimension (Odoo root companies, ERPNext companies).
-- Grain: one row per organisation per source instance. Type 1 (current attributes).
select
    unit_key as organisation_key,
    source_system,
    source_instance,
    unit_name as organisation_name,
    currency_code
from {{ ref('int_organisation_units') }}
where unit_type = 'organisation'
