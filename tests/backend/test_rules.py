"""Deterministic interpreter: question -> registry function + parameters (no database, no LLM)."""

from __future__ import annotations

import pytest
from assistant.interpretation import Context
from assistant.rules import RulesInterpreter
from backend_support import LABELS, REFERENCE_DATE

CTX = Context(LABELS, REFERENCE_DATE)


def interpret(q: str):
    return RulesInterpreter().interpret(q, CTX)


@pytest.mark.parametrize(
    ("question", "function", "params"),
    [
        ("How many active employees are there?", "hr.active_headcount", {}),
        (
            "How many employees work in each department?",
            "hr.active_headcount",
            {"group_by": "department"},
        ),
        ("Headcount per branch", "hr.active_headcount", {"group_by": "branch"}),
        (
            "How many people work in Sales?",
            "hr.active_headcount",
            {"filters": {"department": "Sales"}},
        ),
        (
            "How many employees are in the Finance & Accounts department?",
            "hr.active_headcount",
            {"filters": {"department": "Finance & Accounts"}},
        ),
        (
            "Staff count at the Phuentsholing branch",
            "hr.active_headcount",
            {"filters": {"branch": "DTG Retail - Phuentsholing"}},
        ),
        (
            "How many employees does DTG Retail have?",
            "hr.active_headcount",
            {"filters": {"organisation": "DTG Retail Pvt Ltd"}},
        ),
        ("Headcount on 2026-10-23", "hr.active_headcount", {"as_of": "2026-10-23"}),
        ("How many employees are active vs inactive?", "hr.employment_status", {}),
        ("How many employees are on approved leave?", "hr.approved_leave", {}),
        (
            "How many leave days were approved in October 2026?",
            "hr.approved_leave",
            {"period_start": "2026-10-01", "period_end": "2026-10-31"},
        ),
        ("Approved leave by leave type", "hr.approved_leave", {"group_by": "leave_type"}),
        ("What is the outstanding receivables balance?", "ac.outstanding_receivables", {}),
        ("How much do customers owe us?", "ac.outstanding_receivables", {}),
        ("Accounts receivable by branch", "ac.outstanding_receivables", {"group_by": "branch"}),
        ("What is the outstanding payables balance?", "ac.outstanding_payables", {}),
        ("What do we owe to creditors?", "ac.outstanding_payables", {}),
        ("How much is overdue?", "ac.overdue_balance", {}),
        ("Overdue receivables", "ac.overdue_balance", {"filters": {"ledger": "receivable"}}),
        ("Show overdue balances by ageing category.", "ac.overdue_by_ageing", {}),
        ("Ageing of payables", "ac.ageing", {"filters": {"ledger": "payable"}}),
    ],
)
def test_supported_questions(question, function, params):
    result = interpret(question)
    assert result.kind == "kpi" and result.interpreter == "rules"
    assert result.function == function
    assert result.parameters == params


def test_accounts_payable_is_not_the_accounts_department():
    result = interpret("What are our accounts payable?")
    assert result.function == "ac.outstanding_payables" and "filters" not in result.parameters


def test_unknown_department_is_passed_on_for_validation():
    result = interpret("How many employees are in the Marketing department?")
    assert result.parameters["filters"] == {"department": "marketing"}


@pytest.mark.parametrize(
    "question", ["What is the outstanding balance?", "How many?", "Receivables and payables"]
)
def test_ambiguous_questions_ask_for_clarification(question):
    result = interpret(question)
    assert result.kind == "clarify" and result.options


@pytest.mark.parametrize(
    ("question", "reason"),
    [
        ("What is the salary of the HR manager?", "personal_data"),
        ("Give me the bank account numbers of our employees", "personal_data"),
        ("Who is on leave today?", "individual_records"),
        ("List all employees in Sales", "individual_records"),
        ("Which customers owe us the most?", "individual_records"),
        ("Delete the overdue invoices", "write"),
        ("SELECT * FROM marts.dim_employee", "sql"),
        ("headcount; DROP TABLE marts.kpi_headcount", "sql"),
        ("Forecast receivables for next month", "forecast"),
        ("What is our revenue this year?", "other_module"),
        ("What's the weather in Thimphu?", "not_kpi"),
    ],
)
def test_unsupported_questions_are_refused_before_any_kpi(question, reason):
    result = interpret(question)
    assert result.kind == "unsupported" and result.reason == reason and result.function is None
