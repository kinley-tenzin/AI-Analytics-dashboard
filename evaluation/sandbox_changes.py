"""Controlled business changes in the LOCAL ERP SANDBOXES for the end-to-end test (Milestone 8).

    python evaluation/sandbox_changes.py phase-a     # new activity
    python evaluation/sandbox_changes.py phase-b     # changes to that activity
    python evaluation/sandbox_changes.py phase-c     # post-fix check: one more hire (headcount +1)
    python evaluation/sandbox_changes.py phase-d     # post-fix check: that hire leaves (-1)

SANDBOX ONLY: refuses to run unless both ERP base URLs point to 127.0.0.1/localhost and the
instance ids end with "-sandbox". The platform itself never writes to an ERP; this script plays
the role of business users working in the ERPs (as the sandbox administrators). Every change is
idempotent (tagged "E2E-M8"), so re-running a phase changes nothing.

Phase A (expected effect, by construction):
  Odoo    new active employee in Sales (head office)                 headcount +1, Sales +1
  Odoo    customer invoice 6,000 due 2026-11-23, partial payment 2,500  receivables +3,500 (not due)
  Odoo    customer invoice 1,500 posted, then CANCELLED                 no change
  ERPNext approved leave 2026-10-26 (1 day) for Kezang, who already
          had approved leave this month                                 requests +1, days +1, employees +0
  ERPNext purchase invoice 4,000 due 2026-10-20, partial payment 1,500   payables +2,500, overdue AP +2,500
Phase B:
  Odoo    the new employee leaves (archived, departure 2026-10-25)     headcount -1
  Odoo    the 6,000 invoice is paid in full                             receivables -3,500
  ERPNext the 2026-10-26 leave application is CANCELLED                 requests -1, days -1
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "infrastructure" / "sandboxes"))
sys.path.insert(0, str(REPO / "infrastructure" / "sandboxes" / "erpnext" / "seed"))
from dotenv import dotenv_values  # noqa: E402

ENV = dotenv_values(REPO / ".env")
TAG = "E2E-M8"

ODOO_PHASE_A = """
import datetime
D = datetime.date.fromisoformat
company = env.ref("base.main_company")
sales = env["hr.department"].search([("name", "=", "Sales"), ("company_id", "=", company.id)], limit=1)
emp = env["hr.employee"].with_context(active_test=False).search([("name", "=", "E2E-M8 New Hire")], limit=1)
if not emp:
    env["hr.employee"].create({"name": "E2E-M8 New Hire", "department_id": sales.id, "company_id": company.id})
partner = env["res.partner"].search([("name", "=", "Norbu Hardware")], limit=1)

def invoice(ref, amount, inv, due):
    m = env["account.move"].search([("ref", "=", ref)], limit=1)
    if m:
        return m, False
    m = env["account.move"].with_company(company).create({
        "move_type": "out_invoice", "partner_id": partner.id, "company_id": company.id, "ref": ref,
        "invoice_date": D(inv), "invoice_date_due": D(due),
        "invoice_line_ids": [(0, 0, {"name": "E2E-M8 line", "quantity": 1, "price_unit": amount,
                                     "tax_ids": [(6, 0, [])]})]})
    m.action_post()
    return m, True

m, new = invoice("E2E-M8-A", 6000, "2026-10-24", "2026-11-23")
if new:
    env["account.payment.register"].with_company(company).with_context(
        active_model="account.move", active_ids=m.ids).create(
        {"amount": 2500, "payment_date": D("2026-10-24")}).action_create_payments()
c, new = invoice("E2E-M8-CANCEL", 1500, "2026-10-24", "2026-11-23")
if c.state != "cancel":
    c.button_draft()
    c.button_cancel()
env.cr.commit()
print("E2E CHANGES APPLIED")
"""

ODOO_PHASE_B = """
import datetime
D = datetime.date.fromisoformat
emp = env["hr.employee"].with_context(active_test=False).search([("name", "=", "E2E-M8 New Hire")], limit=1)
if emp.active:
    emp.write({"departure_date": D("2026-10-25"), "active": False})
