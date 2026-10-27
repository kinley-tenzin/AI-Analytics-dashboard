"""SANDBOX ONLY. Load the medium-scale SYNTHETIC plan into the local ERPNext 16 sandbox.

    python infrastructure/sandboxes/scale/load_erpnext.py --phases setup,masters,parties,employees
    python infrastructure/sandboxes/scale/load_erpnext.py --phases leaves,invoices,returns,payments

Uses the site's REST API as Administrator (password from .env), like the first sandbox seed, so every
record goes through ERPNext's own validation, posting and ledger logic. Refuses any base URL that is
not local. Idempotent: every record carries `SCALE-<ref>` in a text field (Sales Invoice.po_no,
Purchase Invoice.bill_no, Payment Entry.reference_no, Employee.employee_number,
Leave Application.description) and is skipped when that marker already exists. Records ERPNext
refuses (e.g. overlapping leave) are counted and skipped, never forced.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values

REPO = Path(__file__).resolve().parents[3]
ENV = dotenv_values(REPO / ".env")
BASE = ENV.get("ERPNEXT_BASE_URL") or "http://127.0.0.1:8090"
PLAN = REPO / "tests" / "fixtures" / "synthetic_medium" / "erp_plan" / "erpnext.json"
COMPANY, ABBR = "DTG Services Pvt Ltd", "DSV"
T0 = time.time()
LOCK = threading.Lock()
RETRY_ON = re.compile(r"deadlock|lock wait timeout|timestamp|try again|connection|temporarily", re.I)


def log(*args) -> None:
    with LOCK:
        print(f"[{time.time() - T0:7.0f}s]", *args, flush=True)


class Refused(Exception):
    """ERPNext rejected the record (validation): counted, not retried."""


class Site:
    def __init__(self) -> None:
        host = urlsplit(BASE).hostname
        if host not in ("127.0.0.1", "localhost"):
            raise SystemExit(f"refusing to load data into non-local ERPNext {BASE}")
        self.http = httpx.Client(base_url=BASE, timeout=300, limits=httpx.Limits(max_connections=16))
        r = self.http.post(
            "/api/method/login", data={"usr": "Administrator", "pwd": ENV["ERPNEXT_SANDBOX_ADMIN_PASSWORD"]}
        )
        r.raise_for_status()

    def _call(self, send):
        last = ""
        for attempt in range(8):
            try:
                r = send()
            except httpx.HTTPError as exc:
                last = str(exc)
                time.sleep(random.uniform(0.5, 1.5) * (1 + attempt))
                continue
            if not r.is_error:
                return r.json()
            body = r.text[:1500]
            if r.status_code >= 500 and RETRY_ON.search(body) or r.status_code in (502, 503, 504):
                last = body[:200]
                time.sleep(random.uniform(0.5, 1.5) * (1 + attempt))
                continue
            raise Refused(f"HTTP {r.status_code}: {self._message(r)}")
        raise Refused(f"gave up after retries: {last}")

    @staticmethod
    def _message(r: httpx.Response) -> str:
        try:
            body = r.json()
            raw = body.get("_server_messages") or body.get("exception") or r.text
            return re.sub(r"<[^>]+>|\\u003c[^\\]*", "", str(raw))[:240]
        except ValueError:
            return r.text[:240]

    def method(self, _method: str, **kw):
        payload = {k: json.dumps(v) if isinstance(v, dict | list) else v for k, v in kw.items()}
        return self._call(lambda: self.http.post(f"/api/method/{_method}", data=payload)).get("message")

    def insert(self, doctype: str, doc: dict) -> dict:
        return self._call(lambda: self.http.post(f"/api/resource/{doctype}", json=doc))["data"]

    def update(self, doctype: str, name: str, values: dict) -> dict:
        return self._call(lambda: self.http.put(f"/api/resource/{doctype}/{name}", json=values))["data"]

    def get_all(self, doctype: str, filters=None, fields=("name",)) -> list[dict]:
        out, start = [], 0
        while True:
            params = {
                "filters": json.dumps(filters or []),
                "fields": json.dumps(list(fields)),
                "limit_start": start,
                "limit_page_length": 5000,
            }
            page = self._call(lambda params=params: self.http.get(f"/api/resource/{doctype}", params=params))["data"]
            out += page
            if len(page) < 5000:
                return out
            start += 5000

    def ensure(self, doctype: str, filters: dict, doc: dict) -> str:
        found = self.get_all(doctype, [[k, "=", v] for k, v in filters.items()])
        return found[0]["name"] if found else self.insert(doctype, doc)["name"]


def run_parallel(label: str, items: list, work, workers: int, group=None) -> tuple[int, int]:
    """Run work(item) for every item; items of one `group` key stay in order on one worker."""
    done = refused = 0
    buckets: dict = {}
    for item in items:
        buckets.setdefault(group(item) if group else id(item), []).append(item)
    lanes: list[list] = [[] for _ in range(workers)]
    for i, bucket in enumerate(buckets.values()):
        lanes[i % workers] += bucket
    counter = {"done": 0, "refused": 0}

    def lane(items_):
        for item in items_:
            try:
                work(item)
                with LOCK:
                    counter["done"] += 1
            except Refused as exc:
                with LOCK:
                    counter["refused"] += 1
                    if counter["refused"] <= 3:
                        print(f"  refused {label} {item.get('ref', item.get('name'))}: {exc}", flush=True)
            n = counter["done"] + counter["refused"]
            if n % 500 == 0:
                log(f"{label}: {n}/{len(items)} ({counter['refused']} refused)")

    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(lane, lanes))
    done, refused = counter["done"], counter["refused"]
    log(f"{label}: {done} created, {refused} refused by ERPNext")
    return done, refused


# ----------------------------------------------------------------------------- phases
def setup(site: Site, plan: dict, workers: int, limit: int | None) -> None:
    for year in ("2025", "2027"):
        site.ensure(
            "Fiscal Year",
            {"year": year},
            {"year": year, "year_start_date": f"{year}-01-01", "year_end_date": f"{year}-12-31"},
        )
    holiday = site.ensure(
        "Holiday List",
        {"holiday_list_name": "Sandbox 2025"},
        {"holiday_list_name": "Sandbox 2025", "from_date": "2025-01-01", "to_date": "2025-12-31"},
    )
    if not site.get_all("Holiday List Assignment", [["assigned_to", "=", COMPANY], ["from_date", "=", "2025-01-01"]]):
        site.insert(
            "Holiday List Assignment",
            {
                "applicable_for": "Company",
                "assigned_to": COMPANY,
                "holiday_list": holiday,
                "from_date": "2025-01-01",
                "docstatus": 1,
            },
        )
    for leave_type in ("Casual Leave", "Sick Leave", "Privilege Leave"):
        name = site.ensure("Leave Type", {"leave_type_name": leave_type}, {"leave_type_name": leave_type, "is_lwp": 1})
        site.update("Leave Type", name, {"is_lwp": 1, "allow_negative": 1, "max_continuous_days_allowed": 0})
    log("setup: fiscal years 2025/2027, holiday list 2025, leave types")


def masters(site: Site, plan: dict, workers: int, limit: int | None) -> None:
    for branch in plan["branches"]:
        site.ensure("Branch", {"branch": branch}, {"branch": branch})
    for dept in plan["departments"]:
        name = dept.removesuffix(f" - {ABBR}")
        site.ensure(
            "Department", {"department_name": name, "company": COMPANY}, {"department_name": name, "company": COMPANY}
        )
    log("masters:", len(plan["branches"]), "branches,", len(plan["departments"]), "departments")


def parties(site: Site, plan: dict, workers: int, limit: int | None) -> None:
    have = {r["name"] for r in site.get_all("Customer")} | {r["name"] for r in site.get_all("Supplier")}
    todo = [("Customer", c) for c in plan["customers"] if c["name"] not in have] + [
        ("Supplier", s) for s in plan["suppliers"] if s["name"] not in have
    ]

    def make(item):
        doctype, p = item
        field = "customer" if doctype == "Customer" else "supplier"
        site.insert(
            doctype,
            {
                f"{field}_name": p["name"],
                f"{field}_type": "Company",
                "tax_id": p["tax_id"],
            },
        )

    run_parallel("parties", [{"ref": p["name"], "item": (d, p)} for d, p in todo], lambda x: make(x["item"]), workers)


def employee_map(site: Site) -> dict[str, str]:
    rows = site.get_all("Employee", [["employee_number", "like", "SCALE-%"]], ("name", "employee_number"))
    return {r["employee_number"].removeprefix("SCALE-"): r["name"] for r in rows}


def employees(site: Site, plan: dict, workers: int, limit: int | None) -> None:
    have = employee_map(site)
    todo = [e for e in plan["employees"] if e["ref"] not in have][:limit]

    def make(e):
        first, _, last = e["name"].partition(" ")
        site.insert(
            "Employee",
            {
                "first_name": first,
                "last_name": last or None,
                "gender": "Female" if int(re.sub(r"\D", "", e["ref"]) or 0) % 2 else "Male",
                "date_of_birth": "1990-01-01",
                "company": COMPANY,
                "status": e["status"],
                "date_of_joining": e["joined"],
                "department": e["dept"],
                "branch": e["branch"],
                "relieving_date": e["relieved"],
                "employee_number": f"SCALE-{e['ref']}",
            },
        )

    run_parallel("employees", todo, make, workers)


def leaves(site: Site, plan: dict, workers: int, limit: int | None) -> None:
    emp = employee_map(site)
    have = {
        r["description"].removeprefix("SCALE-")
        for r in site.get_all("Leave Application", [["description", "like", "SCALE-%"]], ("description",))
    }
    todo = [lv for lv in plan["leaves"] if lv["ref"] not in have and lv["emp"] in emp][:limit]

    def make(lv):
        half = bool(lv["half"])
        doc = {
            "employee": emp[lv["emp"]],
            "leave_type": lv["type"],
            "from_date": lv["from"],
            "to_date": lv["to"],
            "posting_date": lv["from"],
            "status": "Approved" if lv["docstatus"] == 2 else lv["status"],
            "docstatus": 1 if lv["docstatus"] == 2 else lv["docstatus"],
            "company": COMPANY,
            "description": f"SCALE-{lv['ref']}",
            "half_day": int(half),
            **({"half_day_date": lv["from"]} if half else {}),
        }
        name = site.insert("Leave Application", doc)["name"]
        if lv["docstatus"] == 2:
            site.method("frappe.client.cancel", doctype="Leave Application", name=name)

    run_parallel("leaves", todo, make, workers, group=lambda lv: lv["emp"])


MARK = {"Sales Invoice": "po_no", "Purchase Invoice": "bill_no"}


def invoice_map(site: Site, doctype: str) -> dict[str, str]:
    rows = site.get_all(doctype, [[MARK[doctype], "like", "SCALE-%"], ["is_return", "=", 0]], ("name", MARK[doctype]))
    return {r[MARK[doctype]].removeprefix("SCALE-"): r["name"] for r in rows}


def invoices(site: Site, plan: dict, workers: int, limit: int | None) -> None:
    site.ensure(
        "Item",
        {"item_code": "SYN-SERVICE"},
        {
            "item_code": "SYN-SERVICE",
            "item_name": "Synthetic service",
            "item_group": "Services",
            "stock_uom": "Nos",
            "is_stock_item": 0,
        },
    )
    have = set(invoice_map(site, "Sales Invoice")) | set(invoice_map(site, "Purchase Invoice"))
    have |= {
        r[MARK[d]].removeprefix("SCALE-")
        for d in MARK
        for r in site.get_all(d, [[MARK[d], "like", "SCALE-%"], ["is_return", "=", 1]], ("name", MARK[d]))
    }
    todo = [i for i in plan["invoices"] if i["ref"] not in have][:limit]

    def make(inv):
        sales = inv["doctype"] == "Sales Invoice"
        sign = -1 if inv["credit_note"] else 1
        doc = {
            "customer" if sales else "supplier": inv["party"],
            "company": COMPANY,
            "posting_date": inv["date"],
            "set_posting_time": 1,
            "due_date": inv["due"],
            "currency": inv["cur"],
            "conversion_rate": inv["rate"],
            "items": [{"item_code": "SYN-SERVICE", "qty": sign, "rate": inv["amount"]}],
            "docstatus": 0 if inv["state"] == "draft" else 1,
            "is_return": int(inv["credit_note"]),
            MARK[inv["doctype"]]: f"SCALE-{inv['ref']}",
        }
        if not sales:
            doc["bill_date"] = inv["date"]
            doc["bill_no"] = f"SCALE-{inv['ref']}"
        name = site.insert(inv["doctype"], doc)["name"]
        if inv["state"] == "cancel":
            site.method("frappe.client.cancel", doctype=inv["doctype"], name=name)

    run_parallel("invoices", todo, make, workers, group=lambda i: i["party"])


def returns(site: Site, plan: dict, workers: int, limit: int | None) -> None:
    names = {**invoice_map(site, "Sales Invoice"), **invoice_map(site, "Purchase Invoice")}
    have = {
        r[MARK[d]].removeprefix("SCALE-")
        for d in MARK
        for r in site.get_all(d, [[MARK[d], "like", "SCALE-%"], ["is_return", "=", 1]], ("name", MARK[d]))
    }
    todo = [r for r in plan["returns"] if r["ref"] not in have and r["against"] in names][:limit]
    make = {
        "Sales Invoice": "erpnext.accounts.doctype.sales_invoice.sales_invoice.make_sales_return",
        "Purchase Invoice": "erpnext.accounts.doctype.purchase_invoice.purchase_invoice.make_purchase_return",
    }

    def run(r):
        doc = site.method(make[r["doctype"]], source_name=names[r["against"]])
        doc.update(
            {"posting_date": r["date"], "set_posting_time": 1, "docstatus": 1, MARK[r["doctype"]]: f"SCALE-{r['ref']}"}
        )
        doc["items"][0]["rate"] = r["amount"]
        if r["doctype"] == "Purchase Invoice":
            doc["bill_no"] = f"SCALE-{r['ref']}"
        site.insert(r["doctype"], doc)

    run_parallel("returns", todo, run, workers, group=lambda r: r["against"])


def payments(site: Site, plan: dict, workers: int, limit: int | None) -> None:
    names = {**invoice_map(site, "Sales Invoice"), **invoice_map(site, "Purchase Invoice")}
    have = {
        r["reference_no"].removeprefix("SCALE-")
        for r in site.get_all("Payment Entry", [["reference_no", "like", "SCALE-%"]], ("reference_no",))
    }
    todo = [p for p in plan["payments"] if p["ref"] not in have and p["against"] in names][:limit]

    def run(p):
        pe = site.method(
            "erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry",
            dt=p["doctype"],
            dn=names[p["against"]],
        )
        pe.update(
            {
                "posting_date": p["date"],
                "paid_amount": p["amount"],
                "received_amount": p["amount"],
                "reference_no": f"SCALE-{p['ref']}",
                "reference_date": p["date"],
                "docstatus": 1,
            }
        )
        pe["references"][0]["allocated_amount"] = p["amount"]
        site.insert("Payment Entry", pe)

    run_parallel("payments", todo, run, workers, group=lambda p: p["against"])


PHASES = {
    "setup": setup,
    "masters": masters,
    "parties": parties,
    "employees": employees,
    "leaves": leaves,
    "invoices": invoices,
    "returns": returns,
    "payments": payments,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--phases", default=",".join(PHASES), help="comma separated, in order")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--limit", type=int, default=None, help="at most N new records per phase")
    args = parser.parse_args()
    plan = json.loads(PLAN.read_text("utf-8"))
    site = Site()
    for phase in args.phases.split(","):
        started = time.time()
        PHASES[phase](site, plan, args.workers, args.limit)
        log(f"== {phase} finished in {time.time() - started:.0f}s")
    print("LOAD COMPLETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
