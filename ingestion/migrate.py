"""Minimal, ordered SQL migrations for the raw schema (applied as the pipeline role)."""

from __future__ import annotations

from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

TRACKING_TABLE = """
CREATE TABLE IF NOT EXISTS raw.schema_migration (
    version    text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    """Apply each not-yet-applied ``NNN_*.sql`` file in its own transaction. Idempotent."""
    with conn.transaction():
        conn.execute(TRACKING_TABLE)
    applied = {row[0] for row in conn.execute("SELECT version FROM raw.schema_migration")}
    newly_applied = []
    for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")):
        version = path.stem
        if version in applied:
            continue
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO raw.schema_migration (version) VALUES (%s)", (version,))
        newly_applied.append(version)
    return newly_applied
