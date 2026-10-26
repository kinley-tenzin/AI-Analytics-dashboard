with v as ({{ raw_versions('odoo', 'account.payment') }})
select
    {{ version_columns() }},
    {{ source_key('v.source_id') }} as payment_key,
    v.source_id::integer as payment_id,
    {{ odoo_text('name') }} as payment_number,
    {{ odoo_text('payment_type') }} as payment_type,
    {{ odoo_text('partner_type') }} as partner_type,
    {{ odoo_text('state') }} as source_state,
    {{ odoo_m2o_id('partner_id') }} as partner_id,
    {{ money("v.payload ->> 'amount'") }} as amount,
    {{ odoo_m2o_name('currency_id') }} as currency_code,
    {{ odoo_text('date') }}::date as payment_date,
    array(select jsonb_array_elements_text(coalesce(v.payload -> 'reconciled_invoice_ids', '[]'))::integer)
        || array(select jsonb_array_elements_text(coalesce(v.payload -> 'reconciled_bill_ids', '[]'))::integer)
        as reconciled_move_ids
from v
