"""Reference (oracle) KPI calculator over the SYNTHETIC fixtures. Test-only code.

It applies the canonical rules in contracts/canonical/*.yaml directly in Python, so the
hand-calculated numbers in expected_kpis.json can be cross-checked by a second, independent
derivation. It is deliberately simple and is NOT the production implementation (that will
be the dbt models, which must reproduce the same numbers).
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from functools import cache
from pathlib import Path

import yaml

from druksmart_common.config import REPO_ROOT
from druksmart_common.contracts import has_errors, load_source_contract, validate_record

# Same switch as connectors/synthetic/fake_api.py: the scale test points both at the medium set.
_FIXTURE_SET = os.environ.get("DRUKSMART_SYNTHETIC_FIXTURES", "tests/fixtures/synthetic")
FIXTURES_DIR = REPO_ROOT / _FIXTURE_SET
CANONICAL_DIR = REPO_ROOT / "contracts" / "canonical"
MAPPINGS_FILE = REPO_ROOT / "contracts" / "mappings" / "entity_mappings.yaml"
BUCKETS = ("not_due", "1_30", "31_60", "61_90", "91_plus", "no_due_date", "unapplied_credit")


@dataclass(frozen=True)
class Fixture:
    path: Path
    meta: dict
    records: list[dict]

    @property
    def extracted_at(self) -> datetime:
        return datetime.fromisoformat(self.meta["extracted_at"].replace("Z", "+00:00"))


@cache
def load_fixtures() -> tuple[Fixture, ...]:
    fixtures = []
    for path in sorted(FIXTURES_DIR.glob("*/*/*.json")):
        doc = json.loads(path.read_text("utf-8"))
        response = doc["response"]
        records = response if doc["_meta"]["source_system"] == "odoo" else response["data"]
        fixtures.append(Fixture(path, doc["_meta"], records))
    return tuple(fixtures)


@cache
def canonical(name: str) -> dict:
    return yaml.safe_load((CANONICAL_DIR / f"{name}.yaml").read_text("utf-8"))


def instance(system: str) -> str:
    return next(
        f.meta["source_instance"] for f in load_fixtures() if f.meta["source_system"] == system
    )


def key(system: str, source_id) -> str:
    return f"{system}:{instance(system)}:{source_id}"


def rejected_ids() -> dict[str, dict[str, list[str]]]:
    """Source ids whose LATEST version breaks the contract, per system and entity."""
    out: dict[str, dict[str, list[str]]] = defaultdict(dict)
    for system in ("odoo", "erpnext"):
        contract = load_source_contract(system)
        entities = {f.meta["entity"] for f in load_fixtures() if f.meta["source_system"] == system}
        for entity in sorted(entities):
            bad = [
                str(rec[contract.entity(entity).primary_key])
                for rec in latest(system, entity, date.max, include_invalid=True).values()
                if has_errors(validate_record(contract, entity, rec))
            ]
            if bad:
                out[system][entity] = sorted(bad)
    return dict(out)


def latest(system: str, entity: str, as_of: date, include_invalid=False) -> dict[str, dict]:
    """Latest version of each record from batches extracted on or before ``as_of``."""
    contract = load_source_contract(system)
    pk = contract.entity(entity).primary_key
    batches = sorted(
        (
            f
            for f in load_fixtures()
            if f.meta["source_system"] == system
            and f.meta["entity"] == entity
            and f.extracted_at.date() <= as_of
        ),
        key=lambda f: f.extracted_at,
    )
    records: dict[str, dict] = {}
    for batch in batches:
        for rec in batch.records:
            records[str(rec[pk])] = rec
    if include_invalid:
        return records
    return {
        sid: rec
        for sid, rec in records.items()
        if not has_errors(validate_record(contract, entity, rec))
    }


def d(value) -> date | None:
    return date.fromisoformat(value) if isinstance(value, str) and value else None


def m2o_id(value):
    return value[0] if value else None


# --------------------------------------------------------------------------------- HR


def employee_status(system: str, rec: dict, as_of: date) -> str:
    if system == "odoo":
        departure = d(rec["departure_date"])
        if rec["active"]:
            return "left" if departure and departure <= as_of else "active"
        return "left" if departure else "inactive"
    status = canonical("hr")["entities"]["employee"]["status_rules"]["erpnext"]["status_map"][
        rec["status"]
    ]
    if status == "active":
        if d(rec["date_of_joining"]) > as_of:
            return "not_yet_joined"
        if d(rec["relieving_date"]) and d(rec["relieving_date"]) <= as_of:
            return "left"
    return status


def active_employees(as_of: date) -> list[dict]:
    """Canonical rows for employees counted in headcount."""
    counted = canonical("hr")["entities"]["employee"]["counts_in_headcount"]
    rows = []
    for rec in latest("odoo", "hr.employee", as_of).values():
        if employee_status("odoo", rec, as_of) in counted:
            rows.append(
                {
                    "system": "odoo",
                    "employee_key": key("odoo", rec["id"]),
                    "branch_key": key("odoo", m2o_id(rec["company_id"])),
                    "department_key": key("odoo", m2o_id(rec["department_id"]) or "unassigned"),
                    "category": rec["employee_type"],
                }
            )
    for rec in latest("erpnext", "Employee", as_of).values():
        if employee_status("erpnext", rec, as_of) in counted:
            rows.append(
                {
                    "system": "erpnext",
                    "employee_key": key("erpnext", rec["name"]),
                    "branch_key": key("erpnext", rec["branch"] or "unassigned"),
                    "department_key": key("erpnext", rec["department"] or "unassigned"),
                    "category": "unspecified",
                }
            )
    return rows


def headcount(as_of: date) -> dict:
    rows = active_employees(as_of)
    by_instance, by_branch, by_dept = defaultdict(int), defaultdict(int), defaultdict(int)
    for r in rows:
        by_instance[instance(r["system"])] += 1
        by_branch[r["branch_key"]] += 1
        by_dept[r["department_key"]] += 1
    return {
        "by_instance": dict(by_instance),
        "total": len(rows),
        "by_branch": dict(by_branch),
        "by_department": dict(by_dept),
    }


def leave_status(system: str, rec: dict) -> str:
    rules = canonical("hr")["entities"]["leave_request"]["status_rules"]
    if system == "odoo":
        return rules["odoo"]["status_map"][rec["state"]]
    erp = rules["erpnext"]
    if rec["docstatus"] == 2:
        return erp["docstatus_2"]
    if rec["docstatus"] == 0:
        return erp["docstatus_0"]
    return erp["docstatus_1_status_map"][rec["status"]]


def approved_leave(start: date, end: date) -> dict:
    fields = {
        "odoo": ("hr.leave", "request_date_from", "number_of_days", "employee_id"),
        "erpnext": ("Leave Application", "from_date", "total_leave_days", "employee"),
    }
    result = {}
    for system, (entity, start_field, days_field, emp_field) in fields.items():
        approved = [
            rec
            for rec in latest(system, entity, end).values()
            if leave_status(system, rec) == "approved" and start <= d(rec[start_field]) <= end
        ]
        employees = {m2o_id(r[emp_field]) if system == "odoo" else r[emp_field] for r in approved}
        result[instance(system)] = {
            "requests": len(approved),
            "days": float(sum(r[days_field] for r in approved)),
            "employees": len(employees),
        }
    total = {k: sum(v[k] for v in result.values()) for k in ("requests", "days", "employees")}
    total["days"] = float(total["days"])
    return {"by_instance": result, "total": total}


# --------------------------------------------------------------------------- Accounts


@dataclass(frozen=True)
class Document:
    system: str
    document_key: str
    ledger: str
    kind: str
    state: str
    due_date: date | None
    total_company: float
    outstanding_company: float
    counterparty_key: str
    branch_key: str
    source_status: str | None


def company_currency() -> str:
    return next(iter(latest("erpnext", "Company", date.max).values()))["default_currency"]


def odoo_documents(as_of: date) -> list[Document]:
    spec = canonical("accounts")["entities"]["accounting_document"]
    docs = []
    for rec in latest("odoo", "account.move", as_of).values():
        if rec["move_type"] not in spec["type_map"]["odoo"]:
            continue
        if rec["payment_state"] in spec["excluded_payment_states"]["odoo"]:
            continue
        ledger, kind = spec["type_map"]["odoo"][rec["move_type"]]
        sign = spec["document_sign"][kind]
        docs.append(
            Document(
                system="odoo",
                document_key=key("odoo", rec["id"]),
                ledger=ledger,
                kind=kind,
                state=spec["state_map"]["odoo"][rec["state"]],
                due_date=d(rec["invoice_date_due"]),
                total_company=sign * abs(rec["amount_total_signed"]),
                outstanding_company=sign * abs(rec["amount_residual_signed"]),
                counterparty_key=key("odoo", m2o_id(rec["partner_id"])),
                branch_key=key("odoo", m2o_id(rec["company_id"])),
                source_status=rec["payment_state"],
            )
        )
    return docs


def erpnext_documents(as_of: date) -> list[Document]:
    spec = canonical("accounts")["entities"]["accounting_document"]
    base = company_currency()
    docs = []
    for doctype, party_field in (("Sales Invoice", "customer"), ("Purchase Invoice", "supplier")):
        for rec in latest("erpnext", doctype, as_of).values():
            ledger, kind = spec["type_map"]["erpnext"][doctype][rec["is_return"]]
            sign = spec["document_sign"][kind]
            if rec["party_account_currency"] == base:
                factor = 1.0
            elif rec["party_account_currency"] == rec["currency"]:
                factor = rec["conversion_rate"]
            else:
                raise ValueError(f"{rec['name']}: unsupported currency combination")
            docs.append(
                Document(
                    system="erpnext",
                    document_key=key("erpnext", rec["name"]),
                    ledger=ledger,
                    kind=kind,
                    state=spec["state_map"]["erpnext_docstatus"][rec["docstatus"]],
                    due_date=d(rec["due_date"]),
                    total_company=sign * abs(rec["base_grand_total"]),
                    outstanding_company=sign * abs(rec["outstanding_amount"]) * factor,
                    counterparty_key=key("erpnext", rec[party_field]),
                    branch_key=key("erpnext", "unassigned"),
                    source_status=rec["status"],
                )
            )
    return docs


def open_documents(as_of: date) -> list[Document]:
    return [
        doc
        for doc in odoo_documents(as_of) + erpnext_documents(as_of)
        if doc.state == "posted" and doc.outstanding_company != 0
    ]


def bucket(doc: Document, as_of: date) -> str:
    if doc.outstanding_company < 0:
        return "unapplied_credit"
    if doc.due_date is None:
        return "no_due_date"
    days = (as_of - doc.due_date).days
    if days <= 0:
        return "not_due"
    if days <= 30:
        return "1_30"
    if days <= 60:
        return "31_60"
    if days <= 90:
        return "61_90"
    return "91_plus"


def _by_instance(values: dict[str, float]) -> dict[str, float]:
    out = {instance(s): float(values.get(instance(s), 0.0)) for s in ("odoo", "erpnext")}
    out["total"] = float(sum(out.values()))
    return out


def accounts_kpis(as_of: date) -> dict:
    outstanding = {"receivable": defaultdict(float), "payable": defaultdict(float)}
    overdue = {"receivable": defaultdict(float), "payable": defaultdict(float)}
    ageing = {
        ledger: {instance(s): dict.fromkeys(BUCKETS, 0.0) for s in ("odoo", "erpnext")}
        for ledger in ("receivable", "payable")
    }
    by_branch = {"receivable": defaultdict(float), "payable": defaultdict(float)}
    by_counterparty = defaultdict(float)
    unified = unified_ids()

    for doc in open_documents(as_of):
        inst = instance(doc.system)
        outstanding[doc.ledger][inst] += doc.outstanding_company
        b = bucket(doc, as_of)
        ageing[doc.ledger][inst][b] += doc.outstanding_company
        if b in ("1_30", "31_60", "61_90", "91_plus"):
            overdue[doc.ledger][inst] += doc.outstanding_company
        by_branch[doc.ledger][doc.branch_key] += doc.outstanding_company
        if doc.ledger == "receivable":
            by_counterparty[unified.get(doc.counterparty_key, doc.counterparty_key)] += (
                doc.outstanding_company
            )

    return {
        "AC-01_outstanding_receivables": _by_instance(outstanding["receivable"]),
        "AC-02_outstanding_payables": _by_instance(outstanding["payable"]),
        "AC-03_overdue_receivables": _by_instance(overdue["receivable"]),
        "AC-03_overdue_payables": _by_instance(overdue["payable"]),
        "AC-04_receivables_ageing": ageing["receivable"],
        "AC-04_payables_ageing": ageing["payable"],
        "AC-01_receivables_by_branch": dict(by_branch["receivable"]),
        "AC-02_payables_by_branch": dict(by_branch["payable"]),
        "AC-01_receivables_by_counterparty": dict(by_counterparty),
        "unallocated_advances_received": unallocated_advances(as_of),
    }


def unallocated_advances(as_of: date) -> dict[str, float]:
    result = {instance("odoo"): 0.0, instance("erpnext"): 0.0}
    for rec in latest("erpnext", "Payment Entry", as_of).values():
        if rec["docstatus"] == 1 and rec["payment_type"] == "Receive":
            result[instance("erpnext")] += rec["unallocated_amount"] or 0.0
    for rec in latest("odoo", "account.payment", as_of).values():
        # Odoo: a posted inbound payment linked to no invoice is an advance.
        posted = rec["state"] in ("in_process", "paid")
        if posted and rec["payment_type"] == "inbound" and not rec["reconciled_invoice_ids"]:
            result[instance("odoo")] += rec["amount"]
    return result


@cache
def unified_ids() -> dict[str, str]:
    doc = yaml.safe_load(MAPPINGS_FILE.read_text("utf-8"))
    return {member: m["unified_id"] for m in doc["mappings"] for member in m["members"]}


# ---------------------------------------------------------------------- reconciliation


def derived_payment_status(doc: Document) -> str:
    if doc.outstanding_company == 0:
        return "paid"
    if abs(doc.outstanding_company) == abs(doc.total_company):
        return "unpaid"
    return "partially_paid"


def status_inconsistencies(as_of: date) -> list[str]:
    """Posted documents whose derived payment status contradicts the source status."""
    cross = canonical("accounts")["entities"]["accounting_document"]["source_status_cross_check"]
    problems = []
    for doc in odoo_documents(as_of) + erpnext_documents(as_of):
        if doc.state != "posted":
            continue
        table = cross["odoo_payment_state"] if doc.system == "odoo" else cross["erpnext_status"]
        if doc.source_status in table and table[doc.source_status] != derived_payment_status(doc):
            problems.append(f"{doc.document_key}: source {doc.source_status}")
    return problems


def payment_reconciliation_differences(as_of: date) -> list[str]:
    """Invoices where (total - outstanding) differs from posted payment allocations.

    ERPNext: allocations from Payment Entry references plus returns against the invoice.
    Odoo: payments linked through reconciled_*_ids (exact when one invoice per payment).
    Reversed Odoo invoices are settled by their credit note, not by payments.
    """
    problems = []

    odoo_paid = defaultdict(float)
    for pay in latest("odoo", "account.payment", as_of).values():
        if pay["state"] in ("in_process", "paid"):
            for mid in pay["reconciled_invoice_ids"] + pay["reconciled_bill_ids"]:
                odoo_paid[mid] += pay["amount"]
    for rec in latest("odoo", "account.move", as_of).values():
        if rec["state"] != "posted" or rec["move_type"] not in ("out_invoice", "in_invoice"):
            continue
        if rec["payment_state"] == "reversed":
            continue
        settled = rec["amount_total"] - rec["amount_residual"]
        if abs(settled - odoo_paid[rec["id"]]) > 0.005:
            problems.append(
                f"odoo {rec['id']}: settled {settled} vs payments {odoo_paid[rec['id']]}"
            )

    allocated = defaultdict(float)
    for pe in latest("erpnext", "Payment Entry", as_of).values():
        if pe["docstatus"] == 1:
            for ref in pe["references"]:
                allocated[ref["reference_name"]] += ref["allocated_amount"]
    for doctype in ("Sales Invoice", "Purchase Invoice"):
        docs = latest("erpnext", doctype, as_of)
        for rec in docs.values():
            applied_to_original = not rec.get("update_outstanding_for_self", 1)
            if (
                rec["docstatus"] == 1
                and rec["is_return"]
                and rec["return_against"]
                and applied_to_original
            ):
                allocated[rec["return_against"]] += abs(rec["base_grand_total"])
        for rec in docs.values():
            if rec["docstatus"] != 1 or rec["is_return"]:
                continue
            settled = rec["base_grand_total"] - rec["outstanding_amount"]
            paid = allocated[rec["name"]]
            if abs(settled - paid) > 0.005:
                problems.append(f"erpnext {rec['name']}: settled {settled} vs allocated {paid}")
    return problems
