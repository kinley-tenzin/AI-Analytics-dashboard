"""Consistency of the version-controlled Superset definitions (no Superset needed).

Catches, before anything is deployed: a chart using a metric or column that is not governed, a
role reaching a dataset that is not approved, a filter scoped to a chart that does not exist,
and dataset labels for columns the dbt model does not produce.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "superset" / "definitions"))
sys.path.insert(0, str(REPO / "superset" / "scripts"))

from dashboards import DASHBOARDS  # noqa: E402
from superset_api import rison  # noqa: E402


def _yaml(rel: str) -> dict:
    return yaml.safe_load((REPO / rel).read_text(encoding="utf-8"))


APPROVED = {d["relation"] for d in _yaml("superset/approved_datasets.yml")["datasets"]}
DATASETS = {d["table"]: d for d in _yaml("superset/definitions/datasets.yml")["datasets"]}
ACCESS = _yaml("superset/definitions/access.yml")
CHARTS = [(dash, chart) for dash in DASHBOARDS for chart in dash["charts"]]


def _model_sql(table: str) -> str:
    return next((REPO / "warehouse" / "models").rglob(f"{table}.sql")).read_text(encoding="utf-8")


def test_datasets_yml_defines_exactly_the_approved_datasets():
    assert set(DATASETS) == APPROVED


def test_only_kpi_and_freshness_relations_are_approved():
    # Dimensions (employee/customer names) and transaction facts stay out of Superset.
    assert all(r.startswith("kpi_") or r == "data_freshness" for r in APPROVED)


@pytest.mark.parametrize("table", sorted(APPROVED))
def test_labelled_columns_exist_in_the_dbt_model(table):
    sql = _model_sql(table)
    for column in DATASETS[table]["columns"]:
        assert re.search(rf"\b{column}\b", sql), f"{table}.{column} not produced by the dbt model"


@pytest.mark.parametrize("table", sorted(APPROVED))
def test_metrics_only_reaggregate_columns_of_their_dataset(table):
    columns = set(DATASETS[table]["columns"])
    for m in DATASETS[table]["metrics"]:
        identifiers = set(re.findall(r"\b[a-z_]+\b", m["expression"].lower()))
        keywords = {"sum", "case", "when", "then", "else", "end", "count", "distinct"}
        unknown = identifiers - keywords - columns - {"receivable", "payable"}
        assert not unknown, f"{table}.{m['name']} uses {unknown}"
        assert m.get("kpi") and m.get("description"), f"{m['name']} needs a KPI id and description"


def test_point_in_time_metrics_carry_a_warning():
    for table in ("kpi_headcount", "kpi_receivables_payables"):
        for m in DATASETS[table]["metrics"]:
            if m["name"] != "open_documents":
                assert "ONE" in m.get("warning", ""), m["name"]


@pytest.mark.parametrize(("dash", "chart"), CHARTS, ids=[c["key"] for _, c in CHARTS])
def test_charts_use_only_governed_metrics_and_labelled_columns(dash, chart):
    ds = DATASETS[chart["dataset"]]
    metrics = {m["name"] for m in ds["metrics"]}
    p = chart["params"]
    used_metrics = p.get("metrics", []) + ([p["metric"]] if "metric" in p else [])
    assert all(isinstance(m, str) and m in metrics for m in used_metrics), used_metrics
    used_columns = p.get("groupby", []) + p.get("all_columns", []) + [p.get("x_axis")]
    used_columns += [f["subject"] for f in p.get("adhoc_filters", [])]
    assert {c for c in used_columns if c} <= set(ds["columns"]) | set(
        ds.get("calculated_columns") or {}
    )


@pytest.mark.parametrize("dash", DASHBOARDS, ids=[d["key"] for d in DASHBOARDS])
def test_layout_places_every_chart_once_on_the_12_column_grid(dash):
    placed = [key for row in dash["rows"] for key, _, _ in row if key != "MARKDOWN"]
    assert sorted(placed) == sorted(c["key"] for c in dash["charts"])
    assert all(sum(w for _, w, _ in row) <= 12 for row in dash["rows"])


@pytest.mark.parametrize("dash", DASHBOARDS, ids=[d["key"] for d in DASHBOARDS])
def test_native_filters_target_real_columns_and_charts(dash):
    keys = {c["key"] for c in dash["charts"]}
    ids = {f["id"] for f in dash["filters"]}
    for f in dash["filters"]:
        assert f["id"].startswith("NATIVE_FILTER-")
        if f["scope"] != "all_except_freshness":
            assert set(f["scope"]) <= keys
        if f["type"] == "select":
            table, column = f["target"]
            assert column in DATASETS[table]["columns"]
        assert f.get("parent") in (None, *ids)


@pytest.mark.parametrize("dash", DASHBOARDS, ids=[d["key"] for d in DASHBOARDS])
def test_point_in_time_charts_are_scoped_to_a_required_single_date_filter(dash):
    date_filters = [f for f in dash["filters"] if f.get("target", ("", ""))[1] == "snapshot_date"]
    assert len(date_filters) == 1
    f = date_filters[0]
    assert f["single"] and f["required"] and f["default_first"] and not f["sort_ascending"]
    snapshot_charts = {
        c["key"]
        for c in dash["charts"]
        if c["dataset"] in ("kpi_headcount", "kpi_receivables_payables")
        and c["params"]["viz_type"] != "echarts_timeseries_line"
    }
    assert snapshot_charts == set(f["scope"])


def test_roles_reach_only_approved_datasets_and_known_dashboards():
    dash_keys = {d["key"] for d in DASHBOARDS}
    for tables in ACCESS["domains"].values():
        assert set(tables) <= APPROVED
    for role in ACCESS["roles"]:
        assert role["base"] in ACCESS["bases"]
        assert set(role["domains"]) <= set(ACCESS["domains"])
        assert set(role["dashboards"]) <= dash_keys


def test_viewer_base_removes_every_write_permission():
    removed = {tuple(r) for r in ACCESS["bases"]["viewer"]["remove"]}
    for view in ("Chart", "Dashboard", "Tag"):
        assert ("can_write", view) in removed
    for base in ACCESS["bases"].values():
        assert ("can_read", "RowLevelSecurity") in {tuple(r) for r in base["remove"]}
        assert base["from"] == "Gamma"  # Gamma has no SQL Lab, database or dataset-write access


def test_required_roles_exist():
    names = {r["name"] for r in ACCESS["roles"]}
    assert {
        "DrukSmart HR Manager",
        "DrukSmart Accounts Manager",
        "DrukSmart Executive",
        "DrukSmart Branch Manager",
    } <= names
    assert not names & set(ACCESS["retired_roles"])  # retired roles are gone (ADR-044)


def test_rls_rules_reference_approved_tables_with_branch_key():
    for rule in ACCESS["row_level_security"]:
        assert set(rule["tables"]) <= APPROVED
        for t in rule["tables"]:
            assert "branch_key" in DATASETS[t]["columns"]
        assert rule["branch_keys"] and rule["role"] in {r["name"] for r in ACCESS["roles"]}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ([1, 2], "!(1,2)"),
        ({"page": 0, "page_size": 100}, "(page:0,page_size:100)"),
        ("DrukSmart Warehouse", "'DrukSmart Warehouse'"),
        (True, "!t"),
        ("it's", "'it!'s'"),
        (
            {"filters": [{"col": "slug", "opr": "eq", "value": "druksmart-hr"}]},
            "(filters:!((col:slug,opr:eq,value:druksmart-hr)))",
        ),
    ],
)
def test_rison_encoding(value, expected):
    assert rison(value) == expected
