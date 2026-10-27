# SANDBOX ONLY. Loads the medium-scale SYNTHETIC plan into the local Odoo 19 sandbox through the
# real ORM (invoices are created and posted, payments are registered and reconciled).
#
# Runs inside `odoo shell` (env is predefined); load.py copies the plan to /tmp/scale_plan.json,
# prepends `PHASES = [...]` and `BATCH = n`, and pipes this file in.
# Idempotent: every record gets an external id `druksmart_scale.<ref>`; existing ones are skipped.
# Records the ERP refuses (e.g. overlapping leave) are counted and skipped, never forced.
# ruff: noqa: F821  (env, PHASES and BATCH are injected)

import datetime
import json
import time

D = datetime.date.fromisoformat
PLAN = json.load(open("/tmp/scale_plan.json"))
T0 = time.time()
NOTRACK = {
    "tracking_disable": True,
    "mail_notrack": True,
    "mail_create_nolog": True,
    "mail_create_nosubscribe": True,
    "no_reset_password": True,
}


def log(*args):
    print(f"[{time.time() - T0:7.0f}s]", *args, flush=True)


env = env(context=dict(env.context, **NOTRACK))
env.cr.execute("SET synchronous_commit TO off")  # sandbox only: faster commits
company = env.ref("base.main_company")
branch = env["res.company"].search([("name", "=", "DTG Retail - Phuentsholing")], limit=1)
companies = [company, branch]
env = env(context=dict(env.context, allowed_company_ids=[c.id for c in companies]))
btn, usd = env.ref("base.BTN"), env.ref("base.USD")
IMD = env["ir.model.data"].sudo()

existing = {r["name"]: r["res_id"] for r in IMD.search_read([("module", "=", "druksmart_scale")], ["name", "res_id"])}
log("already loaded:", len(existing), "records")


def remember(ref, record):
    IMD.create({"module": "druksmart_scale", "name": ref, "model": record._name, "res_id": record.id})
    existing[ref] = record.id


def chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def todo(items):
    return [i for i in items if i["ref"] not in existing]


# -------------------------------------------------------------------------------- partners
def load_partners():
    items = todo(PLAN["partners"])
    for part in chunks(items, BATCH):
        recs = env["res.partner"].create(
            [
                {
                    "name": p["name"],
                    "vat": p["vat"] or False,
                    "is_company": True,
                    "customer_rank": int(p["customer"]),
                    "supplier_rank": int(not p["customer"]),
                }
                for p in part
            ]
        )
        for p, rec in zip(part, recs, strict=True):
            remember(p["ref"], rec)
        env.cr.commit()
    log("partners:", len(items), "created")


# ------------------------------------------------------------------------------- employees
def departments():
    out = {}
    for ci, comp in enumerate(companies):
        for name in ("Management", "Sales", "Finance & Accounts", "Warehouse", "Operations"):
            dept = env["hr.department"].search([("name", "=", name), ("company_id", "=", comp.id)], limit=1)
            out[(ci, name)] = dept or env["hr.department"].create({"name": name, "company_id": comp.id})
    env.cr.commit()
    return out


def load_employees():
    depts = departments()
    items = todo(PLAN["employees"])
    for part in chunks(items, BATCH):
        for p in part:
            comp = companies[p["company"]]
            emp = (
                env["hr.employee"]
                .with_company(comp)
                .create(
                    {
                        "name": p["name"],
                        "company_id": comp.id,
                        "employee_type": p["type"],
                        "department_id": depts[(p["company"], p["dept"])].id if p["dept"] else False,
                    }
                )
            )
            if p["departure"]:
                emp.departure_date = D(p["departure"])
            if not p["active"]:
                emp.active = False
            remember(p["ref"], emp)
        env.cr.commit()
    log("employees:", len(items), "created")


