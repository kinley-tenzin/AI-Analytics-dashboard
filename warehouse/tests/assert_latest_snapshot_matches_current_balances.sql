-- Consistency: on each instance's LATEST accounts snapshot date, the snapshot balance per ledger
-- must equal the current outstanding balance of posted documents dated on or before that date
-- (no extraction happens after the latest snapshot's cutoff). Rows returned = discrepancies.
with latest as (
    select source_instance, max(snapshot_date) as snapshot_date
    from {{ ref('fct_receivable_payable_snapshot') }}
    group by 1
),

snapshot as (
    select f.source_instance, f.ledger, sum(f.outstanding_company) as amount
    from {{ ref('fct_receivable_payable_snapshot') }} as f
    join latest as l using (source_instance, snapshot_date)
    group by 1, 2
),

current_balance as (
    select d.source_instance, d.ledger, sum(d.current_outstanding_company) as amount
    from {{ ref('fct_accounting_document') }} as d
    join latest as l using (source_instance)
    where d.document_state = 'posted' and not d.is_excluded_legacy
      and d.currency_resolution = 'ok'
      and (d.document_date is null or d.document_date <= l.snapshot_date)
    group by 1, 2
)

select coalesce(s.source_instance, c.source_instance) as source_instance,
       coalesce(s.ledger, c.ledger) as ledger, s.amount as snapshot_amount, c.amount as current_amount
from snapshot as s
full join current_balance as c using (source_instance, ledger)
where abs(coalesce(s.amount, 0) - coalesce(c.amount, 0)) > 0.01
