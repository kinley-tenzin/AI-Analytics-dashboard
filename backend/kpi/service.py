"""Controlled execution of registry KPI functions: validate -> authorise -> query -> result.

Order of checks for every request (API or AI):
  1. the function exists in the registry (allowlist);
  2. the caller's scope includes the function's domain (HR / Accounts);
  3. group-by and filter dimensions are ones the function allows;
  4. dates parse and exist in the data; filter values exist in the dataset (case-insensitive) AND
     lie inside the caller's branch scope (a value outside it is FORBIDDEN, not silently dropped);
  5. the query is composed from registry constants with psycopg.sql; every value is a bound
     parameter, and branch scope is always ANDed in.
"""

from __future__ import annotations

import calendar
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from access.scope import Scope
from psycopg import sql

from . import registry, warehouse
from .registry import DIMENSIONS, KpiFunction

MAX_PERIOD_DAYS = 731
# Data older than this is flagged STALE in every answer (the DAG publishes daily; a missed run
# should be visible, never presented as current). Milestone 8, defect D3.
STALE_AFTER_HOURS = float(os.environ.get("DRUKSMART_STALE_AFTER_HOURS", "30"))
MAX_LISTED_VALUES = 25

# Where each label dimension's values come from. Filter values are validated against ALL these
# governed datasets (the organisation structure), so a real branch that simply has no rows for
# one KPI yields "no data" rather than "unknown branch".
LABEL_SOURCES = {
    "organisation": ("kpi_headcount", "kpi_receivables_payables", "kpi_approved_leave_requests"),
    "branch": ("kpi_headcount", "kpi_receivables_payables", "kpi_approved_leave_requests"),
    "department": ("kpi_headcount", "kpi_approved_leave_requests"),
    "employee_category": ("kpi_headcount",),
    "employment_status": ("kpi_headcount",),
    "leave_type": ("kpi_approved_leave_requests",),
    "ageing": ("kpi_receivables_payables",),
    "currency": ("kpi_receivables_payables",),
}


def publication_age_hours(freshness: list[dict]) -> float | None:
    """Hours since the OLDEST source's last validated publication (None if never published)."""
    stamps = [f["published_at"] for f in freshness]
    if not stamps or any(s is None for s in stamps):
        return None
    oldest = min(datetime.fromisoformat(s) for s in stamps)
    return (datetime.now(UTC) - oldest).total_seconds() / 3600


class KpiError(Exception):
    status = "error"

    def __init__(self, message: str, **details):
        super().__init__(message)
        self.message = message
        self.details = details


class UnknownFunction(KpiError):
    status = "unsupported"


class Forbidden(KpiError):
    status = "forbidden"


class InvalidParameter(KpiError):
    status = "invalid_filter"


class NoData(KpiError):
    status = "no_data"


@dataclass
class KpiRequest:
    function: str
    as_of: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    group_by: str | None = None
    filters: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> KpiRequest:
        if not isinstance(data, dict):
            raise InvalidParameter("parameters must be an object")
        allowed = {"function", "as_of", "period_start", "period_end", "group_by", "filters"}
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise InvalidParameter(f"unknown parameter(s): {', '.join(unknown)}")
        filters = data.get("filters") or {}
        if not isinstance(filters, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in filters.items()
        ):
            raise InvalidParameter("filters must map dimension names to text values")
        for key in ("function", "as_of", "period_start", "period_end", "group_by"):
            if data.get(key) is not None and not isinstance(data[key], str):
                raise InvalidParameter(f"{key} must be text")
        return cls(
            function=str(data.get("function") or ""),
            as_of=data.get("as_of") or None,
            period_start=data.get("period_start") or None,
            period_end=data.get("period_end") or None,
            group_by=data.get("group_by") or None,
            filters={k: v.strip() for k, v in filters.items() if v and v.strip()},
        )


