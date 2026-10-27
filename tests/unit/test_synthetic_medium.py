"""The MEDIUM-scale synthetic generator: deterministic, correctly sized, internally consistent."""

import hashlib
import importlib.util
import json
import sys
from collections import defaultdict

import pytest

from druksmart_common.config import REPO_ROOT

GENERATOR = REPO_ROOT / "tests" / "fixtures" / "synthetic_medium" / "generate_medium.py"


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    spec = importlib.util.spec_from_file_location("generate_medium", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_medium"] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    first, second = tmp_path_factory.mktemp("first"), tmp_path_factory.mktemp("second")
    counts = module.write_all(first)
    module.write_all(second)
    return first, second, counts


def digest(folder):
    return {
        str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(folder.rglob("*.json"))
    }


def records(folder, system, batch, entity):
    path = folder / system / batch / f"{entity.lower().replace(' ', '_')}.json"
    response = json.loads(path.read_text("utf-8"))["response"]
    return response if system == "odoo" else response["data"]


def test_generation_is_deterministic(generated):
    first, second, _ = generated
    assert digest(first) == digest(second)


def test_medium_volume(generated):
    _, _, counts = generated
    assert 100_000 <= sum(counts.values()) <= 130_000
    assert counts["odoo/2026-10-31/hr.leave"] == 10_000
    assert counts["erpnext/2026-10-31/Leave Application"] == 10_000
    assert counts["odoo/2026-10-31/hr.employee"] == 1_000
    assert counts["erpnext/2026-10-31/Employee"] == 1_000


def test_ids_are_unique_and_do_not_collide_with_the_small_fixtures(generated):
    first, _, _ = generated
    for batch, entity, key in (
        ("2026-09-30", "account.move", "id"),
        ("2026-10-31", "hr.employee", "id"),
        ("2026-09-30", "res.partner", "id"),
    ):
        ids = [r[key] for r in records(first, "odoo", batch, entity)]
        assert len(ids) == len(set(ids)), entity
    # the verified synthetic mapping of the small fixtures (odoo partner 303) must stay unmatched
    partner_ids = {r["id"] for r in records(first, "odoo", "2026-09-30", "res.partner")}
    assert 303 not in partner_ids
    names = {r["name"] for r in records(first, "erpnext", "2026-09-30", "Customer")}
    assert "Lhaki Traders" not in names


def test_odoo_payments_reconcile_with_invoice_balances(generated):
    """total - residual == sum of payments, for every posted invoice/bill in the latest version."""
    first, _, _ = generated
    latest = {}
    for batch in ("2026-09-30", "2026-10-31"):
        for rec in records(first, "odoo", batch, "account.move"):
            latest[rec["id"]] = rec
    paid = defaultdict(float)
    for batch in ("2026-09-30", "2026-10-31"):
        for pay in records(first, "odoo", batch, "account.payment"):
            if pay["state"] == "paid":
                for move_id in pay["reconciled_invoice_ids"] + pay["reconciled_bill_ids"]:
                    paid[move_id] += pay["amount"]
    checked = 0
    for rec in latest.values():
        if rec["state"] == "posted" and rec["move_type"] in ("out_invoice", "in_invoice"):
            assert rec["amount_total"] - rec["amount_residual"] == pytest.approx(paid[rec["id"]])
            checked += 1
    assert checked > 10_000


def test_planned_invalid_records_are_present(generated):
    first, _, _ = generated
    invalid_moves = [
        r
        for batch in ("2026-09-30", "2026-10-31")
        for r in records(first, "odoo", batch, "account.move")
        if r["state"] == "posted" and not r["currency_id"]
    ]
    assert len({r["id"] for r in invalid_moves}) == 5
    leaves = records(first, "odoo", "2026-10-31", "hr.leave")
    assert sum(1 for r in leaves if r["request_date_to"] < r["request_date_from"]) == 10
