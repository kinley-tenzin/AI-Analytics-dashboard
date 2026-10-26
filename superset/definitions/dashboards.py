"""DEFAULT dashboard templates: charts, layout and native filters (applied by bootstrap.py).

Every chart uses only the GOVERNED dataset metrics from datasets.yml (referenced by name), so the
KPI arithmetic lives in dbt + one metric definition, never in a chart. Point-in-time KPIs
(headcount, open balances) are shown for ONE snapshot date chosen with a required native filter
that defaults to the LATEST available date; trend charts are excluded from that filter and
plot every snapshot date instead.

Charts are keyed by `key`; `slice_name` is what users see. Rows are laid out on Superset's
12-column grid.
"""

from __future__ import annotations

NO_TIME_FILTER = "No filter"


def temporal(column: str) -> dict:
    """Placeholder time-range filter that dashboard time filters replace (Superset >= 3)."""
    return {
        "clause": "WHERE",
        "expressionType": "SIMPLE",
        "subject": column,
        "operator": "TEMPORAL_RANGE",
        "comparator": NO_TIME_FILTER,
    }


def equals(column: str, values: list[str]) -> dict:
    return {
        "clause": "WHERE",
        "expressionType": "SIMPLE",
        "subject": column,
        "operator": "IN",
        "comparator": values,
    }


def big_number(metric: str, subheader: str, filters: list[dict] | None = None) -> dict:
    return {
        "viz_type": "big_number_total",
        "metric": metric,
        "adhoc_filters": filters or [],
        "subheader": subheader,
        "header_font_size": 0.4,
        "subheader_font_size": 0.15,
    }


def bar(
    x_axis: str,
    metrics: list[str],
    groupby: list[str] | None = None,
    *,
    horizontal=False,
    stack=False,
    time_grain: str | None = None,
    filters: list[dict] | None = None,
) -> dict:
    params = {
        "viz_type": "echarts_timeseries_bar",
        "x_axis": x_axis,
        "metrics": metrics,
        "groupby": groupby or [],
        "adhoc_filters": filters or [],
        "orientation": "horizontal" if horizontal else "vertical",
        "row_limit": 10000,
        "show_legend": bool(groupby),
        "show_value": not stack,
        "rich_tooltip": True,
        "x_axis_sort_asc": True,
        "truncateYAxis": False,
    }
    if stack:
        params["stack"] = "Stack"
    if not horizontal and not time_grain:
        params["xAxisLabelRotation"] = 45  # show every category label (e.g. ageing buckets)
    if time_grain:
        params["time_grain_sqla"] = time_grain
    return params


def line(x_axis: str, metrics: list[str], groupby: list[str], time_grain: str = "P1D") -> dict:
    return {
        "viz_type": "echarts_timeseries_line",
        "x_axis": x_axis,
        "time_grain_sqla": time_grain,
        "metrics": metrics,
        "groupby": groupby,
        "adhoc_filters": [temporal(x_axis)],
        "row_limit": 10000,
        "show_legend": True,
        "rich_tooltip": True,
        "markerEnabled": True,
    }


def pie(groupby: str, metric: str) -> dict:
    return {
        "viz_type": "pie",
        "groupby": [groupby],
        "metric": metric,
        "adhoc_filters": [],
        "row_limit": 100,
        "donut": True,
        "show_labels": True,
        "label_type": "key_value",
        "show_legend": True,
        "sort_by_metric": True,
    }


def table(groupby: list[str], metrics: list[str], filters: list[dict] | None = None) -> dict:
    return {
        "viz_type": "table",
        "query_mode": "aggregate",
        "groupby": groupby,
        "metrics": metrics,
        "all_columns": [],
        "percent_metrics": [],
        "adhoc_filters": filters or [],
        "order_by_cols": [],
        "order_desc": True,
        "row_limit": 1000,
        "server_page_length": 10,
        "include_search": True,
        "show_cell_bars": True,
    }


def freshness(domain: str) -> dict:
    return {
        "viz_type": "table",
        "query_mode": "raw",
        "all_columns": [
            "source_instance",
            "source_system",
            "latest_snapshot_date",
            "published_at",
            "hours_since_publication",
            "pipeline_run_id",
            "source_mode",
        ],
        "adhoc_filters": [equals("domain", [domain])],
        "order_by_cols": [],
        "row_limit": 100,
        "server_page_length": 10,
        "table_timestamp_format": "%Y-%m-%d %H:%M",
    }


HR_INTRO = """### DrukSmart HR overview
Headcount figures are **point-in-time**: they are shown for the *Snapshot date* selected in the
filter bar (default: the latest extracted date). Leave statistics follow the *Leave period*
filter and are counted in the month the leave **starts**. Source: published, tested warehouse
datasets (`marts.kpi_headcount`, `marts.kpi_approved_leave_monthly`). Definitions:
`docs/data/KPI_CATALOGUE.md` (HR-01..HR-03). If a chart says *No results*, the current filters
(or your access rights) leave no data to show."""

