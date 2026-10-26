"""DETERMINISTIC question interpreter (no language model). Development/test fallback.

Keyword and pattern rules map a question to one registry function plus parameters. It is
transparent and repeatable but brittle: phrasings it has no rule for become "clarify" or
"unsupported". It is labelled "rules" everywhere and must never be presented as an LLM.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

from .interpretation import Context, Interpretation

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS |= {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}

# ---- refusals first: never let a sensitive question fall through to a KPI ----------------------
REFUSALS = [
    ("sql", r"\bselect\b.+\bfrom\b|;\s*\w|--|\bsql\b|\bdrop\s+table\b|\bunion\s+select\b"),
    (
        "write",
        r"\b(delete|insert|drop|truncate|alter|update|approve|reject|cancel|remove|"
        r"create|modify|edit|write off)\b",
    ),
    (
        "personal_data",
        r"\b(salar(y|ies)|payslips?|pay\s*slips?|wages?|bank|account numbers?|"
        r"passports?|cid|citizenship|national id|date of birth|birthdays?|"
        r"home address(es)?|phone|e-?mail|contact details|pay amounts?)\b",
    ),
    (
        "individual_records",
        r"\b(who (?:is|are|was|were|has|have|took|owes?)|whose|names? of|"
        r"(?:employee|customer|supplier) names|which (?:employees|customers|"
        r"suppliers|people)|list (?:all |the )?(?:employees|staff|people|"
        r"customers|suppliers|invoices))\b",
    ),
    (
        "forecast",
        r"\b(forecast\w*|predict\w*|projection\w*|will (?:be|have)|next (?:month|"
        r"year|quarter|week))\b",
    ),
    (
        "other_module",
        r"\b(revenue|profit|margin|inventory|stock levels?|sales orders?|"
        r"purchase orders?|cash ?flow|budget\w*|expenses?|payroll|tax(es)?)\b",
    ),
]

LEAVE = r"\b(leaves?|absen\w*|time off|vacation|holidays?)\b"
AGEING = r"\b(age?ing|aged|buckets?|categor(?:y|ies)|age bands?|by age)\b"
OVERDUE = r"\b(overdue|past due|late|delinquent|not paid on time)\b"
RECEIVABLE = (
    r"\b(receivables?|a/?r|debtors?|owed to us|owe us|customers? owes?|"
    r"customer (?:balances?|invoices?)|from customers|owed by customers)\b"
)
PAYABLE = (
    r"\b(payables?|a/?p|creditors?|we owe|owed to (?:our |the )?(?:suppliers|vendors)|"
    r"owe (?:our |the )?(?:suppliers?|vendors?|creditors?)|(?:supplier|vendor) "
    r"(?:balances?|invoices?)|unpaid bills)\b"
)
CONTRACTIONS = {"who's": "who is", "what's": "what is", "how's": "how is", "where's": "where is"}
OUTSTANDING = r"\b(outstanding|open balances?|unpaid|balances?|owed|owing|due amounts?)\b"
HEADCOUNT = (
    r"\b(employees?|staff|headcount|head count|workforce|people|personnel|workers?|"
    r"team members?|employed)\b"
)
STATUS = (
    r"\b(inactive|not active|non-active|employment status|left|resigned|suspended|"
    r"terminated|status(es)?|active (?:vs\.?|versus|and|or) (?:in|not )active)\b"
)
HOW_MANY = r"\b(how many|how much|total|count|number of|what is|what are|show)\b"
GROUP_CUE = r"\b(each|every|per|by|across|breakdown|broken down|split|wise|distribution)\b"

GROUP_WORDS = [
    ("department", r"\b(departments?|teams?|divisions?)\b"),
    ("branch", r"\b(branch(?:es)?|offices?|locations?)\b"),
    ("organisation", r"\b(organi[sz]ations?|compan(?:y|ies)|entit(?:y|ies))\b"),
    ("leave_type", r"\b(leave types?|types? of leave|kinds? of leave)\b"),
    ("month", r"\b(month(?:ly)?|per month|each month)\b"),
    ("employee_category", r"\b(categor(?:y|ies)|employee types?)\b"),
    ("ageing", r"\b(age?ing|buckets?)\b"),
]
# "in the Marketing department" -> an explicit (possibly unknown) filter value
EXPLICIT_FILTER = re.compile(
    r"\b(?:in|for|at|of|from)\s+(?:the\s+)?([a-z][\w&'.\- ]{1,40}?)\s+"
    r"(department|team|division|branch|office)\b"
)
EXPLICIT_DIM = {
    "department": "department",
    "team": "department",
    "division": "department",
    "branch": "branch",
    "office": "branch",
}
LEGAL_SUFFIX = re.compile(r"\s+(pvt\.?\s+ltd\.?|private limited|ltd\.?|limited)$")

SUGGESTIONS = [
    "How many active employees are there?",
    "How many employees work in each department?",
    "How many employees are on approved leave?",
    "What is the outstanding receivables balance?",
    "What is the outstanding payables balance?",
    "How much is overdue?",
    "Show overdue balances by ageing category.",
]


def _has(pattern: str, text: str) -> bool:
    return re.search(pattern, text) is not None


def _aliases(dim: str, label: str) -> set[str]:
    """Ways a user may write an organisational label ("DTG Retail" for "DTG Retail Pvt Ltd")."""
    low = label.lower()
    out = {low}
    stripped = LEGAL_SUFFIX.sub("", low)
    out.add(stripped)
    if dim == "branch":
        if " - " in low:
            out.add(low.split(" - ", 1)[1].strip())
        if "(head office)" in low:
            out.add("head office")
    return {a for a in out if len(a) >= 3}


class RulesInterpreter:
    name = "rules"

    def interpret(self, question: str, context: Context) -> Interpretation:
        q = " ".join(question.lower().replace("’", "'").split())
        q = q.rstrip("?.! ")
        for short, full in CONTRACTIONS.items():
            q = q.replace(short, full)

        for reason, pattern in REFUSALS:
            if _has(pattern, q):
                return Interpretation("unsupported", self.name, reason=reason)

        function, focus = self._function(q)
        if function == "clarify-ledger":
            return Interpretation(
                "clarify",
                self.name,
                message="Do you mean receivables (owed to us) or payables (owed by us)?",
                options=[
                    "What is the outstanding receivables balance?",
                    "What is the outstanding payables balance?",
                ],
            )
        if function is None:
            if _has(HOW_MANY, q) and len(q.split()) <= 4:
                return Interpretation(
                    "clarify",
                    self.name,
                    message="Which KPI do you mean? For example:",
                    options=SUGGESTIONS,
                )
            return Interpretation("unsupported", self.name, reason="not_kpi", options=SUGGESTIONS)

        params: dict = {}
        notes: list[str] = []
        filters = self._filters(q, context, notes)
        params.update(self._dates(q, function, context, notes))
        group_by = self._group_by(q, function, filters)
        if group_by:
            params["group_by"] = group_by
        ledger = self._ledger(q)
        if ledger and function in ("ac.overdue_balance", "ac.overdue_by_ageing", "ac.ageing"):
            filters["ledger"] = ledger
        if filters:
            params["filters"] = filters
        return Interpretation("kpi", self.name, function, params, focus=focus, notes=notes)

    # ------------------------------------------------------------------ intent
    def _function(self, q: str) -> tuple[str | None, str | None]:
        if _has(LEAVE, q):
            if _has(r"\bdays?\b", q):
                return "hr.approved_leave", "approved_leave_days"
            if _has(r"\b(requests?|applications?)\b", q):
                return "hr.approved_leave", "approved_requests"
            return "hr.approved_leave", "employees_on_leave"
        rec, pay = _has(RECEIVABLE, q), _has(PAYABLE, q)
        if _has(OVERDUE, q):
            if _has(AGEING, q):
                return "ac.overdue_by_ageing", None
            return "ac.overdue_balance", None
        if _has(AGEING, q) and (rec or pay or _has(OUTSTANDING, q)):
            return "ac.ageing", None
        if rec and pay:
            return "clarify-ledger", None
        if rec:
            return "ac.outstanding_receivables", None
        if pay:
            return "ac.outstanding_payables", None
        if _has(OUTSTANDING, q):
            return "clarify-ledger", None
        if _has(HEADCOUNT, q) or _has(r"\bactive\b", q):
            if _has(STATUS, q):
                return "hr.employment_status", None
            return "hr.active_headcount", None
        return None, None

    @staticmethod
    def _ledger(q: str) -> str | None:
        rec, pay = _has(RECEIVABLE, q), _has(PAYABLE, q)
        if rec and not pay:
            return "receivable"
        if pay and not rec:
            return "payable"
        return None

    # ------------------------------------------------------------------ parameters
    def _filters(self, q: str, context: Context, notes: list[str]) -> dict[str, str]:
        # "accounts payable/receivable" is a ledger, not the "Accounts" department.
        text = re.sub(r"\baccounts?\s+(payable|receivable)s?\b", r"\1", q)
        found: dict[str, str] = {}
        candidates = sorted(
            (
                (alias, dim, label)
                for dim in (
                    "branch",
                    "organisation",
                    "department",
                    "leave_type",
                    "employee_category",
                )
                for label in context.labels.get(dim, [])
                for alias in _aliases(dim, label)
            ),
            key=lambda c: -len(c[0]),
        )
        taken: list[tuple[int, int]] = []
        for alias, dim, label in candidates:
            if dim in found:
                continue
            for m in re.finditer(rf"(?<![\w]){re.escape(alias)}(?![\w])", text):
                span = m.span()
                if any(s < span[1] and span[0] < e for s, e in taken):
                    continue  # overlaps a longer label already matched
                found[dim] = label
                taken.append(span)
                break
        # Explicit "in the X department" with an unknown X: pass it through so that the
        # service reports an invalid filter (with the valid values) instead of ignoring it.
        for m in EXPLICIT_FILTER.finditer(text):
            value, word = m.group(1).strip(), m.group(2)
            dim = EXPLICIT_DIM[word]
            generic = {"each", "every", "all", "which", "what", "per", "the", "a", "my", "our"}
            if dim not in found and value.split()[-1] not in generic and value not in generic:
                found[dim] = value
                notes.append(f"Interpreted {value!r} as a {dim} name.")
        return found

    def _dates(self, q: str, function: str, context: Context, notes: list[str]) -> dict:
        ref = context.reference_date
        iso = re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", q)
        month = re.search(
            r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?\s+(\d{4})\b", q
        )
        year = re.search(r"\b(?:in|during|for)\s+(20\d{2})\b", q)
        period = function == "hr.approved_leave"
        if period:
            if len(iso) >= 2:
                return {"period_start": iso[0], "period_end": iso[1]}
            if iso:
                return {"period_start": iso[0], "period_end": iso[0]}
            if month:
                y, mth = int(month.group(2)), MONTHS[month.group(1)]
                last = calendar.monthrange(y, mth)[1]
                return {
                    "period_start": date(y, mth, 1).isoformat(),
                    "period_end": date(y, mth, last).isoformat(),
                }
            if year:
                y = int(year.group(1))
                return {"period_start": f"{y}-01-01", "period_end": f"{y}-12-31"}
            if ref and _has(r"\blast month\b", q):
                end = ref.replace(day=1) - timedelta(days=1)
                return {
                    "period_start": end.replace(day=1).isoformat(),
                    "period_end": end.isoformat(),
                }
            if ref and _has(r"\b(today|currently|right now|at the moment)\b", q):
                notes.append("Leave is counted by start date; 'today' was read as this month.")
            return {}
        if iso:
            return {"as_of": iso[0]}
        if ref and _has(r"\byesterday\b", q):
            return {"as_of": (ref - timedelta(days=1)).isoformat()}
        if month:
            y, mth = int(month.group(2)), MONTHS[month.group(1)]
            notes.append(
                "A month was given; balances exist per snapshot date, so the month end was used."
            )
            return {"as_of": date(y, mth, calendar.monthrange(y, mth)[1]).isoformat()}
        return {}

    @staticmethod
    def _group_by(q: str, function: str, filters: dict) -> str | None:
        allowed = {
            "hr.active_headcount": ("department", "branch", "organisation", "employee_category"),
            "hr.approved_leave": ("leave_type", "department", "branch", "organisation", "month"),
            "ac.outstanding_receivables": ("organisation", "branch", "ageing"),
            "ac.outstanding_payables": ("organisation", "branch", "ageing"),
            "ac.overdue_balance": ("organisation", "branch"),
        }.get(function, ())
        cue = _has(GROUP_CUE, q)
        for dim, pattern in GROUP_WORDS:
            if dim not in allowed or dim in filters:
                continue
            m = re.search(pattern, q)
            if m and (cue or m.group(0).endswith(("s", "es", "ies", "ly"))):
                return dim
        return None
