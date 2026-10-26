"""Run one extraction: window from checkpoint, page through the connector, validate, store.

Recovery model:
- Each page is committed on its own, so an interrupted run keeps what it stored.
- The checkpoint only advances when a run succeeds; the next run starts from the previous
  checkpoint and re-fetches. Re-fetched identical records are 'unchanged' (no duplicates).
- Incremental windows start ``overlap`` before the checkpoint to catch records whose
  modification time was written by a long ERP transaction or a clock that runs behind.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from connectors.base import ExtractionWindow, SourceConnector
from druksmart_common.contracts import build_raw_record, has_errors, source_id, validate_record
from ingestion.store import RawStore

log = logging.getLogger(__name__)

DEFAULT_OVERLAP = timedelta(minutes=10)


@dataclass(frozen=True)
class ExtractionResult:
    source_system: str
    source_instance: str
    entity: str
    run_id: str | None
    status: str  # succeeded | failed
    mode: str
    window_from: datetime | None
    window_until: datetime
    pages: int = 0
    fetched: int = 0
    inserted: int = 0
    unchanged: int = 0
    duplicate: int = 0
    quarantined: int = 0
    with_warnings: int = 0
    error: str | None = None


def run_extraction(
    connector: SourceConnector,
    store: RawStore,
    entity: str,
    *,
    full: bool = False,
    page_size: int | None = None,
    overlap: timedelta = DEFAULT_OVERLAP,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ExtractionResult:
    """Extract one entity into raw. Never raises for source errors: the run is marked failed."""
    connector.entity_contract(entity)  # fail fast on unknown/deferred entities
    system, instance = connector.source_system, connector.source_instance
    contract = connector.contract

    with store.entity_lock(system, instance, entity):
        checkpoint = None if full else store.get_checkpoint(system, instance, entity)
        window = ExtractionWindow(
            modified_after=checkpoint - overlap if checkpoint else None,
            modified_until=now(),
        )
        mode = "incremental" if checkpoint else "full"
        run_id = store.start_run(
            source_system=system,
            source_instance=instance,
            entity=entity,
            mode=mode,
            contract_version=contract.contract_version,
            window_from=window.modified_after,
            window_until=window.modified_until,
        )
        log.info(
            "run %s: %s/%s %s window (%s, %s]",
            run_id,
            instance,
            entity,
            mode,
            window.modified_after,
            window.modified_until,
        )

        seen: set[str] = set()
        error: BaseException | None = None
        try:
            for page in connector.fetch_pages(entity, window, page_size=page_size):
                extracted_at = now()
                valid, quarantined, duplicates = [], [], 0
                for record in page.records:
                    issues = validate_record(contract, entity, record)
                    try:
                        sid = source_id(contract, entity, record)
                    except ValueError:
                        sid = None
                    if has_errors(issues) or sid is None:
                        quarantined.append((record, sid, issues))
                        continue
                    if sid in seen:
                        duplicates += 1
                        continue
                    seen.add(sid)
                    raw = build_raw_record(
                        contract,
                        entity,
                        record,
                        source_instance=instance,
                        extraction_batch_id=str(run_id),
                        extracted_at=extracted_at,
                        instance_timezone=connector.config.timezone,
                    )
                    valid.append((raw, issues))
                counts = store.save_page(
                    run_id,
                    valid,
                    quarantined,
                    fetched=len(page.records),
                    duplicates=duplicates,
                    last_source_id=page.last_source_id,
                )
                log.info(
                    "run %s page %d: %d fetched, %d new, %d unchanged, %d quarantined",
                    run_id,
                    page.number,
                    len(page.records),
                    counts.inserted,
                    counts.unchanged,
                    len(quarantined),
                )
        except Exception as exc:  # stored on the run; the caller decides what to do next
            error = exc
            log.error("run %s failed: %s: %s", run_id, type(exc).__name__, exc)

        row = store.finish_run(run_id, succeeded=error is None, error=error)

    return ExtractionResult(
        source_system=system,
        source_instance=instance,
        entity=entity,
        run_id=str(run_id),
        status=row["status"],
        mode=mode,
        window_from=window.modified_after,
        window_until=window.modified_until,
        pages=row["pages"],
        fetched=row["records_fetched"],
        inserted=row["records_inserted"],
        unchanged=row["records_unchanged"],
        duplicate=row["records_duplicate"],
        quarantined=row["records_quarantined"],
        with_warnings=row["records_with_warnings"],
        error=f"{type(error).__name__}: {error}" if error else None,
    )


def run_module(
    connector: SourceConnector,
    store: RawStore,
    module: str | None,
    *,
    entities: list[str] | None = None,
    **kwargs,
) -> list[ExtractionResult]:
    """Extract every entity of a module ('hr', 'accounts', or None for all), in contract order.

    A failing entity does not stop the others; check each result's status.
    """
    targets = entities or connector.entities(module)
    unknown = [e for e in targets if e not in connector.contract.entities]
    if unknown:
        raise ValueError(f"Unknown entities for {connector.source_system}: {unknown}")
    return [run_extraction(connector, store, entity, **kwargs) for entity in targets]
