with v as ({{ raw_versions('odoo', 'account.move') }})
select
    {{ version_columns() }},
    {{ source_key('v.source_id') }} as document_key,
    v.source_id::integer as move_id,
    {{ odoo_text('name') }} as document_number,
    {{ odoo_text('move_type') }} as move_type,
    {{ odoo_text('state') }} as source_state,
    {{ odoo_text('payment_state') }} as payment_state,
    {{ odoo_m2o_id('partner_id') }} as partner_id,
    {{ odoo_m2o_id('company_id') }} as company_id,
    {{ odoo_text('invoice_date') }}::date as document_date,
    {{ odoo_text('invoice_date_due') }}::date as due_date,
    {{ odoo_m2o_name('currency_id') }} as currency_code,
    {{ money("v.payload ->> 'amount_total'") }} as amount_total,
    {{ money("v.payload ->> 'amount_residual'") }} as amount_residual,
    {{ money("v.payload ->> 'amount_total_signed'") }} as amount_total_signed_company,
    {{ money("v.payload ->> 'amount_residual_signed'") }} as amount_residual_signed_company,
    {{ odoo_m2o_id('reversed_entry_id') }} as reversed_move_id
from v
