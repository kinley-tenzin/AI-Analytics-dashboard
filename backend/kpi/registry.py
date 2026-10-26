"""The ALLOWLIST of KPI functions: the only operations the API and the AI assistant can run.

Every function declares:
  * its authorised module (`domain`: hr | accounts) and KPI ids (docs/data/KPI_CATALOGUE.md);
  * its input parameters (as-of date or period, optional group-by) and allowed filters;
  * its data scope (one approved dataset from backend/approved_datasets.yml, fixed conditions such
    as ledger = 'receivable', plus the caller's branch scope added by the service);
  * its computation: fixed SQL aggregate expressions over the dataset's governed KPI columns,
    identical to the certified Superset metrics (superset/definitions/datasets.yml), so both
    systems return the same numbers;
  * its output: named measures with units, one row per group.

Nothing in here is built from user or model input: column names and expressions are constants,
and the service (service.py) only plugs VALIDATED values in as query parameters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Unit = Literal["count", "days", "amount"]


@dataclass(frozen=True)
class Dimension:
    """A column users may group or filter by."""

    name: str  # public name used by the API / AI
    label: str
    column: str | None = None  # dataset column
    expression: str | None = None  # fixed SQL expression when not a plain column (e.g. month)
    choices: tuple[str, ...] = ()  # fixed allowed values; otherwise validated against the data

    def is_filterable(self) -> bool:
        return self.column is not None


DIMENSIONS: dict[str, Dimension] = {
    d.name: d
    for d in [
        Dimension("organisation", "Organisation", "organisation_name"),
        Dimension("branch", "Branch", "branch_name"),
        Dimension("department", "Department", "department_name"),
        Dimension("employee_category", "Employee category", "employee_category"),
        Dimension("employment_status", "Employment status", "employment_status"),
        Dimension("leave_type", "Leave type", "leave_type_name"),
        Dimension(
            "month", "Month (leave start)", expression="date_trunc('month', start_date)::date"
        ),
        Dimension("ledger", "Ledger", "ledger", choices=("receivable", "payable")),
        Dimension("ageing", "Ageing bucket", "ageing_bucket_label"),
        Dimension("currency", "Currency", "currency_code"),
    ]
}


@dataclass(frozen=True)
class Measure:
    name: str
    label: str
    sql: str  # constant aggregate expression over governed KPI columns
    unit: Unit
    additive: bool = True


@dataclass(frozen=True)
class KpiFunction:
    name: str
    domain: Literal["hr", "accounts"]
    kpi_ids: tuple[str, ...]
    title: str
    description: str  # safe to show to users and to send to an LLM
    dataset: str  # relation in marts (must be in backend/approved_datasets.yml)
    time: Literal["snapshot", "period"]
    date_column: str
    measures: tuple[Measure, ...]
    group_by: tuple[str, ...] = ()  # OPTIONAL extra group-by dimensions (at most one)
    always_group: tuple[str, ...] = ()  # dimensions every result is split by
    filters: tuple[str, ...] = ()  # dimensions users may filter on
    fixed: tuple[tuple[str, str], ...] = ()  # (column, value) conditions of the KPI definition
    having_nonzero: str | None = None  # drop groups where this measure is 0
    examples: tuple[str, ...] = field(default=())


HEADCOUNT = Measure("active_headcount", "Active headcount", "sum(active_headcount)", "count")
RECORDS = Measure("employee_records", "Employee records", "sum(employee_records)", "count")
EMPLOYEES_ON_LEAVE = Measure(
    "employees_on_leave",
    "Employees on approved leave",
    "count(distinct employee_key)",
    "count",
    additive=False,
)
LEAVE_REQUESTS = Measure("approved_requests", "Approved leave requests", "count(*)", "count")
LEAVE_DAYS = Measure("approved_leave_days", "Approved leave days", "sum(leave_days)", "days")
OUTSTANDING = Measure(
    "outstanding_amount", "Outstanding balance", "sum(outstanding_amount)", "amount"
)
OVERDUE = Measure("overdue_amount", "Overdue balance", "sum(overdue_amount)", "amount")
OPEN_DOCS = Measure("open_documents", "Open documents", "sum(open_documents)", "count")

ORG_FILTERS = ("organisation", "branch")

FUNCTIONS: dict[str, KpiFunction] = {
    f.name: f
    for f in [
        KpiFunction(
            name="hr.active_headcount",
            domain="hr",
            kpi_ids=("HR-01", "HR-02"),
            title="Active employee headcount",
            description=(
                "Number of employees whose status is active on a snapshot date (default: the "
                "latest "
                "available date). Optionally split by department, branch, organisation or employee "
                "category (HR-02 = by department)."
            ),
            dataset="kpi_headcount",
            time="snapshot",
            date_column="snapshot_date",
            measures=(HEADCOUNT,),
            group_by=("department", "branch", "organisation", "employee_category"),
            filters=(*ORG_FILTERS, "department", "employee_category"),
            examples=(
                "How many active employees are there?",
                "How many employees work in each department?",
            ),
        ),
        KpiFunction(
            name="hr.employment_status",
            domain="hr",
            kpi_ids=("HR-01",),
            title="Employee records by employment status (active vs not active)",
            description=(
                "Employee records on a snapshot date split by employment status (active, left, "
                "inactive, suspended, not yet joined)."
            ),
            dataset="kpi_headcount",
            time="snapshot",
            date_column="snapshot_date",
            measures=(RECORDS,),
            always_group=("employment_status",),
            filters=(*ORG_FILTERS, "department"),
            examples=("How many employees are active versus inactive?",),
        ),
        KpiFunction(
            name="hr.approved_leave",
            domain="hr",
            kpi_ids=("HR-03",),
            title="Approved leave",
            description=(
                "Approved leave whose START date falls in a period (default: the calendar month of "
                "the latest HR data): distinct employees on approved leave, number of approved "
                "requests and approved leave days. Optionally split by leave type, department, "
                "branch, organisation or month."
            ),
            dataset="kpi_approved_leave_requests",
            time="period",
            date_column="start_date",
            measures=(EMPLOYEES_ON_LEAVE, LEAVE_REQUESTS, LEAVE_DAYS),
            group_by=("leave_type", "department", "branch", "organisation", "month"),
            filters=(*ORG_FILTERS, "department", "leave_type"),
            examples=(
                "How many employees are on approved leave?",
                "How many approved leave days were taken in October 2026?",
            ),
        ),
        KpiFunction(
            name="ac.outstanding_receivables",
            domain="accounts",
            kpi_ids=("AC-01",),
            title="Outstanding receivables",
            description=(
                "Open customer balances (posted invoices minus payments and credit notes) on an "
                "as-of date (default: latest), in each organisation's company currency."
            ),
            dataset="kpi_receivables_payables",
            time="snapshot",
            date_column="snapshot_date",
            measures=(OUTSTANDING, OPEN_DOCS),
            fixed=(("ledger", "receivable"),),
            always_group=("currency",),
            group_by=("organisation", "branch", "ageing"),
            filters=(*ORG_FILTERS, "currency"),
            examples=("What is the outstanding receivables balance?",),
        ),
        KpiFunction(
            name="ac.outstanding_payables",
            domain="accounts",
            kpi_ids=("AC-02",),
            title="Outstanding payables",
            description=(
                "Open supplier balances on an as-of date (default: latest), in each organisation's "
                "company currency."
            ),
            dataset="kpi_receivables_payables",
            time="snapshot",
            date_column="snapshot_date",
            measures=(OUTSTANDING, OPEN_DOCS),
            fixed=(("ledger", "payable"),),
            always_group=("currency",),
            group_by=("organisation", "branch", "ageing"),
            filters=(*ORG_FILTERS, "currency"),
            examples=("What is the outstanding payables balance?",),
        ),
        KpiFunction(
            name="ac.overdue_balance",
            domain="accounts",
            kpi_ids=("AC-03",),
            title="Overdue balances",
            description=(
                "Positive open balances whose due date is before the as-of date, reported "
                "separately for receivables and payables (optionally only one ledger)."
            ),
            dataset="kpi_receivables_payables",
            time="snapshot",
            date_column="snapshot_date",
            measures=(OVERDUE,),
            always_group=("ledger", "currency"),
            group_by=("organisation", "branch"),
            filters=(*ORG_FILTERS, "ledger", "currency"),
            examples=("How much is overdue?",),
        ),
        KpiFunction(
            name="ac.overdue_by_ageing",
            domain="accounts",
            kpi_ids=("AC-03", "AC-04"),
            title="Overdue balances by ageing category",
            description=(
                "Overdue balances split into ageing buckets (1-30, 31-60, 61-90, over 90 days past "
                "due), per ledger."
            ),
            dataset="kpi_receivables_payables",
            time="snapshot",
            date_column="snapshot_date",
            measures=(OVERDUE,),
            always_group=("ledger", "ageing", "currency"),
            filters=(*ORG_FILTERS, "ledger", "currency"),
            having_nonzero="overdue_amount",
            examples=("Show overdue balances by ageing category.",),
        ),
        KpiFunction(
            name="ac.ageing",
            domain="accounts",
            kpi_ids=("AC-04",),
            title="Ageing of open balances",
            description=(
                "All open balances (not yet due, overdue buckets, no due date, unapplied credit) "
                "split into ageing buckets, per ledger."
            ),
            dataset="kpi_receivables_payables",
            time="snapshot",
            date_column="snapshot_date",
            measures=(OUTSTANDING,),
            always_group=("ledger", "ageing", "currency"),
            filters=(*ORG_FILTERS, "ledger", "currency"),
            examples=("Show the ageing of receivables.",),
        ),
    ]
}


def get(name: str) -> KpiFunction | None:
    return FUNCTIONS.get(name)


def functions_for(domains) -> list[KpiFunction]:
    return [f for f in FUNCTIONS.values() if f.domain in domains]


def describe(f: KpiFunction) -> dict:
    """Public, safe description (API listing, UI and the LLM's tool declarations)."""
    return {
        "name": f.name,
        "domain": f.domain,
        "kpi_ids": list(f.kpi_ids),
        "title": f.title,
        "description": f.description,
        "time": f.time,
        "parameters": (
            {"as_of": "date YYYY-MM-DD (optional, default latest)"}
            if f.time == "snapshot"
            else {"period_start": "date (optional)", "period_end": "date (optional)"}
        )
        | {"group_by": list(f.group_by), "filters": list(f.filters)},
        "measures": [{"name": m.name, "label": m.label, "unit": m.unit} for m in f.measures],
        "always_split_by": list(f.always_group),
        "examples": list(f.examples),
    }
