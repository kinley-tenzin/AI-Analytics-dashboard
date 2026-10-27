{#-
  Declares a fact -> dimension relationship as a FOREIGN KEY (post-hook in models/marts/_marts.yml):

      post_hook:
        - "{{ foreign_key('employee_key', 'dim_employee', 'employee_key') }}"

  The parent is addressed with ref(), so it lives in the same schema as this table (the hidden
  build schema while the pipeline builds, `marts` for a manual run) and is built first. The
  database then refuses a fact row whose dimension member does not exist, in addition to the dbt
  `relationships` tests. NULL keys are allowed (e.g. a document without a due date).
-#}
{% macro foreign_key(column, parent_model, parent_column) -%}
    alter table {{ this }} add foreign key ({{ column }}) references {{ ref(parent_model) }} ({{ parent_column }})
{%- endmacro %}
