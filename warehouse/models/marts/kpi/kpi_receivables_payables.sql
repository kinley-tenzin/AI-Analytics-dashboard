-- AC-01 outstanding receivables, AC-02 outstanding payables, AC-03 overdue balance and
-- AC-04 ageing distribution, per snapshot date (docs/data/KPI_CATALOGUE.md).
-- One row per snapshot date x instance x ledger x organisation x branch x ageing bucket.
-- outstanding_amount and overdue_amount are in the organisation's company currency
-- (currency_code): additive except across snapshot dates, and only within one currency.
select
    f.snapshot_date,
    f.source_system,
    f.source_instance,
    f.ledger,
    f.organisation_key,
    o.organisation_name,
    o.currency_code,
    f.branch_key,
    b.branch_name,
    f.ageing_bucket,
    -- Display label whose alphabetical order is the bucket order (for chart axes).
    case f.ageing_bucket
        when 'not_due' then '0 Not yet due'
        when '1_30' then '1 1-30 days overdue'
        when '31_60' then '2 31-60 days overdue'
        when '61_90' then '3 61-90 days overdue'
        when '91_plus' then '4 Over 90 days overdue'
        when 'no_due_date' then '5 No due date'
        when 'unapplied_credit' then '6 Unapplied credit'
    end as ageing_bucket_label,
    sum(f.outstanding_company) as outstanding_amount,
    sum(case when f.is_overdue then f.outstanding_company else 0 end) as overdue_amount,
    count(*) as open_documents
from {{ ref('fct_receivable_payable_snapshot') }} as f
left join {{ ref('dim_organisation') }} as o on o.organisation_key = f.organisation_key
left join {{ ref('dim_branch') }} as b on b.branch_key = f.branch_key
group by 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11
