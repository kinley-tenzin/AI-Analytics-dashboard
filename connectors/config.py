"""Connection settings for each ERP source, read from environment variables / .env.

Secrets (API keys) are excluded from ``repr`` and never printed.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

from druksmart_common.config import PLACEHOLDER, REPO_ROOT, ConfigError

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

REQUIRED = {
    "odoo": ("ODOO_INSTANCE_ID", "ODOO_BASE_URL", "ODOO_API_KEY"),
    "erpnext": ("ERPNEXT_INSTANCE_ID", "ERPNEXT_BASE_URL", "ERPNEXT_API_KEY", "ERPNEXT_API_SECRET"),
}


@dataclass(frozen=True)
class SourceConfig:
    source_system: str
    instance_id: str
    base_url: str
    api_key: str = field(repr=False)
    api_secret: str = field(default="", repr=False)  # ERPNext only
    database: str = ""  # Odoo: X-Odoo-Database header (multi-database servers)
    timezone: str = "UTC"  # ERPNext: site time zone of naive datetimes
    timeout_seconds: float = 30.0
    page_size: int = 200


def _number(env: Mapping[str, str], name: str, default: float, low: float, high: float) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from None
    if not low <= value <= high:
        raise ConfigError(f"{name} must be between {low} and {high}, got {value}")
    return value


def load_source_config(
    source_system: str,
    env: Mapping[str, str] | None = None,
    *,
    dotenv_path=REPO_ROOT / ".env",
) -> SourceConfig:
    """Validated settings for one ERP. Raises ConfigError naming missing settings only."""
    if source_system not in REQUIRED:
        raise ConfigError(f"Unknown source system {source_system!r}")
    if env is None:
        load_dotenv(dotenv_path, override=False)
        env = os.environ

    missing = [n for n in REQUIRED[source_system] if not env.get(n, "").strip()]
    if missing:
        raise ConfigError(
            f"Missing {source_system} settings: {', '.join(missing)} "
            "(see .env.example and docs/connectors/CONNECTORS.md)"
        )
    placeholders = [n for n in REQUIRED[source_system] if env[n].strip() == PLACEHOLDER]
    if placeholders:
        raise ConfigError("Settings still contain CHANGE_ME: " + ", ".join(placeholders))

    prefix = source_system.upper()
    base_url = env[f"{prefix}_BASE_URL"].strip().rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ConfigError(f"{prefix}_BASE_URL must be an http(s) URL, got {base_url!r}")
    # Plain http only for this machine, or for hosts explicitly listed (e.g. Docker-internal
    # names such as host.docker.internal / synthetic-erp inside the Airflow containers).
    insecure_ok = LOCAL_HOSTS | {
        h.strip() for h in env.get("DRUKSMART_INSECURE_HTTP_HOSTS", "").split(",") if h.strip()
    }
    if parsed.scheme == "http" and parsed.hostname not in insecure_ok:
        raise ConfigError(f"{prefix}_BASE_URL must use https for non-local servers (API keys)")

    timezone = env.get("ERPNEXT_TIMEZONE", "").strip() or "Asia/Thimphu"
    if source_system == "erpnext":
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError:
            raise ConfigError(
                f"ERPNEXT_TIMEZONE {timezone!r} is not a valid IANA time zone"
            ) from None

    return SourceConfig(
        source_system=source_system,
        instance_id=env[f"{prefix}_INSTANCE_ID"].strip(),
        base_url=base_url,
        api_key=env[f"{prefix}_API_KEY"].strip(),
        api_secret=env.get("ERPNEXT_API_SECRET", "").strip() if source_system == "erpnext" else "",
        database=env.get("ODOO_DATABASE", "").strip() if source_system == "odoo" else "",
        timezone=timezone if source_system == "erpnext" else "UTC",
        timeout_seconds=_number(env, "DRUKSMART_HTTP_TIMEOUT_SECONDS", 30.0, 1, 300),
        page_size=int(_number(env, "DRUKSMART_PAGE_SIZE", 200, 1, 1000)),
    )
