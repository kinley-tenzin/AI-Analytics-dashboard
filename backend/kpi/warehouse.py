"""Warehouse connections for the KPI service: restricted account, read-only, time-limited.

The account (DRUKSMART_KPI_READER_USER) can SELECT only the relations in
backend/approved_datasets.yml (granted at publication). Sessions are additionally forced
read-only with a statement timeout, so even a defect in the service cannot write or run away.

Only the variables below are needed (least privilege: the backend container does not receive
the pipeline or other roles' passwords):
  DRUKSMART_PG_HOST, DRUKSMART_PG_PORT, DRUKSMART_ANALYTICS_DB,
  DRUKSMART_KPI_READER_USER, DRUKSMART_KPI_READER_PASSWORD,
  DRUKSMART_CONSUMER_DATA = live (default) | synthetic
"synthetic" reads the isolated `<analytics db>_test` database that SYNTHETIC-mode pipeline runs
publish to: the clearly labelled fallback for demonstrations without ERP sandboxes.
"""

from __future__ import annotations

import os
from functools import lru_cache

import psycopg

from druksmart_common.config import ConfigError, DatabaseSettings


def consumer_data() -> str:
    mode = os.environ.get("DRUKSMART_CONSUMER_DATA", "live").strip().lower() or "live"
    if mode not in ("live", "synthetic"):
        raise ConfigError("DRUKSMART_CONSUMER_DATA must be 'live' or 'synthetic'")
    return mode


@lru_cache(maxsize=1)
def kpi_reader_settings() -> DatabaseSettings:
    env = os.environ
    user = env.get("DRUKSMART_KPI_READER_USER", "").strip()
    password = env.get("DRUKSMART_KPI_READER_PASSWORD", "")
    if not user or password in ("", "CHANGE_ME"):
        raise ConfigError(
            "DRUKSMART_KPI_READER_USER / DRUKSMART_KPI_READER_PASSWORD are not set "
            "(run infrastructure/scripts/create_local_env.py --add-missing)"
        )
    database = env.get("DRUKSMART_ANALYTICS_DB", "druksmart_analytics").strip()
    if consumer_data() == "synthetic":
        database += "_test"
    return DatabaseSettings(
        env.get("DRUKSMART_PG_HOST", "127.0.0.1").strip(),
        int(env.get("DRUKSMART_PG_PORT", "5433").strip()),
        database,
        user,
        password,
    )


def connect() -> psycopg.Connection:
    return psycopg.connect(
        **kpi_reader_settings().conninfo(),
        connect_timeout=5,
        autocommit=True,
        application_name="druksmart-kpi-service",
        options="-c default_transaction_read_only=on -c statement_timeout=15000",
    )
