{#-
  Declares the grain of a marts table as a PRIMARY KEY (post-hook in models/marts/_marts.yml):

      post_hook:
        - "{{ primary_key(['document_key']) }}"

  The database then rejects duplicate or NULL grain keys itself (in addition to the dbt unique /
  not_null tests), and the key's index speeds up joins and lookups once the tables are large.
  Tables are rebuilt on every run, so the statement never meets an existing key.
-#}
{% macro primary_key(columns) -%}
    alter table {{ this }} add primary key ({{ columns | join(', ') }})
{%- endmacro %}
