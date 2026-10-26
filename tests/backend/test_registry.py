"""The KPI registry is a closed, consistent allowlist (no database needed)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from backend_support import ADMIN, HR_ONLY
from kpi import registry
from kpi.registry import DIMENSIONS, FUNCTIONS
from kpi.service import KpiRequest, KpiService

REPO = Path(__file__).resolve().parents[2]
APPROVED = {
    d["relation"]
    for d in yaml.safe_load((REPO / "backend/approved_datasets.yml").read_text("utf-8"))["datasets"]
}
SUPERSET_METRICS = {
    m["name"]: m["expression"].lower()
    for ds in yaml.safe_load((REPO / "superset/definitions/datasets.yml").read_text("utf-8"))[
        "datasets"
    ]
    for m in ds["metrics"]
}


def _model_sql(table: str) -> str:
    return next((REPO / "warehouse/models").rglob(f"{table}.sql")).read_text(encoding="utf-8")


@pytest.mark.parametrize("f", FUNCTIONS.values(), ids=list(FUNCTIONS))
def test_function_is_fully_specified(f):
    assert f.domain in ("hr", "accounts") and f.kpi_ids and f.title and f.description
    assert f.dataset in APPROVED, "every function reads an APPROVED dataset only"
    assert f.time in ("snapshot", "period") and f.measures
    sql = _model_sql(f.dataset)
    for d in (*f.group_by, *f.always_group, *f.filters):
        dim = DIMENSIONS[d]
        assert dim.column is None or re.search(rf"\b{dim.column}\b", sql), (f.name, d)
    for column, _ in f.fixed:
        assert re.search(rf"\b{column}\b", sql)
    for m in f.measures:
        idents = set(re.findall(r"[a-z_]+", m.sql)) - {"sum", "count", "distinct"}
        assert all(re.search(rf"\b{i}\b", sql) for i in idents), (f.name, m.name)


def test_filters_are_never_free_text_columns():
    for f in FUNCTIONS.values():
        assert all(DIMENSIONS[d].is_filterable() for d in f.filters)


@pytest.mark.parametrize(
    ("function", "measure", "superset_metric"),
    [
        ("hr.active_headcount", "active_headcount", "active_headcount"),
        ("hr.employment_status", "employee_records", "employee_records"),
        ("ac.ageing", "outstanding_amount", "outstanding_amount"),
    ],
)
def test_measures_equal_the_certified_superset_metrics(function, measure, superset_metric):
    m = next(m for m in FUNCTIONS[function].measures if m.name == measure)
    assert m.sql.lower() == SUPERSET_METRICS[superset_metric]


def test_receivable_and_payable_functions_fix_their_ledger():
    assert ("ledger", "receivable") in FUNCTIONS["ac.outstanding_receivables"].fixed
    assert ("ledger", "payable") in FUNCTIONS["ac.outstanding_payables"].fixed


def test_hr_user_sees_only_hr_functions():
    assert {f.domain for f in registry.functions_for(HR_ONLY.domains)} == {"hr"}


class ExplodingConnect:
    """A warehouse connection factory that fails the test if it is ever used."""

    calls = 0

    def __call__(self):
        ExplodingConnect.calls += 1
        raise AssertionError("the warehouse must not be queried")


@pytest.mark.parametrize(
    ("request_dict", "scope", "status"),
    [
        (
            {
                "function": "sql.raw",
            },
            ADMIN,
            "unsupported",
        ),
        ({"function": "ac.outstanding_receivables"}, HR_ONLY, "forbidden"),
        ({"function": "hr.active_headcount", "group_by": "salary"}, ADMIN, "invalid_filter"),
        (
            {"function": "hr.active_headcount", "filters": {"employee_key": "x"}},
            ADMIN,
            "invalid_filter",
        ),
        (
            {"function": "ac.outstanding_payables", "filters": {"department": "Sales"}},
            ADMIN,
            "invalid_filter",
        ),
    ],
)
def test_rejected_before_any_query(request_dict, scope, status):
    from kpi.service import KpiError

    with pytest.raises(KpiError) as exc:
        KpiService(connect=ExplodingConnect()).run(KpiRequest.from_dict(request_dict), scope)
    assert exc.value.status == status


@pytest.mark.parametrize(
    "payload",
    [
        {"function": "hr.active_headcount", "sql": "select 1"},
        {"function": "hr.active_headcount", "filters": {"department": ["Sales"]}},
        {"function": "hr.active_headcount", "as_of": 20261025},
        "not-an-object",
    ],
)
def test_malformed_requests_are_rejected(payload):
    from kpi.service import InvalidParameter

    with pytest.raises(InvalidParameter):
        KpiRequest.from_dict(payload)


def test_query_is_composed_from_constants_and_values_are_parameters():
    f = FUNCTIONS["hr.active_headcount"]
    hostile = "x'; DROP TABLE marts.kpi_headcount; --"
    query, params = KpiService()._compose(
        f,
        ["department"],
        registry_sql("snapshot_date = %s"),
        ["2026-10-25"],
        {"department": hostile},
        ADMIN,
    )
    assert hostile in params and hostile not in repr(query)


def registry_sql(text: str):
    from psycopg import sql

    return sql.SQL(text)
