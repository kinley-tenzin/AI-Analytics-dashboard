-- PERIODIC SNAPSHOT fact of open receivables and payables.
-- Grain: one row per POSTED accounting document with a non-zero outstanding balance, per
-- accounts snapshot date, per source instance. Snapshot dates = dates with a successful
-- extraction of the instance's invoice entities (never fabricated).
-- Measure: outstanding_company (company currency; invoices +, unapplied credit notes -).
-- Additive across documents, customers, branches and buckets; NOT across snapshot dates.
-- Excluded: drafts, cancelled documents, Odoo 'invoicing_legacy', documents dated after D,
-- and documents whose currency could not be resolved (surfaced by a dbt test instead).

with snapshots as (
    select * from {{ ref('int_snapshot_dates') }} where domain = 'accounts'
),

open_items as (
    select s.snapshot_date, d.*
    from snapshots as s
    join {{ ref('int_accounting_document_versions') }} as d
        on d.source_instance = s.source_instance
       and d.valid_from < s.snapshot_cutoff
       and (d.valid_to is null or d.valid_to >= s.snapshot_cutoff)
    where d.document_state = 'posted'
      and not d.is_excluded_legacy
      and d.currency_resolution = 'ok'
      and d.outstanding_company <> 0
      and (d.document_date is null or d.document_date <= s.snapshot_date)
),

partners as (
    select partner_key, partner_role, unified_partner_id from {{ ref('int_partners') }}
)

select
    to_char(o.snapshot_date, 'YYYYMMDD')::integer as snapshot_date_key,
    o.snapshot_date,
    o.document_key,
    o.source_system,
    o.source_instance,
    o.ledger,
    o.document_kind,
    o.counterparty_key,
    coalesce(p.unified_partner_id, o.counterparty_key) as unified_counterparty_id,
    o.branch_key,
    o.organisation_key,
    o.document_date,
    o.due_date,
    o.currency_code,
    o.outstanding_company,
    o.snapshot_date - o.due_date as days_overdue,
    case
        when o.outstanding_company < 0 then 'unapplied_credit'
        when o.due_date is null then 'no_due_date'
        when o.snapshot_date - o.due_date <= 0 then 'not_due'
        when o.snapshot_date - o.due_date <= 30 then '1_30'
        when o.snapshot_date - o.due_date <= 60 then '31_60'
        when o.snapshot_date - o.due_date <= 90 then '61_90'
        else '91_plus'
    end as ageing_bucket,
    (o.outstanding_company > 0 and o.due_date < o.snapshot_date) as is_overdue,
    o.record_version_id
from open_items as o
left join partners as p
    on p.partner_key = o.counterparty_key
   and p.partner_role = case o.ledger when 'receivable' then 'customer' else 'supplier' end
