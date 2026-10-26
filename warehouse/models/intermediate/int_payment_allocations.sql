-- Payment-to-document allocations of POSTED payments (current versions), for reconciliation.
-- ERPNext: exact allocated amounts from Payment Entry references.
-- Odoo: links from reconciled_invoice_ids / reconciled_bill_ids carry no per-document amount;
--       the full payment amount is attributed only when the payment links to exactly one
--       document (allocation_basis = 'single_link'), otherwise 'ambiguous' (no amount).
-- Grain: one row per (payment, document) link.

with odoo_payments as (
    select p.*, st.document_state, cardinality(p.reconciled_move_ids) as link_count
    from {{ ref('stg_odoo__account_payment') }} as p
    join {{ ref('map_payment_state') }} as st
        on st.source_system = p.source_system and st.source_state = p.source_state
    where p.is_current
),

erp_payments as (
    select p.*, st.document_state
    from {{ ref('stg_erpnext__payment_entry') }} as p
    join {{ ref('map_payment_state') }} as st
        on st.source_system = p.source_system and st.source_state = p.docstatus::text
    where p.is_current
)

select
    p.source_system, p.source_instance, p.payment_key,
    {{ source_key('linked.move_id', 'p') }} as document_key,
    case when p.link_count = 1 then p.amount end as allocated_amount,
    p.currency_code,
    case when p.link_count = 1 then 'single_link' else 'ambiguous' end as allocation_basis,
    p.payment_date
from odoo_payments as p
cross join lateral unnest(p.reconciled_move_ids) as linked(move_id)
where p.document_state = 'posted'

union all

select
    p.source_system, p.source_instance, p.payment_key, r.document_key, r.allocated_amount,
    p.currency_code, 'exact', p.payment_date
from erp_payments as p
join {{ ref('stg_erpnext__payment_entry_reference') }} as r
    on r.record_version_id = p.record_version_id
where p.document_state = 'posted'
