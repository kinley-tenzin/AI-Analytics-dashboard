"""PostgreSQL connection helper shared by ingestion, health checks and tests."""

from __future__ import annotations

import psycopg

from druksmart_common.config import DatabaseSettings


def connect(
    db: DatabaseSettings, *, connect_timeout: int = 5, autocommit: bool = False
) -> psycopg.Connection:
    """Open a connection; the caller is responsible for closing it (use ``with``)."""
    return psycopg.connect(
        **db.conninfo(),
        connect_timeout=connect_timeout,
        application_name="druksmart",
        autocommit=autocommit,
    )
