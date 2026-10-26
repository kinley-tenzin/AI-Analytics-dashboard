"""HTTP API, authentication and the assistant pipeline (Django test client, fake warehouse).

The warehouse is replaced by fakes here so that the ACCESS logic is tested in isolation:
a forbidden request must be refused before any warehouse query is made.
"""

from __future__ import annotations

import json

import pytest
from assistant.gemini import GeminiClient, GeminiInterpreter
from assistant.models import QuestionLog
from assistant.pipeline import Assistant
from backend_support import LABELS, REFERENCE_DATE
from kpi.service import KpiResult, KpiService

pytestmark = pytest.mark.django_db

HR = "DrukSmart HR Manager"
ACC = "DrukSmart Accounts Manager"
BRANCH_ROLE = "DrukSmart Branch Manager"


class FakeService(KpiService):
    """Labels from fixtures; runs functions WITHOUT a warehouse (records what was executed)."""

    def __init__(self):
        super().__init__(connect=self._no_warehouse)
        self.executed: list[str] = []

    @staticmethod
    def _no_warehouse():
        raise AssertionError("no warehouse in these tests")

    def labels(self):
        return LABELS

    def latest_data_date(self):
        return REFERENCE_DATE

    def run(self, request, scope):
        from kpi import registry
        from kpi.service import Forbidden

        f = registry.get(request.function)
        if f is not None and not scope.allows(f.domain):  # the real service's first checks
            raise Forbidden("forbidden", domain=f.domain)
        self.executed.append(request.function)
        return KpiResult(
            function=request.function,
            kpi_ids=["HR-01"],
            title="Active employee headcount",
            domain="hr",
            dataset="marts.kpi_headcount",
            as_of="2026-10-25",
            period=None,
            group_by=[],
            filters={},
            branch_restricted=False,
            columns=[{"name": "active_headcount", "label": "Active headcount", "unit": "count"}],
            rows=[{"active_headcount": 16}],
            freshness=[],
            notes=[],
        )


@pytest.fixture(autouse=True)
def fresh_context_cache():
    from django.core.cache import cache

    cache.clear()


def post_json(client, url, data):
    return client.post(url, data=json.dumps(data), content_type="application/json")


# ------------------------------------------------------------------ authentication
@pytest.mark.parametrize("url", ["/api/v1/ask/", "/api/v1/kpis/run/"])
def test_api_requires_login(client, url):
    resp = post_json(client, url, {"question": "x"})
    assert resp.status_code == 401 and resp.json()["status"] == "unauthenticated"


def test_old_pages_redirect_to_the_website(client):
    """Decision 3 (Milestone 10): the website replaced the old server-rendered assistant page."""
    assert client.get("/")["Location"] == "/app/"
    assert client.get("/assistant/")["Location"] == "/app/ask"


def test_csrf_is_enforced_for_session_api_calls(role_user):
    from django.test import Client

    role_user("csrf_user", HR)
    c = Client(enforce_csrf_checks=True)
    c.login(username="csrf_user", password="pw-for-tests")
    resp = post_json(c, "/api/v1/ask/", {"question": "How many active employees are there?"})
    assert resp.status_code == 403


def test_health_live(client):
    assert client.get("/health/").json() == {"status": "ok"}


# ------------------------------------------------------------------ KPI API
def test_kpi_list_contains_only_the_users_domain(client, role_user):
    role_user("hr1", HR)
    client.login(username="hr1", password="pw-for-tests")
    names = {f["name"] for f in client.get("/api/v1/kpis/").json()["functions"]}
    assert names == {"hr.active_headcount", "hr.employment_status", "hr.approved_leave"}


def test_me_reports_scope(client, role_user):
    role_user("br1", BRANCH_ROLE, ("odoo:odoo-sandbox:1",))
    client.login(username="br1", password="pw-for-tests")
    scope = client.get("/api/v1/me/").json()["scope"]
    assert scope["roles"] == [BRANCH_ROLE] and scope["branch_restricted"] is True


@pytest.mark.parametrize(
    ("payload", "status", "code"),
    [
        ({"function": "ac.outstanding_receivables"}, 403, "forbidden"),
        (
            {"function": "hr.active_headcount", "sql": "select * from raw.source_record"},
            400,
            "invalid_filter",
        ),
        ({"function": "warehouse.dump"}, 404, "unsupported"),
    ],
)
def test_kpi_run_rejections_never_reach_the_warehouse(
    client, role_user, monkeypatch, payload, status, code
):
    import kpi.warehouse

    def no_query():
        raise AssertionError("warehouse must not be queried")

    monkeypatch.setattr(kpi.warehouse, "connect", no_query)
    monkeypatch.setattr("kpi.service.warehouse.connect", no_query)
    role_user("hr2", HR)
    client.login(username="hr2", password="pw-for-tests")
    resp = post_json(client, "/api/v1/kpis/run/", payload)
    assert resp.status_code == status and resp.json()["status"] == code


