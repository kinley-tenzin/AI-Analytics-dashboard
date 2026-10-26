"""Ask AI page support endpoint (backend/portal/assistant_info.py, Task 10.6)."""

from __future__ import annotations

import pytest
from kpi import registry

pytestmark = pytest.mark.django_db


def test_requires_sign_in(client):
    assert client.get("/api/v1/portal/assistant/").status_code == 401


@pytest.mark.parametrize(
    "role,domains",
    [
        ("DrukSmart HR Manager", {"hr"}),
        ("DrukSmart Accounts Manager", {"accounts"}),
        ("DrukSmart Executive", {"hr", "accounts"}),
    ],
)
def test_suggestions_are_registry_examples_of_the_users_modules(client, role_user, role, domains):
    role_user("as_user", role)
    client.login(username="as_user", password="pw-for-tests")
    data = client.get("/api/v1/portal/assistant/").json()
    expected = [e for f in registry.functions_for(domains) for e in f.examples]
    assert [s["question"] for s in data["suggestions"]] == expected
    assert {s["domain"] for s in data["suggestions"]} == domains


def test_user_without_role_gets_no_suggestions(client, role_user):
    role_user("as_none", None)
    client.login(username="as_none", password="pw-for-tests")
    assert client.get("/api/v1/portal/assistant/").json()["suggestions"] == []


def test_provider_is_reported_honestly(client, role_user):
    """The test settings use the rules interpreter: the page must not claim a language model."""
    role_user("as_prov", "DrukSmart HR Manager")
    client.login(username="as_prov", password="pw-for-tests")
    data = client.get("/api/v1/portal/assistant/").json()
    assert data["provider"]["provider"] == "rules" and data["provider"]["llm"] is False
    assert data["max_question_length"] == 500
