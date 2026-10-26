"""Administration API: status, dashboard visibility and registration, users (Task 10.7)."""

from __future__ import annotations

import json

import httpx
import pytest
from django.test import Client
from fake_superset import FakeSuperset
from kpi.service import KpiService
from portal import admin_api
from portal.models import PortalDashboard
from portal.superset import SupersetGateway

pytestmark = pytest.mark.django_db
PASSWORD = "pw-for-tests"
ADMIN_URLS = ["/api/v1/portal/admin/status/", "/api/v1/portal/admin/users/"]
MANAGE = "/api/v1/portal/manage/dashboards/"


@pytest.fixture
def superset(monkeypatch, settings):
    fake = FakeSuperset()
    fake.datasets["creator-hr-leave"] = [("kpi_approved_leave_monthly", 2), ("data_freshness", 4)]
    fake.datasets["creator-mixed"] = [("kpi_headcount", 1), ("kpi_receivables_payables", 3)]
    settings.DRUKSMART_SUPERSET = {**settings.DRUKSMART_SUPERSET, "SERVICE_PASSWORD": "pw"}
    transport = httpx.MockTransport(fake.handler)
    monkeypatch.setattr(admin_api, "SupersetGateway", lambda: SupersetGateway(transport))
    monkeypatch.setattr(
        KpiService,
        "freshness",
        lambda self, d: {
            "domain": d,
            "sources": [],
            "hours_since_publication": 2.0,
            "stale": False,
            "synthetic": False,
        },
    )
    SupersetGateway.forget()
    yield fake
    SupersetGateway.forget()


@pytest.fixture
def admin(django_user_model):
    django_user_model.objects.create_superuser("ad_admin", password=PASSWORD)
    client = Client()
    client.login(username="ad_admin", password=PASSWORD)
    return client


def send(client, method, url, body=None):
    return getattr(client, method)(url, json.dumps(body or {}), content_type="application/json")


@pytest.mark.parametrize("url", ADMIN_URLS)
def test_admin_api_is_for_the_administrator_only(client, role_user, url):
    assert client.get(url).status_code == 401
    role_user("ad_hrm", "DrukSmart HR Manager")  # even a module manager
    client.login(username="ad_hrm", password=PASSWORD)
    assert client.get(url).status_code == 403


@pytest.mark.parametrize(
    "role,branches",
    [("DrukSmart Executive", ()), ("DrukSmart Branch Manager", ("odoo:odoo-sandbox:1",))],
)
def test_viewers_cannot_manage_dashboards(client, role_user, role, branches):
    role_user("ad_viewer", role, branches=branches)
    client.login(username="ad_viewer", password=PASSWORD)
    assert client.get(MANAGE).status_code == 403
    assert send(client, "patch", f"{MANAGE}hr/", {"visible": False}).status_code == 403
    assert send(client, "post", MANAGE, {"superset_ref": "x", "domain": "hr"}).status_code == 403
    assert PortalDashboard.objects.get(key="hr").visible is True


def hr_manager(client, role_user):
    role_user("ad_hr_manager", "DrukSmart HR Manager")
    client.login(username="ad_hr_manager", password=PASSWORD)
    return client


def test_hr_manager_manages_only_the_hr_page(client, role_user, superset):
    hr = hr_manager(client, role_user)
    data = hr.get(MANAGE).json()
    assert [d["key"] for d in data["dashboards"]] == ["hr"] and data["author_domains"] == ["hr"]
    assert send(hr, "patch", f"{MANAGE}hr/", {"visible": False}).status_code == 200
    # the Accounts page is not theirs: looks unknown, and nothing changes
    assert send(hr, "patch", f"{MANAGE}accounts/", {"visible": False}).status_code == 404
    assert hr.delete(f"{MANAGE}accounts/").status_code == 404
    assert PortalDashboard.objects.get(key="accounts").visible is True


def test_hr_manager_publishes_own_dashboard_but_not_on_the_accounts_page(
    client, role_user, superset
):
    hr = hr_manager(client, role_user)
    refused = send(hr, "post", MANAGE, {"superset_ref": "creator-hr-leave", "domain": "accounts"})
    assert refused.status_code == 403
    created = send(hr, "post", MANAGE, {"superset_ref": "creator-hr-leave", "domain": "hr"})
    assert created.status_code == 201
    key = created.json()["dashboard"]["key"]
    assert send(hr, "patch", f"{MANAGE}{key}/", {"visible": True}).status_code == 200
    assert hr.delete(f"{MANAGE}{key}/").status_code == 200


def test_hr_manager_cannot_publish_a_dashboard_with_accounts_data(client, role_user, superset):
    hr = hr_manager(client, role_user)
    response = send(hr, "post", MANAGE, {"superset_ref": "creator-mixed", "domain": "hr"})
    assert response.status_code == 400 and "kpi_receivables_payables" in response.json()["message"]


