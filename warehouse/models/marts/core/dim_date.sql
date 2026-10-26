-- Conformed calendar dimension. Grain: one row per calendar date.
select
    to_char(d, 'YYYYMMDD')::integer as date_key,
    d::date as calendar_date,
    extract(year from d)::integer as year,
    extract(quarter from d)::integer as quarter,
    extract(month from d)::integer as month,
    to_char(d, 'FMMonth') as month_name,
    to_char(d, 'YYYY-MM') as year_month,
    date_trunc('month', d)::date as month_start,
    (date_trunc('month', d) + interval '1 month - 1 day')::date as month_end,
    extract(isodow from d)::integer as iso_day_of_week,
    to_char(d, 'FMDay') as day_name,
    extract(isodow from d) in (6, 7) as is_weekend
from generate_series(
    '{{ var("date_dimension_start") }}'::date,
    '{{ var("date_dimension_end") }}'::date,
    interval '1 day'
) as d
