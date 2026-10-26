"""Source data contracts: load the YAML contracts, validate ERP payloads, build raw records.

The contracts in ``contracts/sources/`` describe what each ERP returns. This module applies
them so connectors (and tests) reject malformed records before anything reaches ``raw``.

Severity:
    error   - the record breaks the contract; it must be quarantined, not loaded.
    warning - the record is usable but incomplete (e.g. no department); it is loaded and flagged.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from functools import cache
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from druksmart_common.config import REPO_ROOT

CONTRACTS_DIR = REPO_ROOT / "contracts"
SUPPORTED_SOURCES = ("odoo", "erpnext")


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type: str
    required: bool = False
    expected: bool = False
    values: tuple = ()
    child_fields: Mapping[str, FieldSpec] = field(default_factory=dict)


@dataclass(frozen=True)
class EntityContract:
    name: str
    primary_key: str
    modified_field: str | None
    fields: Mapping[str, FieldSpec]
    checks: tuple[Mapping[str, Any], ...] = ()
    module: str = ""  # "hr" | "accounts"
    extraction: str = "incremental"  # "full" | "incremental" | "deferred"
    request_context: Mapping[str, Any] = field(default_factory=dict)  # Odoo context
    request_domain: tuple = ()  # Odoo base domain, e.g. move_type filter
    detail_fetch: bool = False  # ERPNext: child tables need one GET per document


@dataclass(frozen=True)
class SourceContract:
    source_system: str
    contract_version: str
    entities: Mapping[str, EntityContract]
    empty_values: tuple
    date_format: str
    datetime_format: str
    datetime_timezone: str  # "UTC" or "instance"
    instance_timezone_default: str | None

    def entity(self, name: str) -> EntityContract:
        try:
            return self.entities[name]
        except KeyError:
            raise KeyError(f"{self.source_system} contract has no entity {name!r}") from None


@dataclass(frozen=True)
class Issue:
    field: str
    severity: str  # "error" | "warning"
    message: str


@dataclass(frozen=True)
class RawRecord:
    """One row for the ``raw`` schema (see contracts/raw_record.yaml)."""

    source_system: str
    source_instance: str
    source_entity: str
    source_id: str
    source_modified_at: datetime | None
    extraction_batch_id: str
    extracted_at: datetime
    contract_version: str
    payload: Mapping[str, Any]
    payload_sha256: str

    @property
    def record_key(self) -> tuple[str, str, str, str]:
        return (self.source_system, self.source_instance, self.source_entity, self.source_id)


# --------------------------------------------------------------------------- loading


def _field_spec(name: str, raw: Mapping[str, Any]) -> FieldSpec:
    children = {k: _field_spec(k, v) for k, v in (raw.get("child_fields") or {}).items()}
    return FieldSpec(
        name=name,
        type=raw["type"],
        required=bool(raw.get("required", False)),
        expected=bool(raw.get("expected", False)),
        values=tuple(raw.get("values", ())),
        child_fields=children,
    )


@cache
def load_source_contract(source_system: str) -> SourceContract:
    """Load ``contracts/sources/<source_system>.yaml`` (cached)."""
    if source_system not in SUPPORTED_SOURCES:
        raise ValueError(f"Unsupported source system {source_system!r}")
    doc = yaml.safe_load((CONTRACTS_DIR / "sources" / f"{source_system}.yaml").read_text("utf-8"))
    conventions = doc["value_conventions"]
    entities = {
        name: EntityContract(
            name=name,
            primary_key=spec["primary_key"],
            modified_field=spec.get("modified_field"),
            fields={f: _field_spec(f, fs) for f, fs in spec["fields"].items()},
            checks=tuple(spec.get("checks", ())),
            module=spec["module"],
            extraction=spec.get("extraction", "incremental"),
            request_context=spec.get("request_context") or {},
            request_domain=tuple(json.loads(spec.get("request_domain") or "[]")),
            detail_fetch=bool(spec.get("detail_fetch", False)),
        )
        for name, spec in doc["entities"].items()
    }
    return SourceContract(
        source_system=doc["source_system"],
        contract_version=doc["contract_version"],
        entities=entities,
        empty_values=tuple(conventions["empty_values"]),
        date_format=conventions["date_format"],
        datetime_format=conventions["datetime_format"],
        datetime_timezone=conventions["datetime_timezone"],
        instance_timezone_default=conventions.get("instance_timezone_default"),
    )


# ------------------------------------------------------------------------ validation


def is_empty(contract: SourceContract, spec: FieldSpec, value: Any) -> bool:
    """Apply the ERP's own notion of 'no value'.

    Odoo returns ``false`` for empty fields, except boolean fields where false is a real
    value. Identity checks (``is``) avoid treating 0 as False.
    """
    if value is None:
        return True
    if value is False and spec.type != "boolean":
        return any(e is False for e in contract.empty_values)
    if isinstance(value, str) and value == "":
        return "" in contract.empty_values
    return False


def parse_date(contract: SourceContract, value: str) -> date:
    return datetime.strptime(value, contract.date_format).date()


def parse_datetime(contract: SourceContract, value: str) -> datetime:
    """Parse a naive source datetime; tolerates a missing fractional-seconds part."""
    formats = [contract.datetime_format]
    if contract.datetime_format.endswith(".%f"):
        formats.append(contract.datetime_format.removesuffix(".%f"))
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"{value!r} does not match {contract.datetime_format!r}")


def _type_error(contract: SourceContract, spec: FieldSpec, value: Any) -> str | None:
    """Return a message if ``value`` (known to be non-empty) has the wrong type."""
    kind = spec.type
    is_int = isinstance(value, int) and not isinstance(value, bool)
    if kind == "integer":
        ok = is_int
    elif kind == "number":
        ok = is_int or isinstance(value, float)
    elif kind in ("string", "link"):
        ok = isinstance(value, str) and value.strip() != ""
    elif kind == "boolean":
        ok = isinstance(value, bool)
    elif kind == "check":
        ok = is_int and value in (0, 1)
    elif kind == "selection":
        if value not in spec.values or isinstance(value, bool):
            return f"value {value!r} not in allowed values {list(spec.values)}"
        return None
    elif kind == "many2one":
        ok = (
            isinstance(value, list | tuple)
            and len(value) == 2
            and isinstance(value[0], int)
            and not isinstance(value[0], bool)
            and isinstance(value[1], str)
        )
    elif kind == "id_list":
        ok = isinstance(value, list) and all(
            isinstance(v, int) and not isinstance(v, bool) for v in value
        )
    elif kind in ("date", "datetime"):
        if not isinstance(value, str):
            return f"expected {kind} string, got {type(value).__name__}"
        try:
            parse_date(contract, value) if kind == "date" else parse_datetime(contract, value)
        except ValueError as exc:
            return f"invalid {kind}: {exc}"
        return None
    elif kind == "table":
        ok = isinstance(value, list) and all(isinstance(row, dict) for row in value)
    else:
        return f"contract uses unknown type {kind!r}"
    return None if ok else f"expected {kind}, got {type(value).__name__} {value!r}"


def _validate_fields(
    contract: SourceContract, specs: Mapping[str, FieldSpec], payload: Mapping[str, Any], prefix=""
) -> list[Issue]:
    issues: list[Issue] = []
    for name, spec in specs.items():
        label = f"{prefix}{name}"
        value = payload.get(name)
        if is_empty(contract, spec, value):
            if spec.required:
                issues.append(Issue(label, "error", "required value missing"))
            elif spec.expected:
                issues.append(Issue(label, "warning", "expected value missing"))
            continue
        message = _type_error(contract, spec, value)
        if message:
            issues.append(Issue(label, "error", message))
        elif spec.type == "table":
            for i, row in enumerate(value):
                issues += _validate_fields(contract, spec.child_fields, row, f"{label}[{i}].")
    return issues


def _run_checks(
    contract: SourceContract, entity: EntityContract, payload: Mapping[str, Any]
) -> list[Issue]:
    issues = []
    for check in entity.checks:
        if check["rule"] != "date_order":
            raise ValueError(f"Unknown check rule {check['rule']!r}")
        start, end = payload.get(check["start"]), payload.get(check["end"])
        if not (isinstance(start, str) and isinstance(end, str)) or not start or not end:
            continue
        try:
            if parse_date(contract, end) < parse_date(contract, start):
                issues.append(
                    Issue(
                        f"{check['start']}..{check['end']}",
                        check.get("severity", "error"),
                        f"{check['end']} {end} is before {check['start']} {start}",
                    )
                )
        except ValueError:
            pass  # bad date formats are already reported by the type check
    return issues


def validate_record(
    contract: SourceContract, entity_name: str, payload: Mapping[str, Any]
) -> list[Issue]:
    """Validate one source payload against its entity contract.

    Fields not listed in the contract are ignored, so ERP upgrades that add fields do not
    break extraction; missing or wrongly typed contracted fields are reported.
    """
    if not isinstance(payload, Mapping):
        return [Issue("<record>", "error", f"expected an object, got {type(payload).__name__}")]
    entity = contract.entity(entity_name)
    issues = _validate_fields(contract, entity.fields, payload)
    if not any(i.severity == "error" for i in issues):
        issues += _run_checks(contract, entity, payload)
    return issues


def has_errors(issues: Iterable[Issue]) -> bool:
    return any(i.severity == "error" for i in issues)


# ---------------------------------------------------------------------- raw records


def source_id(contract: SourceContract, entity_name: str, payload: Mapping[str, Any]) -> str:
    entity = contract.entity(entity_name)
    value = payload.get(entity.primary_key)
    if value is None or value is False or value == "":
        raise ValueError(f"{entity_name} record has no primary key {entity.primary_key!r}")
    return str(value)


def source_modified_at(
    contract: SourceContract,
    entity_name: str,
    payload: Mapping[str, Any],
    instance_timezone: str | None = None,
) -> datetime | None:
    """Return the source modification time as an aware UTC datetime (or None)."""
    entity = contract.entity(entity_name)
    raw = payload.get(entity.modified_field) if entity.modified_field else None
    if not isinstance(raw, str) or not raw:
        return None
    naive = parse_datetime(contract, raw)
    if contract.datetime_timezone == "UTC":
        return naive.replace(tzinfo=UTC)
    tz_name = instance_timezone or contract.instance_timezone_default
    if not tz_name:
        raise ValueError(f"{contract.source_system} datetimes need an instance time zone")
    return naive.replace(tzinfo=ZoneInfo(tz_name)).astimezone(UTC)


def payload_sha256(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_raw_record(
    contract: SourceContract,
    entity_name: str,
    payload: Mapping[str, Any],
    *,
    source_instance: str,
    extraction_batch_id: str,
    extracted_at: datetime,
    instance_timezone: str | None = None,
) -> RawRecord:
    """Wrap a source payload in the raw-record envelope (does not validate the payload)."""
    if not source_instance.strip():
        raise ValueError("source_instance must not be empty")
    if extracted_at.tzinfo is None:
        raise ValueError("extracted_at must be timezone-aware")
    return RawRecord(
        source_system=contract.source_system,
        source_instance=source_instance,
        source_entity=entity_name,
        source_id=source_id(contract, entity_name, payload),
        source_modified_at=source_modified_at(contract, entity_name, payload, instance_timezone),
        extraction_batch_id=extraction_batch_id,
        extracted_at=extracted_at.astimezone(UTC),
        contract_version=contract.contract_version,
        payload=payload,
        payload_sha256=payload_sha256(payload),
    )


def duplicate_record_keys(records: Iterable[RawRecord]) -> list[tuple[str, str, str, str]]:
    """Record keys that occur more than once (must be empty within one batch)."""
    counts = Counter(r.record_key for r in records)
    return sorted(k for k, n in counts.items() if n > 1)
