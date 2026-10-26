"""Dashboard authoring workflow end to end, against the RUNNING Superset (marker: superset).

1. A Dashboard Creator saves a new dashboard in Superset's native editor (here: "Save as" = the
   copy API, with the creator's own Superset account).
2. The administrator publishes it in the website (Django admin API): embedding is enabled for the
   website and its datasets are checked against the module.
3. A website viewer of that module gets a guest token that opens it; other modules do not.
The copied dashboards are deleted again at the end.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest
from django.test import Client
from dotenv import dotenv_values

pytestmark = [pytest.mark.superset, pytest.mark.django_db]

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "superset" / "scripts"))
from superset_api import SupersetClient  # noqa: E402

ENV = dotenv_values(REPO / ".env")
BASE = f"http://127.0.0.1:{ENV.get('SUPERSET_PORT') or '8088'}"
PASSWORD = "pw-for-tests"


def _ready() -> bool:
    try:
        up = httpx.get(f"{BASE}/health", timeout=5).status_code == 200
    except httpx.HTTPError:
        return False
    return (
        up
        and bool(ENV.get("SUPERSET_PORTAL_SERVICE_PASSWORD"))
        and bool(ENV.get("SUPERSET_DEMO_USER_PASSWORD"))
    )


if not _ready():
    pytest.skip(
        "Superset, the service account or the demo users are not configured",
        allow_module_level=True,
    )


@pytest.fixture(scope="module")
def creator():
    # ADR-044: the HR Manager authors HR dashboards (Superset demo user demo_hr).
    return SupersetClient.login(BASE, "demo_hr", ENV["SUPERSET_DEMO_USER_PASSWORD"])


@pytest.fixture(scope="module")
def admin_api():
    return SupersetClient.login(BASE, ENV["SUPERSET_ADMIN_USER"], ENV["SUPERSET_ADMIN_PASSWORD"])


def _new_dashboard(creator, title: str, tables: list[str]) -> tuple[int, list[int]]:
    """A dashboard built from scratch by the creator (own charts on approved datasets)."""
    dash_id = int(
        creator.post("/api/v1/dashboard/", {"dashboard_title": title, "published": True})["id"]
    )
    charts = []
    for table in tables:
        dataset = creator.find_one("dataset", "table_name", table)
        assert dataset, f"creator cannot see dataset {table}"
        params = {"viz_type": "table", "query_mode": "raw", "all_columns": [], "adhoc_filters": []}
        charts.append(
            int(
                creator.post(
                    "/api/v1/chart/",
                    {
                        "slice_name": f"{title}: {table}",
                        "viz_type": "table",
                        "datasource_id": dataset["id"],
                        "datasource_type": "table",
                        "params": json.dumps(params),
                        "dashboards": [dash_id],
                    },
                )["id"]
            )
        )
    return dash_id, charts


@pytest.fixture(scope="module")
def copies(creator, admin_api):
    """Dashboards a Dashboard Creator builds in Superset (deleted again afterwards)."""
    made = {
        "hr": _new_dashboard(
            creator, "Creator test HR", ["kpi_headcount", "kpi_approved_leave_monthly"]
        ),
        # An HR Manager cannot even see Accounts data, so the administrator builds the mixed one.
        "mixed": _new_dashboard(
            admin_api, "Creator test mixed", ["kpi_headcount", "kpi_receivables_payables"]
        ),
    }
    yield {key: dash_id for key, (dash_id, _) in made.items()}
    for dash_id, charts in made.values():
        for chart in charts:
            admin_api.delete(f"/api/v1/chart/{chart}")
        admin_api.delete(f"/api/v1/dashboard/{dash_id}")


def test_creator_cannot_save_a_copy_of_an_official_template(creator):
    """Known limitation (docs/web/EMBEDDING.md): with DASHBOARD_RBAC, Superset lets only a
    dashboard's owners use "Save as"; the official templates are owned by the administrator."""
    hr = creator.get("/api/v1/dashboard/druksmart-hr")["result"]
    response = creator.request(
        "POST",
        f"/api/v1/dashboard/{hr['id']}/copy/",
        json={
            "dashboard_title": "copy",
            "json_metadata": hr["json_metadata"],
            "duplicate_slices": True,
        },
    )
    assert response.status_code == 403


