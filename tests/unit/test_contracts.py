"""Unit tests for the contract validator and raw-record envelope (no database, no fixtures)."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from druksmart_common.contracts import (
    build_raw_record,
    duplicate_record_keys,
    has_errors,
    load_source_contract,
    payload_sha256,
    validate_record,
)

ODOO = load_source_contract("odoo")
ERPNEXT = load_source_contract("erpnext")
EXTRACTED = datetime(2026, 10, 31, 17, 30, tzinfo=UTC)


def odoo_employee(**overrides):
    rec = {
        "id": 101,
        "name": "Test Employee",
        "active": True,
        "company_id": [1, "Test Co"],
        "department_id": [2, "Sales"],
        "employee_type": "employee",
        "departure_date": False,
        "parent_id": False,
        "write_date": "2026-10-01 04:00:00",
    }
    return rec | overrides


def erpnext_employee(**overrides):
    rec = {
        "name": "HR-EMP-00001",
        "employee_name": "Test Employee",
        "status": "Active",
        "company": "Test Co",
        "department": "Sales - TC",
        "branch": "Paro",
        "date_of_joining": "2024-01-01",
        "relieving_date": None,
        "modified": "2026-10-01 10:00:00.000000",
    }
    return rec | overrides


def errors(issues):
    return {(i.field, i.severity) for i in issues}


# ---------------------------------------------------------------- valid payloads


def test_valid_odoo_and_erpnext_payloads_pass():
    assert validate_record(ODOO, "hr.employee", odoo_employee()) == []
    assert validate_record(ERPNEXT, "Employee", erpnext_employee()) == []


def test_extra_fields_are_tolerated():
    assert validate_record(ODOO, "hr.employee", odoo_employee(new_v20_field="x")) == []


# ------------------------------------------------------------ required / missing


@pytest.mark.parametrize("missing", ["id", "name", "company_id", "employee_type", "write_date"])
def test_odoo_required_field_missing_is_error(missing):
    rec = odoo_employee()
    del rec[missing]
    assert (missing, "error") in errors(validate_record(ODOO, "hr.employee", rec))


def test_odoo_false_means_empty_but_not_for_booleans():
    # department_id=false -> 'expected' field missing -> warning only
    issues = validate_record(ODOO, "hr.employee", odoo_employee(department_id=False))
    assert errors(issues) == {("department_id", "warning")}
    # active=false is a real boolean value, not 'missing'
    assert validate_record(ODOO, "hr.employee", odoo_employee(active=False)) == []


def test_odoo_zero_is_not_treated_as_empty():
    partner = {"id": 1, "name": "P", "vat": False, "customer_rank": 0, "supplier_rank": 0,
               "write_date": "2026-01-01 00:00:00"}  # fmt: skip
    assert validate_record(ODOO, "res.partner", partner) == []


@pytest.mark.parametrize("empty", [None, ""])
def test_erpnext_null_and_empty_string_are_empty(empty):
    issues = validate_record(ERPNEXT, "Employee", erpnext_employee(company=empty))
    assert ("company", "error") in errors(issues)


def test_erpnext_check_zero_is_a_value():
    dept = {
        "name": "Sales - TC",
        "department_name": "Sales",
        "parent_department": None,
        "company": "Test Co",
        "is_group": 0,
        "disabled": 0,
        "modified": "2026-01-01 10:00:00",
    }
    assert validate_record(ERPNEXT, "Department", dept) == []


# ------------------------------------------------------------------ type handling


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("id", "101"),  # integer expected
        ("id", True),  # bool is not an integer
        ("company_id", 1),  # many2one must be [id, name]
        ("company_id", [1]),
        ("employee_type", "intern"),  # not an allowed selection value
        ("departure_date", "31/10/2026"),  # wrong date format
        ("write_date", "2026-10-01T04:00:00Z"),  # wrong datetime format
        ("active", "yes"),  # boolean expected
    ],
)
def test_odoo_wrong_types_are_rejected(field, bad_value):
    issues = validate_record(ODOO, "hr.employee", odoo_employee(**{field: bad_value}))
    assert (field, "error") in errors(issues)
    assert has_errors(issues)


def test_erpnext_datetime_with_or_without_microseconds():
    for modified in ("2026-10-01 10:00:00.123456", "2026-10-01 10:00:00"):
        assert validate_record(ERPNEXT, "Employee", erpnext_employee(modified=modified)) == []


def test_erpnext_docstatus_must_be_0_1_2():
    leave = {
        "name": "HR-LAP-2026-00001", "employee": "HR-EMP-00001", "leave_type": "Casual Leave",
        "status": "Approved", "docstatus": 3, "from_date": "2026-10-01", "to_date": "2026-10-02",
        "total_leave_days": 2.0, "half_day": 0, "company": "Test Co", "department": None,
        "posting_date": "2026-10-01", "modified": "2026-10-01 10:00:00.000000",
    }  # fmt: skip
    assert ("docstatus", "error") in errors(validate_record(ERPNEXT, "Leave Application", leave))


def test_date_order_check():
    rec = erpnext_employee(date_of_joining="2026-05-01", relieving_date="2026-04-01", status="Left")
    issues = validate_record(ERPNEXT, "Employee", rec)
    assert ("date_of_joining..relieving_date", "error") in errors(issues)


def test_child_table_rows_are_validated():
    pe = {
        "name": "ACC-PAY-2026-00001", "payment_type": "Receive", "party_type": "Customer",
        "party": "C1", "posting_date": "2026-10-01", "paid_amount": 100.0,
        "paid_from_account_currency": "BTN", "unallocated_amount": 0.0, "docstatus": 1,
        "references": [{"reference_doctype": "Sales Invoice", "reference_name": "S1",
                        "allocated_amount": "100", "due_date": None}],
        "modified": "2026-10-01 10:00:00.000000",
    }  # fmt: skip
    issues = validate_record(ERPNEXT, "Payment Entry", pe)
    assert errors(issues) == {("references[0].allocated_amount", "error")}


def test_non_object_payload_is_rejected():
    assert has_errors(validate_record(ODOO, "hr.employee", ["not", "a", "record"]))


# --------------------------------------------------------------- raw record envelope


def test_raw_record_carries_provenance_and_string_id():
    raw = build_raw_record(ODOO, "hr.employee", odoo_employee(), source_instance="odoo-a",
                           extraction_batch_id="b1", extracted_at=EXTRACTED)  # fmt: skip
    assert raw.record_key == ("odoo", "odoo-a", "hr.employee", "101")
    assert raw.contract_version == ODOO.contract_version
    assert raw.source_modified_at == datetime(2026, 10, 1, 4, 0, tzinfo=UTC)


def test_erpnext_local_modified_time_is_converted_to_utc():
    raw = build_raw_record(ERPNEXT, "Employee", erpnext_employee(), source_instance="erp-a",
                           extraction_batch_id="b1", extracted_at=EXTRACTED)  # fmt: skip
    # 10:00 in Asia/Thimphu (UTC+6) is 04:00 UTC
    assert raw.source_modified_at == datetime(2026, 10, 1, 4, 0, tzinfo=UTC)


def test_extracted_at_must_be_timezone_aware_and_is_stored_in_utc():
    with pytest.raises(ValueError):
        build_raw_record(ODOO, "hr.employee", odoo_employee(), source_instance="odoo-a",
                         extraction_batch_id="b1", extracted_at=datetime(2026, 10, 31))  # fmt: skip
    bhutan = timezone(timedelta(hours=6))
    raw = build_raw_record(ODOO, "hr.employee", odoo_employee(), source_instance="odoo-a",
                           extraction_batch_id="b1",
                           extracted_at=datetime(2026, 10, 31, 23, 30, tzinfo=bhutan))  # fmt: skip
    assert raw.extracted_at == EXTRACTED


def test_missing_primary_key_cannot_build_raw_record():
    with pytest.raises(ValueError):
        build_raw_record(ODOO, "hr.employee", odoo_employee(id=False), source_instance="odoo-a",
                         extraction_batch_id="b1", extracted_at=EXTRACTED)  # fmt: skip


def test_payload_hash_ignores_key_order_but_detects_changes():
    a = {"id": 1, "name": "X"}
    assert payload_sha256(a) == payload_sha256({"name": "X", "id": 1})
    assert payload_sha256(a) != payload_sha256({"id": 1, "name": "Y"})


def test_duplicate_keys_within_a_batch_are_detected():
    def raw(rec):
        return build_raw_record(ODOO, "hr.employee", rec, source_instance="odoo-a",
                                extraction_batch_id="b1", extracted_at=EXTRACTED)  # fmt: skip

    batch = [raw(odoo_employee()), raw(odoo_employee(id=102)), raw(odoo_employee(name="changed"))]
    assert duplicate_record_keys(batch) == [("odoo", "odoo-a", "hr.employee", "101")]


def test_same_source_id_in_different_systems_or_instances_is_not_a_duplicate():
    odoo_a = build_raw_record(ODOO, "hr.employee", odoo_employee(id=7), source_instance="odoo-a",
                              extraction_batch_id="b1", extracted_at=EXTRACTED)  # fmt: skip
    odoo_b = build_raw_record(ODOO, "hr.employee", odoo_employee(id=7), source_instance="odoo-b",
                              extraction_batch_id="b1", extracted_at=EXTRACTED)  # fmt: skip
    erp = build_raw_record(ERPNEXT, "Employee", erpnext_employee(name="7"),
                           source_instance="odoo-a", extraction_batch_id="b1",
                           extracted_at=EXTRACTED)  # fmt: skip
    assert odoo_a.source_id == odoo_b.source_id == erp.source_id == "7"
    assert duplicate_record_keys([odoo_a, odoo_b, erp]) == []
