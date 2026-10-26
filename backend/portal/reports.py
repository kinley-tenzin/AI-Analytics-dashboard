"""Reports page (Task 10.7): a fixed catalogue of downloadable results of APPROVED KPI functions.

No report engine: every report is one registry function with a fixed breakdown, run by the KPI
service with the caller's scope (module + branch), exactly like the API and the assistant. The
only user input is the reporting date / period, validated by the service. Richer, ad-hoc exports
stay in Superset (each embedded chart's Download menu, also restricted by the guest token).
"""

from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass

from access.scope import scope_for
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_GET
from kpi import registry
from kpi.http import api_login_required, error
from kpi.service import KpiError, KpiRequest, KpiService
from kpi.views import HTTP_STATUS

log = logging.getLogger("druksmart.portal")


@dataclass(frozen=True)
class Report:
    key: str
    title: str
    description: str
    function: str
    group_by: str | None = None

    @property
    def kpi(self) -> registry.KpiFunction:
        return registry.FUNCTIONS[self.function]


REPORTS: list[Report] = [
    Report(
        "headcount-by-department",
        "Active headcount by department",
        "HR-02: active employees per department on a snapshot date.",
        "hr.active_headcount",
        "department",
    ),
    Report(
        "headcount-by-branch",
        "Active headcount by branch",
        "HR-01: active employees per branch on a snapshot date.",
        "hr.active_headcount",
        "branch",
    ),
    Report(
        "employment-status",
        "Employee records by employment status",
        "HR-01: active, left, inactive, suspended and not-yet-joined records.",
        "hr.employment_status",
    ),
    Report(
        "leave-by-type",
        "Approved leave by leave type",
        "HR-03: employees on leave, requests and days per leave type in a period.",
        "hr.approved_leave",
        "leave_type",
    ),
    Report(
        "leave-by-department",
        "Approved leave by department",
        "HR-03: employees on leave, requests and days per department in a period.",
        "hr.approved_leave",
        "department",
    ),
    Report(
        "receivables-by-branch",
        "Outstanding receivables by branch",
        "AC-01: open customer balances per branch and currency.",
        "ac.outstanding_receivables",
        "branch",
    ),
    Report(
        "payables-by-branch",
        "Outstanding payables by branch",
        "AC-02: open supplier balances per branch and currency.",
        "ac.outstanding_payables",
        "branch",
    ),
    Report(
        "overdue-by-ageing",
        "Overdue balances by ageing",
        "AC-03/AC-04: overdue receivables and payables per ageing bucket.",
        "ac.overdue_by_ageing",
    ),
    Report(
        "ageing",
        "Ageing of open balances",
        "AC-04: all open balances per ledger and ageing bucket.",
        "ac.ageing",
    ),
]
BY_KEY = {r.key: r for r in REPORTS}

# A spreadsheet treats text starting with these as a formula ("CSV injection"); ERP labels are
# not trusted, so such text cells are prefixed with an apostrophe. Numbers are never changed.
FORMULA_START = re.compile(r"^[=+\-@\t\r]")


AGEING_PREFIX = re.compile(r"^\d+\s+")


def display(column: str, value):
    """Ageing buckets carry a sort prefix in the warehouse ("1 1-30 days overdue")."""
    return AGEING_PREFIX.sub("", value) if column == "ageing" and isinstance(value, str) else value


def safe_cell(value) -> str | int | float:
    if value is None:
        return ""
    if isinstance(value, int | float):
        return value
    text = str(value)
    return f"'{text}" if FORMULA_START.match(text) else text


def describe(report: Report) -> dict:
    f = report.kpi
    return {
        "key": report.key,
        "title": report.title,
        "description": report.description,
        "domain": f.domain,
        "kpi_ids": list(f.kpi_ids),
        "time": f.time,  # snapshot -> as_of date; period -> period_start / period_end
    }


def _run(request, key: str):
    report = BY_KEY.get(key)
    scope = scope_for(request.user)
    if report is None or not scope.allows(report.kpi.domain):
        # Unknown and not-permitted reports look the same: the catalogue is per user.
        return None, error(
            404, "not_found", "This report does not exist or is not available to you."
        )
    params = {"function": report.function}
    if report.group_by:
        params["group_by"] = report.group_by
    for name in ("as_of", "period_start", "period_end"):
        value = request.GET.get(name, "").strip()
        if value:
            params[name] = value
    try:
        result = KpiService().run(KpiRequest.from_dict(params), scope)
    except KpiError as exc:
        return None, error(HTTP_STATUS.get(exc.status, 400), exc.status, exc.message, **exc.details)
    except Exception:
        log.exception("report %s failed", key)
        return None, error(
            503, "error", "The warehouse is not reachable right now. Try again later."
        )
    return (report, result), None


@require_GET
@api_login_required
def list_reports(request):
    scope = scope_for(request.user)
    return JsonResponse(
        {
            "status": "ok",
            "reports": [describe(r) for r in REPORTS if scope.allows(r.kpi.domain)],
        }
    )


@require_GET
@api_login_required
def preview(request, key: str):
    ok, failure = _run(request, key)
    if failure:
        return failure
    report, result = ok
    return JsonResponse({"status": "ok", "report": describe(report), "result": result.to_dict()})


@require_GET
@api_login_required
def download_csv(request, key: str):
    ok, failure = _run(request, key)
    if failure:
        return failure
    report, result = ok
    when = result.as_of or f"{result.period['start']}_{result.period['end']}"
    synthetic = "_SYNTHETIC" if result.synthetic else ""
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="druksmart_{report.key}_{when}{synthetic}.csv"'
    )
    response["Cache-Control"] = "no-store"
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    columns = result.columns
    note = ["Data"] if result.synthetic else []
    writer.writerow(note + [c["label"] for c in columns])
    for row in result.rows:
        prefix = ["SYNTHETIC demonstration data"] if result.synthetic else []
        writer.writerow(
            prefix + [safe_cell(display(c["name"], row.get(c["name"]))) for c in columns]
        )
    response.write("﻿" + buffer.getvalue())  # BOM: Excel opens UTF-8 correctly
    log.info(
        "report export %s by %s (%d rows, branch_restricted=%s)",
        report.key,
        request.user.get_username(),
        len(result.rows),
        result.branch_restricted,
    )
    return response