@pytest.fixture
def role_user(django_user_model):
    from django.contrib.auth.models import Group

    def make(username: str, role: str):
        user = django_user_model.objects.create_user(username=username, password=PASSWORD)
        user.groups.add(Group.objects.get_or_create(name=role)[0])
        return user

    return make


@pytest.fixture
def admin(django_user_model, settings):
    from portal.superset import SupersetGateway

    SupersetGateway.forget()
    django_user_model.objects.create_superuser("au_admin", password=PASSWORD)
    client = Client()
    client.login(username="au_admin", password=PASSWORD)
    return client


@pytest.fixture
def hr_manager(role_user):
    """The HR Manager's WEBSITE account: publishes HR dashboards themselves (ADR-044)."""
    from portal.superset import SupersetGateway

    SupersetGateway.forget()
    role_user("au_hr_manager", "DrukSmart HR Manager")
    client = Client()
    client.login(username="au_hr_manager", password=PASSWORD)
    return client


def viewer(role_user, username, role):
    role_user(username, role)
    client = Client()
    client.login(username=username, password=PASSWORD)
    return client


def send(client, method, url, body):
    return getattr(client, method)(url, json.dumps(body), content_type="application/json")


def test_creator_cannot_change_the_official_dashboards(creator):
    """Creators work on their own copies: the governed templates are owned by the admin."""
    hr = creator.get("/api/v1/dashboard/druksmart-hr")["result"]
    response = creator.request(
        "PUT", f"/api/v1/dashboard/{hr['id']}", json={"dashboard_title": "changed"}
    )
    assert response.status_code == 403


def test_hr_manager_cannot_use_accounts_data_in_superset(creator):
    """The HR Manager's Superset role has the HR datasets only."""
    tables = {d["table_name"] for d in creator.list_all("dataset")}
    assert "kpi_receivables_payables" not in tables and "kpi_headcount" in tables


def test_published_creator_dashboard_is_embedded_for_its_module_only(hr_manager, role_user, copies):
    response = send(
        hr_manager,
        "post",
        "/api/v1/portal/manage/dashboards/",
        {"superset_ref": str(copies["hr"]), "domain": "hr", "title": "Creator test copy"},
    )
    assert response.status_code == 201, response.content
    key = response.json()["dashboard"]["key"]
    assert response.json()["dashboard"]["visible"] is False

    hr = viewer(role_user, "au_exec", "DrukSmart Executive")  # a viewer of the HR page
    # hidden: not listed, no token
    assert key not in [d["key"] for d in hr.get("/api/v1/portal/dashboards/").json()["dashboards"]]
    assert hr.post(f"/api/v1/portal/dashboards/{key}/guest-token/").status_code == 404

    assert (
        send(
            hr_manager, "patch", f"/api/v1/portal/manage/dashboards/{key}/", {"visible": True}
        ).status_code
        == 200
    )
    assert key in [d["key"] for d in hr.get("/api/v1/portal/dashboards/").json()["dashboards"]]
    token = hr.post(f"/api/v1/portal/dashboards/{key}/guest-token/").json()["token"]
    charts = httpx.get(
        f"{BASE}/api/v1/dashboard/{copies['hr']}/charts",
        headers={"X-GuestToken": token},
        timeout=20,
    )
    assert charts.status_code == 200 and len(charts.json()["result"]) > 0

    accounts = viewer(role_user, "au_acc", "DrukSmart Accounts Manager")
    assert accounts.post(f"/api/v1/portal/dashboards/{key}/guest-token/").status_code == 403


def test_dashboard_with_another_modules_data_cannot_be_published(admin, copies):
    response = send(
        admin,
        "post",
        "/api/v1/portal/manage/dashboards/",
        {"superset_ref": str(copies["mixed"]), "domain": "hr"},
    )
    assert response.status_code == 400
    assert "kpi_receivables_payables" in response.json()["message"]
