-- TRANSACTION fact: payments received / paid (latest version, all states).
-- Grain: one row per payment document per source instance.
-- unallocated_amount = advance not applied to any invoice. It is reported separately and NOT
-- netted against receivables/payables (DS-AC-07).
--   ERPNext: the Payment Entry's own unallocated_amount.
--   Odoo:    the full amount of a posted payment linked to no invoice/bill (Odoo exposes no
--            partial-allocation amounts without account.partial.reconcile).

with odoo as (
    select p.payment_key, p.source_system, p.source_instance, p.payment_number as document_number,
           d.direction, st.document_state, {{ source_key('p.partner_id', 'p') }} as counterparty_key,
           p.payment_date, p.amount, p.currency_code,
           case when cardinality(p.reconciled_move_ids) = 0 then p.amount else 0 end as unallocated_amount
    from {{ ref('stg_odoo__account_payment') }} as p
    join {{ ref('map_payment_state') }} as st
        on st.source_system = 'odoo' and st.source_state = p.source_state
    join {{ ref('map_payment_direction') }} as d
        on d.source_system = 'odoo' and d.source_payment_type = p.payment_type
    where p.is_current
),

erp as (
    select p.payment_key, p.source_system, p.source_instance, p.payment_id,
           d.direction, st.document_state, {{ source_key('p.party_id', 'p') }},
           p.payment_date, p.amount, p.currency_code, p.unallocated_amount
    from {{ ref('stg_erpnext__payment_entry') }} as p
    join {{ ref('map_payment_state') }} as st
        on st.source_system = 'erpnext' and st.source_state = p.docstatus::text
    join {{ ref('map_payment_direction') }} as d
        on d.source_system = 'erpnext' and d.source_payment_type = p.payment_type
    where p.is_current
)

select
    u.*,
    to_char(u.payment_date, 'YYYYMMDD')::integer as payment_date_key
from (select * from odoo union all select * from erp) as u
where u.direction <> 'excluded'
