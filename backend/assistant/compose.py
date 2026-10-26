"""Deterministic business-language answers from a KpiResult (always available, no LLM).

The text is built only from the result rows, so it cannot contain a number the warehouse did
not return. Used as the answer when no LLM is configured, and as the fallback when an LLM
phrasing fails verification.
"""

from __future__ import annotations

import calendar
import re
from datetime import date

from kpi.service import KpiResult


def _date(iso: str | None) -> str:
    if not iso:
        return ""
    d = date.fromisoformat(iso)
    return f"{d.day} {d:%B %Y}"


def _period(period: dict | None) -> str:
    if not period:
        return ""
    start, end = date.fromisoformat(period["start"]), date.fromisoformat(period["end"])
    month_end = calendar.monthrange(end.year, end.month)[1]
    if (
        start.day == 1
        and (start.year, start.month) == (end.year, end.month)
        and end.day == month_end
    ):
        return f"{start:%B %Y}"
    if start == end:
        return _date(period["start"])
    return f"{_date(period['start'])} to {_date(period['end'])}"


def _num(value, unit: str, currency: str | None = None) -> str:
    if value is None:
        return "n/a"
    if unit == "amount":
        text = f"{value:,.2f}"
        return f"{currency} {text}" if currency else text
    if unit == "days":
        return f"{value:,.1f}".rstrip("0").rstrip(".") if value % 1 else f"{int(value):,}"
    return f"{int(value):,}"


def _bucket(label: str) -> str:
    return re.sub(r"^\d+\s+", "", label)  # "1 1-30 days overdue" -> "1-30 days overdue"


def _context(result: KpiResult) -> str:
    bits = []
    if result.as_of:
        bits.append(f"as of {_date(result.as_of)}")
    if result.period:
        bits.append(f"in {_period(result.period)}")
    filters = [f"{k.replace('_', ' ')}: {v}" for k, v in result.filters.items()]
    text = " ".join(bits)
    if filters:
        text += f" ({'; '.join(filters)})"
    return text


def compose(result: KpiResult, focus: str | None = None) -> str:
    rows, ctx = result.rows, _context(result)
    f = result.function
    if f == "hr.active_headcount":
        if result.group_by:
            dim = result.group_by[0]
            parts = [f"{r[dim]} {r['active_headcount']:,}" for r in rows]
            total = sum(r["active_headcount"] for r in rows)
            label = dim.replace("_", " ")
            return f"Active employees by {label} {ctx}: {', '.join(parts)} (total {total:,})."
        n = rows[0]["active_headcount"]
        return f"There {'is' if n == 1 else 'are'} {n:,} active employee{'s' * (n != 1)} {ctx}."
    if f == "hr.employment_status":
        total = sum(r["employee_records"] for r in rows)
        active = sum(r["employee_records"] for r in rows if r["employment_status"] == "active")
        others = [
            f"{r['employment_status'].replace('_', ' ')} {r['employee_records']:,}"
            for r in rows
            if r["employment_status"] != "active"
        ]
        rest = f" ({', '.join(others)})" if others else ""
        return (
            f"Of {total:,} employee records {ctx}, {active:,} are active and "
            f"{total - active:,} are not active{rest}."
        )
    if f == "hr.approved_leave":
        if result.group_by:
            dim = result.group_by[0]
            parts = [
                f"{r[dim]}: {r['employees_on_leave']:,} employees, {r['approved_requests']:,} "
                f"requests, {_num(r['approved_leave_days'], 'days')} days"
                for r in rows
            ]
            return f"Approved leave starting {ctx}, by {dim.replace('_', ' ')}: {'; '.join(parts)}."
        r = rows[0]
        employees = f"{r['employees_on_leave']:,} employee{'s' * (r['employees_on_leave'] != 1)}"
        requests = (
            f"{r['approved_requests']:,} approved request{'s' * (r['approved_requests'] != 1)}"
        )
        days = f"{_num(r['approved_leave_days'], 'days')} leave days"
        if not r["approved_requests"]:
            return f"No approved leave starts {ctx}."
        if focus == "approved_leave_days":
            return (
                f"{days.capitalize()} were approved for leave starting {ctx} "
                f"({requests}, {employees})."
            )
        if focus == "approved_requests":
            return f"There were {requests} for leave starting {ctx} ({days}, {employees})."
        return f"{employees.capitalize()} had approved leave starting {ctx} ({requests}, {days})."
    if f in ("ac.outstanding_receivables", "ac.outstanding_payables"):
        what = "receivables" if f.endswith("receivables") else "payables"
        if len(result.group_by) > 1:
            dim = result.group_by[1]
            parts = [
                f"{_bucket(r[dim]) if dim == 'ageing' else r[dim]} "
                f"{_num(r['outstanding_amount'], 'amount', r['currency'])}"
                for r in rows
            ]
            return f"Outstanding {what} {ctx} by {dim}: {'; '.join(parts)}."
        parts = [
            f"{_num(r['outstanding_amount'], 'amount', r['currency'])} "
            f"({r['open_documents']:,} open documents)"
            for r in rows
        ]
        return f"Outstanding {what} {ctx}: {' and '.join(parts)}."
    if f == "ac.overdue_balance":
        extra = [d for d in result.group_by if d not in ("ledger", "currency")]
        parts = [
            f"{r['ledger']}s"
            + (f" ({r[extra[0]]})" if extra else "")
            + f" {_num(r['overdue_amount'], 'amount', r['currency'])}"
            for r in rows
        ]
        return f"Overdue balances {ctx}: {'; '.join(parts)}."
    if f in ("ac.overdue_by_ageing", "ac.ageing"):
        measure = "overdue_amount" if f == "ac.overdue_by_ageing" else "outstanding_amount"
        by_ledger: dict[str, list[str]] = {}
        for r in rows:
            by_ledger.setdefault(r["ledger"], []).append(
                f"{_bucket(r['ageing'])} {_num(r[measure], 'amount', r['currency'])}"
            )
        parts = [
            f"{ledger.capitalize()}s: {', '.join(items)}" for ledger, items in by_ledger.items()
        ]
        title = (
            "Overdue balances by ageing category"
            if measure == "overdue_amount"
            else ("Open balances by ageing bucket")
        )
        return f"{title} {ctx}. {'. '.join(parts)}."
    return f"{result.title} {ctx}: see the table."  # pragma: no cover - every function handled
