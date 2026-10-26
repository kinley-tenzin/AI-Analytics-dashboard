# SANDBOX ONLY. Seeds SYNTHETIC data into the local Odoo 19 sandbox and creates the
# read-only bot user + API key used by the DrukSmart connector.
#
# Runs inside `odoo shell`, where `env` is predefined:
#   docker compose ... exec -T odoo odoo shell -d druksmart_sandbox --no-http < seed_odoo.py
# The bot's API key is written to /var/lib/odoo/.druksmart_bot_key (never printed).
# Idempotent: data is created only once; the API key is regenerated on every run.
# ruff: noqa: F821  (env is injected by odoo shell)

import datetime

TODAY = datetime.date(2026, 10, 22)
D = datetime.date.fromisoformat
log = print


def first(model, domain, values):
    record = env[model].with_context(active_test=False).search(domain, limit=1)
    return record or env[model].create(values)


def m2m_field(model):
    # Odoo 19 renamed res.users.groups_id -> group_ids
    return "group_ids" if "group_ids" in env[model]._fields else "groups_id"


# --------------------------------------------------------------- company + accounting
company = env.ref("base.main_company")
btn, usd, bhutan = env.ref("base.BTN"), env.ref("base.USD"), env.ref("base.bt")
btn.active = usd.active = True
# Installing `account` already loads a chart of accounts; the company currency can still be
# changed as long as no journal items exist (true on a fresh sandbox).
company.write({"name": "DTG Retail Pvt Ltd", "country_id": bhutan.id})
if company.currency_id != btn:
    if env["account.move.line"].search_count([("company_id", "=", company.id)]):
        raise SystemExit(
            "company has journal items; destroy and re-create the sandbox to change currency"
        )
    company.currency_id = btn
if not company.chart_template:
    env["account.chart.template"].try_loading("generic_coa", company=company, install_demo=False)
log("company:", company.name, company.currency_id.name, "chart:", company.chart_template)
env["res.currency.rate"].search(
    [("currency_id", "=", usd.id), ("company_id", "=", company.id)]
).unlink()
env["res.currency.rate"].create(
    {
        "currency_id": usd.id,
        "company_id": company.id,
        "name": D("2026-01-01"),
        "inverse_company_rate": 84.0,
    }
)
branch = first(
    "res.company",
    [("name", "=", "DTG Retail - Phuentsholing")],
    {"name": "DTG Retail - Phuentsholing", "parent_id": company.id, "country_id": bhutan.id},
)
companies = company | branch
env = env(context=dict(env.context, allowed_company_ids=companies.ids))
# Apply pending company changes now: Odoo forbids country changes once time off exists.
env.flush_all()

already_seeded = bool(env["hr.department"].search([("name", "=", "Warehouse")]))

