{{ config(materialized='table') }}
-- Freshness of the PUBLISHED datasets, for Superset / AI to display ("data as of ...").
-- Grain: one row per source instance x domain (hr / accounts).
-- Built together with the other marts; published_at, pipeline_run_id and source_mode are
-- filled in by warehouse/publish.py inside the publication transaction, so they always
-- describe exactly the marts that are visible. NULL published_at = built but never published
-- (e.g. a manual dev build).
select
    source_system,
    source_instance,
    domain,
    max(snapshot_date) as latest_snapshot_date,
    count(*) as snapshot_dates_available,
    now() as built_at,
    null::timestamptz as published_at,
    null::text as pipeline_run_id,
    null::text as source_mode
from {{ ref('int_snapshot_dates') }}
group by 1, 2, 3
