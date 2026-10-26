with v as ({{ raw_versions('odoo', 'res.partner') }})
select
    {{ version_columns() }},
    {{ source_key('v.source_id') }} as partner_key,
    v.source_id::integer as partner_id,
    {{ odoo_text('name') }} as partner_name,
    {{ odoo_text('vat') }} as tax_id,
    coalesce(({{ odoo_text('customer_rank') }})::integer, 0) as customer_rank,
    coalesce(({{ odoo_text('supplier_rank') }})::integer, 0) as supplier_rank
from v
