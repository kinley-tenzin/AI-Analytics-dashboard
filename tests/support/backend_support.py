"""Shared constants for the Django backend tests (scopes, labels, reference date)."""

from __future__ import annotations

from datetime import date

from access.scope import ACCOUNTS, HR, Scope

DEMO_BRANCH = "odoo:odoo-sandbox:1"

ADMIN = Scope("admin", ("Administrator",), frozenset({HR, ACCOUNTS}), None)
HR_ONLY = Scope("hr", ("DrukSmart HR Manager",), frozenset({HR}), None)
ACCOUNTS_ONLY = Scope("acc", ("DrukSmart Accounts Manager",), frozenset({ACCOUNTS}), None)
BRANCH = Scope(
    "branch", ("DrukSmart Branch Manager",), frozenset({HR, ACCOUNTS}), frozenset({DEMO_BRANCH})
)

LABELS = {
    "organisation": ["DTG Retail Pvt Ltd", "DTG Services Pvt Ltd"],
    "branch": [
        "Bumthang",
        "DTG Retail - Phuentsholing",
        "DTG Retail Pvt Ltd (head office)",
        "Paro",
        "Unassigned",
    ],
    "department": [
        "Accounts",
        "Administration",
        "Finance & Accounts",
        "Human Resources",
        "Management",
        "Operations",
        "Sales",
        "Unassigned",
        "Warehouse",
    ],
    "employee_category": ["employee", "intern"],
    "leave_type": ["Casual Leave", "Sick Leave", "Synthetic Leave"],
    "ledger": ["receivable", "payable"],
}
REFERENCE_DATE = date(2026, 10, 25)


def warehouse_available() -> bool:
    try:
        from kpi import warehouse

        with warehouse.connect() as conn:
            conn.execute("SELECT 1 FROM marts.kpi_approved_leave_requests LIMIT 1")
        return True
    except Exception:
        return False