def load_leaves():
    leave_type = env["hr.leave.type"].search([("name", "=", "Synthetic Leave")], limit=1)
    if not leave_type:
        vals = {"name": "Synthetic Leave", "company_id": False}
        if "requires_allocation" in env["hr.leave.type"]._fields:
            field = env["hr.leave.type"]._fields["requires_allocation"]
            vals["requires_allocation"] = False if field.type == "boolean" else "no"
        leave_type = env["hr.leave.type"].create(vals)
    items = todo(PLAN["leaves"])
    done = skipped = 0
    for part in chunks(items, BATCH):
        for p in part:
            emp = env["hr.employee"].with_context(active_test=False).browse(existing[p["emp"]])
            try:
                with env.cr.savepoint():
                    leave = (
                        env["hr.leave"]
                        .with_company(emp.company_id)
                        .with_context(active_test=False)
                        .create(
                            {
                                "employee_id": emp.id,
                                "holiday_status_id": leave_type.id,
                                "request_date_from": D(p["start"]),
                                "request_date_to": D(p["end"]),
                                "name": p["ref"],
                            }
                        )
                    )
                    # The workflow (approval mails, calendar events) is skipped on purpose: the
                    # state is set directly, as the first sandbox seed does for cancelled leave.
                    leave.sudo().write({"state": p["state"]})
                    remember(p["ref"], leave)
                    done += 1
            except Exception as exc:  # the ERP refuses it (overlap, archived employee, ...)
                skipped += 1
                if skipped <= 3:
                    log("leave refused:", p["ref"], str(exc).splitlines()[0][:120])
        env.cr.commit()
    log("leaves:", done, "created,", skipped, "refused by Odoo")


# ------------------------------------------------------------------------------ accounting
def load_moves():
    items = todo(PLAN["moves"])
    created = 0
    for part in chunks(items, BATCH):
        vals = []
        for m in part:
            vals.append(
                {
                    "move_type": m["type"],
                    "partner_id": existing[m["partner"]],
                    "company_id": company.id,
                    "invoice_date": D(m["date"]) if m["date"] else False,
                    "invoice_date_due": D(m["due"]) if m["due"] else False,
                    "currency_id": (usd if m["cur"] == "USD" else btn).id,
                    "ref": m["ref"],
                    "invoice_line_ids": [
                        (
                            0,
                            0,
                            {"name": "SCALE line", "quantity": 1, "price_unit": m["amount"], "tax_ids": [(6, 0, [])]},
                        )
                    ],
                }
            )
        moves = env["account.move"].with_company(company).create(vals)
        posted = moves.filtered(lambda r, st={m["ref"]: m["state"] for m in part}: st[r.ref] in ("posted", "cancel"))
        posted.action_post()
        for m, rec in zip(part, moves, strict=True):
            if m["state"] == "cancel":
                rec.button_draft()
                rec.button_cancel()
            remember(m["ref"], rec)
        created += len(part)
        env.cr.commit()
        log("moves:", created, "/", len(items))
    log("moves:", created, "created")


def load_payments():
    key = "paid:"
    items = [p for p in PLAN["payments"] if f"{key}{p['move']}:{p['date']}:{p['amount']}" not in existing]
    done = skipped = 0
    for part in chunks(items, BATCH):
        for p in part:
            move = env["account.move"].browse(existing[p["move"]])
            try:
                with env.cr.savepoint():
                    env["account.payment.register"].with_company(move.company_id).with_context(
                        active_model="account.move", active_ids=move.ids
                    ).create({"amount": p["amount"], "payment_date": D(p["date"])}).action_create_payments()
                    # one marker per payment (a document can have several)
                    IMD.create(
                        {
                            "module": "druksmart_scale",
                            "name": f"{key}{p['move']}:{p['date']}:{p['amount']}",
                            "model": "account.move",
                            "res_id": move.id,
                        }
                    )
                    done += 1
            except Exception as exc:
                skipped += 1
                if skipped <= 3:
                    log("payment refused:", p["move"], str(exc).splitlines()[0][:120])
        env.cr.commit()
        log("payments:", done, "registered,", skipped, "refused")
    log("payments:", done, "registered,", skipped, "refused by Odoo")


STEPS = {
    "partners": load_partners,
    "employees": load_employees,
    "leaves": load_leaves,
    "moves": load_moves,
    "payments": load_payments,
}
for phase in PHASES:
    started = time.time()
    STEPS[phase]()
    log(f"== {phase} finished in {time.time() - started:.0f}s")
env.cr.commit()
print("LOAD COMPLETE", flush=True)
