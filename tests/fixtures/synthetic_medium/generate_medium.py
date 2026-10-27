"""Generate the MEDIUM-scale SYNTHETIC Odoo and ERPNext fixtures (about 115,000 source records).

Purpose: show how the pipeline behaves with realistic volume (the small fixtures in
tests/fixtures/synthetic/ have ~130 records). All companies, people, partners and amounts are
fictional. Nothing here comes from a real ERP.

The record SHAPES, batches and edge-case kinds are the same as the small fixtures (the helpers are
imported from tests/fixtures/synthetic/generate_fixtures.py), so the unchanged connectors, contracts
and dbt models process them. Same two extraction batches:
    2026-09-30  full extraction of partners and accounting documents/payments (state at 30 Sep)
    2026-10-31  full extraction of HR data + INCREMENTAL accounting (records changed in October)

Documents are simulated as a consistent ledger (every payment, partial payment, credit note and
return is an event with a date), so the state at any batch date reconciles exactly:
(total - outstanding) == allocated payments (+ returns). Output is DETERMINISTIC (fixed seed).

Output (git-ignored, ~60 MB): tests/fixtures/synthetic_medium/{odoo,erpnext}/<batch>/<entity>.json

Run (repo root):  python tests/fixtures/synthetic_medium/generate_medium.py
Use it:           set DRUKSMART_SYNTHETIC_FIXTURES=tests/fixtures/synthetic_medium in .env
                  (docs/evaluation/SCALE_TEST.md)
"""

from __future__ import annotations

import importlib.util
import json
import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "small_fixtures", HERE.parent / "synthetic" / "generate_fixtures.py"
)
small = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(small)

SEED = 20261031
SEP, OCT = date(2026, 9, 30), date(2026, 10, 31)
START = date(2025, 1, 1)

# ---- volumes per ERP (totals: ~113,000 business records across both ERPs) -------------------
N_EMPLOYEES = 1_000
N_LEAVES = 10_000
N_CUSTOMERS = 250
N_SUPPLIERS = 250
N_AR, N_AP = 15_000, 9_500  # invoices / bills (Odoo: + credit notes so moves total 25,000)
N_AR_CN, N_AP_CN = 300, 200  # standalone credit notes (unapplied credit)
N_INVALID_DOCS = 5
N_INVALID_EMP = 2
N_INVALID_LEAVE = 10

FIRST = ["Karma", "Sonam", "Tshering", "Dechen", "Ugyen", "Pema", "Kinga", "Jigme", "Yeshey",
         "Thinley", "Chimi", "Sangay", "Tandin", "Rinzin", "Kezang", "Namgay", "Dorji", "Tashi",
         "Nima", "Lhamo", "Choki", "Passang", "Phurba", "Wangchuk", "Tenzin", "Zangmo", "Deki",
         "Singye", "Rigzin", "Ngawang"]  # fmt: skip
LAST = ["Dorji", "Wangmo", "Choden", "Tenzin", "Lhamo", "Namgyel", "Pelmo", "Tshering", "Gyeltshen",
        "Zangpo", "Dema", "Yangzom", "Norbu", "Wangdi", "Phuntsho", "Om", "Bidha", "Lham",
        "Jamtsho", "Rabten", "Penjor", "Samdrup", "Dukpa", "Gurung", "Tamang"]  # fmt: skip
BIZ_A = ["Druk", "Thimphu", "Paro", "Punakha", "Bumthang", "Himalayan", "Dragon", "Snow", "Mountain",
         "Valley", "Tashi", "Yeshey", "Gakidh", "Zhung", "Rinpung", "Trongsa", "Mongar", "Haa",
         "Samtse", "Wangdue", "Dagana", "Lhuentse", "Pemagatshel", "Zhemgang", "Chukha", "Sarpang", "Tsirang", "Gasa"]  # fmt: skip
BIZ_B = ["Traders", "Hardware", "Builders", "Supplies", "Logistics", "Retail", "Enterprises", "Stationers", "Agro", "Electricals", "Motors", "Pharma", "Foods", "Textiles", "Timber", "Printers", "Constructions", "Tools", "Fuels", "Furnishers"]  # fmt: skip

ODOO_COMPANIES = [
    [1, "DTG Retail Pvt Ltd"],
    [2, "DTG Retail - Phuentsholing"],
    [3, "DTG Retail - Paro"],
    [4, "DTG Retail - Gelephu"],
]
ODOO_COMPANY_WEIGHTS = [50, 20, 15, 15]
ODOO_DEPT_NAMES = ["Management", "Sales", "Finance & Accounts", "Warehouse", "Operations"]
ERP_BRANCHES = ["Paro", "Bumthang", "Thimphu", "Punakha", "Trongsa", "Mongar", "Samdrup Jongkhar",
                "Gelephu"]  # fmt: skip
