"""SANDBOX ONLY: seed SYNTHETIC data into the local ERPNext 16 sandbox and create the read-only
API user for the DrukSmart connector. Talks to the site's REST API as Administrator (password
from .env). The read-only user's key pair is written to .env and never printed.

    python infrastructure/sandboxes/sandbox.py seed erpnext

Idempotent: existing records are reused; the API key pair is regenerated on every run.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parents[4]
ENV = dotenv_values(REPO_ROOT / ".env")
BASE = ENV.get("ERPNEXT_BASE_URL") or "http://127.0.0.1:8090"
COMPANY, ABBR = "DTG Services Pvt Ltd", "DSV"
ROLE = "DrukSmart Read Only"
BOT = "druksmart.readonly@example.com"
READ_DOCTYPES = [
    "Company",
    "Branch",
    "Department",
    "Employee",
    "Leave Application",
    "Customer",
    "Supplier",
    "Sales Invoice",
    "Purchase Invoice",
    "Payment Entry",
]

sys.path.insert(0, str(REPO_ROOT / "infrastructure" / "sandboxes"))
from sandbox import set_env_value  # noqa: E402


class Site:
    def __init__(self):
        self.http = httpx.Client(base_url=BASE, timeout=180)
        r = self.http.post(
            "/api/method/login",
            data={"usr": "Administrator", "pwd": ENV["ERPNEXT_SANDBOX_ADMIN_PASSWORD"]},
        )
        r.raise_for_status()

    def _check(self, r: httpx.Response):
        if r.is_error:
            body = (
                r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            )
            msg = body.get("_server_messages") or body.get("exception") or r.text[:400]
            raise RuntimeError(
                f"{r.request.method} {r.request.url.path}: HTTP {r.status_code}: {str(msg)[:600]}"
            )
        return r.json()

    def method(self, _method: str, **kwargs):
        payload = {k: json.dumps(v) if isinstance(v, dict | list) else v for k, v in kwargs.items()}
        return self._check(self.http.post(f"/api/method/{_method}", data=payload)).get("message")

    def get_list(self, doctype: str, filters=None, fields=("name",)):
        params = {
            "filters": json.dumps(filters or []),
            "fields": json.dumps(list(fields)),
            "limit_page_length": 1000,
        }
        return self._check(self.http.get(f"/api/resource/{doctype}", params=params))["data"]

    def insert(self, doctype: str, doc: dict) -> dict:
        return self._check(self.http.post(f"/api/resource/{doctype}", json=doc))["data"]

    def update(self, doctype: str, name: str, values: dict) -> dict:
        return self._check(self.http.put(f"/api/resource/{doctype}/{name}", json=values))["data"]

    def ensure(self, doctype: str, filters: dict, doc: dict) -> str:
        found = self.get_list(doctype, [[k, "=", v] for k, v in filters.items()])
        return found[0]["name"] if found else self.insert(doctype, doc)["name"]


def setup_wizard(site: Site) -> None:
    if site.get_list("Company"):
        return
    print("running setup wizard ...")
    args = {
        "language": "English",
        "country": "Bhutan",
        "timezone": "Asia/Thimphu",
        "currency": "BTN",
        "full_name": "Sandbox Admin",
        "email": "admin@example.com",
        "company_name": COMPANY,
        "company_abbr": ABBR,
        "chart_of_accounts": "Standard",
        "fy_start_date": "2026-01-01",
        "fy_end_date": "2026-12-31",
        "setup_demo": 0,
    }
    site.method("frappe.desk.page.setup_wizard.setup_wizard.setup_complete", args=args)
    for _ in range(60):  # setup may run as a background job
        if site.get_list("Company"):
            return
        time.sleep(5)
    raise RuntimeError("setup wizard did not create the company")


def hr(site: Site, hrms: bool) -> None:
    for b in ("Paro", "Bumthang"):
        site.ensure("Branch", {"branch": b}, {"branch": b})
    for d in ("Operations", "Accounts", "Sales", "Human Resources"):
        site.ensure(
            "Department",
            {"department_name": d, "company": COMPANY},
            {"department_name": d, "company": COMPANY},
        )
    people = [
        ("Pema", "Wangmo", "Female", "Active", "Operations", "Paro", "2021-03-01", None),
        ("Kezang", "Dorji", "Male", "Active", "Operations", "Paro", "2022-06-15", None),
        ("Namgay", "Lham", "Female", "Active", "Accounts", "Paro", "2020-01-06", None),
        ("Sangay", "Tenzin", "Male", "Active", "Sales", "Bumthang", "2023-02-01", None),
        ("Tandin", "Bidha", "Female", "Left", "Sales", "Bumthang", "2019-05-01", "2026-09-30"),
        ("Rinzin", "Om", "Female", "Suspended", "Human Resources", "Paro", "2022-09-01", None),
        ("Wangchuk", "Dorji", "Male", "Inactive", "Operations", "Paro", "2018-04-01", None),
        ("Lhamo", "Yangchen", "Female", "Active", "Human Resources", None, "2025-01-15", None),
        ("Nima", "Gyeltshen", "Male", "Active", None, "Bumthang", "2025-08-01", None),
    ]
    emp = {}
    for first, last, gender, status, dept, branch, joined, relieved in people:
        doc = {
            "first_name": first,
            "last_name": last,
            "gender": gender,
            "date_of_birth": "1990-01-01",
            "company": COMPANY,
            "status": status,
            "date_of_joining": joined,
            "department": f"{dept} - {ABBR}" if dept else None,
            "branch": branch,
            "relieving_date": relieved,
        }
        emp[first] = site.ensure("Employee", {"first_name": first, "last_name": last}, doc)
    print(f"employees: {len(emp)}")
    if not hrms:
        print("hrms not installed: Leave Application not seeded")
        return

    holiday = site.ensure(
        "Holiday List",
        {"holiday_list_name": "Sandbox 2026"},
        {"holiday_list_name": "Sandbox 2026", "from_date": "2026-01-01", "to_date": "2026-12-31"},
    )
    site.update("Company", COMPANY, {"default_holiday_list": holiday})
    # HRMS 16 resolves holidays through a submitted Holiday List Assignment (new DocType).
    if not site.get_list(
        "Holiday List Assignment", [["assigned_to", "=", COMPANY], ["docstatus", "=", 1]]
    ):
        site.insert(
            "Holiday List Assignment",
            {
                "applicable_for": "Company",
                "assigned_to": COMPANY,
                "holiday_list": holiday,
                "from_date": "2026-01-01",
                "docstatus": 1,
            },
        )
    site.update("HR Settings", "HR Settings", {"leave_approver_mandatory_in_leave_application": 0})
    # Leave Without Pay types need no leave allocation, which keeps the sandbox simple.
    for lt in ("Casual Leave", "Sick Leave"):
        name = site.ensure(
            "Leave Type", {"leave_type_name": lt}, {"leave_type_name": lt, "is_lwp": 1}
        )
        site.update(
            "Leave Type", name, {"is_lwp": 1, "allow_negative": 1, "max_continuous_days_allowed": 0}
        )
    leaves = [
        ("Pema", "Casual Leave", "2026-10-06", "2026-10-07", "Approved", 1),
        ("Kezang", "Sick Leave", "2026-10-09", "2026-10-09", "Approved", 1),
        ("Namgay", "Casual Leave", "2026-10-13", "2026-10-17", "Open", 0),
        ("Sangay", "Casual Leave", "2026-10-20", "2026-10-21", "Rejected", 1),
        ("Lhamo", "Casual Leave", "2026-10-27", "2026-10-28", "Approved", 0),
        ("Pema", "Casual Leave", "2026-10-29", "2026-10-30", "Approved", 1),
    ]
    for first, lt, start, end, status, docstatus in leaves:
        if site.get_list(
            "Leave Application", [["employee", "=", emp[first]], ["from_date", "=", start]]
        ):
            continue
        site.insert(
            "Leave Application",
            {
                "employee": emp[first],
                "leave_type": lt,
                "from_date": start,
                "to_date": end,
                "posting_date": start,
                "status": status,
                "docstatus": docstatus,
                "company": COMPANY,
            },
        )
    print(f"leave applications: {len(leaves)}")


def invoice(site, doctype, party, posting, due, amount, currency="BTN", rate=1.0, submit=True):
    """Create the invoice unless one with the same party, date and amount exists (idempotent)."""
    party_field = "customer" if doctype == "Sales Invoice" else "supplier"
    existing = site.get_list(
        doctype,
        [
            [party_field, "=", party],
            ["posting_date", "=", posting],
            ["grand_total", "=", amount],
            ["is_return", "=", 0],
        ],
    )
    if existing:
        return existing[0]["name"]
    doc = {
        party_field: party,
        "company": COMPANY,
        "posting_date": posting,
        "set_posting_time": 1,
        "due_date": due,
        "currency": currency,
        "conversion_rate": rate,
        "items": [{"item_code": "SYN-SERVICE", "qty": 1, "rate": amount}],
        "docstatus": 1 if submit else 0,
    }
    if doctype == "Purchase Invoice":
        doc["bill_no"] = f"SUP-{posting}-{amount}"
        doc["bill_date"] = posting
    return site.insert(doctype, doc)["name"]


def pay(site, doctype, name, amount, posting):
    if site.get_list(
        "Payment Entry", [["reference_no", "=", f"SYN-{name}"], ["docstatus", "=", 1]]
    ):
        return None
    pe = site.method(
        "erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry",
        dt=doctype,
        dn=name,
    )
    pe.update(
        {
            "posting_date": posting,
            "paid_amount": amount,
            "received_amount": amount,
            "reference_no": f"SYN-{name}",
            "reference_date": posting,
            "docstatus": 1,
        }
    )
    pe["references"][0]["allocated_amount"] = amount
    return site.insert("Payment Entry", pe)["name"]


def accounts(site: Site) -> None:
    for c, tax in (
        ("Lhaki Traders", "TPN-LHK-1001"),
        ("Norbu Hardware", "TPN-NRB-2999"),
        ("Gakidh Retail", "TPN-GKR-6001"),
    ):
        site.ensure(
            "Customer",
            {"customer_name": c},
            {"customer_name": c, "customer_type": "Company", "tax_id": tax},
        )
    for s in ("Thunder Paper Works", "Peling Logistics"):
        site.ensure(
            "Supplier", {"supplier_name": s}, {"supplier_name": s, "supplier_type": "Company"}
        )
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
    usd = site.get_list("Currency", [["name", "=", "USD"]], fields=("name", "enabled"))
    if usd and not usd[0]["enabled"]:
        site.update("Currency", "USD", {"enabled": 1})

    s1 = invoice(site, "Sales Invoice", "Norbu Hardware", "2026-08-12", "2026-09-11", 25000)
    pay(site, "Sales Invoice", s1, 15000, "2026-10-10")
    s2 = invoice(site, "Sales Invoice", "Lhaki Traders", "2026-09-01", "2026-10-01", 12000)
    pay(site, "Sales Invoice", s2, 12000, "2026-09-20")
    s3 = invoice(site, "Sales Invoice", "Gakidh Retail", "2026-09-15", "2026-10-15", 18000)
    pay(site, "Sales Invoice", s3, 7000, "2026-09-28")
    if not site.get_list("Sales Invoice", [["return_against", "=", s3], ["docstatus", "=", 1]]):
        ret = site.method(
            "erpnext.accounts.doctype.sales_invoice.sales_invoice.make_sales_return", source_name=s3
        )
        ret.update({"posting_date": "2026-09-27", "set_posting_time": 1, "docstatus": 1})
        ret["items"][0]["rate"] = 3000
        site.insert("Sales Invoice", ret)
    invoice(site, "Sales Invoice", "Norbu Hardware", "2026-09-29", "2026-10-29", 5000, submit=False)
    s5 = invoice(site, "Sales Invoice", "Gakidh Retail", "2026-09-20", "2026-10-20", 4000)
    if site.get_list("Sales Invoice", [["name", "=", s5], ["docstatus", "=", 1]]):
        site.method("frappe.client.cancel", doctype="Sales Invoice", name=s5)
    invoice(
        site,
        "Sales Invoice",
        "Gakidh Retail",
        "2026-10-02",
        "2026-10-02",
        300,
        currency="USD",
        rate=84,
    )
    invoice(site, "Sales Invoice", "Lhaki Traders", "2026-10-05", "2026-11-04", 22000)

    p1 = invoice(site, "Purchase Invoice", "Thunder Paper Works", "2026-08-01", "2026-08-31", 9000)
    pay(site, "Purchase Invoice", p1, 9000, "2026-10-03")
    p2 = invoice(site, "Purchase Invoice", "Peling Logistics", "2026-09-10", "2026-10-10", 14000)
    pay(site, "Purchase Invoice", p2, 10000, "2026-09-25")
    invoice(site, "Purchase Invoice", "Peling Logistics", "2026-10-15", "2026-11-14", 7000)
    print(
        "sales invoices:",
        len(site.get_list("Sales Invoice")),
        "purchase invoices:",
        len(site.get_list("Purchase Invoice")),
        "payment entries:",
        len(site.get_list("Payment Entry")),
    )


def read_only_user(site: Site) -> None:
    if not site.get_list("Role", [["name", "=", ROLE]]):
        site.insert("Role", {"role_name": ROLE, "desk_access": 0})
    pm = "frappe.core.page.permission_manager.permission_manager"
    for doctype in READ_DOCTYPES:
        existing = site.get_list(
            "Custom DocPerm",
            [["parent", "=", doctype], ["role", "=", ROLE]],
            fields=("name", "permlevel"),
        )
        for level in (0, 1):  # some fields (e.g. Leave Application.status) are at permlevel 1
            if any(p["permlevel"] == level for p in existing):
                continue
            try:
                site.method(f"{pm}.add", parent=doctype, role=ROLE, permlevel=level)
            except RuntimeError as exc:
                if "DocType" in str(exc) and doctype == "Leave Application":
                    continue  # hrms not installed
                raise
            site.method(
                f"{pm}.update", doctype=doctype, role=ROLE, permlevel=level, ptype="read", value=1
            )
    if not site.get_list("User", [["name", "=", BOT]]):
        site.insert(
            "User",
            {
                "email": BOT,
                "first_name": "DrukSmart Read-Only",
                "send_welcome_email": 0,
                "user_type": "System User",
                "roles": [{"role": ROLE}],
            },
        )
    keys = site.method("frappe.core.doctype.user.user.generate_keys", user=BOT)
    api_key = (
        keys.get("api_key")
        or site._check(site.http.get(f"/api/resource/User/{BOT}"))["data"]["api_key"]
    )
    set_env_value("ERPNEXT_API_KEY", api_key)
    set_env_value("ERPNEXT_API_SECRET", keys["api_secret"])
    print(f"read-only user {BOT} with role '{ROLE}'; API key pair written to .env (not displayed)")


def main() -> int:
    site = Site()
    apps = site.method("frappe.utils.change_log.get_versions") or {}
    hrms = "hrms" in apps
    print("installed apps:", {k: v.get("version") for k, v in apps.items()})
    setup_wizard(site)
    hr(site, hrms)
    accounts(site)
    read_only_user(site)
    print("SEED COMPLETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
