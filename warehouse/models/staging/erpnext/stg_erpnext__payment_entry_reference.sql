-- One row per allocation line of a Payment Entry version (child table `references`).
with v as ({{ raw_versions('erpnext', 'Payment Entry') }})
select
    v.record_version_id,
    v.source_system,
    v.source_instance,
    v.valid_from,
    v.valid_to,
    v.valid_to is null as is_current,
    {{ source_key('v.source_id') }} as payment_key,
    ref.line_number::integer as line_number,
    ref.row ->> 'reference_doctype' as reference_doctype,
    ref.row ->> 'reference_name' as reference_id,
    {{ source_key("ref.row ->> 'reference_name'") }} as document_key,
    {{ money("ref.row ->> 'allocated_amount'") }} as allocated_amount
from v
cross join lateral jsonb_array_elements(coalesce(v.payload -> 'references', '[]'))
    with ordinality as ref(row, line_number)
