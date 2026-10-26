"""Odoo 19 adapter using the External JSON-2 API (``POST /json/2/<model>/<method>``).

Read-only by construction: ``_call`` refuses any ORM method not in READ_METHODS.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

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
    ReadOnlyViolationError,
    ResponseFormatError,
    SourceConnector,
)
from connectors.http import ApiClient, RetryPolicy

READ_METHODS = frozenset({"search_read", "search_count", "fields_get", "context_get"})
ODOO_DATETIME = "%Y-%m-%d %H:%M:%S"  # naive UTC, as Odoo stores write_date


def odoo_datetime(value: datetime) -> str:
    return value.astimezone(UTC).strftime(ODOO_DATETIME)


class OdooConnector(SourceConnector):
    source_system = "odoo"
    supported_major_versions = ("19",)

    def __init__(
        self,
        config,
        *,
        transport: httpx.BaseTransport | None = None,
        retry: RetryPolicy | None = None,
        sleep=None,
    ):
        super().__init__(config)
        headers = {
            "Authorization": f"bearer {config.api_key}",
            "Content-Type": "application/json; charset=utf-8",
        }
        if config.database:
            headers["X-Odoo-Database"] = config.database
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

    def _call(self, model: str, method: str, **params: Any) -> Any:
        if method not in READ_METHODS:
            raise ReadOnlyViolationError(f"Odoo method {method!r} is not a permitted read method")
        response = self.api.request("POST", f"/json/2/{model}/{method}", json=params)
        if response.is_success:
            try:
                return response.json()
            except ValueError:
                raise ResponseFormatError(f"{model}.{method}: response is not JSON") from None
        raise self._error(model, method, response)

    @staticmethod
    def _error(model: str, method: str, response: httpx.Response) -> ConnectorError:
        try:
            body = response.json()
            name, message = body.get("name", ""), body.get("message", "")
        except (ValueError, AttributeError):
            name, message = "", response.text[:200]
        where = f"{model}.{method}: HTTP {response.status_code} {name} {message}".strip()
        status = response.status_code
        if status == 401:
            return AuthenticationError(f"Odoo rejected the API key ({where})")
        if status == 403 or name.endswith("AccessError"):
            return PermissionDeniedError(where)
        if status == 404:
            return EntityNotFoundError(where)
        if status in (400, 422) or name.endswith(("ValueError", "UserError", "ValidationError")):
            return InvalidRequestError(where)
        return ConnectorError(where)

    # ------------------------------------------------------------------ interface

    def check_connection(self) -> ConnectionReport:
        details: list[str] = []
        version = None
        try:
            response = self.api.request("GET", "/web/version")
            if response.is_success:
                version = str(response.json().get("version") or "") or None
            else:
                details.append(f"/web/version answered HTTP {response.status_code}")
        except (ConnectorError, ValueError) as exc:
            return ConnectionReport(
                self.source_system,
                self.config.base_url,
                False,
                False,
                details=[f"server not reachable: {exc}"],
            )

        try:
            context = self._call("res.users", "context_get")
        except AuthenticationError as exc:
            return ConnectionReport(
                self.source_system,
                self.config.base_url,
                True,
                False,
                server_version=version,
                details=details + [str(exc)],
            )
        user = f"uid={context.get('uid')}" if isinstance(context, dict) else None
        supported = None
        if version:
            supported = version.split(".")[0] in self.supported_major_versions
            if not supported:
                details.append(f"Odoo {version} is not a supported version (expects 19.x)")
        else:
            details.append("server version unknown")
        return ConnectionReport(
            self.source_system, self.config.base_url, True, True, user, version, supported, details
        )

    def validate_entity(self, entity: str) -> EntityCheck:
        spec = self.entity_contract(entity)
        try:
            fields = self._call(entity, "fields_get", attributes=["type"])
        except (EntityNotFoundError, InvalidRequestError, PermissionDeniedError) as exc:
            return EntityCheck(entity, False, detail=str(exc))
        if not isinstance(fields, dict):
            raise ResponseFormatError(f"{entity}.fields_get did not return an object")
        # fields_get omits fields the user's groups may not read, so this also checks access
        missing = sorted(set(spec.fields) - set(fields))
        detail = (
            "all contracted fields readable" if not missing else "fields missing or not readable"
        )
        return EntityCheck(entity, not missing, missing, detail)

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
        base_domain = [list(term) for term in spec.request_domain]
        if window.modified_after is not None:
            base_domain.append(["write_date", ">", odoo_datetime(window.modified_after)])
        base_domain.append(["write_date", "<=", odoo_datetime(window.modified_until)])

        last_id = int(start_after) if start_after else 0
        number = 0
        while True:
            domain = base_domain + ([["id", ">", last_id]] if last_id else [])
            records = self._call(
                entity,
                "search_read",
                domain=domain,
                fields=list(spec.fields),
                limit=size,
                order="id asc",
                context=dict(spec.request_context),
            )
            if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
                raise ResponseFormatError(f"{entity}.search_read did not return a list of records")
            if not records:
                return
            ids = [r.get("id") for r in records]
            if not all(isinstance(i, int) for i in ids) or ids != sorted(ids) or ids[0] <= last_id:
                raise ResponseFormatError(f"{entity}: ids missing or not ascending after {last_id}")
            number += 1
            last_id = ids[-1]
            yield Page(entity, number, records, str(last_id))
            if len(records) < size:
                return

    def close(self) -> None:
        self.api.close()