def test_branch_manager_without_branch_gets_nothing():
    from access.scope import scope_for
    from django.contrib.auth.models import Group, User
    from kpi.service import Forbidden, KpiRequest

    user = User.objects.create_user("lonely_manager", password="x")
    user.groups.add(Group.objects.get_or_create(name=BRANCH_ROLE)[0])
    scope = scope_for(user)
    assert scope.branch_keys == frozenset()
    with pytest.raises(Forbidden):
        KpiService(connect=FakeService._no_warehouse).run(KpiRequest("hr.active_headcount"), scope)


def test_user_without_role_has_no_access(role_user):
    from access.scope import scope_for

    assert scope_for(role_user("norole", None)).domains == frozenset()


# ------------------------------------------------------------------ assistant pipeline
@pytest.mark.parametrize(
    ("role", "question", "status", "executed"),
    [
        (HR, "How many active employees are there?", "answered", ["hr.active_headcount"]),
        (HR, "What is the outstanding receivables balance?", "forbidden", []),
        (HR, "How much is overdue?", "forbidden", []),
        (ACC, "How many employees are on approved leave?", "forbidden", []),
        (HR, "What is the salary of the HR manager?", "unsupported", []),
        (HR, "What is the outstanding balance?", "clarification_needed", []),
        (HR, "", "invalid_request", []),
        (HR, "x" * 501, "invalid_request", []),
    ],
)
def test_assistant_statuses(role_user, role, question, status, executed):
    user = role_user("u1", role)
    service = FakeService()
    answer = Assistant(service=service).ask(question, user)
    assert answer.status == status
    assert service.executed == executed  # forbidden / refused questions execute NOTHING
    log = QuestionLog.objects.get()
    assert log.status == status and log.user == user


def test_user_without_role_is_refused(role_user):
    answer = Assistant(service=FakeService()).ask("How many employees?", role_user("x", None))
    assert answer.status == "forbidden"


def test_ask_endpoint_returns_answer_and_context(client, role_user, monkeypatch):
    monkeypatch.setattr("assistant.views.Assistant", lambda: Assistant(service=FakeService()))
    role_user("hr3", HR)
    client.login(username="hr3", password="pw-for-tests")
    data = post_json(
        client, "/api/v1/ask/", {"question": "How many active employees are there?"}
    ).json()
    assert data["status"] == "answered" and "16 active employees" in data["answer"]
    assert data["interpreter"] == "rules" and data["llm_used"] is False
    assert data["result"]["rows"] == [{"active_headcount": 16}]


def test_gemini_failure_falls_back_to_clearly_labelled_rules(role_user):
    import httpx

    failing = GeminiClient(
        "k", "gemini-test", transport=httpx.MockTransport(lambda r: httpx.Response(503, json={}))
    )
    gemini = GeminiInterpreter(failing)
    answer = Assistant(service=FakeService(), interpreter=gemini, gemini=None).ask(
        "How many active employees are there?", role_user("hr4", HR)
    )
    assert answer.status == "answered"
    assert answer.interpreter == "rules (fallback)"
    assert any("Gemini was unavailable" in n for n in answer.notes)
    assert answer.to_dict()["llm_used"] is False


def test_llm_phrasing_with_invented_numbers_is_rejected(role_user, settings):
    import httpx

    settings.DRUKSMART_AI = {**settings.DRUKSMART_AI, "LLM_PHRASING": True}
    replies = [
        {
            "candidates": [
                {
                    "content": {
                        "parts": [{"functionCall": {"name": "hr_active_headcount", "args": {}}}]
                    }
                }
            ]
        },
        {"candidates": [{"content": {"parts": [{"text": "There are 18 active employees."}]}}]},
    ]
    client = GeminiClient(
        "k",
        "gemini-test",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=replies.pop(0))),
    )
    gemini = GeminiInterpreter(client)
    answer = Assistant(service=FakeService(), interpreter=gemini, gemini=gemini).ask(
        "How many active employees are there?", role_user("hr5", HR)
    )
    assert answer.status == "answered" and answer.interpreter == "gemini:gemini-test"
    assert "16" in answer.answer and "18" not in answer.answer
    assert answer.phrasing == "template (LLM text rejected)"


def test_api_keeps_json_contract_when_the_database_fails(client, role_user, monkeypatch):
    """Milestone 8 defect D10: database errors under /api/ become JSON 503, not an HTML page."""
    from django.db import OperationalError

    def broken(*args, **kwargs):
        raise OperationalError("server closed the connection")

    role_user("hr_db", HR)
    client.login(username="hr_db", password="pw-for-tests")
    monkeypatch.setattr("assistant.views.Assistant", lambda: type("A", (), {"ask": broken})())
    resp = post_json(client, "/api/v1/ask/", {"question": "How many active employees are there?"})
    assert resp.status_code == 503
    assert resp.json()["status"] == "error"
