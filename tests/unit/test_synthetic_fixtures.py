"""Fixture tests: the synthetic datasets obey the contracts and contain the intended edge cases."""

import json
from datetime import datetime

import pytest
import yaml
from generate_fixtures_loader import generator
from kpi_reference import FIXTURES_DIR, canonical, load_fixtures, rejected_ids

from druksmart_common.config import REPO_ROOT
from druksmart_common.contracts import (
    build_raw_record,
    duplicate_record_keys,
    has_errors,
    load_source_contract,
    validate_record,
)

FIXTURES = load_fixtures()
EXPECTED = json.loads((FIXTURES_DIR / "expected_kpis.json").read_text("utf-8"))


def fixture_id(f):
    return f"{f.meta['source_system']}/{f.path.parent.name}/{f.meta['entity']}"


def raw_records(f):
    contract = load_source_contract(f.meta["source_system"])
    return [
        build_raw_record(
            contract, f.meta["entity"], rec,
            source_instance=f.meta["source_instance"],
            extraction_batch_id=f.meta["extraction_batch_id"],
            extracted_at=f.extracted_at,
            instance_timezone=f.meta.get("instance_timezone"),
        )
        for rec in f.records
    ]  # fmt: skip


def test_fixture_set_is_complete():
    assert len(FIXTURES) == 22
    entities = {(f.meta["source_system"], f.meta["entity"]) for f in FIXTURES}
    for system in ("odoo", "erpnext"):
        contract_entities = set(load_source_contract(system).entities)
        covered = {e for s, e in entities if s == system}
        # every contracted entity except deferred ones has fixture data
        assert contract_entities - covered <= {"account.partial.reconcile"}


@pytest.mark.parametrize("fixture", FIXTURES, ids=fixture_id)
def test_every_fixture_is_marked_synthetic(fixture):
    assert fixture.meta["synthetic"] is True
    assert "SYNTHETIC" in fixture.meta["notice"]


@pytest.mark.parametrize("fixture", FIXTURES, ids=fixture_id)
def test_response_shape_matches_the_api(fixture):
    body = json.loads(fixture.path.read_text("utf-8"))["response"]
    if fixture.meta["source_system"] == "odoo":
        assert isinstance(body, list)  # JSON-2 returns a bare array
    else:
        assert isinstance(body, dict) and isinstance(body["data"], list)  # Frappe {"data": [...]}


@pytest.mark.parametrize("fixture", FIXTURES, ids=fixture_id)
def test_source_identity_is_unique_within_each_batch(fixture):
    assert duplicate_record_keys(raw_records(fixture)) == []


@pytest.mark.parametrize("fixture", FIXTURES, ids=fixture_id)
def test_modification_times_respect_the_extraction_window(fixture):
    extracted = fixture.extracted_at
    checkpoint = fixture.meta["checkpoint_utc"]
    for raw in raw_records(fixture):
        assert raw.source_modified_at <= extracted, raw.record_key
        if fixture.meta["extraction_mode"] == "incremental":
            # incremental batches contain only records changed since the previous run
            assert raw.source_modified_at > datetime.fromisoformat(checkpoint), raw.record_key


def test_only_the_intended_records_break_the_contract():
    expected = {s: v for s, v in EXPECTED["rejected_records"].items() if s != "working"}
    assert rejected_ids() == expected


def test_valid_records_produce_no_unexpected_warnings():
    """Warnings must come only from the deliberate 'missing value' edge cases."""
    warned = set()
    for f in FIXTURES:
        contract = load_source_contract(f.meta["source_system"])
        pk = contract.entity(f.meta["entity"]).primary_key
        for rec in f.records:
            issues = validate_record(contract, f.meta["entity"], rec)
            if not has_errors(issues):
                warned |= {(f.meta["entity"], str(rec[pk]), i.field) for i in issues}
    assert warned == {
        ("hr.employee", "110", "department_id"),
        ("account.move", "404", "name"),
        ("account.move", "404", "invoice_date"),
        ("account.move", "404", "invoice_date_due"),
        ("account.move", "454", "name"),
        ("account.move", "454", "invoice_date"),
        ("account.move", "454", "invoice_date_due"),
        ("Employee", "HR-EMP-00009", "branch"),
        ("Employee", "HR-EMP-00010", "department"),
    }


