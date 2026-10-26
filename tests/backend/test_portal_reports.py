"""Reports page API: catalogue, preview and CSV export (backend/portal/reports.py, Task 10.7)."""

from __future__ import annotations

import csv
import io

import pytest
from backend_support import DEMO_BRANCH, warehouse_available
from kpi.service import InvalidParameter, KpiRequest, KpiResult, KpiService
from portal.reports import REPORTS

pytestmark = pytest.mark.django_db
PASSWORD = "pw-for-tests"


def result(rows, columns, *, synthetic=False, domain="hr") -> KpiResult:
    return KpiResult(
        function="x",
        kpi_ids=["X"],
        title="x",
        domain=domain,
        dataset="marts.x",
        as_of="2026-10-25",
        period=None,
        group_by=[],
        filters={},
        branch_restricted=False,
        columns=columns,
        rows=rows,
        freshness=[],
        notes=[],
        synthetic=synthetic,
    )


@pytest.fixture
def fake_run(monkeypatch):
    calls: list[KpiRequest] = []
    answer = {"value": None}

    def run(self, request, scope):
        calls.append(request)
        if isinstance(answer["value"], Exception):
            raise answer["value"]
        return answer["value"]

    monkeypatch.setattr(KpiService, "run", run)
    return calls, answer


def login(client, role_user, username, role, branches=()):
    role_user(username, role, branches=branches)
    client.login(username=username, password=PASSWORD)


def csv_rows(response) -> list[list[str]]:
    text = b"".join(
        response.streaming_content if response.streaming else [response.content]
    ).decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text)))


def test_catalogue_follows_the_users_modules(client, role_user):
    login(client, role_user, "rp_hr", "DrukSmart HR Manager")
    reports = client.get("/api/v1/portal/reports/").json()["reports"]
    assert {r["domain"] for r in reports} == {"hr"}
    assert [r["key"] for r in reports] == [r.key for r in REPORTS if r.kpi.domain == "hr"]
    assert {r["time"] for r in reports} == {"snapshot", "period"}


def test_reports_require_sign_in(client):
    assert client.get("/api/v1/portal/reports/").status_code == 401
    assert client.get("/api/v1/portal/reports/ageing.csv").status_code == 401


def test_report_of_another_module_is_not_found(client, role_user, fake_run):
    login(client, role_user, "rp_hr2", "DrukSmart HR Manager")
    assert client.get("/api/v1/portal/reports/ageing/").status_code == 404
    assert client.get("/api/v1/portal/reports/ageing.csv").status_code == 404
    assert client.get("/api/v1/portal/reports/nope/").status_code == 404
    assert fake_run[0] == []


def test_preview_runs_the_registry_function_with_the_date(client, role_user, fake_run):
    calls, answer = fake_run
    answer["value"] = result([{"department": "Sales", "active_headcount": 5}], [])
    login(client, role_user, "rp_prev", "DrukSmart HR Manager")
    data = client.get("/api/v1/portal/reports/headcount-by-department/?as_of=2026-10-24").json()
    assert data["report"]["key"] == "headcount-by-department"
    (request,) = calls
    assert (request.function, request.group_by, request.as_of) == (
        "hr.active_headcount",
        "department",
        "2026-10-24",
    )


def test_invalid_date_is_a_400(client, role_user, fake_run):
    fake_run[1]["value"] = InvalidParameter("as_of must be a date in YYYY-MM-DD format")
    login(client, role_user, "rp_bad", "DrukSmart HR Manager")
    response = client.get("/api/v1/portal/reports/headcount-by-department.csv?as_of=yesterday")
    assert response.status_code == 400 and response.json()["status"] == "invalid_filter"


