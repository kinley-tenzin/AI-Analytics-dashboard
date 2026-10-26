with v as ({{ raw_versions('erpnext', 'Branch') }})
select
    {{ version_columns() }},
    {{ source_key('v.source_id') }} as branch_key,
    v.source_id as branch_name
from v