ERP_DEPT_NAMES = ["Operations", "Accounts", "Sales", "Human Resources", "Procurement", "IT",
                  "Logistics", "Customer Service"]  # fmt: skip
ERP_LEAVE_TYPES = ["Casual Leave", "Sick Leave", "Privilege Leave"]
BTN, USD, INR = small.BTN, small.USD, small.INR
RATE = {
    "BTN": 1,
    "USD": 84,
    "INR": 1,
}  # as in the small fixtures (ODOO rate / ERPNext conversion_rate)


# ------------------------------------------------------------------------------ helpers


def weighted(rng: random.Random, items: list[tuple]):
    total = sum(w for _, w in items)
    pick, acc = rng.random() * total, 0.0
    for value, weight in items:
        acc += weight
        if pick < acc:
            return value
    return items[-1][0]


def rand_date(rng: random.Random, lo: date, hi: date, recency: float = 0.8) -> date:
    """Random date in [lo, hi]; recency < 1 puts more dates near `hi` (business growth)."""
    return lo + timedelta(days=int((hi - lo).days * (rng.random() ** recency)))


def person(rng: random.Random) -> str:
    return f"{rng.choice(FIRST)} {rng.choice(LAST)}"


def business_names(rng: random.Random, count: int, taken: set[str]) -> list[str]:
    combos = [f"{a} {b}" for a in BIZ_A for b in BIZ_B]
    rng.shuffle(combos)
    names = [n for n in combos if n not in taken][:count]
    assert len(names) == count, "not enough business names"
    taken.update(names)
    return names


# ------------------------------------------------------------------------ document ledger


@dataclass
class Doc:
    kind: str  # AR invoice | AP bill | AR_CN / AP_CN standalone credit note
    party: int  # index into the ERP's customer (AR) or supplier (AP) list
    branch: int  # index into the ERP's company list (Odoo) - unused by ERPNext
    day: date
    due: date
    cur: str
    total: int
    state: str  # posted | draft | cancel | invalid
    stub: bool = False  # draft on 30 Sep, posted in October
    pays: list[tuple[date, int]] = field(default_factory=list)  # (date, amount) payments
    rets: list[tuple[date, int]] = field(default_factory=list)  # ERPNext returns against it
    name: str = ""
    key: int = 0

    def paid_at(self, t: date) -> int:
        return sum(a for d, a in self.pays if d <= t)

    def returned_at(self, t: date) -> int:
        return sum(a for d, a in self.rets if d <= t)

    def residual_at(self, t: date) -> int:
        if self.state != "posted":
            return self.total
        return self.total - self.paid_at(t) - self.returned_at(t)

    def last_change(self, t: date) -> date:
        days = [self.day] + [d for d, _ in self.pays + self.rets if d <= t]
        return max(days)

    def changed_in_october(self) -> bool:
        return self.day > SEP or self.stub or any(SEP < d <= OCT for d, _ in self.pays + self.rets)


def plan_payments(rng: random.Random, doc: Doc) -> None:
    """Payment events for a posted invoice/bill. Events after 31 Oct do not exist yet."""
    # Old documents are almost always settled (a few stay open: disputes, write-offs pending);
    # recent ones are more often still unpaid, which gives a realistic ageing profile.
    if (OCT - doc.day).days > 120:
        mix = [("full", 76), ("split", 12), ("partial", 7), ("none", 5)]
    else:
        mix = [("full", 40), ("split", 5), ("partial", 15), ("none", 40)]
    pattern = weighted(rng, mix)
    if pattern == "none":
        return
    first = doc.day + timedelta(days=int(rng.expovariate(1 / 25)) + rng.randint(0, 5))
    if pattern == "full":
        events = [(first, doc.total)]
    elif pattern == "partial":
        events = [(first, max(1, min(doc.total - 1, round(doc.total * rng.uniform(0.2, 0.8)))))]
    else:
        part = max(1, min(doc.total - 1, round(doc.total * rng.uniform(0.3, 0.7))))
        second = first + timedelta(days=1 + int(rng.expovariate(1 / 20)))
        events = [(first, part), (second, doc.total - part)]
    if doc.total < 2:
        events = [(first, doc.total)]
    doc.pays = [(d, a) for d, a in events if d <= OCT]