def test_csv_export_is_a_download_with_readable_labels(client, role_user, fake_run):
    fake_run[1]["value"] = result(
        [
            {
                "ledger": "receivable",
                "ageing": "1 1-30 days overdue",
                "currency": "BTN",
                "outstanding_amount": 124200,
            },
            {
                "ledger": "receivable",
                "ageing": "6 Unapplied credit",
                "currency": "BTN",
                "outstanding_amount": -5000,
            },
        ],
        [
            {"name": "ledger", "label": "Ledger", "unit": "label"},
            {"name": "ageing", "label": "Ageing bucket", "unit": "label"},
            {"name": "currency", "label": "Currency", "unit": "label"},
            {"name": "outstanding_amount", "label": "Outstanding balance", "unit": "amount"},
        ],
        domain="accounts",
    )
    login(client, role_user, "rp_csv", "DrukSmart Accounts Manager")
    response = client.get("/api/v1/portal/reports/ageing.csv")
    assert response["Content-Type"].startswith("text/csv")
    assert (
        response["Content-Disposition"] == 'attachment; filename="druksmart_ageing_2026-10-25.csv"'
    )
    assert response["Cache-Control"] == "no-store"
    assert csv_rows(response) == [
        ["Ledger", "Ageing bucket", "Currency", "Outstanding balance"],
        ["receivable", "1-30 days overdue", "BTN", "124200"],
        ["receivable", "Unapplied credit", "BTN", "-5000"],
    ]


def test_csv_neutralises_spreadsheet_formulas_in_labels(client, role_user, fake_run):
    """ERP labels are untrusted: a department named '=HYPERLINK(...)' must not run in Excel."""
    fake_run[1]["value"] = result(
        [
            {"department": '=HYPERLINK("http://evil.example","x")', "active_headcount": 1},
            {"department": "+cmd", "active_headcount": -2},
        ],
        [
            {"name": "department", "label": "Department", "unit": "label"},
            {"name": "active_headcount", "label": "Active headcount", "unit": "count"},
        ],
    )
    login(client, role_user, "rp_inj", "DrukSmart HR Manager")
    rows = csv_rows(client.get("/api/v1/portal/reports/headcount-by-department.csv"))
    assert rows[1] == ['\'=HYPERLINK("http://evil.example","x")', "1"]
    assert rows[2] == ["'+cmd", "-2"]  # the label is neutralised, the number is unchanged


def test_synthetic_data_is_labelled_in_the_file(client, role_user, fake_run):
    fake_run[1]["value"] = result(
        [{"active_headcount": 16}],
        [{"name": "active_headcount", "label": "Active headcount", "unit": "count"}],
        synthetic=True,
    )
    login(client, role_user, "rp_syn", "DrukSmart HR Manager")
    response = client.get("/api/v1/portal/reports/headcount-by-department.csv")
    assert "_SYNTHETIC.csv" in response["Content-Disposition"]
    assert csv_rows(response) == [
        ["Data", "Active headcount"],
        ["SYNTHETIC demonstration data", "16"],
    ]


live = pytest.mark.skipif(not warehouse_available(), reason="warehouse / KPI reader not available")


@pytest.mark.backend
@live
def test_live_csv_equals_the_kpi_service(client, role_user):
    from access.scope import scope_for

    user = role_user("rp_exec", "DrukSmart Executive")
    client.login(username="rp_exec", password=PASSWORD)
    rows = csv_rows(client.get("/api/v1/portal/reports/headcount-by-branch.csv"))
    direct = (
        KpiService().run(KpiRequest("hr.active_headcount", group_by="branch"), scope_for(user)).rows
    )
    assert rows[1:] == [[r["branch"], str(r["active_headcount"])] for r in direct]


@pytest.mark.backend
@live
def test_live_branch_manager_export_contains_only_the_branch(client, role_user):
    role_user("rp_branch", "DrukSmart Branch Manager", branches=(DEMO_BRANCH,))
    client.login(username="rp_branch", password=PASSWORD)
    rows = csv_rows(client.get("/api/v1/portal/reports/headcount-by-branch.csv"))
    assert [r[0] for r in rows[1:]] == ["DTG Retail Pvt Ltd (head office)"]