def test_status_reports_services_without_kpi_values(admin, superset):
    data = admin.get("/api/v1/portal/admin/status/").json()
    assert data["superset"] == {
        "reachable": True,
        "service_account": True,
        "public_url": data["superset"]["public_url"],
    }
    assert [m["domain"] for m in data["modules"]] == ["hr", "accounts"]
    assert data["assistant"]["provider"] == "rules"
    assert data["warehouse"]["consumer_data"] in ("live", "synthetic")
    assert data["counts"]["dashboards"] == 2


def test_status_when_superset_is_down(admin, superset):
    superset.down = True
    data = admin.get("/api/v1/portal/admin/status/").json()
    assert data["superset"]["reachable"] is False and data["superset"]["service_account"] is False


def test_hide_and_show_a_dashboard(admin, superset):
    response = send(admin, "patch", "/api/v1/portal/manage/dashboards/hr/", {"visible": False})
    assert response.status_code == 200 and response.json()["dashboard"]["visible"] is False
    assert PortalDashboard.objects.get(key="hr").visible is False
    send(
        admin,
        "patch",
        "/api/v1/portal/manage/dashboards/hr/",
        {"visible": True, "title": "HR", "position": 5},
    )
    d = PortalDashboard.objects.get(key="hr")
    assert (d.visible, d.title, d.position) == (True, "HR", 5)


@pytest.mark.parametrize(
    "body",
    [
        {"visible": "no"},
        {"title": " "},
        {"domain": "accounts"},
        {"superset_ref": "other"},
        {"position": "x"},
    ],
)
def test_invalid_changes_are_rejected(admin, superset, body):
    response = send(admin, "patch", "/api/v1/portal/manage/dashboards/hr/", body)
    assert response.status_code == 400
    d = PortalDashboard.objects.get(key="hr")
    assert (d.domain, d.superset_ref, d.visible) == ("hr", "druksmart-hr", True)


def test_official_dashboards_cannot_be_removed(admin, superset):
    assert admin.delete("/api/v1/portal/manage/dashboards/hr/").status_code == 400
    assert PortalDashboard.objects.filter(key="hr").exists()


def test_register_a_creators_dashboard(admin, superset, settings):
    response = send(
        admin,
        "post",
        "/api/v1/portal/manage/dashboards/",
        {"superset_ref": "creator-hr-leave", "domain": "hr", "title": "Leave planner"},
    )
    assert response.status_code == 201
    d = response.json()["dashboard"]
    assert (d["kind"], d["domain"], d["visible"], d["title"]) == (
        "custom",
        "hr",
        False,
        "Leave planner",
    )
    # embedding was enabled for the website's origin only
    assert superset.embedding_enabled == [
        ("creator-hr-leave", [settings.DRUKSMART_SUPERSET["WEB_ORIGIN"]])
    ]
    # ... and it can be removed again (Superset keeps the dashboard)
    assert admin.delete(f"/api/v1/portal/manage/dashboards/{d['key']}/").status_code == 200


def test_register_refuses_a_dashboard_with_data_of_another_module(admin, superset):
    response = send(
        admin,
        "post",
        "/api/v1/portal/manage/dashboards/",
        {"superset_ref": "creator-mixed", "domain": "hr"},
    )
    assert response.status_code == 400
    assert "kpi_receivables_payables" in response.json()["message"]
    assert not PortalDashboard.objects.filter(superset_ref="creator-mixed").exists()


@pytest.mark.parametrize(
    "body,status",
    [
        ({"superset_ref": "missing", "domain": "hr"}, 404),
        ({"superset_ref": "druksmart-hr", "domain": "hr"}, 409),
        ({"superset_ref": "x'; drop", "domain": "hr"}, 400),
        ({"superset_ref": "creator-hr-leave", "domain": "sales"}, 400),
    ],
)
def test_register_validation(admin, superset, body, status):
    assert send(admin, "post", "/api/v1/portal/manage/dashboards/", body).status_code == status


def test_users_list_shows_roles_modules_and_branches(admin, role_user):
    role_user("ad_branch", "DrukSmart Branch Manager", branches=("odoo:odoo-sandbox:1",))
    data = admin.get("/api/v1/portal/admin/users/").json()
    row = next(u for u in data["users"] if u["username"] == "ad_branch")
    assert row["roles"] == ["DrukSmart Branch Manager"]
    assert row["modules"] == ["accounts", "hr"]
    assert row["branches"] == ["odoo:odoo-sandbox:1"]
    assert {"role": "DrukSmart HR Manager", "modules": ["hr"]} in data["roles"]
    assert data["manage_url"] == "/admin/auth/user/"
    assert "password" not in json.dumps(data)
