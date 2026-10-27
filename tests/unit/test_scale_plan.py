"""The ERP load plan (sandboxes/scale/plan.py): slices keep every reference intact."""

import importlib.util
import sys

import pytest

from druksmart_common.config import REPO_ROOT

SCALE = REPO_ROOT / "infrastructure" / "sandboxes" / "scale" / "plan.py"
GENERATOR = REPO_ROOT / "tests" / "fixtures" / "synthetic_medium" / "generate_medium.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def plans(tmp_path_factory):
    fixtures = tmp_path_factory.mktemp("medium")
    load("generate_medium_for_plan", GENERATOR).write_all(fixtures)
    plan = load("scale_plan", SCALE)
    plan.FIXTURES = fixtures
    return (
        plan.odoo_plan(0.05),
        plan.erpnext_plan(0.05),
        plan.odoo_plan(1.0),
        plan.erpnext_plan(1.0),
    )


def test_slice_is_about_five_percent(plans):
    odoo, erpnext, odoo_all, erpnext_all = plans
    assert 0.03 <= len(odoo["moves"]) / len(odoo_all["moves"]) <= 0.07
    assert 0.03 <= len(erpnext["invoices"]) / len(erpnext_all["invoices"]) <= 0.07


def test_odoo_references_stay_intact(plans):
    odoo = plans[0]
    partners = {p["ref"] for p in odoo["partners"]}
    employees = {e["ref"] for e in odoo["employees"]}
    moves = {m["ref"] for m in odoo["moves"]}
    assert all(m["partner"] in partners for m in odoo["moves"])
    assert all(p["move"] in moves for p in odoo["payments"])
    assert all(lv["emp"] in employees for lv in odoo["leaves"])


def test_erpnext_references_stay_intact(plans):
    erpnext = plans[1]
    parties = {c["name"] for c in erpnext["customers"]} | {s["name"] for s in erpnext["suppliers"]}
    invoices = {i["ref"] for i in erpnext["invoices"]}
    employees = {e["ref"] for e in erpnext["employees"]}
    assert all(i["party"] in parties for i in erpnext["invoices"])
    assert all(p["against"] in invoices for p in erpnext["payments"])
    assert all(r["against"] in invoices for r in erpnext["returns"])
    assert all(lv["emp"] in employees for lv in erpnext["leaves"])


def test_records_the_erps_would_refuse_are_dropped(plans):
    odoo_all, erpnext_all = plans[2], plans[3]
    assert {e["type"] for e in odoo_all["employees"]} <= {"employee", "contractor", "trainee"}
    assert all(m["cur"] in ("BTN", "USD") for m in odoo_all["moves"])
    assert all(i["party"] for i in erpnext_all["invoices"])
    assert all(lv["to"] >= lv["from"] for lv in erpnext_all["leaves"])