ACC_INTRO = """### DrukSmart Accounts overview
Balances are **open amounts as of the selected *As-of date*** (default: the latest extracted
date), in each organisation's company currency; never add amounts of different currencies.
Drafts and cancelled documents are excluded; credit notes reduce balances. Source:
`marts.kpi_receivables_payables` (AC-01..AC-04 in `docs/data/KPI_CATALOGUE.md`). If a chart says
*No results*, the current filters (or your access rights) leave no data to show."""


DASHBOARDS = [
    {
        "key": "hr",
        "title": "DrukSmart HR Overview",
        "slug": "druksmart-hr",
        "intro": HR_INTRO,
        "charts": [
            {
                "key": "hr_headcount",
                "dataset": "kpi_headcount",
                "slice_name": "Active headcount",
                "params": big_number("active_headcount", "employees active on the snapshot date"),
            },
            {
                "key": "hr_not_active",
                "dataset": "kpi_headcount",
                "slice_name": "Not-active employee records",
                "params": big_number(
                    "not_active_records", "left, inactive, suspended or not yet joined"
                ),
            },
            {
                "key": "hr_leave_days",
                "dataset": "kpi_approved_leave_monthly",
                "slice_name": "Approved leave days",
                "params": big_number(
                    "approved_leave_days",
                    "approved leave starting in the leave period",
                    [temporal("period_month")],
                ),
            },
            {
                "key": "hr_leave_requests",
                "dataset": "kpi_approved_leave_monthly",
                "slice_name": "Approved leave requests",
                "params": big_number(
                    "approved_requests",
                    "approved requests starting in the leave period",
                    [temporal("period_month")],
                ),
            },
            {
                "key": "hr_by_department",
                "dataset": "kpi_headcount",
                "slice_name": "Active headcount by department",
                "params": bar("department_name", ["active_headcount"], horizontal=True),
            },
            {
                "key": "hr_status",
                "dataset": "kpi_headcount",
                "slice_name": "Employee records by employment status (active vs not active)",
                "params": pie("employment_status", "employee_records"),
            },
            {
                "key": "hr_by_branch",
                "dataset": "kpi_headcount",
                "slice_name": "Headcount by organisation and branch",
                "params": table(
                    ["organisation_name", "branch_name"],
                    ["active_headcount", "not_active_records", "employee_records"],
                ),
            },
            {
                "key": "hr_trend",
                "dataset": "kpi_headcount",
                "slice_name": "Active headcount trend (all snapshot dates)",
                "params": line("snapshot_date", ["active_headcount"], ["organisation_name"]),
            },
            {
                "key": "hr_leave_by_month",
                "dataset": "kpi_approved_leave_monthly",
                "slice_name": "Approved leave days by month and leave type",
                "params": bar(
                    "period_month",
                    ["approved_leave_days"],
                    ["leave_type_name"],
                    stack=True,
                    time_grain="P1M",
                    filters=[temporal("period_month")],
                ),
            },
            {
                "key": "hr_leave_table",
                "dataset": "kpi_approved_leave_monthly",
                "slice_name": "Approved leave by department and leave type",
                "params": table(
                    ["department_name", "leave_type_name"],
                    ["approved_requests", "approved_leave_days"],
                    [temporal("period_month")],
                ),
            },
            {
                "key": "hr_freshness",
                "dataset": "data_freshness",
                "slice_name": "HR data freshness",
                "params": freshness("hr"),
            },
        ],
        "rows": [
            [("MARKDOWN", 8, 38), ("hr_freshness", 4, 38)],
            [
                ("hr_headcount", 3, 40),
                ("hr_not_active", 3, 40),
                ("hr_leave_days", 3, 40),
                ("hr_leave_requests", 3, 40),
            ],
            [("hr_by_department", 6, 60), ("hr_status", 6, 60)],
            [("hr_by_branch", 6, 60), ("hr_trend", 6, 60)],
            [("hr_leave_by_month", 6, 60), ("hr_leave_table", 6, 60)],
        ],
        # Native filters. `target` = (dataset, column). `scope` = chart keys the filter applies to.
        "filters": [
            {
                "id": "NATIVE_FILTER-hrSnapshotDate",
                "name": "Snapshot date",
                "type": "select",
                "target": ("kpi_headcount", "snapshot_date"),
                "single": True,
                "required": True,
                "default_first": True,
                "sort_ascending": False,
                "scope": [
                    "hr_headcount",
                    "hr_not_active",
                    "hr_by_department",
                    "hr_status",
                    "hr_by_branch",
                ],
                "description": "Point-in-time date for headcount (defaults to the latest).",
            },
            {
                "id": "NATIVE_FILTER-hrLeavePeriod",
                "name": "Leave period",
                "type": "time",
                "scope": [
                    "hr_leave_days",
                    "hr_leave_requests",
                    "hr_leave_by_month",
                    "hr_leave_table",
                ],
                "description": "Months whose leave START date is in this range.",
            },
            {
                "id": "NATIVE_FILTER-hrOrganisation",
                "name": "Organisation",
                "type": "select",
                "target": ("kpi_headcount", "organisation_name"),
                "scope": "all_except_freshness",
            },
            {
                "id": "NATIVE_FILTER-hrBranch",
                "name": "Branch",
                "type": "select",
                "target": ("kpi_headcount", "branch_name"),
                "parent": "NATIVE_FILTER-hrOrganisation",
                "scope": "all_except_freshness",
            },
            {
                "id": "NATIVE_FILTER-hrDepartment",
                "name": "Department",
                "type": "select",
                "target": ("kpi_headcount", "department_name"),
                "parent": "NATIVE_FILTER-hrBranch",
                "scope": "all_except_freshness",
            },
        ],
    },
    {
        "key": "accounts",
        "title": "DrukSmart Accounts Overview",
        "slug": "druksmart-accounts",
        "intro": ACC_INTRO,
        "charts": [
            {
                "key": "ac_ar",
                "dataset": "kpi_receivables_payables",
                "slice_name": "Outstanding receivables",
                "params": big_number("outstanding_receivables", "open customer balances (AC-01)"),
            },
            {
                "key": "ac_ap",
                "dataset": "kpi_receivables_payables",
                "slice_name": "Outstanding payables",
                "params": big_number("outstanding_payables", "open supplier balances (AC-02)"),
            },
            {
                "key": "ac_ar_overdue",
                "dataset": "kpi_receivables_payables",
                "slice_name": "Overdue receivables",
                "params": big_number("overdue_receivables", "past due date (AC-03)"),
            },
            {
                "key": "ac_ap_overdue",
                "dataset": "kpi_receivables_payables",
                "slice_name": "Overdue payables",
                "params": big_number("overdue_payables", "past due date (AC-03)"),
            },
            {
                "key": "ac_ageing",
                "dataset": "kpi_receivables_payables",
                "slice_name": "Ageing of open balances by ledger",
                "params": bar("ageing_bucket_label", ["outstanding_amount"], ["ledger"]),
            },
            {
                "key": "ac_by_branch",
                "dataset": "kpi_receivables_payables",
                "slice_name": "Open balances by organisation and branch",
                "params": table(
                    ["organisation_name", "branch_name", "currency_code"],
                    [
                        "outstanding_receivables",
                        "overdue_receivables",
                        "outstanding_payables",
                        "overdue_payables",
                        "open_documents",
                    ],
                ),
            },
            {
                "key": "ac_trend",
                "dataset": "kpi_receivables_payables",
                "slice_name": "Outstanding balance trend by ledger (all as-of dates)",
                "params": line("snapshot_date", ["outstanding_amount"], ["ledger"]),
            },
            {
                "key": "ac_freshness",
                "dataset": "data_freshness",
                "slice_name": "Accounts data freshness",
                "params": freshness("accounts"),
            },
        ],
        "rows": [
            [("MARKDOWN", 8, 38), ("ac_freshness", 4, 38)],
            [
                ("ac_ar", 3, 40),
                ("ac_ar_overdue", 3, 40),
                ("ac_ap", 3, 40),
                ("ac_ap_overdue", 3, 40),
            ],
            [("ac_ageing", 6, 60), ("ac_trend", 6, 60)],
            [("ac_by_branch", 12, 50)],
        ],
        "filters": [
            {
                "id": "NATIVE_FILTER-acAsOfDate",
                "name": "As-of date",
                "type": "select",
                "target": ("kpi_receivables_payables", "snapshot_date"),
                "single": True,
                "required": True,
                "default_first": True,
                "sort_ascending": False,
                "scope": [
                    "ac_ar",
                    "ac_ap",
                    "ac_ar_overdue",
                    "ac_ap_overdue",
                    "ac_ageing",
                    "ac_by_branch",
                ],
                "description": "Balances as of this date (defaults to the latest).",
            },
            {
                "id": "NATIVE_FILTER-acTrendPeriod",
                "name": "Trend period",
                "type": "time",
                "scope": ["ac_trend"],
                "description": "Date range of the trend chart.",
            },
            {
                "id": "NATIVE_FILTER-acOrganisation",
                "name": "Organisation",
                "type": "select",
                "target": ("kpi_receivables_payables", "organisation_name"),
                "scope": "all_except_freshness",
            },
            {
                "id": "NATIVE_FILTER-acBranch",
                "name": "Branch",
                "type": "select",
                "target": ("kpi_receivables_payables", "branch_name"),
                "parent": "NATIVE_FILTER-acOrganisation",
                "scope": "all_except_freshness",
            },
            {
                "id": "NATIVE_FILTER-acCurrency",
                "name": "Currency",
                "type": "select",
                "target": ("kpi_receivables_payables", "currency_code"),
                "scope": "all_except_freshness",
                "description": "Amounts are only comparable within one currency.",
            },
        ],
    },
]
