"""ERPNext/Frappe REST adapter against a controlled fake server (NOT proof of live connectivity)."""

import json
from datetime import UTC, date, datetime

import pytest
from fake_erp import ERP_KEY, ERP_SECRET, FakeFrappe, fixture_records

from connectors.base import (
    AuthenticationError,
    ExtractionWindow,
    InvalidRequestError,
    RetryExhaustedError,
)
from connectors.config import SourceConfig
from connectors.erpnext import ERPNextConnector
from connectors.http import RetryPolicy
from druksmart_common.contracts import load_source_contract, validate_record

UNTIL = datetime(2026, 10, 31, 17, 30, tzinfo=UTC)
FULL = ExtractionWindow(None, UNTIL)


def make(fake, secret=ERP_SECRET, page_size=200):
    config = SourceConfig(
        "erpnext",
        "erp-test",
        "http://erp.test",
        api_key=ERP_KEY,
        api_secret=secret,
        timezone="Asia/Thimphu",
        page_size=page_size,
    )
    return ERPNextConnector(
        config,
        transport=fake.transport(),
        retry=RetryPolicy(max_attempts=3, base_delay=0.01),
        sleep=lambda s: None,
    )


@pytest.fixture
def fake():
    return FakeFrappe(fixture_records("erpnext", date(2026, 10, 31)))


def test_check_connection_reports_versions_and_hrms(fake):
    report = make(fake).check_connection()
    assert report.ok and report.user == "druksmart.readonly@example.com"
    assert report.server_version == "16.52.0" and "hrms 16.51.0 installed" in report.details
    assert fake.requests[0].headers["Authorization"] == f"token {ERP_KEY}:{ERP_SECRET}"


def test_missing_hrms_is_reported():
    fake = FakeFrappe({}, versions={"frappe": "16.40.0", "erpnext": "16.52.0"})
    assert "hrms app NOT installed" in make(fake).check_connection().details


def test_authentication_failure(fake):
    connector = make(fake, secret="wrong")
    assert connector.check_connection().authenticated is False
    with pytest.raises(AuthenticationError):
        list(connector.fetch_pages("Employee", FULL))


def test_page_size_is_always_explicit_and_keyset_paginates(fake):
    pages = list(make(fake, page_size=5).fetch_pages("Employee", FULL))
    assert [len(p.records) for p in pages] == [5, 5, 3]
    params = fake.list_params()
    assert all(p["limit_page_length"] == "5" and p["limit_start"] == "0" for p in params)
    assert ["name", ">", "HR-EMP-00005"] in json.loads(params[1]["filters"])
    assert params[0]["order_by"] == "name asc"


def test_default_page_size_would_truncate_without_explicit_limit(fake):
    # The fake mirrors Frappe's default of 20 rows when limit_page_length is absent.
    fake.records["Customer"] = [
        {"name": f"C{i:03d}", "modified": "2026-01-01 00:00:00.000000"} for i in range(30)
    ]
    import httpx

    response = fake.handle(
        httpx.Request(
            "GET",
            "http://erp.test/api/resource/Customer",
            headers={"Authorization": f"token {ERP_KEY}:{ERP_SECRET}"},
        )
    )
    assert len(response.json()["data"]) == 20
    pages = list(make(fake).fetch_pages("Customer", FULL))
    assert sum(len(p.records) for p in pages) == 30


def test_incremental_filters_use_site_local_time(fake):
    after = datetime(2026, 9, 30, 17, 20, tzinfo=UTC)  # 23:20 in Asia/Thimphu
    pages = list(make(fake).fetch_pages("Sales Invoice", ExtractionWindow(after, UNTIL)))
    filters = json.loads(fake.list_params()[0]["filters"])
    assert ["modified", ">", "2026-09-30 23:20:00.000000"] in filters
    assert ["modified", "<=", "2026-10-31 23:30:00.000000"] in filters
    names = {r["name"] for p in pages for r in p.records}
    assert names == {
        "ACC-SINV-2026-00001",
        "ACC-SINV-2026-00004",
        "ACC-SINV-2026-00007",
        "ACC-SINV-2026-00008",
        "ACC-SINV-2026-00010",
        "ACC-SINV-RET-2026-00002",
    }


def test_child_tables_are_fetched_per_document(fake):
    pages = list(make(fake).fetch_pages("Payment Entry", FULL))
    docs = {r["name"]: r for p in pages for r in p.records}
    assert docs["ACC-PAY-2026-00004"]["references"] == [
        {
            "reference_doctype": "Sales Invoice",
            "reference_name": "ACC-SINV-2026-00001",
            "allocated_amount": 15000.0,
            "due_date": None,
        }
    ]
    assert "owner" not in docs["ACC-PAY-2026-00004"]  # projected to contracted fields
    list_fields = json.loads(fake.list_params()[0]["fields"])
    assert "references" not in list_fields
    contract = load_source_contract("erpnext")
    assert all(validate_record(contract, "Payment Entry", d) == [] for d in docs.values())


def test_unknown_field_is_an_invalid_request(fake):
    # A DocType without the contracted fields (e.g. older ERPNext version) -> Frappe DataError
    fake.schema_override["Employee"] = {"employee_name", "status"}
    with pytest.raises(InvalidRequestError, match="DataError"):
        list(make(fake).fetch_pages("Employee", FULL))
    assert len(fake.requests) == 1  # not retried


def test_rate_limit_and_timeout_retry(fake):
    fake.failures = [429, "timeout"]
    pages = list(make(fake).fetch_pages("Branch", FULL))
    assert {r["name"] for r in pages[0].records} == {"Paro", "Bumthang"}


def test_persistent_failure_raises(fake):
    fake.failures = ["connect"] * 3
    with pytest.raises(RetryExhaustedError):
        list(make(fake).fetch_pages("Branch", FULL))


def test_only_get_requests_are_ever_sent(fake):
    connector = make(fake)
    connector.check_connection()
    connector.validate_entities()
    for entity in connector.entities():
        list(connector.fetch_pages(entity, FULL))
    assert {r.method for r in fake.requests} == {"GET"}


def test_entity_validation_detects_missing_fields(fake):
    fake.schema_override["Leave Application"] = {"status", "employee"}
    check = make(fake).validate_entity("Leave Application")
    assert not check.available and "leave_type" in check.missing_fields
    missing_doctype = FakeFrappe({})
    assert make(missing_doctype).validate_entity("Employee").available is False
