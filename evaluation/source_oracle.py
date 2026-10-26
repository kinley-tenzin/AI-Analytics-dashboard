"""INDEPENDENT source oracle: KPI figures computed directly from the ERPs' own records.

It does not use the connectors, the raw tables or dbt. It calls each ERP's API with its own small
read-only HTTP client (the same READ-ONLY API users the pipeline uses), takes the ERPs' own
computed balances (Odoo `amount_residual_signed`, ERPNext `outstanding_amount`) and applies the
business rules of docs/data/KPI_CATALOGUE.md in plain Python. Agreement between this oracle and
the warehouse is evidence that extraction + transformation reproduce the source figures.

    python evaluation/source_oracle.py 2026-10-25        # prints the figures for that date
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date

import httpx

sys.path.insert(0, os.path.dirname(__file__))
import evaltools  # noqa: E402,F401  (loads .env)

BUCKETS = ((0, "not_due"), (30, "1_30"), (60, "31_60"), (90, "61_90"))


def bucket(amount: float, due: date | None, as_of: date) -> str:
    if amount < 0:
        return "unapplied_credit"
    if due is None:
        return "no_due_date"
    days = (as_of - due).days
    for limit, name in BUCKETS:
        if days <= limit:
            return name
    return "91_plus"


def _d(value) -> date | None:
    return date.fromisoformat(str(value)[:10]) if value else None


class Odoo:
    def __init__(self):
        self.http = httpx.Client(
            base_url=os.environ["ODOO_BASE_URL"],
            timeout=60,
            headers={
                "Authorization": f"bearer {os.environ['ODOO_API_KEY']}",
                "X-Odoo-Database": os.environ["ODOO_DATABASE"],
            },
        )

    def read(self, model: str, domain: list, fields: list) -> list[dict]:
        resp = self.http.post(
            f"/json/2/{model}/search_read",
            json={"domain": domain, "fields": fields, "context": {"active_test": False}},
        )
        resp.raise_for_status()
        return resp.json()


class ERPNext:
    def __init__(self):
        self.http = httpx.Client(
            base_url=os.environ["ERPNEXT_BASE_URL"],
            timeout=60,
            headers={"Authorization": f"token {os.environ['ERPNEXT_API_KEY']}:{os.environ['ERPNEXT_API_SECRET']}"},
        )

    def read(self, doctype: str, filters: list, fields: list) -> list[dict]:
        resp = self.http.get(
            f"/api/resource/{doctype}",
            params={
                "filters": json.dumps(filters),
                "fields": json.dumps(fields),
                "limit_page_length": 0,
            },
        )
        resp.raise_for_status()
        return resp.json()["data"]


def _ledgers(docs: list[tuple[str, float, date | None]], as_of: date) -> dict:
    """docs: (ledger, signed company-currency open amount, due date)."""
    out = {"receivable": 0.0, "payable": 0.0, "overdue_receivable": 0.0, "overdue_payable": 0.0}
    ageing: dict[str, float] = defaultdict(float)
    for ledger, amount, due in docs:
        if round(amount, 2) == 0:
            continue
        out[ledger] += amount
        if amount > 0 and due is not None and due < as_of:
            out[f"overdue_{ledger}"] += amount
        ageing[f"{ledger}|{bucket(amount, due, as_of)}"] += amount
    out = {k: round(v, 2) for k, v in out.items()}
    out["ageing"] = {k: round(v, 2) for k, v in sorted(ageing.items())}
    return out


def odoo_figures(as_of: date, period: tuple[date, date]) -> dict:
    api = Odoo()
    employees = api.read("hr.employee", [], ["active", "departure_date", "department_id"])
    active = [e for e in employees if e["active"] and (not e["departure_date"] or _d(e["departure_date"]) > as_of)]
    by_dept = Counter((e["department_id"] or [None, "Unassigned"])[1] for e in active)
    leaves = api.read(
        "hr.leave",
        [
            ["state", "=", "validate"],
            ["request_date_from", ">=", str(period[0])],
            ["request_date_from", "<=", str(period[1])],
        ],
        ["employee_id", "number_of_days"],
    )
    moves = api.read(
        "account.move",
        [
            ["state", "=", "posted"],
            ["payment_state", "!=", "invoicing_legacy"],
            ["move_type", "in", ["out_invoice", "out_refund", "in_invoice", "in_refund"]],
            ["invoice_date", "<=", str(as_of)],
        ],
        ["move_type", "amount_residual_signed", "invoice_date_due"],
    )
    docs = []
    for m in moves:
        ledger = "receivable" if m["move_type"].startswith("out") else "payable"
        sign = -1 if m["move_type"].endswith("refund") else 1
        docs.append((ledger, sign * abs(m["amount_residual_signed"]), _d(m["invoice_date_due"])))
    return {
        "headcount": len(active),
        "by_department": dict(by_dept),
        "leave": {
            "employees": len({lv["employee_id"][0] for lv in leaves}),
            "requests": len(leaves),
            "days": round(sum(lv["number_of_days"] for lv in leaves), 2),
        },
        **_ledgers(docs, as_of),
    }


def erpnext_figures(as_of: date, period: tuple[date, date]) -> dict:
    api = ERPNext()
    depts = {d["name"]: d["department_name"] for d in api.read("Department", [], ["name", "department_name"])}
    employees = api.read("Employee", [], ["status", "date_of_joining", "relieving_date", "department"])
    active = [
        e
        for e in employees
        if e["status"] == "Active"
        and _d(e["date_of_joining"]) <= as_of
        and (not e["relieving_date"] or _d(e["relieving_date"]) > as_of)
    ]
    by_dept = Counter(depts.get(e["department"], "Unassigned") for e in active)
    leaves = api.read(
        "Leave Application",
        [
            ["docstatus", "=", 1],
            ["status", "=", "Approved"],
            ["from_date", ">=", str(period[0])],
            ["from_date", "<=", str(period[1])],
        ],
        ["employee", "total_leave_days"],
    )
    docs = []
    for doctype, ledger in (("Sales Invoice", "receivable"), ("Purchase Invoice", "payable")):
        for inv in api.read(
            doctype,
            [["docstatus", "=", 1], ["posting_date", "<=", str(as_of)]],
            [
                "outstanding_amount",
                "is_return",
                "due_date",
                "conversion_rate",
                "currency",
                "party_account_currency",
            ],
        ):
            amount = abs(inv["outstanding_amount"])
            if inv["party_account_currency"] != "BTN":  # company currency of the sandbox
                amount *= inv["conversion_rate"]
            sign = -1 if inv["is_return"] else 1
            docs.append((ledger, sign * amount, _d(inv["due_date"])))
    return {
        "headcount": len(active),
        "by_department": dict(by_dept),
        "leave": {
            "employees": len({lv["employee"] for lv in leaves}),
            "requests": len(leaves),
            "days": round(sum(lv["total_leave_days"] for lv in leaves), 2),
        },
        **_ledgers(docs, as_of),
    }


def figures(as_of: date, period: tuple[date, date]) -> dict:
    return {
        os.environ["ODOO_INSTANCE_ID"]: odoo_figures(as_of, period),
        os.environ["ERPNEXT_INSTANCE_ID"]: erpnext_figures(as_of, period),
    }


if __name__ == "__main__":
    d = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    print(json.dumps(figures(d, (d.replace(day=1), d)), indent=2))
