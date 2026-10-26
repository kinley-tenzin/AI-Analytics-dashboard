{#
    Generic test: the combination of `columns` is unique (enforces a model's declared grain).
    Usage in YAML:
        data_tests:
          - unique_combination:
              arguments:
                columns: [snapshot_date, document_key]
#}
{% test unique_combination(model, columns) %}
select {{ columns | join(', ') }}, count(*) as occurrences
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}
