"""Load and validate platform settings from environment variables.

Local development reads them from the git-ignored ``.env`` file at the repository
root; containers and CI provide them as real environment variables. Validation
fails fast with the names of missing settings, never their values.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER = "CHANGE_ME"

REQUIRED_SETTINGS = (
    "DRUKSMART_PG_HOST",
    "DRUKSMART_PG_PORT",
    "DRUKSMART_ANALYTICS_DB",
    "DRUKSMART_APP_DB",
    "DRUKSMART_PIPELINE_USER",
    "DRUKSMART_PIPELINE_PASSWORD",
    "DRUKSMART_BI_READER_USER",
    "DRUKSMART_BI_READER_PASSWORD",
    "DRUKSMART_APP_USER",
    "DRUKSMART_APP_PASSWORD",
)


class ConfigError(ValueError):
    """Raised when required settings are missing or invalid."""


@dataclass(frozen=True)
class DatabaseSettings:
    """Connection parameters for one database as one role."""

    host: str
    port: int
    dbname: str
    user: str
    password: str = field(repr=False)

    def conninfo(self) -> dict[str, str | int]:
        return {
            "host": self.host,
            "port": self.port,
            "dbname": self.dbname,
            "user": self.user,
            "password": self.password,
        }


@dataclass(frozen=True)
class Settings:
    """Validated platform settings. Passwords are excluded from ``repr``."""

    pg_host: str
    pg_port: int
    analytics_db: str
    app_db: str
    pipeline_user: str
    pipeline_password: str = field(repr=False)
    bi_reader_user: str
    bi_reader_password: str = field(repr=False)
    app_user: str
    app_password: str = field(repr=False)
    # Optional (Milestone 7): the Django KPI service's restricted warehouse account.
    kpi_reader_user: str = ""
    kpi_reader_password: str = field(default="", repr=False)

    def pipeline(self) -> DatabaseSettings:
        """Analytics database as the pipeline role (ingestion and dbt)."""
        return DatabaseSettings(
            self.pg_host,
            self.pg_port,
            self.analytics_db,
            self.pipeline_user,
            self.pipeline_password,
        )

    @property
    def analytics_test_db(self) -> str:
        """Isolated copy for automated warehouse tests (created by the PostgreSQL init script)."""
        return f"{self.analytics_db}_test"

    def pipeline_test(self) -> DatabaseSettings:
        """Test analytics database as the pipeline role (synthetic fixtures only)."""
        return DatabaseSettings(
            self.pg_host,
            self.pg_port,
            self.analytics_test_db,
            self.pipeline_user,
            self.pipeline_password,
        )

    def bi_reader(self) -> DatabaseSettings:
        """Analytics database as the read-only BI/AI role (marts only)."""
        return DatabaseSettings(
            self.pg_host,
            self.pg_port,
            self.analytics_db,
            self.bi_reader_user,
            self.bi_reader_password,
        )

    def kpi_reader(self) -> DatabaseSettings:
        """Analytics database as the Django KPI service (approved datasets only)."""
        if not self.kpi_reader_user or self.kpi_reader_password in ("", PLACEHOLDER):
            raise ConfigError(
                "DRUKSMART_KPI_READER_USER / DRUKSMART_KPI_READER_PASSWORD are not set "
                "(run infrastructure/scripts/create_local_env.py --add-missing)"
            )
        return DatabaseSettings(
            self.pg_host,
            self.pg_port,
            self.analytics_db,
            self.kpi_reader_user,
            self.kpi_reader_password,
        )

    def application(self) -> DatabaseSettings:
        """Application metadata database as the Django role."""
        return DatabaseSettings(
            self.pg_host,
            self.pg_port,
            self.app_db,
            self.app_user,
            self.app_password,
        )


def load_settings(
    env: Mapping[str, str] | None = None,
    *,
    dotenv_path: Path = REPO_ROOT / ".env",
) -> Settings:
    """Build validated ``Settings``.

    If ``env`` is omitted, ``.env`` is loaded first (without overriding variables
    already set in the process environment) and ``os.environ`` is used.
    """
    if env is None:
        load_dotenv(dotenv_path, override=False)
        env = os.environ

    missing = [name for name in REQUIRED_SETTINGS if not env.get(name, "").strip()]
    if missing:
        raise ConfigError(
            "Missing required settings: "
            + ", ".join(missing)
            + ". Create .env from .env.example (see docs/DEVELOPMENT_SETUP.md)."
        )

    placeholders = [name for name in REQUIRED_SETTINGS if env[name].strip() == PLACEHOLDER]
    if placeholders:
        raise ConfigError(
            "Settings still contain the CHANGE_ME placeholder: " + ", ".join(placeholders)
        )

    raw_port = env["DRUKSMART_PG_PORT"].strip()
    if not raw_port.isdigit() or not 1 <= int(raw_port) <= 65535:
        raise ConfigError(f"DRUKSMART_PG_PORT must be a port number (1-65535), got {raw_port!r}")

    return Settings(
        pg_host=env["DRUKSMART_PG_HOST"].strip(),
        pg_port=int(raw_port),
        analytics_db=env["DRUKSMART_ANALYTICS_DB"].strip(),
        app_db=env["DRUKSMART_APP_DB"].strip(),
        pipeline_user=env["DRUKSMART_PIPELINE_USER"].strip(),
        pipeline_password=env["DRUKSMART_PIPELINE_PASSWORD"],
        bi_reader_user=env["DRUKSMART_BI_READER_USER"].strip(),
        bi_reader_password=env["DRUKSMART_BI_READER_PASSWORD"],
        app_user=env["DRUKSMART_APP_USER"].strip(),
        app_password=env["DRUKSMART_APP_PASSWORD"],
        kpi_reader_user=env.get("DRUKSMART_KPI_READER_USER", "").strip(),
        kpi_reader_password=env.get("DRUKSMART_KPI_READER_PASSWORD", ""),
    )