if not already_seeded:
    # ------------------------------------------------------------------------ HR
    depts = {
        "Management": first(
            "hr.department",
            [("name", "=", "Management")],
            {"name": "Management", "company_id": company.id},
        ),
        "Sales HO": env["hr.department"].create({"name": "Sales", "company_id": company.id}),
        "Finance": env["hr.department"].create(
            {"name": "Finance & Accounts", "company_id": company.id}
        ),
        "Warehouse": env["hr.department"].create({"name": "Warehouse", "company_id": branch.id}),
        "Sales PL": env["hr.department"].create({"name": "Sales", "company_id": branch.id}),
    }
    rows = [
        ("Karma Dorji", company, "Management", "employee", None, True),
        ("Sonam Choden", company, "Sales HO", "employee", None, True),
        ("Tshering Wangdi", company, "Sales HO", "employee", "2026-11-15", True),
        ("Dechen Pelmo", company, "Finance", "employee", None, True),
        ("Ugyen Tenzin", branch, "Warehouse", "employee", None, True),
        ("Pema Wangmo", branch, "Sales PL", "employee", None, True),
        ("Kinga Lhamo", branch, "Sales PL", "contractor", None, True),
        ("Jigme Namgyel", company, "Sales HO", "employee", "2026-08-15", False),
        ("Thinley Norbu", company, None, "employee", None, True),
        ("Chimi Yangzom", company, "Finance", "trainee", None, True),
    ]
    employees = {}
    for name, comp, dept, etype, departure, active in rows:
        emp = (
            env["hr.employee"]
            .with_company(comp)
            .create(
                {
                    "name": name,
                    "company_id": comp.id,
                    "employee_type": etype,
                    "department_id": depts[dept].id if dept else False,
                }
            )
        )
        if departure:
            emp.departure_date = D(departure)
        if not active:
            emp.active = False
        employees[name] = emp
    log("employees:", len(employees))

    leave_type_vals = {"name": "Synthetic Leave", "company_id": False}
    if "requires_allocation" in env["hr.leave.type"]._fields:
        field = env["hr.leave.type"]._fields["requires_allocation"]
        leave_type_vals["requires_allocation"] = False if field.type == "boolean" else "no"
    leave_type = env["hr.leave.type"].create(leave_type_vals)
    leaves = [
        ("Karma Dorji", "2026-10-05", "2026-10-07", "validate"),
        ("Sonam Choden", "2026-10-12", "2026-10-12", "validate"),
        ("Dechen Pelmo", "2026-10-20", "2026-10-22", "confirm"),
        ("Ugyen Tenzin", "2026-10-14", "2026-10-15", "refuse"),
        ("Sonam Choden", "2026-10-27", "2026-10-28", "validate"),
        ("Tshering Wangdi", "2026-10-01", "2026-10-02", "cancel"),
    ]
    for name, start, end, state in leaves:
        leave = (
            env["hr.leave"]
            .with_company(employees[name].company_id)
            .create(
                {
                    "employee_id": employees[name].id,
                    "holiday_status_id": leave_type.id,
                    "request_date_from": D(start),
                    "request_date_to": D(end),
                }
            )
        )
        if state == "validate":
            leave.sudo().action_approve()
            if leave.state != "validate":
                leave.sudo().action_validate()
        elif state == "refuse":
            leave.sudo().action_refuse()
        elif state == "cancel":
            leave.sudo().write({"state": "cancel"})
    log("leaves:", env["hr.leave"].search_count([]))

    # ------------------------------------------------------------------ Accounts
    partners = {}
    for name, vat, kind in [
        ("Norbu Hardware", "TPN-NRB-2001", "customer"),
        ("Zangpo Builders", "TPN-ZNG-3001", "customer"),
        ("Lhaki Traders", "TPN-LHK-1001", "customer"),
        ("Himalayan Supplies Co", "TPN-HMS-4001", "supplier"),
        ("Global Parts Ltd", False, "supplier"),
    ]:
        partners[name] = env["res.partner"].create(
            {
                "name": name,
                "vat": vat,
                "is_company": True,
                "customer_rank": int(kind == "customer"),
                "supplier_rank": int(kind == "supplier"),
            }
        )

    def move(move_type, partner, inv_date, due, amount, currency=btn, comp=company, post=True):
        m = (
            env["account.move"]
            .with_company(comp)
            .create(
                {
                    "move_type": move_type,
                    "partner_id": partners[partner].id,
                    "company_id": comp.id,
                    "invoice_date": D(inv_date),
                    "invoice_date_due": D(due),
                    "currency_id": currency.id,
                    "invoice_line_ids": [
                        (
                            0,
                            0,
                            {
                                "name": "SYNTHETIC line",
                                "quantity": 1,
                                "price_unit": amount,
                                "tax_ids": [(6, 0, [])],
                            },
                        )
                    ],
                }
            )
        )
        if post:
            m.action_post()
        return m

    def pay(m, amount, day):
        env["account.payment.register"].with_company(m.company_id).with_context(
            active_model="account.move", active_ids=m.ids
        ).create({"amount": amount, "payment_date": D(day)}).action_create_payments()

    pay(
        move("out_invoice", "Norbu Hardware", "2026-08-05", "2026-09-04", 10000),
        10000,
        "2026-08-25",
    )
    pay(
        move("out_invoice", "Zangpo Builders", "2026-08-20", "2026-09-19", 20000),
        12000,
        "2026-10-08",
    )
    move("out_invoice", "Lhaki Traders", "2026-09-15", "2026-10-15", 1000, currency=usd)
    move("out_invoice", "Norbu Hardware", "2026-06-01", "2026-07-01", 7500)
    # Branch-company invoices need branch accounting setup (fiscal positions/journals) that this
    # sandbox does not configure; the invoice is booked on the head office instead.
    move("out_invoice", "Zangpo Builders", "2026-10-01", "2026-10-01", 4000)
    move("out_refund", "Zangpo Builders", "2026-09-25", "2026-09-25", 2000)
    move("out_invoice", "Norbu Hardware", "2026-10-03", "2026-11-02", 8000, post=False)  # draft
    cancelled = move("out_invoice", "Zangpo Builders", "2026-09-01", "2026-10-01", 5000)
    cancelled.button_draft()
    cancelled.button_cancel()
    pay(
        move("in_invoice", "Himalayan Supplies Co", "2026-08-10", "2026-09-09", 12000),
        12000,
        "2026-10-15",
    )
    pay(
        move("in_invoice", "Global Parts Ltd", "2026-09-12", "2026-10-12", 500, currency=usd),
        200,
        "2026-10-25",
    )
    move("in_refund", "Himalayan Supplies Co", "2026-10-22", "2026-10-22", 1000)
    log(
        "invoices:",
        env["account.move"].search_count([("move_type", "!=", "entry")]),
        "payments:",
        env["account.payment"].search_count([]),
    )

# --------------------------------------------------------------- read-only bot user
groups = [
    env.ref(x)
    for x in (
        "base.group_user",
        "hr.group_hr_user",
        "hr_holidays.group_hr_holidays_user",
        "account.group_account_readonly",
    )
]
bot = env["res.users"].with_context(active_test=False).search([("login", "=", "druksmart_bot")])
if not bot:
    bot = (
        env["res.users"]
        .with_context(no_reset_password=True)
        .create(
            {
                "name": "DrukSmart Read-Only Bot",
                "login": "druksmart_bot",
                "company_id": company.id,
                "company_ids": [(6, 0, companies.ids)],
                m2m_field("res.users"): [(6, 0, [g.id for g in groups])],
            }
        )
    )
# Replace Odoo's default admin password with the one from .env (ADMIN_PASSWORD is prepended
# to this script by sandbox.py and never printed).
env.ref("base.user_admin").password = ADMIN_PASSWORD

apikeys = env["res.users.apikeys"].with_user(bot)
apikeys.sudo().search([("user_id", "=", bot.id)]).unlink()
key = apikeys._generate(
    "rpc", "druksmart-sandbox", datetime.datetime.now() + datetime.timedelta(days=89)
)
with open("/var/lib/odoo/.druksmart_bot_key", "w") as fh:
    fh.write(key)
log("bot user:", bot.login, "groups:", [g.full_name for g in getattr(bot, m2m_field("res.users"))])
env.cr.commit()
log("SEED COMPLETE")
