"""Gemini integration with a MOCKED HTTP transport (no network, no API key).

These tests prove what the code sends and how it treats replies. They do NOT prove the real
model's accuracy: that needs GEMINI_API_KEY and `manage.py evaluate_assistant --provider gemini`.
"""

from __future__ import annotations

import json

import httpx
import pytest
from assistant.gemini import (
    GeminiClient,
    GeminiError,
    GeminiInterpreter,
    tool_declarations,
    verify_numbers,
)
from assistant.interpretation import Context
from backend_support import LABELS, REFERENCE_DATE

CTX = Context(LABELS, REFERENCE_DATE)
KEY = "test-key-not-real"


def function_call(name: str, args: dict | None = None) -> dict:
    return {
        "candidates": [
            {"content": {"parts": [{"functionCall": {"name": name, "args": args or {}}}]}}
        ]
    }


def client_returning(*responses, seen: list | None = None) -> GeminiClient:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        status, body = queue.pop(0)
        return httpx.Response(status, json=body)

    return GeminiClient(KEY, "gemini-test", transport=httpx.MockTransport(handler))


def test_request_offers_only_registry_tools_and_forces_a_tool_call():
    seen: list[httpx.Request] = []
    gemini = GeminiInterpreter(
        client_returning((200, function_call("hr_active_headcount")), seen=seen)
    )
    gemini.interpret("How many active employees are there?", CTX)
    request = seen[0]
    body = json.loads(request.content)
    assert request.headers["x-goog-api-key"] == KEY and KEY not in request.content.decode()
    assert body["toolConfig"]["functionCallingConfig"]["mode"] == "ANY"
    names = {d["name"] for d in body["tools"][0]["functionDeclarations"]}
    assert names == {
        "hr_active_headcount",
        "hr_employment_status",
        "hr_approved_leave",
        "ac_outstanding_receivables",
        "ac_outstanding_payables",
        "ac_overdue_balance",
        "ac_overdue_by_ageing",
        "ac_ageing",
        "request_clarification",
        "decline",
    }
    text = request.content.decode().lower()
    # No SQL, tables, keys or personal identifiers are sent to the model.
    for forbidden in ("select ", "marts.", "employee_key", "branch_key", "dim_employee", "raw."):
        assert forbidden not in text


def test_department_names_are_offered_as_allowed_values():
    decl = {d["name"]: d for d in tool_declarations(CTX)}
    props = decl["hr_active_headcount"]["parameters"]["properties"]
    assert props["department"]["enum"] == LABELS["department"]
    assert props["group_by"]["enum"] == [
        "department",
        "branch",
        "organisation",
        "employee_category",
    ]


@pytest.mark.parametrize(
    ("reply", "kind", "function", "params"),
    [
        (
            function_call("hr_active_headcount", {"group_by": "department"}),
            "kpi",
            "hr.active_headcount",
            {"group_by": "department"},
        ),
        (
            function_call("ac_overdue_balance", {"ledger": "receivable", "as_of": "2026-10-24"}),
            "kpi",
            "ac.overdue_balance",
            {"as_of": "2026-10-24", "filters": {"ledger": "receivable"}},
        ),
        (function_call("decline", {"reason": "personal_data"}), "unsupported", None, {}),
        (
            function_call(
                "request_clarification", {"message": "Which ledger?", "options": ["a", "b"]}
            ),
            "clarify",
            None,
            {},
        ),
        (function_call("run_sql", {"query": "select 1"}), "unsupported", None, {}),
    ],
)
def test_replies_become_proposals_only(reply, kind, function, params):
    result = GeminiInterpreter(client_returning((200, reply))).interpret("q", CTX)
    assert (result.kind, result.function, result.parameters) == (kind, function, params)
    assert result.interpreter == "gemini:gemini-test"


def test_unknown_arguments_are_dropped():
    reply = function_call("hr_active_headcount", {"department": "Sales", "sql": "drop table x"})
    result = GeminiInterpreter(client_returning((200, reply))).interpret("q", CTX)
    assert result.parameters == {"filters": {"department": "Sales"}}


@pytest.mark.parametrize(
    "reply",
    [
        (500, {"error": {"message": "internal"}}),
        (429, {"error": {"message": "quota"}}),
        (200, {"candidates": []}),
        (200, {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}),
    ],
)
def test_api_failures_raise_gemini_error(reply):
    with pytest.raises(GeminiError):
        GeminiInterpreter(client_returning(reply)).interpret("q", CTX)


def test_missing_key_is_a_configuration_error():
    with pytest.raises(GeminiError):
        GeminiClient("", "gemini-test")


RESULT = {
    "kpi": "Outstanding receivables",
    "as_of": "2026-10-25",
    "rows": [{"currency": "BTN", "outstanding_amount": 166700, "open_documents": 10}],
}


@pytest.mark.parametrize(
    ("text", "bad"),
    [
        (
            "Outstanding receivables are BTN 166,700.00 as of 25 October 2026 (10 open documents).",
            [],
        ),
        ("Receivables total BTN 166,700 across 10 documents.", []),
        ("Receivables are BTN 170,000, up 2% from last month.", ["170,000", "2"]),
    ],
)
def test_llm_numbers_must_come_from_the_result(text, bad):
    assert verify_numbers(text, RESULT) == bad
