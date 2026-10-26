-- Reconciliation (Odoo): for current, posted invoices / vendor bills that are not reversed and
-- whose payments link to exactly one document, amount_total - amount_residual (document
-- currency) must equal the posted payments linked to them. Documents with an ambiguous
-- (multi-document) payment are skipped: Odoo exposes those amounts only in
-- account.partial.reconcile, which is deferred. Rows returned = discrepancies.
with documents as (
    select source_instance, document_key, amount_total - amount_residual as settled
    from {{ ref('stg_odoo__account_move') }}
    where is_current and source_state = 'posted'
      and move_type in ('out_invoice', 'in_invoice')
      and payment_state <> 'reversed'
),

links as (
    select source_instance, document_key, allocated_amount, allocation_basis
    from {{ ref('int_payment_allocations') }}
    where source_system = 'odoo'
),

ambiguous as (
    select distinct document_key from links where allocation_basis = 'ambiguous'
),

paid as (
    select source_instance, document_key, sum(allocated_amount) as amount
    from links group by 1, 2
)

select d.source_instance, d.document_key, d.settled, coalesce(p.amount, 0) as paid
from documents as d
left join paid as p using (source_instance, document_key)
where d.document_key not in (select document_key from ambiguous)
  and abs(d.settled - coalesce(p.amount, 0)) > 0.01