def test_fixtures_cover_required_edge_cases():
    def values(system, entity, field):
        return {
            r[field] if not isinstance(r[field], list) else tuple(r[field])
            for f in FIXTURES
            if f.meta["source_system"] == system and f.meta["entity"] == entity
            for r in f.records
        }

    assert values("odoo", "hr.employee", "active") == {True, False}
    assert {"validate", "confirm", "refuse", "validate1", "cancel"} <= values(
        "odoo", "hr.leave", "state"
    )
    assert {"Active", "Left", "Suspended", "Inactive"} <= values("erpnext", "Employee", "status")
    assert {"draft", "posted", "cancel"} <= values("odoo", "account.move", "state")
    assert {"not_paid", "partial", "paid", "reversed"} <= values(
        "odoo", "account.move", "payment_state"
    )
    assert {"out_invoice", "out_refund", "in_invoice", "in_refund"} <= values(
        "odoo", "account.move", "move_type"
    )
    assert {0, 1, 2} <= values("erpnext", "Sales Invoice", "docstatus")
    assert {0, 1} == values("erpnext", "Sales Invoice", "is_return")
    assert {"BTN", "USD", "INR"} <= values("erpnext", "Sales Invoice", "currency")
    assert len(values("odoo", "res.company", "id")) == 2  # head office + branch
    assert len(values("erpnext", "Branch", "name")) == 2


def test_generator_output_matches_committed_fixtures():
    """The committed JSON files are exactly what the generator produces (no hand edits)."""
    for path, text in generator().render_all().items():
        assert path.read_text("utf-8") == text, f"{path} differs; re-run generate_fixtures.py"


# ------------------------------------------------------------- mapping completeness


def test_every_source_status_value_has_a_canonical_mapping():
    odoo, erp = load_source_contract("odoo"), load_source_contract("erpnext")
    hr, acc = canonical("hr")["entities"], canonical("accounts")["entities"]

    leave_rules = hr["leave_request"]["status_rules"]
    assert set(odoo.entity("hr.leave").fields["state"].values) == set(
        leave_rules["odoo"]["status_map"]
    )
    assert set(erp.entity("Leave Application").fields["status"].values) == set(
        leave_rules["erpnext"]["docstatus_1_status_map"]
    )
    assert set(erp.entity("Employee").fields["status"].values) == set(
        hr["employee"]["status_rules"]["erpnext"]["status_map"]
    )

    doc = acc["accounting_document"]
    assert set(odoo.entity("account.move").fields["state"].values) == set(doc["state_map"]["odoo"])
    for doctype in ("Sales Invoice", "Purchase Invoice"):
        assert set(erp.entity(doctype).fields["docstatus"].values) == set(
            doc["state_map"]["erpnext_docstatus"]
        )
    extracted_types = {"out_invoice", "out_refund", "in_invoice", "in_refund"}
    assert set(doc["type_map"]["odoo"]) == extracted_types

    pay = acc["payment"]
    assert set(odoo.entity("account.payment").fields["state"].values) == set(
        pay["state_map"]["odoo"]
    )
    assert set(erp.entity("Payment Entry").fields["payment_type"].values) == set(
        pay["direction_map"]["erpnext"]
    )


def test_verified_mappings_reference_existing_records_and_have_evidence():
    doc = yaml.safe_load((REPO_ROOT / "contracts/mappings/entity_mappings.yaml").read_text("utf-8"))
    existing = set()
    for f in FIXTURES:
        pk = load_source_contract(f.meta["source_system"]).entity(f.meta["entity"]).primary_key
        existing |= {
            f"{f.meta['source_system']}:{f.meta['source_instance']}:{r[pk]}" for r in f.records
        }
    for mapping in doc["mappings"]:
        assert mapping["evidence"] and mapping["verified_by"] and mapping["verified_on"]
        systems = {m.split(":")[0] for m in mapping["members"]}
        assert len(systems) == len(mapping["members"]), "one member per source system"
        for member in mapping["members"]:
            assert member in existing, member
