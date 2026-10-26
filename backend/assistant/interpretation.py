"""What an interpreter (rules or LLM) may produce from a question: a PROPOSAL, never an action.

An interpretation is one of:
  * kpi         -> a registry function name + parameters, still to be validated and authorised
                   by the KPI service;
  * clarify     -> the question is ambiguous; suggested rephrasings;
  * unsupported -> outside what the assistant answers (personal data, SQL, writes, forecasts,
                   other modules, not a KPI question), with a reason.
Interpreters never see query results, the user's permissions or any database connection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Protocol

Kind = Literal["kpi", "clarify", "unsupported"]

UNSUPPORTED_REASONS = {
    "personal_data": (
        "Individual pay, bank, identity and contact details are not available through the "
        "assistant."
    ),
    "individual_records": (
        "The assistant answers with aggregated KPIs only. It does not list or identify "
        "individual employees, customers or suppliers."
    ),
    "write": "The assistant is read-only: it cannot create, change, approve or delete records.",
    "sql": "Database queries (SQL) are not accepted. Ask a question in plain language instead.",
    "forecast": "Forecasts and predictions are not part of the supported KPIs.",
    "other_module": (
        "Only Human Resources (headcount, leave) and Accounts (receivables, payables, overdue, "
        "ageing) KPIs are supported."
    ),
    "not_kpi": "This does not look like a question about a supported HR or Accounts KPI.",
}


@dataclass
class Interpretation:
    kind: Kind
    interpreter: str  # e.g. "rules" or "gemini:gemini-2.5-flash"
    function: str | None = None
    parameters: dict = field(default_factory=dict)
    focus: str | None = None  # measure to lead the answer with (e.g. approved_leave_days)
    reason: str | None = None  # key of UNSUPPORTED_REASONS
    message: str = ""
    options: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # e.g. "Gemini unavailable, rules fallback"

    def request_dict(self) -> dict:
        return {"function": self.function, **self.parameters}


@dataclass(frozen=True)
class Context:
    labels: dict[str, list[str]]  # organisational labels per dimension (KpiService.labels)
    reference_date: date | None  # latest data date, anchors "this month", "yesterday"


class Interpreter(Protocol):
    name: str

    def interpret(self, question: str, context: Context) -> Interpretation: ...
