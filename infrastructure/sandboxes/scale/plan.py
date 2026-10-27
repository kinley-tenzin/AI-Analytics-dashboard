"""Build the LOAD PLAN that fills the local ERP SANDBOXES with the medium-scale synthetic data.

    python infrastructure/sandboxes/scale/plan.py --slice 0.05     # a 5 % pilot slice
    python infrastructure/sandboxes/scale/plan.py                  # everything

Input : tests/fixtures/synthetic_medium/ (python tests/fixtures/synthetic_medium/generate_medium.py)
Output: tests/fixtures/synthetic_medium/erp_plan/{odoo,erpnext}.json (git-ignored)

The plan is the FINAL state of each fixture entity (later batches overwrite earlier ones). A real ERP
only has its current state, so the 30 Sep / 31 Oct batch history of the fixtures does not carry over.
Records the ERP would refuse on purpose (the fixtures' invalid records) are dropped here.

A slice keeps referential integrity: it selects the first N % of employees and partners and keeps only
the leave requests, documents and payments that belong to them. Every plan item has a stable `ref`,
which the loaders store in the ERP so that loading again never creates duplicates.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "tests" / "fixtures" / "synthetic_medium"
OUT = FIXTURES / "erp_plan"


def final_state(system: str, entity: str, key: str) -> dict:
    """Latest version of every record of one entity across the fixture batches."""
    records: dict = {}
    folder = entity.lower().replace(" ", "_")
    for path in sorted(FIXTURES.glob(f"{system}/*/{folder}.json")):
        response = json.loads(path.read_text("utf-8"))["response"]
        for rec in response if system == "odoo" else response["data"]:
            records[rec[key]] = rec
    return records


def take(items: list, fraction: float) -> list:
    return items[: max(1, math.ceil(len(items) * fraction))] if fraction < 1 else items


# ------------------------------------------------------------------------------- Odoo
def odoo_plan(fraction: float) -> dict:
    partners_all = sorted(final_state("odoo", "res.partner", "id").values(), key=lambda r: r["id"])
    customers = take([p for p in partners_all if p["customer_rank"]], fraction)
    suppliers = take([p for p in partners_all if p["supplier_rank"]], fraction)
    partner_ids = {p["id"] for p in customers + suppliers}
    kind = {p["id"]: "customer" if p["customer_rank"] else "supplier" for p in customers + suppliers}

    departments = {d["id"]: d for d in final_state("odoo", "hr.department", "id").values()}
    employees = []
    for e in take(sorted(final_state("odoo", "hr.employee", "id").values(), key=lambda r: r["id"]), fraction):
        if e["employee_type"] not in ("employee", "contractor", "trainee"):
            continue  # the fixtures' deliberately invalid record
        dept = departments.get((e["department_id"] or [None])[0])
        employees.append(
            {
                "ref": f"SCALE-E-{e['id']}",
                "name": e["name"],
                # the sandbox has two companies (head office, Phuentsholing branch)
                "company": (e["company_id"][0] - 1) % 2,
                "dept": dept["name"] if dept and dept["active"] else None,
                "type": e["employee_type"],
                "active": bool(e["active"]),
                "departure": e["departure_date"] or None,
            }
        )
    emp_refs = {e["ref"] for e in employees}

    leaves = []
    for lv in sorted(final_state("odoo", "hr.leave", "id").values(), key=lambda r: r["id"]):
        ref = f"SCALE-E-{lv['employee_id'][0]}"
        if ref not in emp_refs or lv["request_date_to"] < lv["request_date_from"]:
            continue
        leaves.append(
            {
                "ref": f"SCALE-L-{lv['id']}",
                "emp": ref,
                "start": lv["request_date_from"],
                "end": lv["request_date_to"],
                "state": lv["state"],
            }
        )

    moves, kept = [], set()
    for m in sorted(final_state("odoo", "account.move", "id").values(), key=lambda r: r["id"]):
        if m["partner_id"][0] not in partner_ids or not m["currency_id"]:
            continue
        cur = m["currency_id"][1]
        moves.append(
            {
                "ref": f"SCALE-M-{m['id']}",
                "type": m["move_type"],
                "partner": f"SCALE-P-{m['partner_id'][0]}",
                "date": m["invoice_date"] or None,
                "due": m["invoice_date_due"] or None,
                "cur": "USD" if cur == "USD" else "BTN",  # INR (rate 1) is booked in BTN
                "amount": m["amount_total"],
                "state": m["state"],
            }
        )
        kept.add(m["id"])
    payments = []
    for pay in sorted(final_state("odoo", "account.payment", "id").values(), key=lambda r: r["id"]):
        linked = pay["reconciled_invoice_ids"] + pay["reconciled_bill_ids"]
        if pay["state"] != "paid" or len(linked) != 1 or linked[0] not in kept:
            continue
        payments.append({"move": f"SCALE-M-{linked[0]}", "amount": pay["amount"], "date": pay["date"]})
    return {
        "partners": [
            {
                "ref": f"SCALE-P-{p['id']}",
                "name": p["name"],
                "vat": p["vat"] or None,
                "customer": kind[p["id"]] == "customer",
            }
            for p in customers + suppliers
        ],
        "employees": employees,
        "leaves": leaves,
        "moves": moves,
        "payments": payments,
    }


# ----------------------------------------------------------------------------- ERPNext
def erpnext_plan(fraction: float) -> dict:
    customers = take(list(final_state("erpnext", "Customer", "name").values()), fraction)
    suppliers = take(list(final_state("erpnext", "Supplier", "name").values()), fraction)
    parties = {c["name"] for c in customers} | {s["name"] for s in suppliers}

    employees = {}
    for e in take(list(final_state("erpnext", "Employee", "name").values()), fraction):
        if e["status"] not in ("Active", "Left", "Inactive", "Suspended") or not e["company"]:
            continue  # the fixtures' deliberately invalid records
        employees[e["name"]] = {
            "ref": e["name"],
            "name": e["employee_name"],
            "status": e["status"],
            "dept": e["department"],
            "branch": e["branch"],
            "joined": e["date_of_joining"],
            "relieved": e["relieving_date"],
        }

    leaves = []
    for lv in sorted(final_state("erpnext", "Leave Application", "name").values(), key=lambda r: r["name"]):
        emp = employees.get(lv["employee"])
        if not emp or not lv["leave_type"] or lv["from_date"] < emp["joined"]:
            continue  # HRMS refuses leave before the joining date
        if emp["relieved"] and lv["to_date"] > emp["relieved"]:
            continue
        leaves.append(
            {
                "ref": lv["name"],
                "emp": lv["employee"],
                "type": lv["leave_type"],
                "status": lv["status"],
                "docstatus": lv["docstatus"],
                "from": lv["from_date"],
                "to": lv["to_date"],
                "half": lv["half_day"],
            }
        )

    docs, kept, returns = [], {}, []
    for doctype, party_field in (("Sales Invoice", "customer"), ("Purchase Invoice", "supplier")):
        for inv in sorted(final_state("erpnext", doctype, "name").values(), key=lambda r: r["name"]):
            party = inv[party_field]
            if party not in parties:
                continue
            if inv["is_return"] and inv["return_against"]:
                returns.append(
                    {
                        "ref": inv["name"],
                        "doctype": doctype,
                        "against": inv["return_against"],
                        "date": inv["posting_date"],
                        "amount": abs(inv["grand_total"]),
                    }
                )
                continue
            cur = "USD" if inv["currency"] == "USD" else "BTN"
            docs.append(
                {
                    "ref": inv["name"],
                    "doctype": doctype,
                    "party": party,
                    "date": inv["posting_date"],
                    "due": inv["due_date"],
                    "cur": cur,
                    "rate": inv["conversion_rate"] if cur == "USD" else 1,
                    "amount": abs(inv["grand_total"]),
                    "credit_note": bool(inv["is_return"]),
                    "state": {0: "draft", 1: "posted", 2: "cancel"}[inv["docstatus"]],
                }
            )
            kept[inv["name"]] = doctype
    returns = [r for r in returns if r["against"] in kept]

    payments = []
    for pe in sorted(final_state("erpnext", "Payment Entry", "name").values(), key=lambda r: r["name"]):
        refs = pe["references"]
        if pe["docstatus"] != 1 or len(refs) != 1 or refs[0]["reference_name"] not in kept:
            continue
        payments.append(
            {
                "ref": pe["name"],
                "doctype": kept[refs[0]["reference_name"]],
                "against": refs[0]["reference_name"],
                "amount": refs[0]["allocated_amount"],
                "date": pe["posting_date"],
            }
        )
    return {
        "branches": sorted({e["branch"] for e in employees.values() if e["branch"]}),
        "departments": sorted({e["dept"] for e in employees.values() if e["dept"]}),
        "customers": [{"name": c["name"], "tax_id": c["tax_id"]} for c in customers],
        "suppliers": [{"name": s["name"], "tax_id": s["tax_id"]} for s in suppliers],
        "employees": list(employees.values()),
        "leaves": leaves,
        "invoices": docs,
        "returns": returns,
        "payments": payments,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--slice", type=float, default=1.0, help="fraction to load (0 < f <= 1)")
    args = parser.parse_args()
    if not FIXTURES.joinpath("odoo").is_dir():
        raise SystemExit("generate the data first: python tests/fixtures/synthetic_medium/generate_medium.py")
    OUT.mkdir(parents=True, exist_ok=True)
    for name, builder in (("odoo", odoo_plan), ("erpnext", erpnext_plan)):
        plan = builder(args.slice)
        (OUT / f"{name}.json").write_text(json.dumps(plan, separators=(",", ":")), encoding="utf-8")
        print(name, {k: len(v) for k, v in plan.items()})
    print(f"plans written to {OUT.relative_to(REPO)} (slice {args.slice})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
