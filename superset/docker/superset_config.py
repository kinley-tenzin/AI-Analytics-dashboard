"""DrukSmart Superset configuration (loaded via SUPERSET_CONFIG_PATH).

Only settings that differ from Superset 6.1.0's defaults are listed. Every secret comes from the
container environment, which compose.yaml fills from .env; nothing secret is stored here.
"""

import copy
import os


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value or value == "CHANGE_ME":
        raise RuntimeError(f"{name} is not set (see .env.example)")
    return value


# Signs session cookies and ENCRYPTS the stored warehouse password in the metadata database.
# Changing it later makes saved database passwords unreadable (re-run the bootstrap to re-enter).
SECRET_KEY = _required("SUPERSET_SECRET_KEY")

# Superset's own metadata (users, roles, charts, dashboards) in its own PostgreSQL container,
# never in the analytics warehouse.
SQLALCHEMY_DATABASE_URI = (
    "postgresql+psycopg2://superset:"
    f"{_required('SUPERSET_DB_PASSWORD')}@superset-db:5432/"
    f"{os.environ.get('SUPERSET_DB_NAME', 'superset')}"
)

FEATURE_FLAGS = {
    # Dashboards can be limited to roles (defence in depth on top of dataset permissions).
    "DASHBOARD_RBAC": True,
    # Jinja in SQL would let chart authors build arbitrary queries; keep governed SQL only.
    "ENABLE_TEMPLATE_PROCESSING": False,
    # No sub-queries in ad-hoc SQL expressions, so a chart cannot reach unapproved tables.
    "ALLOW_ADHOC_SUBQUERY": False,
    # Dashboards embedded in the DrukSmart website with guest tokens (Milestone 10).
    "EMBEDDED_SUPERSET": True,
}

# ---- Embedded dashboards (Milestone 10, docs/web/EMBEDDING.md) ------------------------------
# The website's Django backend authorises the user and asks Superset (as the portal service
# account) for a GUEST TOKEN limited to one dashboard, with the user's branch filters as RLS rules.
# The token is signed with this secret: Superset's built-in default is public, so it is required.
GUEST_TOKEN_JWT_SECRET = _required("SUPERSET_GUEST_TOKEN_SECRET")
GUEST_TOKEN_JWT_EXP_SECONDS = 300  # 5 minutes; the website's Embedded SDK renews tokens
# Embedded viewers act with this role ONLY (viewer permissions, no dataset access of its own:
# Superset lets a guest query only the charts of the dashboard named in its token).
GUEST_ROLE_NAME = "DrukSmart Embedded Guest"

# Only the DrukSmart website may frame Superset pages (CSP frame-ancestors); everything else in
# Superset's default security headers is kept.
WEB_ORIGIN = os.environ.get("DRUKSMART_WEB_ORIGIN", "http://127.0.0.1:8000").rstrip("/")
from superset.config import TALISMAN_CONFIG as _DEFAULT_TALISMAN  # noqa: E402

TALISMAN_CONFIG = copy.deepcopy(_DEFAULT_TALISMAN)
TALISMAN_CONFIG["content_security_policy"]["frame-ancestors"] = ["'self'", WEB_ORIGIN]
# X-Frame-Options cannot name another origin; modern browsers follow frame-ancestors instead.
TALISMAN_CONFIG["frame_options"] = None

# No self-registration and no anonymous access: every user is created by an administrator.
AUTH_USER_REGISTRATION = False
PUBLIC_ROLE_LIKE = None

# Exports (CSV/Excel) and chart queries are capped; a viewer cannot dump unlimited rows.
ROW_LIMIT = 50000
SQL_MAX_ROW = 100000

# Local development over plain HTTP on 127.0.0.1 (no TLS terminator in front).
SESSION_COOKIE_SECURE = False
SESSION_COOKIE_SAMESITE = "Lax"

# NO chart-data cache (Milestone 8, defect D2). A 5-minute cache made dashboards, including the
# data-freshness table, show the PREVIOUS publication right after a new one (measured in the
# end-to-end test). At this data volume queries take milliseconds, so correctness wins. A larger
# deployment can re-enable caching (Redis) if publication invalidates it.
DATA_CACHE_CONFIG = {"CACHE_TYPE": "NullCache"}
CACHE_CONFIG = {"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": 300}

BABEL_DEFAULT_LOCALE = "en"
APP_NAME = "DrukSmart Analytics"
