"""Developer commands for ERP extraction (run from the repo root with the venv active).

    python -m ingestion migrate
    python -m ingestion check --source odoo
    python -m ingestion extract --source odoo --module hr
    python -m ingestion extract --source erpnext --module accounts --entity "Sales Invoice"
    python -m ingestion runs --limit 20
    python -m ingestion summary
    python -m ingestion quarantine --limit 20

Exit codes: 0 success, 1 a check/extraction failed, 2 configuration error.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime

from connectors import create_connector, load_source_config
from druksmart_common.config import ConfigError, load_settings
from druksmart_common.db import connect
from ingestion.migrate import apply_migrations
from ingestion.runner import run_module
from ingestion.store import ExtractionAlreadyRunningError, RawStore


def _db():
    return connect(load_settings().pipeline(), autocommit=True)


def _table(rows: list[tuple], headers: list[str]) -> str:
    cells = [[("" if v is None else str(v)) for v in row] for row in rows]
    widths = [
        max(len(h), *(len(r[i]) for r in cells)) if cells else len(h) for i, h in enumerate(headers)
    ]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True))
    body = ["  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)) for r in cells]
    return "\n".join([line, "-" * len(line), *body])


def cmd_migrate(_args) -> int:
    with _db() as conn:
        applied = apply_migrations(conn)
    print("applied: " + (", ".join(applied) if applied else "nothing (already up to date)"))
    return 0


def cmd_check(args) -> int:
    config = load_source_config(args.source)
    with create_connector(config) as connector:
        report = connector.check_connection()
        print(f"source       : {report.source_system} ({config.instance_id})")
        print(f"url          : {report.base_url}")
        print(f"reachable    : {report.reachable}")
        print(f"authenticated: {report.authenticated} {report.user or ''}")
        print(f"version      : {report.server_version} (supported: {report.version_supported})")
        for detail in report.details:
            print(f"note         : {detail}")
        if not (report.reachable and report.authenticated):
            return 1
        checks = connector.validate_entities()
    print()
    print(
        _table(
            [
                (
                    c.entity,
                    "OK" if c.available else "FAIL",
                    ", ".join(c.missing_fields),
                    c.detail[:80],
                )
                for c in checks
            ],
            ["entity", "status", "missing fields", "detail"],
        )
    )
    return 0 if report.ok and all(c.available for c in checks) else 1


def _as_of(value: str | None):
    """Fixed extraction time: only for replaying SYNTHETIC data, never for real ERPs."""
    if not value:
        return {}
    if os.environ.get("DRUKSMART_SOURCE_MODE", "configured") != "synthetic":
        raise ConfigError("--as-of is only allowed with DRUKSMART_SOURCE_MODE=synthetic")
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ConfigError(f"--as-of must be an ISO timestamp, got {value!r}") from None
    if when.tzinfo is None:
        raise ConfigError("--as-of needs a time zone, e.g. 2026-10-31T17:30:00Z")
    return {"now": lambda: when}


def cmd_extract(args) -> int:
    config = load_source_config(args.source)
    module = None if args.module == "all" else args.module
    clock = _as_of(args.as_of)
    with create_connector(config) as connector, _db() as conn:
        store = RawStore(conn)
        try:
            results = run_module(
                connector,
                store,
                module,
                entities=args.entity or None,
                full=args.full,
                page_size=args.page_size,
                **clock,
            )
        except ExtractionAlreadyRunningError as exc:
            print(f"refused: {exc}")
            return 1
    print(
        _table(
            [
                (
                    r.entity,
                    r.status,
                    r.mode,
                    r.pages,
                    r.fetched,
                    r.inserted,
                    r.unchanged,
                    r.duplicate,
                    r.quarantined,
                    r.with_warnings,
                    (r.error or "")[:60],
                )
                for r in results
            ],
            [
                "entity",
                "status",
                "mode",
                "pages",
                "fetched",
                "new",
                "unchanged",
                "dup",
                "quarantined",
                "warnings",
                "error",
            ],
        )
    )
    return 0 if all(r.status == "succeeded" for r in results) else 1


def cmd_runs(args) -> int:
    sql = (
        "SELECT to_char(started_at, 'YYYY-MM-DD HH24:MI:SS'), source_instance, source_entity, "
        "mode, status, pages, records_fetched, records_inserted, records_unchanged, "
        "records_quarantined, left(coalesce(error_type || ': ' || error_message, ''), 60) "
        "FROM raw.extraction_run WHERE (%(src)s::text IS NULL OR source_system = %(src)s) "
        "AND (%(failed)s = false OR status <> 'succeeded') ORDER BY started_at DESC LIMIT %(n)s"
    )
    with _db() as conn:
        rows = conn.execute(
            sql, {"src": args.source, "failed": args.failed, "n": args.limit}
        ).fetchall()
    print(
        _table(
            rows,
            [
                "started (UTC)",
                "instance",
                "entity",
                "mode",
                "status",
                "pages",
                "fetched",
                "new",
                "unchanged",
                "quarantined",
                "error",
            ],
        )
    )
    return 0


def cmd_summary(args) -> int:
    sql = """
        SELECT s.source_system, s.source_instance, s.source_entity,
               count(DISTINCT s.source_id) AS records, count(*) AS versions,
               to_char(max(s.source_modified_at), 'YYYY-MM-DD HH24:MI') AS newest_source_change,
               (SELECT count(*) FROM raw.quarantined_record q
                 WHERE (q.source_system, q.source_instance, q.source_entity)
                     = (s.source_system, s.source_instance, s.source_entity)) AS quarantined,
               to_char(c.checkpoint_at, 'YYYY-MM-DD HH24:MI:SS') AS checkpoint_utc
        FROM raw.source_record s
        LEFT JOIN raw.extraction_checkpoint c USING (source_system, source_instance, source_entity)
        WHERE (%(src)s::text IS NULL OR s.source_system = %(src)s)
        GROUP BY s.source_system, s.source_instance, s.source_entity, c.checkpoint_at
        ORDER BY 1, 2, 3"""
    with _db() as conn:
        rows = conn.execute(sql, {"src": args.source}).fetchall()
    print(
        _table(
            rows,
            [
                "system",
                "instance",
                "entity",
                "records",
                "versions",
                "newest change (UTC)",
                "quarantined",
                "checkpoint (UTC)",
            ],
        )
    )
    return 0


def cmd_quarantine(args) -> int:
    sql = (
        "SELECT to_char(quarantined_at, 'YYYY-MM-DD HH24:MI'), source_instance, source_entity, "
        "source_id, (SELECT string_agg(i->>'field' || ': ' || (i->>'message'), '; ') "
        "FROM jsonb_array_elements(issues) i WHERE i->>'severity' = 'error') "
        "FROM raw.quarantined_record ORDER BY quarantined_at DESC LIMIT %s"
    )
    with _db() as conn:
        rows = conn.execute(sql, (args.limit,)).fetchall()
    print(_table(rows, ["when (UTC)", "instance", "entity", "source id", "errors"]))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ingestion",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="log every page")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate", help="create/upgrade the raw tables").set_defaults(func=cmd_migrate)

    check = sub.add_parser("check", help="test ERP connection, version and entity access")
    check.add_argument("--source", required=True, choices=["odoo", "erpnext"])
    check.set_defaults(func=cmd_check)

    extract = sub.add_parser("extract", help="extract HR and/or Accounts records into raw")
    extract.add_argument("--source", required=True, choices=["odoo", "erpnext"])
    extract.add_argument("--module", default="all", choices=["hr", "accounts", "all"])
    extract.add_argument("--entity", action="append", help="only this entity (repeatable)")
    extract.add_argument("--full", action="store_true", help="ignore the checkpoint")
    extract.add_argument("--page-size", type=int, help="records per API request")
    extract.add_argument(
        "--as-of",
        help="SYNTHETIC MODE ONLY: fixed extraction time (ISO, with zone) for replaying fixtures",
    )
    extract.set_defaults(func=cmd_extract)

    runs = sub.add_parser("runs", help="show the extraction log")
    runs.add_argument("--source", choices=["odoo", "erpnext"])
    runs.add_argument("--failed", action="store_true", help="only failed/running runs")
    runs.add_argument("--limit", type=int, default=20)
    runs.set_defaults(func=cmd_runs)

    summary = sub.add_parser("summary", help="raw table contents per entity")
    summary.add_argument("--source", choices=["odoo", "erpnext"])
    summary.set_defaults(func=cmd_summary)

    quarantine = sub.add_parser("quarantine", help="records rejected by the contracts")
    quarantine.add_argument("--limit", type=int, default=20)
    quarantine.set_defaults(func=cmd_quarantine)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"CONFIG ERROR: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
