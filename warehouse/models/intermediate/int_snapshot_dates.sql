-- Dates on which a dated snapshot EXISTS for a source instance and domain.
-- A snapshot exists only for a local calendar date on which the domain's key entities were
-- actually extracted successfully. Snapshots are never invented for other dates
-- (no history is fabricated from current-state records).
-- Grain: one row per (source_instance, domain, snapshot_date).
{% set tz = var('reporting_timezone') %}

with required_entities as (
    select * from (values
        ('odoo', 'hr', 'hr.employee'),
        ('erpnext', 'hr', 'Employee'),
        ('odoo', 'accounts', 'account.move'),
        ('erpnext', 'accounts', 'Sales Invoice'),
        ('erpnext', 'accounts', 'Purchase Invoice')
    ) as t(source_system, domain, source_entity)
),

successful_runs as (
    select
        r.source_system,
        r.source_instance,
        e.domain,
        r.source_entity,
        (r.window_until at time zone '{{ tz }}')::date as snapshot_date
    from {{ source('raw', 'extraction_run') }} as r
    join required_entities as e using (source_system, source_entity)
    where r.status = 'succeeded'
)

select
    s.source_system,
    s.source_instance,
    s.domain,
    s.snapshot_date,
    -- state "as of the end of the snapshot date": versions first extracted before this instant
    ((s.snapshot_date + 1)::timestamp at time zone '{{ tz }}') as snapshot_cutoff
from successful_runs as s
group by 1, 2, 3, 4
-- every required entity of the domain must have succeeded that day (e.g. both ERPNext invoice types)
having count(distinct s.source_entity) = (
    select count(*) from required_entities as e
    where e.source_system = s.source_system and e.domain = s.domain
)