def plan_documents(
    rng: random.Random, *, n_ar: int, n_ap: int, n_ar_cn: int, n_ap_cn: int, n_customers: int,
    n_suppliers: int, n_branches: int, branch_weights: list[int] | None,
    pay_foreign: bool,
) -> list[Doc]:  # fmt: skip
    docs: list[Doc] = []

    def branch() -> int:
        if branch_weights:
            return weighted(rng, list(enumerate(branch_weights)))
        return rng.randrange(n_branches)

    def make(kind: str, count: int, parties: int) -> None:
        for _ in range(count):
            cur = weighted(rng, [("BTN", 95.5), ("USD", 3.0), ("INR", 1.5)])
            if cur == "BTN":
                total = int(min(max(rng.lognormvariate(9.2, 1.1), 300), 3_000_000))
            elif cur == "USD":
                total = rng.randint(100, 3000)
            else:
                total = rng.randint(5000, 200_000)
            state, stub = "posted", False
            u = rng.random()
            if kind in ("AR_CN", "AP_CN"):
                day = rand_date(rng, START, OCT)
            elif u < 0.015:
                state, day = "cancel", rand_date(rng, START, OCT)
            elif u < 0.035:
                state, day = "draft", rand_date(rng, date(2026, 9, 1), OCT)
            elif u < 0.037:
                state, stub, day = (
                    "posted",
                    True,
                    date(2026, 10, 1) + timedelta(days=rng.randint(0, 4)),
                )
            else:
                day = rand_date(rng, START, OCT)
            terms = weighted(rng, [(0, 10), (15, 15), (30, 50), (45, 15), (60, 10)])
            doc = Doc(kind, rng.randrange(parties), branch(), day, day + timedelta(days=terms),
                      cur, total, state, stub)  # fmt: skip
            if state == "posted" and kind in ("AR", "AP") and (cur == "BTN" or pay_foreign):
                plan_payments(rng, doc)
            docs.append(doc)

    make("AR", n_ar, n_customers)
    make("AP", n_ap, n_suppliers)
    make("AR_CN", n_ar_cn, n_customers)
    make("AP_CN", n_ap_cn, n_suppliers)
    # invalid documents (must be rejected by the contract and never reach the marts)
    for i in range(N_INVALID_DOCS):
        day = rand_date(rng, date(2026, 9, 1), OCT)
        docs.append(Doc("AR" if i % 2 == 0 else "AP", rng.randrange(n_customers), branch(), day,
                        day + timedelta(days=30), "BTN", rng.randint(1000, 9000), "invalid"))  # fmt: skip
    docs.sort(key=lambda d: (d.day, d.kind))
    return docs


# ------------------------------------------------------------------------------- Odoo


