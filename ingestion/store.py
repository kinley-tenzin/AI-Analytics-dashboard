"""PostgreSQL persistence for extraction runs, raw record versions, quarantine and checkpoints."""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb

from druksmart_common.contracts import Issue, RawRecord


class ExtractionAlreadyRunningError(RuntimeError):
    """Another process is extracting the same entity from the same source instance."""


@dataclass(frozen=True)
class PageCounts:
    inserted: int
    unchanged: int


UPSERT_VERSION = """
INSERT INTO raw.source_record (
    source_system, source_instance, source_entity, source_id, payload, payload_sha256,
    source_modified_at, contract_version, validation_warnings,
    first_run_id, first_extracted_at, last_run_id, last_extracted_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT ON CONSTRAINT source_record_version_uq DO UPDATE SET
    last_run_id = EXCLUDED.last_run_id,
    last_extracted_at = EXCLUDED.last_extracted_at,
    times_seen = raw.source_record.times_seen
        + CASE WHEN raw.source_record.last_run_id = EXCLUDED.last_run_id THEN 0 ELSE 1 END
RETURNING (xmax = 0) AS inserted
"""


class RawStore:
    """All writes for one extraction go through here; each page is its own transaction."""

    def __init__(self, conn: psycopg.Connection):
        # With autocommit on, every `with conn.transaction()` block is exactly one
        # BEGIN ... COMMIT, so each page is durable as soon as it is saved.
        if not conn.autocommit:
            raise ValueError("RawStore needs a connection opened with autocommit=True")
        self.conn = conn

    # ---------------------------------------------------------------------- locks

    @contextlib.contextmanager
    def entity_lock(self, source_system: str, source_instance: str, entity: str) -> Iterator[None]:
        """Session advisory lock so two runs never extract the same entity concurrently."""
        key = f"druksmart:{source_system}:{source_instance}:{entity}"
        with self.conn.transaction():
            got = self.conn.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", (key,)
            ).fetchone()[0]
        if not got:
            raise ExtractionAlreadyRunningError(f"{key} is already being extracted")
        try:
            yield
        finally:
            with self.conn.transaction():
                self.conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (key,))

    # ------------------------------------------------------------------ checkpoints

    def get_checkpoint(
        self, source_system: str, source_instance: str, entity: str
    ) -> datetime | None:
        with self.conn.transaction():
            row = self.conn.execute(
                "SELECT checkpoint_at FROM raw.extraction_checkpoint "
                "WHERE source_system = %s AND source_instance = %s AND source_entity = %s",
                (source_system, source_instance, entity),
            ).fetchone()
        return row[0] if row else None

    # ------------------------------------------------------------------------- runs

    def start_run(
        self,
        *,
        source_system: str,
        source_instance: str,
        entity: str,
        mode: str,
        contract_version: str,
        window_from: datetime | None,
        window_until: datetime,
    ) -> uuid.UUID:
        run_id = uuid.uuid4()
        with self.conn.transaction():
            self.conn.execute(
                "INSERT INTO raw.extraction_run (run_id, source_system, source_instance, "
                "source_entity, mode, status, contract_version, window_from, window_until) "
                "VALUES (%s, %s, %s, %s, %s, 'running', %s, %s, %s)",
                (
                    run_id,
                    source_system,
                    source_instance,
                    entity,
                    mode,
                    contract_version,
                    window_from,
                    window_until,
                ),
            )
        return run_id

    def save_page(
        self,
        run_id: uuid.UUID,
        records: Sequence[tuple[RawRecord, list[Issue]]],
        quarantined: Sequence[tuple[dict, str | None, list[Issue]]],
        *,
        fetched: int,
        duplicates: int,
        last_source_id: str,
    ) -> PageCounts:
        """Store one page atomically: record versions, quarantine rows and run counters."""
        inserted = unchanged = 0
        with self.conn.transaction():
            for raw, warnings in records:
                row = self.conn.execute(
                    UPSERT_VERSION,
                    (
                        raw.source_system,
                        raw.source_instance,
                        raw.source_entity,
                        raw.source_id,
                        Jsonb(raw.payload),
                        raw.payload_sha256,
                        raw.source_modified_at,
                        raw.contract_version,
                        Jsonb([asdict(w) for w in warnings]),
                        run_id,
                        raw.extracted_at,
                        run_id,
                        raw.extracted_at,
                    ),
                ).fetchone()
                if row[0]:
                    inserted += 1
                else:
                    unchanged += 1
            for payload, source_id, issues in quarantined:
                self.conn.execute(
                    "INSERT INTO raw.quarantined_record (run_id, source_system, source_instance, "
                    "source_entity, source_id, payload, issues) "
                    "SELECT run_id, source_system, source_instance, source_entity, %s, %s, %s "
                    "FROM raw.extraction_run WHERE run_id = %s",
                    (source_id, Jsonb(payload), Jsonb([asdict(i) for i in issues]), run_id),
                )
            self.conn.execute(
                "UPDATE raw.extraction_run SET pages = pages + 1, "
                "records_fetched = records_fetched + %s, records_inserted = records_inserted + %s, "
                "records_unchanged = records_unchanged + %s, "
                "records_duplicate = records_duplicate + %s, "
                "records_quarantined = records_quarantined + %s, "
                "records_with_warnings = records_with_warnings + %s, last_source_id = %s "
                "WHERE run_id = %s",
                (
                    fetched,
                    inserted,
                    unchanged,
                    duplicates,
                    len(quarantined),
                    sum(1 for _, w in records if w),
                    last_source_id,
                    run_id,
                ),
            )
        return PageCounts(inserted, unchanged)

    def finish_run(
        self, run_id: uuid.UUID, *, succeeded: bool, error: BaseException | None = None
    ) -> dict:
        """Close the run; on success the window end becomes the entity's checkpoint."""
        with self.conn.transaction():
            self.conn.execute(
                "UPDATE raw.extraction_run SET status = %s, finished_at = now(), "
                "error_type = %s, error_message = %s WHERE run_id = %s",
                (
                    "succeeded" if succeeded else "failed",
                    type(error).__name__ if error else None,
                    str(error)[:2000] if error else None,
                    run_id,
                ),
            )
            if succeeded:
                self.conn.execute(
                    "INSERT INTO raw.extraction_checkpoint "
                    "(source_system, source_instance, source_entity, checkpoint_at, last_run_id) "
                    "SELECT source_system, source_instance, source_entity, window_until, run_id "
                    "FROM raw.extraction_run WHERE run_id = %s "
                    "ON CONFLICT (source_system, source_instance, source_entity) DO UPDATE SET "
                    "checkpoint_at = EXCLUDED.checkpoint_at, last_run_id = EXCLUDED.last_run_id, "
                    "updated_at = now()",
                    (run_id,),
                )
            cur = self.conn.execute("SELECT * FROM raw.extraction_run WHERE run_id = %s", (run_id,))
            columns = [c.name for c in cur.description]
            return dict(zip(columns, cur.fetchone(), strict=True))