@dataclass
class KpiResult:
    function: str
    kpi_ids: list[str]
    title: str
    domain: str
    dataset: str
    as_of: str | None
    period: dict | None
    group_by: list[str]
    filters: dict[str, str]
    branch_restricted: bool
    columns: list[dict]
    rows: list[dict]
    freshness: list[dict]
    notes: list[str]
    hours_since_publication: float | None = None
    stale: bool = False
    synthetic: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    def for_llm(self) -> dict:
        """Only what an external model needs to phrase the answer: definitions + aggregates."""
        return {
            "kpi": self.title,
            "kpi_ids": self.kpi_ids,
            "as_of": self.as_of,
            "period": self.period,
            "filters": self.filters,
            "columns": self.columns,
            "rows": self.rows,
            "notes": self.notes,
        }


def _parse_date(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except (ValueError, AttributeError):
        raise InvalidParameter(
            f"{name} must be a date in YYYY-MM-DD format, got {value!r}"
        ) from None


def _jsonable(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else round(float(value), 2)
    if isinstance(value, date):
        return value.isoformat()
    return value


class KpiService:
    def __init__(self, connect=warehouse.connect):
        self._connect = connect

    # ------------------------------------------------------------------ public API
    def run(self, request: KpiRequest, scope: Scope) -> KpiResult:
        f = registry.get(request.function)
        if f is None:
            raise UnknownFunction(f"{request.function!r} is not an approved KPI function")
        if not scope.allows(f.domain):
            raise Forbidden(
                f"Your role does not give access to {f.domain.upper()} KPIs ({f.title}).",
                domain=f.domain,
            )
        if scope.branch_keys is not None and not scope.branch_keys:
            raise Forbidden("No branch is assigned to your Branch Manager role.")
        if request.group_by and request.group_by not in f.group_by:
            raise InvalidParameter(
                f"{f.title} cannot be split by {request.group_by!r}",
                allowed=list(f.group_by),
            )
        for dim in request.filters:
            if dim not in f.filters:
                raise InvalidParameter(
                    f"{f.title} cannot be filtered by {dim!r}", allowed=list(f.filters)
                )

        with self._connect() as conn:
            filters = {
                dim: self._canonical_value(conn, f, dim, value, scope)
                for dim, value in request.filters.items()
            }
            notes: list[str] = []
            if f.time == "snapshot":
                as_of = self._resolve_as_of(conn, f, request.as_of, notes)
                period = None
                date_cond = sql.SQL("{} = %s").format(sql.Identifier(f.date_column))
                date_params = [as_of]
            else:
                start, end = self._resolve_period(conn, request, notes)
                as_of, period = None, {"start": start.isoformat(), "end": end.isoformat()}
                date_cond = sql.SQL("{} BETWEEN %s AND %s").format(sql.Identifier(f.date_column))
                date_params = [start, end]
            dims = [*f.always_group, *([request.group_by] if request.group_by else [])]
            query, params = self._compose(f, dims, date_cond, date_params, filters, scope)
            cursor = conn.execute(query, params)
            names = [d.name for d in cursor.description]
            rows = [dict(zip(names, map(_jsonable, r), strict=True)) for r in cursor.fetchall()]
            freshness = self._freshness(conn, f.domain)

        measure_names = [m.name for m in f.measures]
        if not rows or all(r[m] is None for r in rows for m in measure_names):
            raise NoData(
                "No data matches this request.",
                as_of=as_of.isoformat() if as_of else None,
                period=period,
                filters=filters,
            )
        if scope.branch_keys is not None:
            notes.append("Limited to the branch(es) assigned to your role.")
        if any(not m.additive for m in f.measures) and dims:
            notes.append("Distinct employee counts are not additive across groups.")
        synthetic = any(f["source_mode"] == "synthetic" for f in freshness)
        if synthetic:
            notes.insert(
                0,
                "SYNTHETIC DATA: these figures come from the fictional demonstration dataset, "
                "not from an ERP.",
            )
        age = publication_age_hours(freshness)
        stale = age is None or age > STALE_AFTER_HOURS
        if stale:
            notes.insert(
                0,
                "WARNING: this data is not current. "
                + (
                    f"The last validated publication was {age:.1f} hours ago"
                    if age is not None
                    else "No validated publication is recorded"
                )
                + "; the scheduled refresh may have failed.",
            )
        return KpiResult(
            function=f.name,
            kpi_ids=list(f.kpi_ids),
            title=f.title,
            domain=f.domain,
            dataset=f"marts.{f.dataset}",
            as_of=as_of.isoformat() if as_of else None,
            period=period,
            group_by=dims,
            filters=filters,
            branch_restricted=scope.branch_keys is not None,
            columns=[{"name": d, "label": DIMENSIONS[d].label, "unit": "label"} for d in dims]
            + [{"name": m.name, "label": m.label, "unit": m.unit} for m in f.measures],
            rows=rows,
            freshness=freshness,
            notes=notes,
            hours_since_publication=round(age, 1) if age is not None else None,
            stale=stale,
            synthetic=synthetic,
        )

    def known_values(self, function: str, scope: Scope) -> dict[str, list[str]]:
        """Filter values the caller may use for a function (used by the question parser)."""
        f = registry.get(function)
        if f is None or not scope.allows(f.domain):
            return {}
        with self._connect() as conn:
            return {
                dim: list(DIMENSIONS[dim].choices) or self._values(conn, dim, scope)
                for dim in f.filters
            }

    def labels(self) -> dict[str, list[str]]:
        """Organisational labels (department, branch, ... names) across the approved datasets.

        Used by the question interpreters to recognise filter values. Scope-free on purpose:
        a value outside the caller's scope must be recognised so that the service can answer
        FORBIDDEN instead of silently ignoring it. Labels are structure, never KPI values.
        """
        dims = ("organisation", "branch", "department", "employee_category", "leave_type")
        with self._connect() as conn:
            result = {dim: self._values(conn, dim, None) for dim in dims}
        result["ledger"] = list(DIMENSIONS["ledger"].choices)
        return result

    def freshness(self, domain: str) -> dict:
        """Publication status of one module (status pages; no KPI values, no scope needed)."""
        with self._connect() as conn:
            sources = self._freshness(conn, domain)
        age = publication_age_hours(sources)
        return {
            "domain": domain,
            "sources": sources,
            "hours_since_publication": round(age, 1) if age is not None else None,
            "stale": age is None or age > STALE_AFTER_HOURS,
            "synthetic": any(f["source_mode"] == "synthetic" for f in sources),
        }

    def latest_data_date(self) -> date | None:
        with self._connect() as conn:
            return conn.execute(
                "SELECT max(latest_snapshot_date) FROM marts.data_freshness"
            ).fetchone()[0]

    # ------------------------------------------------------------------ helpers
    def _scope_condition(self, scope: Scope):
        if scope.branch_keys is None:
            return None, []
        return sql.SQL("branch_key = ANY(%s)"), [sorted(scope.branch_keys)]

    def _values(self, conn, dim: str, scope: Scope | None) -> list[str]:
        """Distinct values of a label dimension (within the scope's branches, if given)."""
        column = sql.Identifier(DIMENSIONS[dim].column)
        where, params = (None, [])
        if scope is not None:
            where, params = self._scope_condition(scope)
        parts = []
        for table in LABEL_SOURCES[dim]:
            part = sql.SQL("SELECT {col} FROM {tbl} WHERE {col} IS NOT NULL").format(
                col=column, tbl=sql.Identifier("marts", table)
            )
            if where is not None:
                part += sql.SQL(" AND ") + where
            parts.append(part)
        query = sql.SQL(" UNION ").join(parts) + sql.SQL(" ORDER BY 1")
        return [r[0] for r in conn.execute(query, params * len(parts)).fetchall()]

    def _canonical_value(self, conn, f: KpiFunction, dim: str, value: str, scope: Scope) -> str:
        d = DIMENSIONS[dim]
        if d.choices:
            if value.lower() not in d.choices:
                raise InvalidParameter(
                    f"{d.label} must be one of {', '.join(d.choices)}", allowed=list(d.choices)
                )
            return value.lower()
        everywhere = {v.lower(): v for v in self._values(conn, dim, None)}
        in_scope = self._values(conn, dim, scope)
        match = everywhere.get(value.lower())
        if match is None:
            raise InvalidParameter(
                f"Unknown {d.label.lower()} {value!r}.", allowed=in_scope[:MAX_LISTED_VALUES]
            )
        if match not in in_scope:
            raise Forbidden(f"{d.label} {match!r} is outside your authorised scope.")
        return match

    def _resolve_as_of(self, conn, f: KpiFunction, requested: str | None, notes: list) -> date:
        dates = [
            r[0]
            for r in conn.execute(
                sql.SQL("SELECT DISTINCT {d} FROM {t} ORDER BY 1 DESC").format(
                    d=sql.Identifier(f.date_column), t=sql.Identifier("marts", f.dataset)
                )
            ).fetchall()
        ]
        if not dates:
            raise NoData("The warehouse has no published data for this KPI yet.")
        if requested is None:
            notes.append(f"Latest available snapshot date: {dates[0].isoformat()}.")
            return dates[0]
        wanted = _parse_date(requested, "as_of")
        if wanted not in dates:
            raise NoData(
                f"There is no snapshot for {wanted.isoformat()}. Balances and headcount exist only "
                "for dates with a successful extraction (history is never reconstructed).",
                available_dates=[d.isoformat() for d in dates[:MAX_LISTED_VALUES]],
            )
        return wanted

    def _resolve_period(self, conn, request: KpiRequest, notes: list) -> tuple[date, date]:
        if request.period_start or request.period_end:
            start = _parse_date(request.period_start or request.period_end, "period_start")
            end = _parse_date(request.period_end or request.period_start, "period_end")
            if end < start:
                raise InvalidParameter("period_end is before period_start")
            if (end - start).days > MAX_PERIOD_DAYS:
                raise InvalidParameter(f"periods are limited to {MAX_PERIOD_DAYS} days")
            return start, end
        latest = conn.execute(
            "SELECT max(latest_snapshot_date) FROM marts.data_freshness WHERE domain = 'hr'"
        ).fetchone()[0]
        if latest is None:
            raise NoData("The warehouse has no published HR data yet.")
        start = latest.replace(day=1)
        end = latest.replace(day=calendar.monthrange(latest.year, latest.month)[1])
        notes.append(
            f"Period defaulted to {start:%B %Y} (month of the latest HR data, "
            f"{latest.isoformat()}); "
            "leave is counted in the month it starts."
        )
        return start, end

    def _compose(self, f: KpiFunction, dims, date_cond, date_params, filters, scope):
        select = []
        for name in dims:
            d = DIMENSIONS[name]
            expr = sql.SQL(d.expression) if d.expression else sql.Identifier(d.column)
            select.append(sql.SQL("{} AS {}").format(expr, sql.Identifier(name)))
        for m in f.measures:
            select.append(sql.SQL("{} AS {}").format(sql.SQL(m.sql), sql.Identifier(m.name)))
        where = [date_cond]
        params: list = list(date_params)
        for column, value in f.fixed:
            where.append(sql.SQL("{} = %s").format(sql.Identifier(column)))
            params.append(value)
        for dim, value in filters.items():
            where.append(sql.SQL("{} = %s").format(sql.Identifier(DIMENSIONS[dim].column)))
            params.append(value)
        scope_cond, scope_params = self._scope_condition(scope)
        if scope_cond is not None:
            where.append(scope_cond)
            params.extend(scope_params)
        query = sql.SQL("SELECT {sel} FROM {tbl} WHERE {where}").format(
            sel=sql.SQL(", ").join(select),
            tbl=sql.Identifier("marts", f.dataset),
            where=sql.SQL(" AND ").join(where),
        )
        if dims:
            positions = sql.SQL(", ").join(sql.Literal(i + 1) for i in range(len(dims)))
            query += sql.SQL(" GROUP BY {}").format(positions)
        if f.having_nonzero:
            measure = next(m for m in f.measures if m.name == f.having_nonzero)
            query += sql.SQL(" HAVING {} <> 0").format(sql.SQL(measure.sql))
        if dims:
            query += sql.SQL(" ORDER BY {}").format(positions)
        return query, params

    def _freshness(self, conn, domain: str) -> list[dict]:
        rows = conn.execute(
            "SELECT source_instance, latest_snapshot_date, published_at, source_mode "
            "FROM marts.data_freshness "
            "WHERE domain = %s ORDER BY 1",
            (domain,),
        ).fetchall()
        return [
            {
                "source_instance": r[0],
                "data_as_of": _jsonable(r[1]),
                "published_at": r[2].isoformat() if r[2] else None,
                "source_mode": r[3],
            }
            for r in rows
        ]
