"""ERPNext / Frappe HR adapter using the Frappe REST API (v1 ``/api/resource``).

Read-only by construction: the adapter only ever sends HTTP GET.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from connectors.base import (
    AuthenticationError,
    ConnectionReport,
    ConnectorError,
    EntityCheck,
    EntityNotFoundError,
    ExtractionWindow,
    InvalidRequestError,
    Page,
    PermissionDeniedError,
    ResponseFormatError,
    SourceConnector,
)
from connectors.http import ApiClient, RetryPolicy

# Fields every DocType has (frappe/model/__init__.py default_fields); not listed in DocType meta.
STANDARD_FIELDS = {"name", "owner", "creation", "modified", "modified_by", "docstatus", "idx"}
FRAPPE_DATETIME = "%Y-%m-%d %H:%M:%S.%f"


class ERPNextConnector(SourceConnector):
    source_system = "erpnext"
    supported_major_versions = ("16",)

    def __init__(
        self,
        config,
        *,
        transport: httpx.BaseTransport | None = None,
        retry: RetryPolicy | None = None,
        sleep=None,
    ):
        super().__init__(config)
        self.tz = ZoneInfo(config.timezone)
        headers = {"Authorization": f"token {config.api_key}:{config.api_secret}"}
        kwargs = {"sleep": sleep} if sleep else {}
        self.api = ApiClient(
            config.base_url,
            headers,
            timeout=config.timeout_seconds,
            retry=retry,
            transport=transport,
            **kwargs,
        )

    # ------------------------------------------------------------------- transport

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = self.api.request("GET", path, params=params)
        if response.is_success:
            try:
                return response.json()
            except ValueError:
                raise ResponseFormatError(f"GET {path}: response is not JSON") from None
        raise self._error(path, response)

    @staticmethod
    def _error(path: str, response: httpx.Response) -> ConnectorError:
        try:
            body = response.json()
            exc_type = body.get("exc_type", "")
            message = body.get("message") or body.get("exception") or ""
        except (ValueError, AttributeError):
            exc_type, message = "", response.text[:200]
        if isinstance(message, str):
            message = message.splitlines()[-1][:200] if message else ""  # no tracebacks
        where = f"GET {path}: HTTP {response.status_code} {exc_type} {message}".strip()
        status = response.status_code
        if status == 401 or exc_type == "AuthenticationError":
            return AuthenticationError(f"ERPNext rejected the API key/secret ({where})")
        if status == 403 or exc_type == "PermissionError":
            return PermissionDeniedError(where)
        if status == 404 or exc_type == "DoesNotExistError":
            return EntityNotFoundError(where)
        if status in (400, 409, 417, 422) or exc_type in ("DataError", "ValidationError"):
            return InvalidRequestError(where)
        return ConnectorError(where)

    def _local(self, value: datetime) -> str:
        """Frappe stores naive datetimes in the site time zone; filters must match."""
        return value.astimezone(self.tz).strftime(FRAPPE_DATETIME)

    @staticmethod
    def _data(body: Any, path: str) -> Any:
        if not isinstance(body, dict) or "data" not in body:
            raise ResponseFormatError(f"GET {path}: expected a {{'data': ...}} envelope")
        return body["data"]

    # ------------------------------------------------------------------ interface

    def check_connection(self) -> ConnectionReport:
        url = self.config.base_url
        try:
            body = self._get("/api/method/frappe.auth.get_logged_user")
        except AuthenticationError as exc:
            return ConnectionReport(self.source_system, url, True, False, details=[str(exc)])
        except ConnectorError as exc:
            return ConnectionReport(
                self.source_system, url, False, False, details=[f"server not reachable: {exc}"]
            )
        user = body.get("message") if isinstance(body, dict) else None
        if not user or user == "Guest":
            return ConnectionReport(
                self.source_system, url, True, False, details=["request was not authenticated"]
            )

        details: list[str] = []
        version, supported = None, None
        try:
            apps = self._get("/api/method/frappe.utils.change_log.get_versions").get("message", {})
            version = str(apps.get("erpnext", {}).get("version") or "") or None
            hrms = apps.get("hrms", {}).get("version")
            details.append(f"hrms {hrms} installed" if hrms else "hrms app NOT installed")
        except (ConnectorError, AttributeError) as exc:
            details.append(f"could not read app versions: {exc}")
        if version:
            supported = version.split(".")[0] in self.supported_major_versions
            if not supported:
                details.append(f"ERPNext {version} is not a supported version (expects 16.x)")
        return ConnectionReport(
            self.source_system, url, True, True, user, version, supported, details
        )

    def validate_entity(self, entity: str) -> EntityCheck:
        spec = self.entity_contract(entity)
        path = f"/api/v2/doctype/{quote(entity)}/meta"
        try:
            meta = self._data(self._get(path), path)
        except (EntityNotFoundError, PermissionDeniedError, InvalidRequestError) as exc:
            return EntityCheck(entity, False, detail=str(exc))
        if not isinstance(meta, dict) or not isinstance(meta.get("fields"), list):
            raise ResponseFormatError(f"{path}: meta has no field list")
        available = {f.get("fieldname") for f in meta["fields"]} | STANDARD_FIELDS
        missing = sorted(set(spec.fields) - available)
        detail = "all contracted fields exist" if not missing else "fields missing from DocType"
        return EntityCheck(entity, not missing, missing, detail)

    def _list_fields(self, entity: str) -> list[str]:
        spec = self.entity_contract(entity)
        return [name for name, f in spec.fields.items() if f.type != "table"]

    def _project(self, entity: str, doc: dict[str, Any]) -> dict[str, Any]:
        """Keep only contracted fields of a full document (stable payload hash)."""
        spec = self.entity_contract(entity)
        out = {}
        for name, f in spec.fields.items():
            value = doc.get(name)
            if f.type == "table" and isinstance(value, list):
                value = [{k: row.get(k) for k in f.child_fields} for row in value]
            out[name] = value
        return out

    def fetch_pages(
        self,
        entity: str,
        window: ExtractionWindow,
        *,
        page_size: int | None = None,
        start_after: str | None = None,
    ) -> Iterator[Page]:
        spec = self.entity_contract(entity)
        size = page_size or self.config.page_size
        path = f"/api/resource/{quote(entity)}"
        base_filters: list[list[Any]] = []
        if window.modified_after is not None:
            base_filters.append(["modified", ">", self._local(window.modified_after)])
        base_filters.append(["modified", "<=", self._local(window.modified_until)])

        last_name = start_after
        number = 0
        while True:
            filters = base_filters + ([["name", ">", last_name]] if last_name else [])
            params = {
                "fields": json.dumps(self._list_fields(entity)),
                "filters": json.dumps(filters),
                "order_by": "name asc",
                "limit_start": 0,
                "limit_page_length": size,  # always explicit: Frappe defaults to 20
            }
            records = self._data(self._get(path, params), path)
            if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
                raise ResponseFormatError(f"{path}: data is not a list of records")
            if not records:
                return
            names = [r.get("name") for r in records]
            if not all(isinstance(n, str) and n for n in names):
                raise ResponseFormatError(f"{path}: records without a name")
            if spec.detail_fetch:
                records = [self._project(entity, self._fetch_document(entity, n)) for n in names]
            number += 1
            last_name = names[-1]
            yield Page(entity, number, records, last_name)
            if len(records) < size:
                return

    def _fetch_document(self, entity: str, name: str) -> dict[str, Any]:
        path = f"/api/resource/{quote(entity)}/{quote(name, safe='')}"
        doc = self._data(self._get(path), path)
        if not isinstance(doc, dict):
            raise ResponseFormatError(f"{path}: document is not an object")
        return doc

    def close(self) -> None:
        self.api.close()
