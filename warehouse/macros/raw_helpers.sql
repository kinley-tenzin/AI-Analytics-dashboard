{#
    Helpers for reading raw ERP payloads (jsonb) in staging models.

    raw_versions(system, entity)
        Every stored version of every record of one source entity, with a validity window:
        valid_from = when this version was first extracted, valid_to = when the next version was
        first extracted (NULL = current). See docs/warehouse/WAREHOUSE.md for the limitation on
        A -> B -> A reversions.
#}
{% macro raw_versions(system, entity) %}
    select
        r.record_version_id,
        r.source_system,
        r.source_instance,
        r.source_entity,
        r.source_id,
        r.payload,
        r.payload_sha256,
        r.contract_version,
        r.source_modified_at,
        r.first_extracted_at as valid_from,
        lead(r.first_extracted_at) over (
            partition by r.source_instance, r.source_id
            order by r.first_extracted_at, r.record_version_id
        ) as valid_to
    from {{ source('raw', 'source_record') }} as r
    where r.source_system = '{{ system }}'
      and r.source_entity = '{{ entity }}'
{% endmacro %}

{# Provenance and version columns every staging model exposes. #}
{% macro version_columns(alias='v') %}
    {{ alias }}.record_version_id,
    {{ alias }}.source_system,
    {{ alias }}.source_instance,
    {{ alias }}.source_id,
    {{ alias }}.source_modified_at,
    {{ alias }}.valid_from,
    {{ alias }}.valid_to,
    {{ alias }}.valid_to is null as is_current,
    {{ alias }}.contract_version
{% endmacro %}

{# Canonical key "system:instance:id" (never shared between ERPs or instances). #}
{% macro source_key(id_expr, alias='v') -%}
    ({{ alias }}.source_system || ':' || {{ alias }}.source_instance || ':' || ({{ id_expr }})::text)
{%- endmacro %}

{# Odoo returns `false` for empty non-boolean fields: treat it as NULL. #}
{% macro odoo_text(field) -%}
    (case when jsonb_typeof(payload -> '{{ field }}') in ('string', 'number')
          then payload ->> '{{ field }}' end)
{%- endmacro %}

{# Odoo many2one = [id, "display name"] or false. #}
{% macro odoo_m2o_id(field) -%}
    (case when jsonb_typeof(payload -> '{{ field }}') = 'array'
          then (payload -> '{{ field }}' ->> 0)::integer end)
{%- endmacro %}

{% macro odoo_m2o_name(field) -%}
    (case when jsonb_typeof(payload -> '{{ field }}') = 'array'
          then payload -> '{{ field }}' ->> 1 end)
{%- endmacro %}

{# ERPNext returns null (or "" for some Data fields) for empty values. #}
{% macro erp_text(field) -%}
    nullif(payload ->> '{{ field }}', '')
{%- endmacro %}

{% macro money(expr) -%}
    ({{ expr }})::numeric(20, 4)
{%- endmacro %}