m = env["account.move"].search([("ref", "=", "E2E-M8-A")], limit=1)
if m and m.amount_residual > 0:
    env["account.payment.register"].with_company(m.company_id).with_context(
        active_model="account.move", active_ids=m.ids).create(
        {"amount": m.amount_residual, "payment_date": D("2026-10-25")}).action_create_payments()
env.cr.commit()
print("E2E CHANGES APPLIED")
"""


ODOO_PHASE_C = """
company = env.ref("base.main_company")
sales = env["hr.department"].search([("name", "=", "Sales"), ("company_id", "=", company.id)], limit=1)
if not env["hr.employee"].with_context(active_test=False).search([("name", "=", "E2E-M8 Cache Check")]):
    env["hr.employee"].create({"name": "E2E-M8 Cache Check", "department_id": sales.id, "company_id": company.id})
env.cr.commit()
print("E2E CHANGES APPLIED")
"""

ODOO_PHASE_D = """
import datetime
emp = env["hr.employee"].with_context(active_test=False).search([("name", "=", "E2E-M8 Cache Check")], limit=1)
if emp.active:
    emp.write({"departure_date": datetime.date(2026, 10, 25), "active": False})
env.cr.commit()
print("E2E CHANGES APPLIED")
"""


def guard() -> None:
    for name in ("ODOO", "ERPNEXT"):
        host = urlparse(ENV.get(f"{name}_BASE_URL", "")).hostname
        instance = ENV.get(f"{name}_INSTANCE_ID", "")
        if host not in ("127.0.0.1", "localhost") or not instance.endswith("-sandbox"):
            raise SystemExit(f"refusing: {name} is not a local sandbox ({host}, {instance})")


def odoo(script: str) -> None:
    from sandbox import ODOO_DB, compose

    shell = (
        f'odoo shell -d {ODOO_DB} --db_host "$HOST" --db_user "$USER" '
        '--db_password "$PASSWORD" --no-http --log-level=warn'
    )
    run = compose("odoo", "exec", "-T", "odoo", "bash", "-c", shell, stdin=script.encode(), capture=True)
    out = run.stdout.decode(errors="replace")
    if "E2E CHANGES APPLIED" not in out:
        raise SystemExit("Odoo change failed:\n" + (out + run.stderr.decode(errors="replace"))[-1500:])
    print("odoo: changes applied")


def erpnext(phase: str) -> None:
    import seed_erpnext as s

    site = s.Site()
    kezang = site.get_list("Employee", [["first_name", "=", "Kezang"]])[0]["name"]
    leave = site.get_list(
        "Leave Application",
        [["employee", "=", kezang], ["from_date", "=", "2026-10-26"]],
        fields=("name", "docstatus"),
    )
    if phase == "a":
        if not leave:
            site.insert(
                "Leave Application",
                {
                    "employee": kezang,
                    "leave_type": "Casual Leave",
                    "from_date": "2026-10-26",
                    "to_date": "2026-10-26",
                    "posting_date": "2026-10-25",
                    "status": "Approved",
                    "docstatus": 1,
                    "company": s.COMPANY,
                    "description": TAG,
                },
            )
        bill = s.invoice(site, "Purchase Invoice", "Thunder Paper Works", "2026-10-15", "2026-10-20", 4000)
        s.pay(site, "Purchase Invoice", bill, 1500, "2026-10-16")
    else:
        for row in leave:
            if row["docstatus"] == 1:
                site.method("frappe.client.cancel", doctype="Leave Application", name=row["name"])
    print("erpnext: changes applied")


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("phase-c", "phase-d"):
        guard()
        odoo(ODOO_PHASE_C if argv[0] == "phase-c" else ODOO_PHASE_D)
        return 0
    if not argv or argv[0] not in ("phase-a", "phase-b"):
        print(__doc__)
        return 2
    guard()
    if argv[0] == "phase-a":
        odoo(ODOO_PHASE_A)
        erpnext("a")
    else:
        odoo(ODOO_PHASE_B)
        erpnext("b")
    return 0


if __name__ == "__main__":
    os.environ.pop("COMPOSE_PROJECT_NAME", None)
    sys.exit(main(sys.argv[1:]))