def build_odoo(rng: random.Random) -> dict[tuple[str, str], tuple[str, list[dict]]]:
    out: dict[tuple[str, str], tuple[str, list[dict]]] = {}
    taken = {"Lhaki Traders", "Norbu Hardware"}

    # partners: ids from 10001, so the verified synthetic mapping of the small fixtures never matches
    names = business_names(rng, N_CUSTOMERS + N_SUPPLIERS, taken)
    customer_ids = [10001 + i for i in range(N_CUSTOMERS)]
    supplier_ids = [10001 + N_CUSTOMERS + i for i in range(N_SUPPLIERS)]
    small.PARTNERS.update(dict(zip(customer_ids + supplier_ids, names, strict=True)))
    partners = [
        {
            "id": pid,
            "name": small.PARTNERS[pid],
            "vat": False if i % 20 == 7 else f"TPN-O-{pid:05d}",
            "customer_rank": 1 if pid in customer_ids else 0,
            "supplier_rank": 0 if pid in customer_ids else 1,
            "write_date": "2026-02-01 04:00:00",
        }
        for i, pid in enumerate(customer_ids + supplier_ids)
    ]
    out[("2026-09-30", "res.partner")] = ("full", partners)

    # companies / departments
    common = {"currency_id": BTN, "active": True, "write_date": "2026-01-05 03:00:00"}
    companies = [
        {"id": cid, "name": name, "parent_id": False if cid == 1 else ODOO_COMPANIES[0], **common}
        for cid, name in ODOO_COMPANIES
    ]
    out[("2026-10-31", "res.company")] = ("full", companies)
    departments, dept_by_company = [], {}
    for ci, company in enumerate(ODOO_COMPANIES):
        ids = []
        for k, dname in enumerate(ODOO_DEPT_NAMES):
            did = ci * 5 + k + 1
            ids.append(did)
            departments.append({"id": did, "name": dname, "complete_name": dname, "parent_id": False,
                                "company_id": company, "active": True,
                                "write_date": "2026-01-05 03:10:00"})  # fmt: skip
        dept_by_company[ci] = ids
    departments.append({"id": 21, "name": "Old Projects", "complete_name": "Old Projects",
                        "parent_id": False, "company_id": ODOO_COMPANIES[0], "active": False,
                        "write_date": "2026-01-05 03:10:00"})  # fmt: skip
    dept_name = {d["id"]: d["name"] for d in departments}
    out[("2026-10-31", "hr.department")] = ("full", departments)

    # employees
    employees = []
    emp_ids = [1001 + i for i in range(N_EMPLOYEES)]
    emp_dept: dict[int, object] = {}
    for i, eid in enumerate(emp_ids):
        ci = weighted(rng, list(enumerate(ODOO_COMPANY_WEIGHTS)))
        did = False if rng.random() < 0.01 else rng.choice(dept_by_company[ci])
        etype = weighted(rng, [("employee", 85), ("contractor", 8), ("trainee", 7)])
        active, departure = True, False
        u = rng.random()
        if u < 0.02:
            departure = (OCT + timedelta(days=rng.randint(1, 120))).isoformat()  # still employed
        elif u < 0.04:
            departure = rand_date(rng, date(2025, 2, 1), OCT).isoformat()  # left, record active
        elif u < 0.13:
            active, departure = False, rand_date(rng, date(2025, 2, 1), OCT).isoformat()
        elif u < 0.15:
            active = False  # archived without departure -> inactive
        if i == 500:
            etype = "intern"  # INVALID employee_type -> rejected
        emp_dept[eid] = [did, dept_name[did]] if did else False
        employees.append({
            "id": eid, "name": person(rng), "active": active,
            "company_id": ODOO_COMPANIES[ci], "department_id": emp_dept[eid],
            "employee_type": etype, "departure_date": departure,
            "parent_id": False if i == 0 else [1001, "Manager"],
            "write_date": "2026-03-02 04:00:00",
        })  # fmt: skip
    # the invalid second record
    employees[900]["employee_type"] = "intern"
    out[("2026-10-31", "hr.employee")] = ("full", employees)
    valid_emps = [e["id"] for e in employees if e["employee_type"] != "intern"]
    emp_name = {e["id"]: e["name"] for e in employees}

    # leaves
    leaves = []
    for i in range(N_LEAVES):
        eid = rng.choice(valid_emps)
        start = rand_date(rng, START, OCT)
        span = weighted(rng, [(1, 40), (2, 25), (3, 18), (4, 7), (5, 10)])
        end = start + timedelta(days=span - 1)
        state = weighted(rng, [("validate", 70), ("validate1", 5), ("confirm", 10),
                               ("refuse", 8), ("cancel", 7)])  # fmt: skip
        ltype = small.PAID_TIME_OFF if rng.random() < 0.75 else small.SICK_TIME_OFF
        if i < N_INVALID_LEAVE:  # INVALID: end before start
            end = start - timedelta(days=2)
        leaves.append({
            "id": 5001 + i, "employee_id": [eid, emp_name[eid]], "holiday_status_id": ltype,
            "state": state, "request_date_from": start.isoformat(),
            "request_date_to": end.isoformat(), "number_of_days": float(span),
            "department_id": emp_dept[eid], "write_date": f"{start.isoformat()} 05:00:00",
        })  # fmt: skip
    out[("2026-10-31", "hr.leave")] = ("full", leaves)

    # accounting
    docs = plan_documents(
        rng, n_ar=N_AR, n_ap=N_AP, n_ar_cn=N_AR_CN, n_ap_cn=N_AP_CN, n_customers=N_CUSTOMERS,
        n_suppliers=N_SUPPLIERS, n_branches=len(ODOO_COMPANIES), branch_weights=ODOO_COMPANY_WEIGHTS,
        pay_foreign=True,
    )  # fmt: skip
    cur_of = {"BTN": BTN, "USD": USD, "INR": INR}
    seq: Counter = Counter()
    for n, doc in enumerate(docs, start=1):
        doc.key = 100_000 + n

    def odoo_name(doc: Doc) -> str:
        prefix = {"AR": "INV", "AP": "BILL", "AR_CN": "RINV", "AP_CN": "RBILL"}[doc.kind]
        ym = (
            f"{doc.day.year}/{doc.day.month:02d}"
            if doc.kind in ("AP", "AP_CN")
            else f"{doc.day.year}"
        )
        seq[(prefix, ym)] += 1
        return f"{prefix}/{ym}/{seq[(prefix, ym)]:05d}"

    for doc in docs:
        if doc.state in ("posted", "cancel", "invalid") and not doc.stub:
            doc.name = odoo_name(doc)
    for doc in docs:
        if doc.stub:
            doc.name = odoo_name(doc)

    move_type = {
        "AR": "out_invoice",
        "AP": "in_invoice",
        "AR_CN": "out_refund",
        "AP_CN": "in_refund",
    }

    def pid_of(doc: Doc) -> int:
        return (customer_ids if doc.kind in ("AR", "AR_CN") else supplier_ids)[doc.party]

    def move_version(doc: Doc, t: date) -> dict:
        company = ODOO_COMPANIES[doc.branch]
        cur = False if doc.state == "invalid" else cur_of[doc.cur]
        mtype = move_type[doc.kind]
        if doc.stub and t == SEP:
            return small.odoo_move(doc.key, False, mtype, "draft", "not_paid", pid_of(doc), company,
                                   False, False, cur, doc.total, doc.total, "2026-09-28 04:00:00")  # fmt: skip
        if doc.state == "draft":
            return small.odoo_move(doc.key, False, mtype, "draft", "not_paid", pid_of(doc), company,
                                   False, False, cur, doc.total, doc.total,
                                   f"{doc.day.isoformat()} 04:00:00")  # fmt: skip
        if doc.state == "cancel":
            return small.odoo_move(doc.key, doc.name, mtype, "cancel", "not_paid", pid_of(doc),
                                   company, doc.day.isoformat(), doc.due.isoformat(), cur, doc.total,
                                   doc.total, f"{doc.day.isoformat()} 04:00:00")  # fmt: skip
        residual = doc.residual_at(t)
        paid = doc.total - residual
        pstate = "paid" if residual == 0 else ("partial" if paid > 0 else "not_paid")
        return small.odoo_move(doc.key, doc.name, mtype, "posted", pstate, pid_of(doc), company,
                               doc.day.isoformat(), doc.due.isoformat(), cur, doc.total, residual,
                               f"{doc.last_change(t).isoformat()} 04:00:00")  # fmt: skip

    sep_moves = [
        move_version(d, SEP) for d in docs
        if d.day <= SEP or d.stub  # drafts created before 30 Sep are present then too
    ]  # fmt: skip
    oct_moves = [move_version(d, OCT) for d in docs if d.changed_in_october()]
    out[("2026-09-30", "account.move")] = ("full", sep_moves)
    out[("2026-10-31", "account.move")] = ("incremental", oct_moves)

    # payments
    events = []
    for doc in docs:
        if doc.state == "posted" and doc.kind in ("AR", "AP"):
            events += [(d, a, doc) for d, a in doc.pays]
    events.sort(key=lambda e: (e[0], e[2].key))
    pay_seq: Counter = Counter()
    sep_pay, oct_pay = [], []
    for j, (day, amount, doc) in enumerate(events, start=1):
        inbound = doc.kind == "AR"
        pay_seq[day.year] += 1
        record = small.odoo_payment(
            500_000 + j, f"PBNK1/{day.year}/{pay_seq[day.year]:05d}",
            "inbound" if inbound else "outbound", "paid", pid_of(doc), amount, cur_of[doc.cur],
            day.isoformat(), [doc.key] if inbound else [], [] if inbound else [doc.key],
            f"{day.isoformat()} 04:00:00",
        )  # fmt: skip
        (sep_pay if day <= SEP else oct_pay).append(record)
    next_id = 500_000 + len(events) + 1
    extra_day = date(2026, 10, 1)
    for k in range(40):  # draft payments (never counted)
        day = date(2026, 10, 20) + timedelta(days=k % 11)
        oct_pay.append(small.odoo_payment(next_id, f"PBNK1/2026/D{k:04d}", "inbound", "draft",
                                          rng.choice(customer_ids), rng.randint(500, 20000), BTN,
                                          day.isoformat(), [], [], f"{day.isoformat()} 04:00:00"))  # fmt: skip
        next_id += 1
    for k in range(30):  # unallocated advances received
        day = extra_day + timedelta(days=k % 28)
        oct_pay.append(small.odoo_payment(next_id, f"PBNK1/2026/A{k:04d}", "inbound", "paid",
                                          rng.choice(customer_ids), rng.randint(1000, 30000), BTN,
                                          day.isoformat(), [], [], f"{day.isoformat()} 04:00:00"))  # fmt: skip
        next_id += 1
    out[("2026-09-30", "account.payment")] = ("full", sep_pay)
    out[("2026-10-31", "account.payment")] = ("incremental", oct_pay)
    return out


