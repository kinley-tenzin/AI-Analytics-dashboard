"""The hand-calculated expected KPIs agree with an independent reference calculation.

expected_kpis.json was written by hand from the record tables. kpi_reference.py derives the
same numbers in code from the fixtures + canonical YAML rules. Agreement of the two is the
evidence that the expected results (the target for future dbt marts) are correct.
"""

import copy
import json
from datetime import date

import kpi_reference as ref
import pytest

EXPECTED = json.loads((ref.FIXTURES_DIR / "expected_kpis.json").read_text("utf-8"))
AS_OF = date(2026, 10, 31)
SNAPSHOTS = ["2026-09-30", "2026-10-31"]


def without_working(value):
    if isinstance(value, dict):
        return {k: v for k, v in value.items() if k != "working"}
    return value


# --------------------------------------------------------------------------------- HR


def test_hr01_active_headcount():
    got, want = ref.headcount(AS_OF), EXPECTED["HR-01_active_headcount"]
    assert got["by_instance"] == want["by_instance"]
    assert got["total"] == want["total"]
    assert got["by_branch"] == want["by_branch"]


def test_hr01_alternative_policy_figure():
    rows = ref.active_employees(AS_OF)
    odoo_core = [
        r for r in rows if r["system"] == "odoo" and r["category"] in ("employee", "worker")
    ]
    want = EXPECTED["HR-01_active_headcount"]["policy_alternative_odoo_employee_and_worker_only"]
    assert len(odoo_core) == want["odoo-dtg-retail"]


def test_hr02_headcount_by_department():
    assert (
        ref.headcount(AS_OF)["by_department"] == EXPECTED["HR-02_headcount_by_department"]["counts"]
    )


def test_hr03_approved_leave():
    want = EXPECTED["HR-03_approved_leave"]
    got = ref.approved_leave(date.fromisoformat(want["period"]["start"]),
                             date.fromisoformat(want["period"]["end"]))  # fmt: skip
    assert got == {"by_instance": want["by_instance"], "total": want["total"]}


def test_same_name_employees_in_two_erps_are_counted_separately():
    keys = {r["employee_key"] for r in ref.active_employees(AS_OF)}
    assert "odoo:odoo-dtg-retail:106" in keys  # Pema Wangmo (Odoo)
    assert "erpnext:erpnext-dtg-services:HR-EMP-00001" in keys  # Pema Wangmo (ERPNext)


# --------------------------------------------------------------------------- Accounts

ACCOUNT_KPIS = [
    "AC-01_outstanding_receivables",
    "AC-02_outstanding_payables",
    "AC-03_overdue_receivables",
    "AC-03_overdue_payables",
    "AC-04_receivables_ageing",
    "AC-04_payables_ageing",
]


@pytest.mark.parametrize("snapshot", SNAPSHOTS)
@pytest.mark.parametrize("kpi", ACCOUNT_KPIS)
def test_accounts_kpis(snapshot, kpi):
    got = ref.accounts_kpis(date.fromisoformat(snapshot))[kpi]
    assert got == EXPECTED["accounts"][snapshot][kpi]


@pytest.mark.parametrize("kpi", ["AC-01_receivables_by_branch", "AC-02_payables_by_branch",
                                 "unallocated_advances_received"])  # fmt: skip
def test_accounts_breakdowns_at_month_end(kpi):
    got = ref.accounts_kpis(AS_OF)[kpi]
    assert got == without_working(EXPECTED["accounts"]["2026-10-31"][kpi])


def test_receivables_by_counterparty_respects_verified_mappings_only():
    got = ref.accounts_kpis(AS_OF)["AC-01_receivables_by_counterparty"]
    want = without_working(
        EXPECTED["accounts"]["2026-10-31"]["AC-01_receivables_by_counterparty_selected"]
    )
    assert {k: got.get(k) for k in want} == want
    # the mapped members no longer appear on their own
    assert "odoo:odoo-dtg-retail:303" not in got
    assert "erpnext:erpnext-dtg-services:Lhaki Traders" not in got


def test_ageing_buckets_sum_to_outstanding():
    for snapshot in SNAPSHOTS:
        kpis = ref.accounts_kpis(date.fromisoformat(snapshot))
        for ledger, total_kpi in (("receivables", "AC-01_outstanding_receivables"),
                                  ("payables", "AC-02_outstanding_payables")):  # fmt: skip
            for inst, buckets in kpis[f"AC-04_{ledger}_ageing"].items():
                assert sum(buckets.values()) == pytest.approx(kpis[total_kpi][inst])


def test_source_payment_statuses_agree_with_derived_status():
    for snapshot in SNAPSHOTS:
        assert ref.status_inconsistencies(date.fromisoformat(snapshot)) == []


def test_payments_reconcile_with_document_balances():
    for snapshot in SNAPSHOTS:
        assert ref.payment_reconciliation_differences(date.fromisoformat(snapshot)) == []


# ------------------------------------------------------- the checks can actually fail


def _mutated(monkeypatch, system, entity, source_id, **changes):
    """Patch the in-memory fixtures so one record differs from the committed data."""
    fixtures = copy.deepcopy(list(ref.load_fixtures()))
    pk = "id" if system == "odoo" else "name"
    for f in fixtures:
        if f.meta["source_system"] == system and f.meta["entity"] == entity:
            for rec in f.records:
                if str(rec[pk]) == source_id:
                    rec.update(changes)
    monkeypatch.setattr(ref, "load_fixtures", lambda: tuple(fixtures))


def test_mutation_changes_kpi_and_breaks_reconciliation(monkeypatch):
    # ERPNext SINV-00001 outstanding wrongly reported as 12000 instead of 10000
    _mutated(
        monkeypatch, "erpnext", "Sales Invoice", "ACC-SINV-2026-00001", outstanding_amount=12000.0
    )
    kpis = ref.accounts_kpis(AS_OF)
    assert (
        kpis["AC-01_outstanding_receivables"]
        != EXPECTED["accounts"]["2026-10-31"]["AC-01_outstanding_receivables"]
    )
    assert any("ACC-SINV-2026-00001" in p for p in ref.payment_reconciliation_differences(AS_OF))


def test_mutation_inconsistent_source_status_is_detected(monkeypatch):
    _mutated(monkeypatch, "odoo", "account.move", "408", payment_state="paid")
    assert ref.status_inconsistencies(AS_OF) == ["odoo:odoo-dtg-retail:408: source paid"]


def test_mutation_unsubmitted_leave_is_not_approved(monkeypatch):
    _mutated(monkeypatch, "erpnext", "Leave Application", "HR-LAP-2026-00001", docstatus=0)
    got = ref.approved_leave(date(2026, 10, 1), AS_OF)["by_instance"]["erpnext-dtg-services"]
    assert got == {"requests": 2, "days": 2.5, "employees": 2}
