"""Server-to-server access to Superset for embedded dashboards (Task 10.5).

The backend signs in to Superset as the PORTAL SERVICE ACCOUNT (SUPERSET_PORTAL_SERVICE_USER;
viewer permissions plus issuing guest tokens). Its password never leaves the backend. For each
viewer the website asks for a short-lived GUEST TOKEN limited to ONE dashboard, with row-level
security rules decided here from the Django user's scope (Superset's role-based RLS does not
apply to guest users). See docs/web/EMBEDDING.md.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import httpx
import yaml
from django.conf import settings

log = logging.getLogger("druksmart.portal")

TIMEOUT = httpx.Timeout(10.0, connect=5.0)
METADATA_TTL = 300  # seconds a dashboard's embedded id and datasets are cached
BRANCH_KEY = re.compile(r"^[A-Za-z0-9_.:-]{1,255}$")


class SupersetUnavailable(Exception):
    """Superset cannot be reached or refused the service account (shown as 503)."""


class DashboardNotFound(Exception):
    """The dashboard does not exist in Superset or is not enabled for embedding."""


@dataclass(frozen=True)
class DashboardInfo:
    id: int
    slug: str | None
    title: str
    embedded_id: str
    datasets: dict[str, int]  # table name -> Superset dataset id


# --------------------------------------------------------------------------- access rules
@dataclass(frozen=True)
class AccessRules:
    """Dataset rules from superset/definitions/access.yml (the single source for both systems)."""

    domain_tables: dict[str, frozenset[str]]  # module -> datasets its dashboards may use
    branch_filtered: frozenset[str]  # datasets with a branch_key column (RLS applies)
    branch_neutral: frozenset[str]  # datasets without branch data


@lru_cache(maxsize=1)
def access_rules() -> AccessRules:
    path = Path(settings.DRUKSMART_SUPERSET["ACCESS_FILE"])
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    return AccessRules(
        domain_tables={d: frozenset(t) for d, t in spec["domains"].items()},
        branch_filtered=frozenset(
            t for rule in spec.get("row_level_security", []) for t in rule["tables"]
        ),
        branch_neutral=frozenset(spec["embedding"].get("branch_neutral_tables", [])),
    )


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def branch_clause(branch_keys) -> str:
    keys = sorted(branch_keys)
    if not keys or not all(BRANCH_KEY.match(k) for k in keys):
        raise ValueError("invalid branch scope")
    return "branch_key IN (" + ", ".join(sql_literal(k) for k in keys) + ")"


# --------------------------------------------------------------------------- the gateway
def _jwt_expiry(token: str) -> float:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return float(json.loads(base64.urlsafe_b64decode(payload))["exp"])
    except (IndexError, KeyError, ValueError):
        return time.time() + 60


class SupersetGateway:
    _lock = threading.Lock()
    _access_token: str | None = None
    _access_expiry: float = 0.0
    _metadata: dict[str, tuple[float, DashboardInfo]] = {}

    def __init__(self, transport: httpx.BaseTransport | None = None):
        cfg = settings.DRUKSMART_SUPERSET
        self.base_url = cfg["INTERNAL_URL"].rstrip("/")
        self.username = cfg["SERVICE_USER"]
        self.password = cfg["SERVICE_PASSWORD"]
        self.transport = transport

    # -- low level
    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, timeout=TIMEOUT, transport=self.transport)

    def _bearer(self, client: httpx.Client, *, renew: bool = False) -> dict[str, str]:
        cls = type(self)
        with cls._lock:
            if renew or not cls._access_token or cls._access_expiry - time.time() < 30:
                if not self.password:
                    raise SupersetUnavailable("SUPERSET_PORTAL_SERVICE_PASSWORD is not configured")
                response = client.post(
                    "/api/v1/security/login",
                    json={"username": self.username, "password": self.password, "provider": "db"},
                )
                if response.status_code != 200:
                    raise SupersetUnavailable(
                        f"service account sign-in failed ({response.status_code})"
                    )
                cls._access_token = response.json()["access_token"]
                cls._access_expiry = _jwt_expiry(cls._access_token)
            return {"Authorization": f"Bearer {cls._access_token}"}

    def _get(self, client: httpx.Client, path: str) -> httpx.Response:
        response = client.get(path, headers=self._bearer(client))
        if response.status_code == 401:  # token revoked or Superset restarted
            response = client.get(path, headers=self._bearer(client, renew=True))
        return response

    # -- public
    def dashboard(self, ref: str) -> DashboardInfo:
        cached = self._metadata.get(ref)
        if cached and cached[0] > time.time():
            return cached[1]
        try:
            with self._client() as client:
                meta = self._get(client, f"/api/v1/dashboard/{ref}")
                if meta.status_code in (403, 404):
                    raise DashboardNotFound(ref)
                meta.raise_for_status()
                embedded = self._get(client, f"/api/v1/dashboard/{ref}/embedded")
                if embedded.status_code == 404:
                    raise DashboardNotFound(f"{ref} is not enabled for embedding")
                embedded.raise_for_status()
                datasets = self._get(client, f"/api/v1/dashboard/{ref}/datasets")
                datasets.raise_for_status()
        except httpx.HTTPError as exc:
            raise SupersetUnavailable(str(exc)) from exc
        result = meta.json()["result"]
        info = DashboardInfo(
            id=int(result["id"]),
            slug=result.get("slug"),
            title=result.get("dashboard_title", ""),
            embedded_id=embedded.json()["result"]["uuid"],
            datasets={d["table_name"]: int(d["id"]) for d in datasets.json()["result"]},
        )
        self._metadata[ref] = (time.time() + METADATA_TTL, info)
        return info

    def guest_token(self, info: DashboardInfo, username: str, rls: list[dict]) -> str:
        body = {
            "user": {"username": f"web:{username}", "first_name": username, "last_name": ""},
            "resources": [{"type": "dashboard", "id": info.embedded_id}],
            "rls": rls,
        }
        try:
            with self._client() as client:
                headers = self._bearer(client)
                csrf = client.get("/api/v1/security/csrf_token/", headers=headers)
                if csrf.status_code == 401:
                    headers = self._bearer(client, renew=True)
                    csrf = client.get("/api/v1/security/csrf_token/", headers=headers)
                csrf.raise_for_status()
                response = client.post(
                    "/api/v1/security/guest_token/",
                    json=body,
                    headers={
                        **headers,
                        "X-CSRFToken": csrf.json()["result"],
                        "Referer": self.base_url,
                    },
                )
                response.raise_for_status()
                return response.json()["token"]
        except httpx.HTTPError as exc:
            raise SupersetUnavailable(str(exc)) from exc

    def set_embedded(self, ref: str, allowed_origins: list[str]) -> str:
        """Enable embedding of a (customer) dashboard for the website's origin (Task 10.7)."""
        try:
            with self._client() as client:
                headers = self._bearer(client)
                csrf = client.get("/api/v1/security/csrf_token/", headers=headers)
                csrf.raise_for_status()
                response = client.put(
                    f"/api/v1/dashboard/{ref}/embedded",
                    json={"allowed_domains": allowed_origins},
                    headers={
                        **headers,
                        "X-CSRFToken": csrf.json()["result"],
                        "Referer": self.base_url,
                    },
                )
                if response.status_code in (403, 404):
                    raise DashboardNotFound(ref)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SupersetUnavailable(str(exc)) from exc
        self._metadata.pop(ref, None)
        return response.json()["result"]["uuid"]

    def ping(self) -> bool:
        try:
            with self._client() as client:
                return client.get("/health").status_code == 200
        except httpx.HTTPError:
            return False

    @classmethod
    def forget(cls) -> None:
        """Drop cached tokens and metadata (tests; after re-registering a dashboard)."""
        with cls._lock:
            cls._access_token, cls._access_expiry = None, 0.0
            cls._metadata.clear()
