-- Reconciliation (ERPNext): for every current, posted, non-return invoice,
--   settled = base_grand_total - outstanding (party account currency = company currency)
-- must equal the posted Payment Entry allocations plus returns that reduce the original
-- (update_outstanding_for_self = 0). Rows returned = discrepancies.
with invoices as (
    select source_instance, document_key, base_grand_total - outstanding_amount as settled
    from {{ ref('stg_erpnext__sales_invoice') }}
    where is_current and docstatus = 1 and is_return = 0
    union all
    select source_instance, document_key, base_grand_total - outstanding_amount
    from {{ ref('stg_erpnext__purchase_invoice') }}
    where is_current and docstatus = 1 and is_return = 0
),

applied_returns as (
    select source_instance, return_against_key as document_key, abs(amount_total_company) as amount
    from {{ ref('int_accounting_document_versions') }}
    where source_system = 'erpnext' and is_current and document_state = 'posted'
      and document_kind = 'credit_note' and return_against_key is not null
      and coalesce(update_outstanding_for_self, 1) = 0
),

allocations as (
    select source_instance, document_key, allocated_amount as amount
    from {{ ref('int_payment_allocations') }}
    where source_system = 'erpnext'
),

explained as (
    select source_instance, document_key, sum(amount) as amount
    from (select * from applied_returns union all select * from allocations) as x
    group by 1, 2
)

select i.source_instance, i.document_key, i.settled, coalesce(e.amount, 0) as explained
from invoices as i
left join explained as e using (source_instance, document_key)
where abs(i.settled - coalesce(e.amount, 0)) > 0.01
