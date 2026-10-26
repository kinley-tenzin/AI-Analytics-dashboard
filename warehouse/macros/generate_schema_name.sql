{#
    Use the configured schema names exactly (staging / intermediate / marts) instead of dbt's
    default "<target_schema>_<custom_schema>" prefixing. These schemas are created and permissioned
    by the PostgreSQL init script (marts is the only schema the BI reader may query).

    The orchestrated pipeline builds marts into a hidden schema first
    (--vars '{marts_schema: marts_build}'), tests them there, and only then publishes them by an
    atomic schema swap (warehouse/publish.py). Manual dev builds go straight to `marts`.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- elif custom_schema_name | trim == 'marts' -%}
        {{ var('marts_schema', 'marts') }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
