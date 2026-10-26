-- Raw landing tables for ERP extraction (Milestone 3).
-- Applied by `python -m ingestion migrate` as the pipeline role (owner of schema raw).
-- Strategy: append-only VERSION history. One row per distinct payload of a source record;
-- re-extracting an identical record only updates last_seen columns (no duplicate rows).

CREATE TABLE raw.extraction_run (
    run_id                uuid PRIMARY KEY,
    source_system         text NOT NULL CHECK (source_system IN ('odoo', 'erpnext')),
    source_instance       text NOT NULL,
    source_entity         text NOT NULL,
    mode                  text NOT NULL CHECK (mode IN ('full', 'incremental')),
    status                text NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    contract_version      text NOT NULL,
    window_from           timestamptz,             -- exclusive; NULL = from the beginning
    window_until          timestamptz NOT NULL,    -- inclusive; becomes the checkpoint on success
    started_at            timestamptz NOT NULL DEFAULT now(),
    finished_at           timestamptz,
    pages                 integer NOT NULL DEFAULT 0,
    records_fetched       integer NOT NULL DEFAULT 0,
    records_inserted      integer NOT NULL DEFAULT 0,  -- new record versions
    records_unchanged     integer NOT NULL DEFAULT 0,  -- identical version already stored
    records_duplicate     integer NOT NULL DEFAULT 0,  -- same source id seen twice in this run
    records_quarantined   integer NOT NULL DEFAULT 0,  -- contract errors
    records_with_warnings integer NOT NULL DEFAULT 0,
    last_source_id        text,                        -- keyset cursor of the last stored page
    error_type            text,
    error_message         text
);
CREATE INDEX extraction_run_entity_idx
    ON raw.extraction_run (source_system, source_instance, source_entity, started_at DESC);

COMMENT ON TABLE raw.extraction_run IS
    'One row per entity extraction attempt: window, status, counters and error (the extraction log).';

CREATE TABLE raw.source_record (
    record_version_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_system       text NOT NULL,
    source_instance     text NOT NULL,
    source_entity       text NOT NULL,
    source_id           text NOT NULL,
    payload             jsonb NOT NULL,              -- record as returned by the API
    payload_sha256      char(64) NOT NULL,
    source_modified_at  timestamptz,                 -- write_date / modified, in UTC
    contract_version    text NOT NULL,
    validation_warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
    first_run_id        uuid NOT NULL REFERENCES raw.extraction_run (run_id),
    first_extracted_at  timestamptz NOT NULL,
    last_run_id         uuid NOT NULL REFERENCES raw.extraction_run (run_id),
    last_extracted_at   timestamptz NOT NULL,
    times_seen          integer NOT NULL DEFAULT 1,
    CONSTRAINT source_record_version_uq
        UNIQUE (source_system, source_instance, source_entity, source_id, payload_sha256)
);
CREATE INDEX source_record_current_idx
    ON raw.source_record (source_system, source_instance, source_entity, source_id, last_extracted_at DESC);

COMMENT ON TABLE raw.source_record IS
    'Append-only versions of ERP records with provenance. Identical re-extractions update last_* only.';

CREATE TABLE raw.quarantined_record (
    quarantine_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id          uuid NOT NULL REFERENCES raw.extraction_run (run_id),
    source_system   text NOT NULL,
    source_instance text NOT NULL,
    source_entity   text NOT NULL,
    source_id       text,                            -- NULL when the id itself is missing
    payload         jsonb NOT NULL,
    issues          jsonb NOT NULL,
    quarantined_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX quarantined_record_entity_idx
    ON raw.quarantined_record (source_system, source_instance, source_entity, quarantined_at DESC);

COMMENT ON TABLE raw.quarantined_record IS
    'Records that broke the source contract; never promoted downstream. Kept for investigation.';

CREATE TABLE raw.extraction_checkpoint (
    source_system   text NOT NULL,
    source_instance text NOT NULL,
    source_entity   text NOT NULL,
    checkpoint_at   timestamptz NOT NULL,   -- window_until of the last SUCCESSFUL run
    last_run_id     uuid NOT NULL REFERENCES raw.extraction_run (run_id),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_system, source_instance, source_entity)
);

-- Latest version of every record (the current state as last extracted).
CREATE VIEW raw.current_source_record AS
SELECT DISTINCT ON (source_system, source_instance, source_entity, source_id) *
FROM raw.source_record
ORDER BY source_system, source_instance, source_entity, source_id,
         last_extracted_at DESC, record_version_id DESC;
