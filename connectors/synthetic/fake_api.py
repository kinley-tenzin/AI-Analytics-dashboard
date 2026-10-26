"""SYNTHETIC ERP APIs: fake Odoo JSON-2 and Frappe REST behaviour over the synthetic fixtures.

Used in two places:
* tests: in-process via httpx MockTransport (``FakeOdoo(...).transport()``);
* the pipeline's explicitly identified SYNTHETIC SOURCE MODE: served over HTTP by
  ``connectors.synthetic.server`` so the REAL connectors run unchanged against synthetic data.

They implement the behaviour documented in docs/data/ERP_SOURCE_ANALYSIS.md: auth headers,
domain/filter evaluation, ordering, limits, Odoo active_test, Frappe default page size 20,
{"data": ...} envelopes and error bodies. Data is fictional (tests/fixtures/synthetic/).
Passing against these APIs proves pipeline logic, NOT connectivity to a real ERP.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from datetime import date, datetime
from functools import cache
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx

ODOO_KEY = "test-odoo-key"
ERP_KEY, ERP_SECRET = "test-erp-key", "test-erp-secret"
FRAPPE_STANDARD = {"name", "owner", "creation", "modified", "modified_by", "docstatus", "idx"}


def _matches(value: Any, op: str, target: Any) -> bool:
    if op in ("=", "=="):
        return value == target
    if op == "!=":
        return value != target
    if op == "in":
        return value in target
    if op == "not in":
        return value not in target
    if value is None or value is False:
        return False
    return {">": value > target, ">=": value >= target, "<": value < target, "<=": value <= target}[
        op
    ]


def _schema(system: str, entity: str) -> set[str]:
    from druksmart_common.contracts import load_source_contract

    contract = load_source_contract(system)
    return set(contract.entities[entity].fields) if entity in contract.entities else set()


def _json(status: int, body: Any) -> httpx.Response:
    return httpx.Response(status, json=body)


class _FailureInjection:
    """Queue of failures returned before normal handling: 'timeout', 'connect', or a status."""

    def __init__(self):
        self.failures: list[Any] = []
        self.requests: list[httpx.Request] = []
        self.on_request: Callable[[httpx.Request], None] | None = None

    def _maybe_fail(self, request: httpx.Request) -> httpx.Response | None:
        self.requests.append(request)
        if self.on_request:
            self.on_request(request)
        if not self.failures:
            return None
        failure = self.failures.pop(0)
        if failure == "timeout":
            raise httpx.ReadTimeout("simulated timeout", request=request)
        if failure == "connect":
            raise httpx.ConnectError("simulated connection refused", request=request)
        headers = {"Retry-After": "2"} if failure == 429 else {}
        return httpx.Response(failure, json={"error": "simulated"}, headers=headers)


class FakeOdoo(_FailureInjection):
    def __init__(
        self,
        records: dict[str, list[dict]],
        *,
        version: str = "19.0",
        hidden_fields: dict[str, set[str]] | None = None,
    ):
        super().__init__()
        self.records = copy.deepcopy(records)
        self.version = version
        self.hidden_fields = hidden_fields or {}  # simulate fields the user may not read

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def bodies(self, method: str = "search_read") -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.url.path.endswith(f"/{method}")]

    def handle(self, request: httpx.Request) -> httpx.Response:
        if (failed := self._maybe_fail(request)) is not None:
            return failed
        if request.url.path == "/web/version":
            return _json(200, {"version": self.version, "version_info": [19, 0, 0, "final", 0, ""]})
        if request.headers.get("Authorization") != f"bearer {ODOO_KEY}":
            return _json(
                401,
                {
                    "name": "werkzeug.exceptions.Unauthorized",
                    "message": "Invalid apikey",
                    "arguments": ["Invalid apikey", 401],
                    "context": {},
                },
            )
        parts = request.url.path.split("/")  # ['', 'json', '2', model, method]
        if len(parts) != 5 or parts[1:3] != ["json", "2"] or request.method != "POST":
            return _json(404, {"name": "werkzeug.exceptions.NotFound", "message": "Not Found"})
        model, method = parts[3], parts[4]
        body = json.loads(request.content or b"{}")
        if model == "res.users" and method == "context_get":
            return _json(200, {"lang": "en_US", "tz": "Asia/Thimphu", "uid": 7})
        if model not in self.records:
            return _json(404, {"name": "builtins.KeyError", "message": f"Model {model} not found"})
        readable = self._fields(model)
        if method == "fields_get":
            return _json(200, {f: {"type": "char", "string": f} for f in readable})
        if method != "search_read":
            return _json(403, {"name": "odoo.exceptions.AccessError", "message": "not allowed"})

        fields = body.get("fields") or sorted(readable)
        bad = [f for f in fields if f not in readable]
        if bad:
            return _json(
                422,
                {
                    "name": "builtins.ValueError",
                    "message": f"Invalid field {bad[0]!r} on model {model!r}",
                },
            )
        rows = self.records[model]
        if body.get("context", {}).get("active_test", True) and "active" in readable:
            rows = [r for r in rows if r.get("active", True)]
        for field, op, target in body.get("domain", []):
            rows = [r for r in rows if _matches(r.get(field), op, target)]
        rows = sorted(rows, key=lambda r: r["id"])[body.get("offset", 0) :]
        if body.get("limit"):
            rows = rows[: body["limit"]]
        return _json(200, [{"id": r["id"], **{f: r.get(f, False) for f in fields}} for r in rows])

    def _fields(self, model: str) -> set[str]:
        # The server's schema (contracted fields + any extra fields present in the data)
        names = _schema("odoo", model) | {k for r in self.records[model] for k in r}
        return names - self.hidden_fields.get(model, set())


class FakeFrappe(_FailureInjection):
    def __init__(self, records: dict[str, list[dict]], *, versions: dict[str, str] | None = None):
        super().__init__()
        self.records = copy.deepcopy(records)
        self.versions = versions or {"frappe": "16.40.0", "erpnext": "16.52.0", "hrms": "16.51.0"}
        self.schema_override: dict[str, set[str]] = {}

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def list_params(self) -> list[dict]:
        out = []
        for r in self.requests:
            path = unquote(r.url.path)
            if path.startswith("/api/resource/") and path.count("/") == 3:
                out.append(dict(r.url.params))
        return out

    def handle(self, request: httpx.Request) -> httpx.Response:
        if (failed := self._maybe_fail(request)) is not None:
            return failed
        if request.headers.get("Authorization") != f"token {ERP_KEY}:{ERP_SECRET}":
            return _json(401, {"exc_type": "AuthenticationError", "message": "Invalid credentials"})
        if request.method != "GET":
            return _json(403, {"exc_type": "PermissionError", "message": "Not permitted"})
        path = unquote(request.url.path)
        if path == "/api/method/frappe.auth.get_logged_user":
            return _json(200, {"message": "druksmart.readonly@example.com"})
        if path == "/api/method/frappe.utils.change_log.get_versions":
            return _json(
                200, {"message": {app: {"version": v} for app, v in self.versions.items()}}
            )
        if path.startswith("/api/v2/doctype/") and path.endswith("/meta"):
            doctype = path.removeprefix("/api/v2/doctype/").removesuffix("/meta")
            if doctype not in self.records:
                return _json(
                    404, {"exc_type": "DoesNotExistError", "message": f"{doctype} not found"}
                )
            fields = self._known(doctype) - FRAPPE_STANDARD
            return _json(
                200,
                {"data": {"name": doctype, "fields": [{"fieldname": f} for f in sorted(fields)]}},
            )
        if path.startswith("/api/resource/"):
            parts = path.removeprefix("/api/resource/").split("/", 1)
            doctype = parts[0]
            if doctype not in self.records:
                return _json(
                    404,
                    {"exc_type": "DoesNotExistError", "message": f"DocType {doctype} not found"},
                )
            if len(parts) == 2:
                doc = next((r for r in self.records[doctype] if r["name"] == parts[1]), None)
                if doc is None:
                    return _json(404, {"exc_type": "DoesNotExistError", "message": "not found"})
                return _json(
                    200, {"data": {**doc, "doctype": doctype, "owner": "Administrator", "idx": 0}}
                )
            return self._list(doctype, request.url.params)
        return _json(404, {"exc_type": "DoesNotExistError", "message": "Not found"})

    def _known(self, doctype: str) -> set[str]:
        """DocType schema; `schema_override` simulates a DocType lacking contracted fields."""
        if doctype in self.schema_override:
            return set(self.schema_override[doctype]) | FRAPPE_STANDARD
        data_fields = {k for r in self.records[doctype] for k in r}
        return _schema("erpnext", doctype) | data_fields | FRAPPE_STANDARD

    def _list(self, doctype: str, params) -> httpx.Response:
        known = self._known(doctype)
        fields = json.loads(params.get("fields", '["name"]'))
        bad = [f for f in fields if f not in known]
        if bad:
            return _json(
                417, {"exc_type": "DataError", "message": f"Field not permitted in query: {bad[0]}"}
            )
        rows = self.records[doctype]
        for field, op, target in json.loads(params.get("filters", "[]")):
            rows = [r for r in rows if _matches(r.get(field), op, target)]
        rows = sorted(rows, key=lambda r: r["name"])
        start = int(params.get("limit_start", 0))
        size = int(params.get("limit_page_length", 20))  # Frappe default page size
        rows = rows[start : start + size]
        return _json(200, {"data": [{f: r.get(f) for f in fields} for r in rows]})


# ---------------------------------------------------------------- synthetic fixture state

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "synthetic"


@cache
def _batches(system: str) -> tuple[tuple[datetime, dict, list[dict]], ...]:
    """(extracted_at, meta, records) for every fixture file of one source system."""
    out = []
    for path in sorted(FIXTURES_DIR.glob(f"{system}/*/*.json")):
        doc = json.loads(path.read_text("utf-8"))
        response = doc["response"]
        records = response if system == "odoo" else response["data"]
        when = datetime.fromisoformat(doc["_meta"]["extracted_at"].replace("Z", "+00:00"))
        out.append((when, doc["_meta"], records))
    return tuple(sorted(out, key=lambda b: b[0]))


def fixture_records(system: str, as_of: date) -> dict[str, list[dict]]:
    """What the synthetic ERP contained at the end of ``as_of`` (incl. invalid records).

    Latest version from batches extracted on/before ``as_of``, plus records captured only by
    LATER batches whose own modification time is on/before that cutoff (e.g. HR records
    created in January but first extracted in the October batch).
    """
    from druksmart_common.contracts import load_source_contract, source_modified_at

    contract = load_source_contract(system)
    batches = _batches(system)
    earlier = [b for b in batches if b[0].date() <= as_of]
    cutoff = max((b[0] for b in earlier), default=None)
    state: dict[str, dict[str, dict]] = {}
    for when, meta, records in batches:
        entity = meta["entity"]
        pk = contract.entity(entity).primary_key
        bucket = state.setdefault(entity, {})
        if when.date() <= as_of:
            for rec in records:  # later batches overwrite earlier versions
                bucket[str(rec[pk])] = rec
        elif cutoff is not None:
            for rec in records:
                modified = source_modified_at(contract, entity, rec, meta.get("instance_timezone"))
                if modified and modified <= cutoff and str(rec[pk]) not in bucket:
                    bucket[str(rec[pk])] = rec
    return {entity: list(recs.values()) for entity, recs in state.items()}


def fixture_instances() -> dict[str, str]:
    """Source instance ids used by the synthetic fixtures, per system."""
    return {s: _batches(s)[0][1]["source_instance"] for s in ("odoo", "erpnext")}
