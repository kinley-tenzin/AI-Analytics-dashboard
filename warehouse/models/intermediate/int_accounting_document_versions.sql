-- Canonical invoices / credit notes of both ERPs, every extracted version.
-- Amounts follow contracts/canonical/accounts.yaml:
--   * sign: +1 invoice, -1 credit note, applied to abs() of the source amount (independent of
--     each ERP's own sign convention);
--   * company currency at the document's own rate (no revaluation, DS-AC-04);
--   * ERPNext outstanding is in the PARTY ACCOUNT currency: converted with conversion_rate when
--     that currency is the document currency; any other combination is flagged 'currency_unresolved'.
-- Organisation: ERPNext from the document's own company (its 'unassigned' branch has none);
-- Odoo from the branch company's root company.
-- Grain: one row per accounting document version.

with odoo as (
    select
        m.record_version_id, m.source_system, m.source_instance, m.document_key,
        m.move_id::text as source_document_id, m.document_number,
        m.move_type as source_document_type, null::integer as is_return,
        m.source_state, m.payment_state as source_payment_status,
        {{ source_key('m.partner_id', 'm') }} as counterparty_key,
        {{ source_key('m.company_id', 'm') }} as branch_key,
        null::text as organisation_key,                 -- resolved via the branch (root company)
        m.document_date, m.due_date, m.currency_code,
        abs(m.amount_total) as amount_total_document,
        abs(m.amount_total_signed_company) as amount_total_company_abs,
        abs(m.amount_residual_signed_company) as outstanding_company_abs,
        m.payment_state = 'invoicing_legacy' as is_excluded_legacy,
        null::text as return_against_key,
        null::integer as update_outstanding_for_self,
        'ok' as currency_resolution,
        m.valid_from, m.valid_to, m.is_current
    from {{ ref('stg_odoo__account_move') }} as m
),

erp_docs as (
    select * from {{ ref('stg_erpnext__sales_invoice') }}
    union all
    select * from {{ ref('stg_erpnext__purchase_invoice') }}
),

erp_company as (
    select source_instance, company_name, default_currency
    from {{ ref('stg_erpnext__company') }} where is_current
),

erp as (
    select
        d.record_version_id, d.source_system, d.source_instance, d.document_key,
        d.invoice_id, d.invoice_id, d.doctype, d.is_return,
        d.docstatus::text, d.source_status,
        {{ source_key('d.party_id', 'd') }},
        d.source_system || ':' || d.source_instance || ':unassigned',   -- no branch on invoices (DS-AC-05)
        {{ source_key('d.company_name', 'd') }},       -- every ERPNext invoice names its company
        d.document_date, d.due_date, d.currency_code,
        abs(d.grand_total),
        abs(d.base_grand_total),
        case
            when d.party_account_currency = c.default_currency then abs(d.outstanding_amount)
            when d.party_account_currency = d.currency_code then abs(d.outstanding_amount) * d.conversion_rate
        end,
        false,
        case when d.return_against_id is not null then {{ source_key('d.return_against_id', 'd') }} end,
        d.update_outstanding_for_self,
        case
            when d.party_account_currency = c.default_currency
              or d.party_account_currency = d.currency_code then 'ok'
            else 'currency_unresolved'
        end,
        d.valid_from, d.valid_to, d.is_current
    from erp_docs as d
    left join erp_company as c using (source_instance, company_name)
),

unioned as (
    select * from odoo
    union all
    select * from erp
)

select
    u.record_version_id, u.source_system, u.source_instance, u.document_key,
    u.source_document_id, u.document_number, u.source_document_type, u.source_state,
    u.source_payment_status, t.ledger, t.document_kind, st.document_state,
    u.counterparty_key, u.branch_key, coalesce(u.organisation_key, b.organisation_key) as organisation_key,
    u.document_date, u.due_date, u.currency_code,
    u.amount_total_document,
    sg.document_sign * u.amount_total_company_abs as amount_total_company,
    sg.document_sign * u.outstanding_company_abs as outstanding_company,
    u.is_excluded_legacy, u.currency_resolution, u.return_against_key, u.update_outstanding_for_self,
    u.valid_from, u.valid_to, u.is_current
from unioned as u
join {{ ref('map_document_type') }} as t
    on t.source_system = u.source_system
   and t.source_document_type = u.source_document_type
   and coalesce(t.is_return, -1) = coalesce(u.is_return, -1)
join {{ ref('map_document_state') }} as st
    on st.source_system = u.source_system and st.source_state = u.source_state
join {{ ref('map_document_sign') }} as sg on sg.document_kind = t.document_kind
left join {{ ref('int_organisation_units') }} as b
    on b.unit_type = 'branch' and b.unit_key = u.branch_key
