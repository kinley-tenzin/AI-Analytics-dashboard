-- Publication log (Milestone 5): one row each time validated marts are published (swapped in).
-- Written by warehouse/publish.py in the same transaction as the schema swap.

CREATE TABLE raw.publication (
    publication_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    published_at      timestamptz NOT NULL DEFAULT now(),
    pipeline_run_id   text NOT NULL,           -- Airflow dag_run id (or "manual")
    source_mode       text NOT NULL CHECK (source_mode IN ('configured', 'synthetic')),
    build_schema      text NOT NULL,
    relations         integer NOT NULL,        -- tables + views published
    data_as_of        jsonb NOT NULL           -- latest snapshot date per domain / instance
);

COMMENT ON TABLE raw.publication IS
    'Audit log of marts publications; KPIs are only visible to BI/AI after a logged publication.';