# ----------------------------------------------------------------------------- ERPNext


def build_erpnext(rng: random.Random) -> dict[tuple[str, str], tuple[str, list[dict]]]:
    out: dict[tuple[str, str], tuple[str, list[dict]]] = {}
    company = small.COMPANY
    ts = small.frappe_ts
    taken = {"Lhaki Traders", "Norbu Hardware", "Gakidh Retail"}

    customers = business_names(rng, N_CUSTOMERS, taken)
    suppliers = business_names(rng, N_SUPPLIERS, taken)
    out[("2026-09-30", "Customer")] = ("full", [
        {"name": n, "customer_name": n, "tax_id": None if i % 20 == 3 else f"TPN-E-C{i:05d}",
         "disabled": 0, "modified": ts("2026-02-01")} for i, n in enumerate(customers)])  # fmt: skip
    out[("2026-09-30", "Supplier")] = ("full", [
        {"name": n, "supplier_name": n, "tax_id": None if i % 20 == 3 else f"TPN-E-S{i:05d}",
         "disabled": 0, "modified": ts("2026-02-01")} for i, n in enumerate(suppliers)])  # fmt: skip

    out[("2026-10-31", "Company")] = ("full", small.erpnext_companies())
    out[("2026-10-31", "Branch")] = ("full", [
        {"name": b, "branch": b, "modified": ts("2026-01-10")} for b in ERP_BRANCHES])  # fmt: skip
    dept_full = [f"{n} - DSV" for n in ERP_DEPT_NAMES]
    out[("2026-10-31", "Department")] = ("full", [
        {"name": f"{n} - DSV", "department_name": n, "parent_department": None, "company": company,
         "is_group": 0, "disabled": 0, "modified": ts("2026-01-10")} for n in ERP_DEPT_NAMES])  # fmt: skip

    employees = []
    for i in range(N_EMPLOYEES):
        status, relieving = "Active", None
        joined = rand_date(rng, date(2015, 1, 1), date(2026, 9, 30), 1.2)
        branch, dept, comp = rng.choice(ERP_BRANCHES), rng.choice(dept_full), company
        u = rng.random()
        if u < 0.09:
            status = "Left"
            relieving = rand_date(rng, max(joined, date(2025, 2, 1)), OCT - timedelta(days=1))
        elif u < 0.11:
            status = "Inactive"
        elif u < 0.13:
            status = "Suspended"
        elif u < 0.14:
            joined = date(2026, 11, 1) + timedelta(days=rng.randint(0, 60))  # future joiner
        elif u < 0.15:
            branch = None
        elif u < 0.16:
            dept = None
        if i < N_INVALID_EMP:  # INVALID: unknown status / missing company
            status, comp = ("Retired", company) if i == 0 else ("Active", None)
        full = person(rng)
        employees.append({
            "name": f"HR-EMP-{i + 1:05d}", "employee_name": full, "first_name": full.split()[0],
            "status": status, "company": comp, "department": dept, "branch": branch,
            "date_of_joining": joined.isoformat(),
            "relieving_date": relieving.isoformat() if relieving else None,
            # Every employee already existed before the first extraction (as in a real ERP), so a
            # leave request never points at an employee the warehouse has not seen yet.
            "modified": ts("2026-03-02"),
        })  # fmt: skip
    out[("2026-10-31", "Employee")] = ("full", employees)
    valid = [e for e in employees if e["status"] != "Retired" and e["company"]]

    leaves = []
    for i in range(N_LEAVES):
        emp = rng.choice(valid)
        start = rand_date(rng, START, OCT)
        span = weighted(rng, [(1, 40), (2, 25), (3, 18), (4, 7), (5, 10)])
        end = start + timedelta(days=span - 1)
        status, docstatus, half, days = weighted(rng, [
            (("Approved", 1, 0, float(span)), 63), (("Approved", 1, 1, 0.5), 5),
            (("Approved", 0, 0, float(span)), 2), (("Open", 0, 0, float(span)), 10),
            (("Rejected", 1, 0, float(span)), 8), (("Cancelled", 2, 0, float(span)), 7),
        ])  # fmt: skip
        if half:
            end = start
        ltype = rng.choice(ERP_LEAVE_TYPES)
        if i < N_INVALID_LEAVE:
            ltype = None  # INVALID: no leave type
        leaves.append({
            "name": f"HR-LAP-2026-{i + 1:05d}", "employee": emp["name"],
            "employee_name": emp["employee_name"], "leave_type": ltype, "status": status,
            "docstatus": docstatus, "from_date": start.isoformat(), "to_date": end.isoformat(),
            "total_leave_days": days, "half_day": half, "company": company,
            "department": emp["department"], "posting_date": min(start, date(2026, 10, 1)).isoformat(),
            "modified": ts(min(start, date(2026, 10, 30)).isoformat()),
        })  # fmt: skip
    out[("2026-10-31", "Leave Application")] = ("full", leaves)

    # accounting
    docs = plan_documents(
        rng, n_ar=N_AR, n_ap=N_AP, n_ar_cn=N_AR_CN, n_ap_cn=N_AP_CN, n_customers=N_CUSTOMERS,
        n_suppliers=N_SUPPLIERS, n_branches=1, branch_weights=None, pay_foreign=False,
    )  # fmt: skip
    # Returns against invoices that still have an open balance (reduce the ORIGINAL, DS-AC-02)
    candidates = [d for d in docs if d.state == "posted" and d.kind in ("AR", "AP")
                  and d.cur == "BTN" and d.residual_at(OCT) > 20 and d.day < OCT]  # fmt: skip
    for doc in rng.sample(candidates, k=int(len(candidates) * 0.02)):
        amount = max(1, round(doc.residual_at(OCT) * rng.uniform(0.1, 0.5)))
        when = doc.day + timedelta(days=rng.randint(1, max(1, (OCT - doc.day).days)))
        doc.rets.append((min(when, OCT), amount))
    seq: Counter = Counter()

    def name_of(prefix: str) -> str:
        seq[prefix] += 1
        return f"{prefix}-2026-{seq[prefix]:05d}"

    for doc in docs:
        doc.name = name_of("ACC-SINV" if doc.kind in ("AR", "AR_CN") else "ACC-PINV")
    ret_names: dict[int, list[str]] = {}
    for doc in docs:  # a return document per recorded return
        ret_names[id(doc)] = [name_of("ACC-SINV-RET" if doc.kind == "AR" else "ACC-PINV-RET")
                              for _ in doc.rets]  # fmt: skip

    def party_of(doc: Doc) -> str | None:
        if doc.state == "invalid":
            return None
        return (customers if doc.kind in ("AR", "AR_CN") else suppliers)[doc.party]

    def invoice_version(doc: Doc, t: date) -> dict:
        builder = small.sinv if doc.kind in ("AR", "AR_CN") else small.pinv
        rate = RATE[doc.cur]
        grand, base = doc.total, doc.total * rate
        day = (doc.day if not (doc.stub and t == SEP) else date(2026, 9, 28)).isoformat()
        if doc.kind in ("AR_CN", "AP_CN"):
            return builder(doc.name, party_of(doc), day, day, doc.cur, rate, -grand, -base, "Return", 1,
                           ts(day), is_return=1)  # fmt: skip
        if doc.stub and t == SEP:
            return builder(doc.name, party_of(doc), day, day, doc.cur, rate, grand, base, "Draft", 0,
                           ts(day))  # fmt: skip
        if doc.state == "draft":
            return builder(doc.name, party_of(doc), day, doc.due.isoformat(), doc.cur, rate, grand,
                           base, "Draft", 0, ts(day))  # fmt: skip
        if doc.state == "cancel":
            return builder(doc.name, party_of(doc), day, doc.due.isoformat(), doc.cur, rate, grand,
                           base, "Cancelled", 2, ts(day))  # fmt: skip
        residual = doc.residual_at(t) * rate if doc.cur != "BTN" else doc.residual_at(t)
        paid = doc.paid_at(t) + doc.returned_at(t)
        if residual == 0:
            status = "Paid"
        elif paid > 0:
            status = "Partly Paid"
        else:
            status = "Overdue" if doc.due < t else "Unpaid"
        return builder(doc.name, party_of(doc), day, doc.due.isoformat(), doc.cur, rate, grand,
                       residual, status, 1, ts(doc.last_change(t).isoformat()))  # fmt: skip

    def returns_at(t: date, only_new: bool) -> list[dict]:
        rows = []
        builder_for = {"AR": small.sinv, "AP": small.pinv}
        for doc in docs:
            for (when, amount), rname in zip(doc.rets, ret_names[id(doc)], strict=True):
                if when > t or (only_new and when <= SEP):
                    continue
                rows.append(builder_for[doc.kind](
                    rname, party_of(doc), when.isoformat(), when.isoformat(), "BTN", 1, -amount, 0,
                    "Return", 1, ts(when.isoformat()), is_return=1, return_against=doc.name))  # fmt: skip
        return rows

    def split(doctype_kinds: tuple[str, ...]):
        mine = [d for d in docs if d.kind in doctype_kinds]
        sep = [invoice_version(d, SEP) for d in mine if d.day <= SEP or d.stub]
        octo = [invoice_version(d, OCT) for d in mine if d.changed_in_october()]
        return mine, sep, octo

    _, sales_sep, sales_oct = split(("AR", "AR_CN"))
    _, purch_sep, purch_oct = split(("AP", "AP_CN"))
    ar_ret_sep = [r for r in returns_at(SEP, False) if r["name"].startswith("ACC-SINV")]
    ap_ret_sep = [r for r in returns_at(SEP, False) if r["name"].startswith("ACC-PINV")]
    ar_ret_oct = [r for r in returns_at(OCT, True) if r["name"].startswith("ACC-SINV")]
    ap_ret_oct = [r for r in returns_at(OCT, True) if r["name"].startswith("ACC-PINV")]
    out[("2026-09-30", "Sales Invoice")] = ("full", sales_sep + ar_ret_sep)
    out[("2026-09-30", "Purchase Invoice")] = ("full", purch_sep + ap_ret_sep)
    out[("2026-10-31", "Sales Invoice")] = ("incremental", sales_oct + ar_ret_oct)
    out[("2026-10-31", "Purchase Invoice")] = ("incremental", purch_oct + ap_ret_oct)

    # payment entries
    events = []
    for doc in docs:
        if doc.state == "posted" and doc.kind in ("AR", "AP"):
            events += [(d, a, doc) for d, a in doc.pays]
    events.sort(key=lambda e: (e[0], e[2].name))
    sep_pay, oct_pay = [], []
    for j, (day, amount, doc) in enumerate(events, start=1):
        receive = doc.kind == "AR"
        record = small.payment_entry(f"ACC-PAY-2026-{j:05d}", "Receive" if receive else "Pay",
                                     party_of(doc), day.isoformat(), amount, 1,
                                     [(doc.name, amount)])  # fmt: skip
        (sep_pay if day <= SEP else oct_pay).append(record)
    next_no = len(events) + 1
    for k in range(40):  # draft payment entries
        day = date(2026, 10, 20) + timedelta(days=k % 11)
        oct_pay.append(small.payment_entry(f"ACC-PAY-2026-{next_no:05d}", "Receive",
                                           rng.choice(customers), day.isoformat(),
                                           rng.randint(500, 20000), 0, []))  # fmt: skip
        next_no += 1
    for k in range(30):  # unallocated advances
        day = date(2026, 10, 1) + timedelta(days=k % 28)
        amount = rng.randint(1000, 30000)
        oct_pay.append(small.payment_entry(f"ACC-PAY-2026-{next_no:05d}", "Receive",
                                           rng.choice(customers), day.isoformat(), amount, 1, [],
                                           unallocated=amount))  # fmt: skip
        next_no += 1
    out[("2026-09-30", "Payment Entry")] = ("full", sep_pay)
    out[("2026-10-31", "Payment Entry")] = ("incremental", oct_pay)
    return out


# ------------------------------------------------------------------------------- output


def write_all(out_dir: Path = HERE) -> dict[str, int]:
    rng = random.Random(SEED)
    counts: dict[str, int] = {}
    for system, builder in (("odoo", build_odoo), ("erpnext", build_erpnext)):
        for (batch, entity), (mode, records) in builder(rng).items():
            doc = small.build_fixture(system, batch, entity, mode, records)
            path = out_dir / system / batch / f"{entity.lower().replace(' ', '_')}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(doc, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8", newline="\n",
            )  # fmt: skip
            counts[f"{system}/{batch}/{entity}"] = len(records)
    return counts


def main() -> None:
    counts = write_all()
    for name, n in counts.items():
        print(f"{name:55s} {n:>8,}")
    print(f"{'TOTAL source records (all files)':55s} {sum(counts.values()):>8,}")


if __name__ == "__main__":
    main()
