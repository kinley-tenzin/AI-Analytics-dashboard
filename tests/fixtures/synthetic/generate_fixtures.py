"""Generate the SYNTHETIC Odoo and ERPNext fixture files.

All companies, people, partners and amounts are fictional. Record shapes follow the
documented / source-code behaviour of each API (see contracts/sources/*.yaml); where a
shape is an assumption (e.g. Odoo date strings) it is marked in the contract.

Each output file represents ONE extraction batch of ONE entity:
    {"_meta": {...extraction metadata...}, "response": <API response body>}

Batches:
    2026-09-30  full extraction of partners and accounting documents
    2026-10-31  full extraction of HR data + INCREMENTAL extraction of accounting data
                (only records modified since the 2026-09-30 run)

Regenerate (from the repo root):  python tests/fixtures/synthetic/generate_fixtures.py
Expected KPI results are NOT generated here; they are hand-calculated in
expected_kpis.json so they stay independent of any code.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent
NOTICE = "SYNTHETIC TEST DATA - fictional organisations, people and amounts. Not real ERP data."

ODOO_INSTANCE = "odoo-dtg-retail"
ERPNEXT_INSTANCE = "erpnext-dtg-services"
ERPNEXT_TZ = "Asia/Thimphu"

BATCHES = {
    "2026-09-30": {"extracted_at": "2026-09-30T17:30:00Z", "checkpoint": None},
    "2026-10-31": {"extracted_at": "2026-10-31T17:30:00Z", "checkpoint": "2026-09-30T17:30:00Z"},
}

# Odoo many2one values are [id, display_name] pairs.
C1 = [1, "DTG Retail Pvt Ltd"]
C2 = [2, "DTG Retail - Phuentsholing"]
BTN, USD, INR = [120, "BTN"], [2, "USD"], [20, "INR"]
PAID_TIME_OFF, SICK_TIME_OFF = [1, "Paid Time Off"], [2, "Sick Time Off"]
PARTNERS = {
    301: "Norbu Hardware",
    302: "Zangpo Builders",
    303: "Lhaki Traders",
    304: "Himalayan Supplies Co",
    305: "Druk Office Mart",
    306: "Global Parts Ltd",
}
DEPTS = {
    1: "Management",
    2: "Sales",
    3: "Finance & Accounts",
    4: "Warehouse",
    5: "Sales",
    6: "Old Projects",
}
EMP_NAMES = {
    101: "Karma Dorji",
    102: "Sonam Choden",
    103: "Tshering Wangdi",
    104: "Dechen Pelmo",
    105: "Ugyen Tenzin",
    106: "Pema Wangmo",
    107: "Kinga Lhamo",
    108: "Jigme Namgyel",
    109: "Yeshey Dema",
    110: "Thinley Norbu",
    111: "Chimi Yangzom",
    112: "Phurba Tshering",
    113: "Sangay Lhamo",
}


def partner(pid: int) -> list:
    return [pid, PARTNERS[pid]]


def dept(did: int | None):
    return [did, DEPTS[did]] if did else False


# ------------------------------------------------------------------------------ Odoo


def odoo_companies() -> list[dict]:
    common = {"currency_id": BTN, "active": True, "write_date": "2026-01-05 03:00:00"}
    return [
        {"id": 1, "name": C1[1], "parent_id": False, **common},
        {"id": 2, "name": C2[1], "parent_id": C1, **common},
    ]


def odoo_departments() -> list[dict]:
    rows = [
        (1, C1, True),
        (2, C1, True),
        (3, C1, True),
        (4, C2, True),
        (5, C2, True),
        (6, C1, False),
    ]
    return [
        {
            "id": did,
            "name": DEPTS[did],
            "complete_name": DEPTS[did],
            "parent_id": False,
            "company_id": company,
            "active": active,
            "write_date": "2026-01-05 03:10:00",
        }
        for did, company, active in rows
    ]


def odoo_employees() -> list[dict]:
    # id, active, company, department, employee_type, departure_date
    rows = [
        (101, True, C1, 1, "employee", False),
        (102, True, C1, 2, "employee", False),
        (103, True, C1, 2, "employee", "2026-11-15"),  # resigning, still employed on 31 Oct
        (104, True, C1, 3, "employee", False),
        (105, True, C2, 4, "employee", False),
        (
            106,
            True,
            C2,
            5,
            "employee",
            False,
        ),  # same name as ERPNext HR-EMP-00001: NOT the same person
        (107, True, C2, 5, "contractor", False),
        (108, False, C1, 2, "employee", "2026-08-15"),  # archived leaver
        (109, False, C2, 4, "employee", "2026-10-20"),  # left in October
        (110, True, C1, None, "employee", False),  # no department -> warning, 'unassigned'
        (111, True, C1, 3, "trainee", False),
        (112, True, C1, 2, "intern", False),  # INVALID: not an Odoo employee_type -> rejected
        (113, False, C1, 6, "employee", False),  # archived without departure date -> inactive
    ]
    return [
        {
            "id": eid,
            "name": EMP_NAMES[eid],
            "active": active,
            "company_id": company,
            "department_id": dept(did),
            "employee_type": etype,
            "departure_date": departure,
            "parent_id": False if eid == 101 else [101, "Karma Dorji"],
            "write_date": "2026-10-21 04:00:00" if eid == 109 else "2026-03-02 04:00:00",
        }
        for eid, active, company, did, etype, departure in rows
    ]


def odoo_leaves() -> list[dict]:
    # id, employee, type, state, from, to, days
    rows = [
        (201, 101, PAID_TIME_OFF, "validate", "2026-10-05", "2026-10-07", 3.0),
        (202, 102, SICK_TIME_OFF, "validate", "2026-10-12", "2026-10-12", 1.0),
        (203, 104, PAID_TIME_OFF, "confirm", "2026-10-20", "2026-10-22", 3.0),
        (204, 105, PAID_TIME_OFF, "refuse", "2026-10-14", "2026-10-15", 2.0),
        (205, 106, PAID_TIME_OFF, "validate1", "2026-10-26", "2026-10-28", 3.0),
        (206, 102, PAID_TIME_OFF, "validate", "2026-10-27", "2026-10-28", 2.0),
        (207, 103, PAID_TIME_OFF, "cancel", "2026-10-01", "2026-10-02", 2.0),
        (208, 101, PAID_TIME_OFF, "validate", "2026-09-22", "2026-09-23", 2.0),
        (209, 107, SICK_TIME_OFF, "validate", "2026-10-30", "2026-11-03", 3.0),  # spans months
        (210, 110, PAID_TIME_OFF, "validate", "2026-10-18", "2026-10-16", 1.0),  # INVALID dates
    ]
    employees = {e["id"]: e for e in odoo_employees()}
    return [
        {
            "id": lid,
            "employee_id": [eid, EMP_NAMES[eid]],
            "holiday_status_id": leave_type,
            "state": state,
            "request_date_from": start,
            "request_date_to": end,
            "number_of_days": days,
            "department_id": employees[eid]["department_id"],
            "write_date": f"{max(start, '2026-09-20')} 05:00:00",
        }
        for lid, eid, leave_type, state, start, end, days in rows
    ]


def odoo_partners() -> list[dict]:
    vat = {301: "TPN-NRB-2001", 302: "TPN-ZNG-3001", 303: "TPN-LHK-1001",
           304: "TPN-HMS-4001", 305: "TPN-DOM-5001", 306: False}  # fmt: skip
    return [
        {
            "id": pid,
            "name": name,
            "vat": vat[pid],
            "customer_rank": 1 if pid <= 303 else 0,
            "supplier_rank": 1 if pid >= 304 else 0,
            "write_date": "2026-02-01 04:00:00",
        }
        for pid, name in PARTNERS.items()
    ]


# Assumed Odoo sign convention for *_signed company amounts (to verify in the sandbox):
ODOO_SIGN = {"out_invoice": 1, "out_refund": -1, "in_invoice": -1, "in_refund": 1}
RATE_TO_BTN = {"BTN": 1, "USD": 84, "INR": 1}


def odoo_move(mid, name, move_type, state, payment_state, pid, company, inv_date, due,
              currency, total, residual, write_date, reversed_entry=False) -> dict:  # fmt: skip
    rate = RATE_TO_BTN[currency[1]] if currency else 1
    sign = ODOO_SIGN[move_type]
    return {
        "id": mid,
        "name": name,
        "move_type": move_type,
        "state": state,
        "payment_state": payment_state,
        "partner_id": partner(pid),
        "company_id": company,
        "invoice_date": inv_date,
        "invoice_date_due": due,
        "currency_id": currency,
        "amount_total": float(total),
        "amount_residual": float(residual),
        "amount_total_signed": float(sign * total * rate),
        "amount_residual_signed": float(sign * residual * rate),
        "reversed_entry_id": reversed_entry,
        "write_date": write_date,
    }


def odoo_moves_sep() -> list[dict]:
    m = odoo_move
    return [
        m(401, "INV/2026/00001", "out_invoice", "posted", "paid", 301, C1, "2026-08-05", "2026-09-04", BTN, 10000, 0, "2026-08-25 04:10:00"),
        m(402, "INV/2026/00002", "out_invoice", "posted", "not_paid", 302, C1, "2026-08-20", "2026-09-19", BTN, 20000, 20000, "2026-08-20 04:00:00"),
        m(403, "INV/2026/00003", "out_invoice", "posted", "partial", 303, C1, "2026-09-10", "2026-10-10", BTN, 15000, 5000, "2026-09-25 04:00:00"),
        m(404, False, "out_invoice", "draft", "not_paid", 301, C1, False, False, BTN, 8000, 8000, "2026-09-28 04:00:00"),
        m(405, "INV/2026/00004", "out_invoice", "cancel", "not_paid", 302, C1, "2026-09-01", "2026-10-01", BTN, 5000, 5000, "2026-09-03 04:00:00"),
        m(406, "INV/2026/00005", "out_invoice", "posted", "not_paid", 303, C1, "2026-09-15", "2026-10-15", USD, 1000, 1000, "2026-09-15 04:00:00"),
        m(407, "RINV/2026/00001", "out_refund", "posted", "not_paid", 302, C1, "2026-09-25", "2026-09-25", BTN, 2000, 2000, "2026-09-25 05:00:00"),
        m(411, "INV/2026/00006", "out_invoice", "posted", "not_paid", 301, C1, "2026-06-01", "2026-07-01", BTN, 7500, 7500, "2026-06-01 04:00:00"),
        m(412, "INV/2026/00007", "out_invoice", "posted", "not_paid", 302, C1, "2026-07-10", "2026-08-09", BTN, 3000, 3000, "2026-07-10 04:00:00"),
        m(451, "BILL/2026/08/0001", "in_invoice", "posted", "not_paid", 304, C1, "2026-08-10", "2026-09-09", BTN, 12000, 12000, "2026-08-10 04:00:00"),
        m(452, "BILL/2026/09/0001", "in_invoice", "posted", "paid", 305, C1, "2026-09-05", "2026-10-05", BTN, 6000, 0, "2026-09-20 04:00:00"),
        m(453, "BILL/2026/09/0002", "in_invoice", "posted", "not_paid", 306, C1, "2026-09-12", "2026-10-12", USD, 500, 500, "2026-09-12 04:00:00"),
        m(454, False, "in_invoice", "draft", "not_paid", 304, C1, False, False, BTN, 3000, 3000, "2026-09-29 04:00:00"),
    ]  # fmt: skip


def odoo_moves_oct() -> list[dict]:
    m = odoo_move
    return [
        m(402, "INV/2026/00002", "out_invoice", "posted", "partial", 302, C1, "2026-08-20", "2026-09-19", BTN, 20000, 8000, "2026-10-08 04:00:00"),
        m(403, "INV/2026/00003", "out_invoice", "posted", "paid", 303, C1, "2026-09-10", "2026-10-10", BTN, 15000, 0, "2026-10-05 04:00:00"),
        m(404, "INV/2026/00008", "out_invoice", "posted", "not_paid", 301, C1, "2026-10-03", "2026-11-02", BTN, 8000, 8000, "2026-10-03 04:00:00"),
        m(408, "INV/2026/00009", "out_invoice", "posted", "not_paid", 301, C1, "2026-10-10", "2026-11-09", BTN, 30000, 30000, "2026-10-10 04:00:00"),
        m(409, "INV/2026/00010", "out_invoice", "posted", "not_paid", 302, C2, "2026-10-01", "2026-10-01", BTN, 4000, 4000, "2026-10-01 04:00:00"),
        m(413, "INV/2026/00011", "out_invoice", "posted", "reversed", 303, C1, "2026-10-12", "2026-11-11", BTN, 6000, 0, "2026-10-14 05:00:00"),
        m(414, "RINV/2026/00002", "out_refund", "posted", "reversed", 303, C1, "2026-10-14", "2026-10-14", BTN, 6000, 0, "2026-10-14 05:00:00", reversed_entry=[413, "INV/2026/00011"]),
        m(451, "BILL/2026/08/0001", "in_invoice", "posted", "paid", 304, C1, "2026-08-10", "2026-09-09", BTN, 12000, 0, "2026-10-15 04:00:00"),
        m(453, "BILL/2026/09/0002", "in_invoice", "posted", "partial", 306, C1, "2026-09-12", "2026-10-12", USD, 500, 300, "2026-10-25 04:00:00"),
        m(455, "BILL/2026/10/0001", "in_invoice", "posted", "not_paid", 305, C2, "2026-10-20", "2026-11-19", BTN, 9000, 9000, "2026-10-20 04:00:00"),
        m(456, "RBILL/2026/10/0001", "in_refund", "posted", "not_paid", 304, C1, "2026-10-22", "2026-10-22", BTN, 1000, 1000, "2026-10-22 04:00:00"),
        # INVALID: posted bill without currency -> rejected by the contract
        m(457, "BILL/2026/10/0002", "in_invoice", "posted", "not_paid", 305, C1, "2026-10-26", "2026-11-25", False, 2500, 2500, "2026-10-26 04:00:00"),
    ]  # fmt: skip


def odoo_payment(pid, name, ptype, state, partner_id, amount, currency, day, invoices, bills, write_date):  # fmt: skip
    return {
        "id": pid,
        "name": name,
        "payment_type": ptype,
        "partner_type": "customer" if ptype == "inbound" else "supplier",
        "state": state,
        "partner_id": partner(partner_id),
        "amount": float(amount),
        "currency_id": currency,
        "date": day,
        "reconciled_invoice_ids": invoices,
        "reconciled_bill_ids": bills,
        "write_date": write_date,
    }


def odoo_payments_sep() -> list[dict]:
    p = odoo_payment
    return [
        p(501, "PBNK1/2026/00001", "inbound", "paid", 301, 10000, BTN, "2026-08-25", [401], [], "2026-08-25 04:10:00"),
        p(502, "PBNK1/2026/00002", "inbound", "paid", 303, 10000, BTN, "2026-09-25", [403], [], "2026-09-25 04:00:00"),
        p(503, "PBNK1/2026/00003", "outbound", "paid", 305, 6000, BTN, "2026-09-20", [], [452], "2026-09-20 04:00:00"),
    ]  # fmt: skip


def odoo_payments_oct() -> list[dict]:
    p = odoo_payment
    return [
        p(504, "PBNK1/2026/00004", "inbound", "paid", 302, 12000, BTN, "2026-10-08", [402], [], "2026-10-08 04:00:00"),
        p(505, "PBNK1/2026/00005", "inbound", "paid", 303, 5000, BTN, "2026-10-05", [403], [], "2026-10-05 04:00:00"),
        p(506, "PBNK1/2026/00006", "outbound", "paid", 304, 12000, BTN, "2026-10-15", [], [451], "2026-10-15 04:00:00"),
        p(507, "PBNK1/2026/00007", "outbound", "paid", 306, 200, USD, "2026-10-25", [], [453], "2026-10-25 04:00:00"),
        p(508, "PBNK1/2026/00008", "inbound", "draft", 301, 3000, BTN, "2026-10-30", [], [], "2026-10-30 04:00:00"),
    ]  # fmt: skip


# --------------------------------------------------------------------------- ERPNext

COMPANY = "DTG Services Pvt Ltd"


def frappe_ts(day: str, time: str = "10:00:00") -> str:
    """ERPNext `modified`: naive local time (Asia/Thimphu) with microseconds."""
    return f"{day} {time}.000000"


def erpnext_companies() -> list[dict]:
    return [{"name": COMPANY, "abbr": "DSV", "default_currency": "BTN",
             "modified": frappe_ts("2026-01-10")}]  # fmt: skip


def erpnext_branches() -> list[dict]:
    return [
        {"name": b, "branch": b, "modified": frappe_ts("2026-01-10")} for b in ("Paro", "Bumthang")
    ]


def erpnext_departments() -> list[dict]:
    names = ["Operations", "Accounts", "Sales", "Human Resources"]
    return [
        {
            "name": f"{n} - DSV",
            "department_name": n,
            "parent_department": None,
            "company": COMPANY,
            "is_group": 0,
            "disabled": 0,
            "modified": frappe_ts("2026-01-10"),
        }
        for n in names
    ]


def erpnext_employees() -> list[dict]:
    # name, full name, status, company, department, branch, joining, relieving
    rows = [
        ("HR-EMP-00001", "Pema Wangmo", "Active", COMPANY, "Operations - DSV", "Paro", "2021-03-01", None),
        ("HR-EMP-00002", "Kezang Dorji", "Active", COMPANY, "Operations - DSV", "Paro", "2022-06-15", None),
        ("HR-EMP-00003", "Namgay Lham", "Active", COMPANY, "Accounts - DSV", "Paro", "2020-01-06", None),
        ("HR-EMP-00004", "Sangay Tenzin", "Active", COMPANY, "Sales - DSV", "Bumthang", "2023-02-01", None),
        ("HR-EMP-00005", "Dorji Wangchuk", "Active", COMPANY, "Sales - DSV", "Bumthang", "2024-07-01", None),
        ("HR-EMP-00006", "Tandin Bidha", "Left", COMPANY, "Sales - DSV", "Bumthang", "2019-05-01", "2026-09-30"),
        ("HR-EMP-00007", "Rinzin Om", "Suspended", COMPANY, "Human Resources - DSV", "Paro", "2022-09-01", None),
        ("HR-EMP-00008", "Wangchuk Dorji", "Inactive", COMPANY, "Operations - DSV", "Paro", "2018-04-01", None),
        ("HR-EMP-00009", "Lhamo Yangchen", "Active", COMPANY, "Human Resources - DSV", None, "2025-01-15", None),
        ("HR-EMP-00010", "Nima Gyeltshen", "Active", COMPANY, None, "Bumthang", "2025-08-01", None),
        ("HR-EMP-00011", "Tashi Phuntsho", "Retired", COMPANY, "Operations - DSV", "Paro", "2010-02-01", None),  # INVALID status
        ("HR-EMP-00012", "Choki Wangmo", "Active", None, "Accounts - DSV", "Paro", "2024-03-01", None),  # INVALID: no company
        ("HR-EMP-00013", "Karma Choki", "Active", COMPANY, "Accounts - DSV", "Paro", "2026-11-03", None),  # future joiner
    ]  # fmt: skip
    return [
        {
            "name": name,
            "employee_name": full,
            "first_name": full.split()[0],
            "status": status,
            "company": company,
            "department": department,
            "branch": branch,
            "date_of_joining": joined,
            "relieving_date": relieved,
            "modified": frappe_ts("2026-10-01" if status == "Left" else "2026-03-02"),
        }
        for name, full, status, company, department, branch, joined, relieved in rows
    ]


def erpnext_leaves() -> list[dict]:
    employees = {e["name"]: e for e in erpnext_employees()}
    # name, employee, type, status, docstatus, from, to, days, half_day
    rows = [
        ("HR-LAP-2026-00001", "HR-EMP-00001", "Casual Leave", "Approved", 1, "2026-10-06", "2026-10-07", 2.0, 0),
        ("HR-LAP-2026-00002", "HR-EMP-00002", "Sick Leave", "Approved", 1, "2026-10-09", "2026-10-09", 0.5, 1),
        ("HR-LAP-2026-00003", "HR-EMP-00003", "Privilege Leave", "Open", 0, "2026-10-13", "2026-10-17", 5.0, 0),
        ("HR-LAP-2026-00004", "HR-EMP-00004", "Casual Leave", "Rejected", 1, "2026-10-20", "2026-10-21", 2.0, 0),
        ("HR-LAP-2026-00005", "HR-EMP-00005", "Privilege Leave", "Cancelled", 2, "2026-10-22", "2026-10-24", 3.0, 0),
        ("HR-LAP-2026-00006", "HR-EMP-00009", "Casual Leave", "Approved", 0, "2026-10-27", "2026-10-28", 2.0, 0),  # approved but NOT submitted
        ("HR-LAP-2026-00007", "HR-EMP-00001", "Casual Leave", "Approved", 1, "2026-10-29", "2026-10-30", 2.0, 0),
        ("HR-LAP-2026-00008", "HR-EMP-00010", "Privilege Leave", "Approved", 1, "2026-09-29", "2026-10-02", 4.0, 0),
        ("HR-LAP-2026-00009", "HR-EMP-00002", None, "Approved", 1, "2026-10-15", "2026-10-15", 1.0, 0),  # INVALID: no leave type
    ]  # fmt: skip
    return [
        {
            "name": name,
            "employee": emp,
            "employee_name": employees[emp]["employee_name"],
            "leave_type": leave_type,
            "status": status,
            "docstatus": docstatus,
            "from_date": start,
            "to_date": end,
            "total_leave_days": days,
            "half_day": half,
            "company": COMPANY,
            "department": employees[emp]["department"],
            "posting_date": min(start, "2026-10-01"),
            "modified": frappe_ts(min(start, "2026-10-30")),
        }
        for name, emp, leave_type, status, docstatus, start, end, days, half in rows
    ]


def erpnext_customers() -> list[dict]:
    rows = [("Lhaki Traders", "TPN-LHK-1001"), ("Norbu Hardware", "TPN-NRB-2999"),
            ("Gakidh Retail", "TPN-GKR-6001")]  # fmt: skip
    return [{"name": n, "customer_name": n, "tax_id": t, "disabled": 0,
             "modified": frappe_ts("2026-02-01")} for n, t in rows]  # fmt: skip


def erpnext_suppliers() -> list[dict]:
    rows = [("Thunder Paper Works", "TPN-TPW-7001"), ("Peling Logistics", "TPN-PLG-8001"),
            ("Delhi Tools Pvt Ltd", None)]  # fmt: skip
    return [{"name": n, "supplier_name": n, "tax_id": t, "disabled": 0,
             "modified": frappe_ts("2026-02-01")} for n, t in rows]  # fmt: skip


def erpnext_invoice(doctype, name, party, posting, due, currency, rate, grand, outstanding,
                    status, docstatus, modified, is_return=0, return_against=None) -> dict:  # fmt: skip
    doc = {
        "name": name,
        "company": COMPANY,
        "posting_date": posting,
        "due_date": due,
        "currency": currency,
        "conversion_rate": float(rate),
        "grand_total": float(grand),
        "base_grand_total": float(grand * rate),
        "outstanding_amount": float(outstanding),
        "party_account_currency": "BTN",
        "is_return": is_return,
        "return_against": return_against,
        # These fixture returns REDUCE the original invoice (setting 0). ERPNext 16 defaults to 1,
        # where the return keeps its own negative outstanding instead (verified live in M3).
        "update_outstanding_for_self": 0 if return_against else 1,
        "status": status,
        "docstatus": docstatus,
        "modified": modified,
    }
    if doctype == "Sales Invoice":
        doc["customer"] = party
    else:
        doc["supplier"] = party
        doc["bill_no"] = f"SUP-{name[-5:]}"
    return doc


def sinv(*args, **kwargs):
    return erpnext_invoice("Sales Invoice", *args, **kwargs)


def pinv(*args, **kwargs):
    return erpnext_invoice("Purchase Invoice", *args, **kwargs)


def erpnext_sales_sep() -> list[dict]:
    return [
        sinv("ACC-SINV-2026-00001", "Norbu Hardware", "2026-08-12", "2026-09-11", "BTN", 1, 25000, 25000, "Overdue", 1, frappe_ts("2026-09-12")),
        sinv("ACC-SINV-2026-00002", "Lhaki Traders", "2026-09-01", "2026-10-01", "BTN", 1, 12000, 0, "Paid", 1, frappe_ts("2026-09-20")),
        sinv("ACC-SINV-2026-00003", "Gakidh Retail", "2026-09-15", "2026-10-15", "BTN", 1, 18000, 8000, "Partly Paid", 1, frappe_ts("2026-09-28")),
        sinv("ACC-SINV-2026-00004", "Norbu Hardware", "2026-09-29", "2026-10-29", "BTN", 1, 5000, 5000, "Draft", 0, frappe_ts("2026-09-29")),
        sinv("ACC-SINV-2026-00005", "Gakidh Retail", "2026-09-20", "2026-10-20", "BTN", 1, 4000, 4000, "Cancelled", 2, frappe_ts("2026-09-22")),
        sinv("ACC-SINV-2026-00006", "Norbu Hardware", "2026-09-18", "2026-10-18", "INR", 1, 10000, 10000, "Unpaid", 1, frappe_ts("2026-09-18")),
        sinv("ACC-SINV-RET-2026-00001", "Gakidh Retail", "2026-09-27", "2026-09-27", "BTN", 1, -3000, 0, "Return", 1, frappe_ts("2026-09-27"), is_return=1, return_against="ACC-SINV-2026-00003"),
    ]  # fmt: skip


def erpnext_sales_oct() -> list[dict]:
    return [
        sinv("ACC-SINV-2026-00001", "Norbu Hardware", "2026-08-12", "2026-09-11", "BTN", 1, 25000, 10000, "Overdue", 1, frappe_ts("2026-10-10")),
        sinv("ACC-SINV-2026-00004", "Norbu Hardware", "2026-10-28", "2026-11-27", "BTN", 1, 5000, 5000, "Unpaid", 1, frappe_ts("2026-10-28")),
        sinv("ACC-SINV-2026-00007", "Lhaki Traders", "2026-10-05", "2026-11-04", "BTN", 1, 22000, 22000, "Unpaid", 1, frappe_ts("2026-10-05")),
        sinv("ACC-SINV-2026-00008", "Gakidh Retail", "2026-10-02", "2026-10-02", "USD", 84, 300, 25200, "Overdue", 1, frappe_ts("2026-10-03")),
        sinv("ACC-SINV-RET-2026-00002", "Gakidh Retail", "2026-10-25", "2026-10-25", "BTN", 1, -1500, -1500, "Return", 1, frappe_ts("2026-10-25"), is_return=1),
        # INVALID: submitted invoice without customer -> rejected
        sinv("ACC-SINV-2026-00010", None, "2026-10-26", "2026-11-25", "BTN", 1, 3000, 3000, "Unpaid", 1, frappe_ts("2026-10-26")),
    ]  # fmt: skip


def erpnext_purchase_sep() -> list[dict]:
    return [
        pinv("ACC-PINV-2026-00001", "Thunder Paper Works", "2026-08-01", "2026-08-31", "BTN", 1, 9000, 9000, "Overdue", 1, frappe_ts("2026-09-01")),
        pinv("ACC-PINV-2026-00002", "Peling Logistics", "2026-09-10", "2026-10-10", "BTN", 1, 14000, 4000, "Partly Paid", 1, frappe_ts("2026-09-25")),
        pinv("ACC-PINV-2026-00003", "Delhi Tools Pvt Ltd", "2026-09-05", "2026-09-20", "INR", 1, 20000, 20000, "Overdue", 1, frappe_ts("2026-09-21")),
        pinv("ACC-PINV-2026-00004", "Thunder Paper Works", "2026-09-28", "2026-10-28", "BTN", 1, 2000, 2000, "Draft", 0, frappe_ts("2026-09-28")),
    ]  # fmt: skip


def erpnext_purchase_oct() -> list[dict]:
    return [
        pinv("ACC-PINV-2026-00001", "Thunder Paper Works", "2026-08-01", "2026-08-31", "BTN", 1, 9000, 0, "Paid", 1, frappe_ts("2026-10-03")),
        pinv("ACC-PINV-2026-00002", "Peling Logistics", "2026-09-10", "2026-10-10", "BTN", 1, 14000, 3000, "Partly Paid", 1, frappe_ts("2026-10-18")),
        pinv("ACC-PINV-2026-00004", "Thunder Paper Works", "2026-09-28", "2026-10-28", "BTN", 1, 2000, 2000, "Cancelled", 2, frappe_ts("2026-10-12")),
        pinv("ACC-PINV-2026-00005", "Peling Logistics", "2026-10-15", "2026-11-14", "BTN", 1, 7000, 7000, "Unpaid", 1, frappe_ts("2026-10-15")),
        pinv("ACC-PINV-RET-2026-00001", "Peling Logistics", "2026-10-18", "2026-10-18", "BTN", 1, -1000, 0, "Return", 1, frappe_ts("2026-10-18"), is_return=1, return_against="ACC-PINV-2026-00002"),
    ]  # fmt: skip


def payment_entry(name, ptype, party, day, amount, docstatus, refs, unallocated=0.0):
    party_type = "Customer" if ptype == "Receive" else "Supplier"
    ref_doctype = "Sales Invoice" if ptype == "Receive" else "Purchase Invoice"
    return {
        "name": name,
        "payment_type": ptype,
        "party_type": party_type,
        "party": party,
        "posting_date": day,
        "paid_amount": float(amount),
        "paid_from_account_currency": "BTN",
        "unallocated_amount": float(unallocated),
        "docstatus": docstatus,
        "references": [
            {
                "reference_doctype": ref_doctype,
                "reference_name": ref,
                "allocated_amount": float(a),
                "due_date": None,
            }  # fmt: skip
            for ref, a in refs
        ],
        "modified": frappe_ts(day),
    }


def erpnext_payments_sep() -> list[dict]:
    pe = payment_entry
    return [
        pe("ACC-PAY-2026-00001", "Receive", "Lhaki Traders", "2026-09-20", 12000, 1, [("ACC-SINV-2026-00002", 12000)]),
        pe("ACC-PAY-2026-00002", "Receive", "Gakidh Retail", "2026-09-28", 7000, 1, [("ACC-SINV-2026-00003", 7000)]),
        pe("ACC-PAY-2026-00003", "Pay", "Peling Logistics", "2026-09-25", 10000, 1, [("ACC-PINV-2026-00002", 10000)]),
    ]  # fmt: skip


def erpnext_payments_oct() -> list[dict]:
    pe = payment_entry
    return [
        pe("ACC-PAY-2026-00004", "Receive", "Norbu Hardware", "2026-10-10", 15000, 1, [("ACC-SINV-2026-00001", 15000)]),
        pe("ACC-PAY-2026-00005", "Pay", "Thunder Paper Works", "2026-10-03", 9000, 1, [("ACC-PINV-2026-00001", 9000)]),
        pe("ACC-PAY-2026-00006", "Receive", "Norbu Hardware", "2026-10-30", 2000, 0, [("ACC-SINV-2026-00001", 2000)]),  # draft
        pe("ACC-PAY-2026-00007", "Receive", "Lhaki Traders", "2026-10-30", 5000, 1, [], unallocated=5000),  # advance
    ]  # fmt: skip


# ---------------------------------------------------------------------------- output


def odoo_request(entity: str, batch: str, full: bool) -> dict:
    domain = [] if full else [["write_date", ">", "2026-09-30 17:30:00"]]
    return {"method": "POST", "path": f"/json/2/{entity}/search_read",
            "body": {"domain": domain, "order": "id asc", "limit": 200, "offset": 0,
                     "context": {"active_test": False}}}  # fmt: skip


def erpnext_request(entity: str, batch: str, full: bool) -> dict:
    filters = [] if full else [["modified", ">", "2026-09-30 23:30:00"]]
    return {"method": "GET", "path": f"/api/resource/{entity}",
            "params": {"filters": filters, "order_by": "name asc", "limit_start": 0,
                       "limit_page_length": 200}}  # fmt: skip


FILES = [
    # (system, batch, entity, mode, builder)
    ("odoo", "2026-09-30", "res.partner", "full", odoo_partners),
    ("odoo", "2026-09-30", "account.move", "full", odoo_moves_sep),
    ("odoo", "2026-09-30", "account.payment", "full", odoo_payments_sep),
    ("odoo", "2026-10-31", "res.company", "full", odoo_companies),
    ("odoo", "2026-10-31", "hr.department", "full", odoo_departments),
    ("odoo", "2026-10-31", "hr.employee", "full", odoo_employees),
    ("odoo", "2026-10-31", "hr.leave", "full", odoo_leaves),
    ("odoo", "2026-10-31", "account.move", "incremental", odoo_moves_oct),
    ("odoo", "2026-10-31", "account.payment", "incremental", odoo_payments_oct),
    ("erpnext", "2026-09-30", "Customer", "full", erpnext_customers),
    ("erpnext", "2026-09-30", "Supplier", "full", erpnext_suppliers),
    ("erpnext", "2026-09-30", "Sales Invoice", "full", erpnext_sales_sep),
    ("erpnext", "2026-09-30", "Purchase Invoice", "full", erpnext_purchase_sep),
    ("erpnext", "2026-09-30", "Payment Entry", "full", erpnext_payments_sep),
    ("erpnext", "2026-10-31", "Company", "full", erpnext_companies),
    ("erpnext", "2026-10-31", "Branch", "full", erpnext_branches),
    ("erpnext", "2026-10-31", "Department", "full", erpnext_departments),
    ("erpnext", "2026-10-31", "Employee", "full", erpnext_employees),
    ("erpnext", "2026-10-31", "Leave Application", "full", erpnext_leaves),
    ("erpnext", "2026-10-31", "Sales Invoice", "incremental", erpnext_sales_oct),
    ("erpnext", "2026-10-31", "Purchase Invoice", "incremental", erpnext_purchase_oct),
    ("erpnext", "2026-10-31", "Payment Entry", "incremental", erpnext_payments_oct),
]


def build_fixture(system: str, batch: str, entity: str, mode: str, records: list[dict]) -> dict:
    full = mode == "full"
    meta = {
        "synthetic": True,
        "notice": NOTICE,
        "source_system": system,
        "source_instance": ODOO_INSTANCE if system == "odoo" else ERPNEXT_INSTANCE,
        "entity": entity,
        "extraction_batch_id": f"{system}-{batch}-{entity.lower().replace(' ', '_').replace('.', '_')}",
        "extracted_at": BATCHES[batch]["extracted_at"],
        "extraction_mode": mode,
        "checkpoint_utc": None if full else BATCHES[batch]["checkpoint"],
    }
    if system == "odoo":
        meta["request"] = odoo_request(entity, batch, full)
        response: object = records  # JSON-2 returns a bare array
    else:
        meta["instance_timezone"] = ERPNEXT_TZ
        meta["request"] = erpnext_request(entity, batch, full)
        if entity == "Payment Entry":
            meta["note"] = (
                "List call + one GET per document to include the `references` child table."
            )
        response = {"data": records}  # Frappe wraps results in {"data": ...}
    return {"_meta": meta, "response": response}


def fixture_path(system: str, batch: str, entity: str) -> Path:
    return OUT_DIR / system / batch / f"{entity.lower().replace(' ', '_')}.json"


def render_all() -> dict[Path, str]:
    return {
        fixture_path(system, batch, entity): json.dumps(
            build_fixture(system, batch, entity, mode, builder()), indent=2, ensure_ascii=False
        )
        + "\n"
        for system, batch, entity, mode, builder in FILES
    }


def main() -> None:
    for path, text in render_all().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(OUT_DIR)}")


if __name__ == "__main__":
    main()
