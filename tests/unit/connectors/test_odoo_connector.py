"""Odoo JSON-2 adapter against a controlled fake server (NOT proof of live connectivity)."""

from datetime import UTC, date, datetime

import pytest
from fake_erp import ODOO_KEY, FakeOdoo, fixture_records

from connectors.base import (
    AuthenticationError,
    ExtractionWindow,
    InvalidRequestError,
    ReadOnlyViolationError,
    RetryExhaustedError,
    UnsupportedEntityError,
)
from connectors.config import SourceConfig
from connectors.http import RetryPolicy
from connectors.odoo import OdooConnector

UNTIL = datetime(2026, 10, 31, 17, 30, tzinfo=UTC)
FULL = ExtractionWindow(None, UNTIL)


def make(fake, key=ODOO_KEY, page_size=200):
    config = SourceConfig(
        "odoo", "odoo-test", "http://odoo.test", api_key=key, database="db1", page_size=page_size
    )
    return OdooConnector(
        config,
        transport=fake.transport(),
        retry=RetryPolicy(max_attempts=3, base_delay=0.01),
        sleep=lambda s: None,
    )


@pytest.fixture
def fake():
    return FakeOdoo(fixture_records("odoo", date(2026, 10, 31)))


def test_check_connection_reports_version_and_user(fake):
    report = make(fake).check_connection()
    assert report.ok
    assert (report.server_version, report.version_supported, report.user) == ("19.0", True, "uid=7")
    sent = fake.requests[-1]
    assert sent.headers["Authorization"] == f"bearer {ODOO_KEY}"
    assert sent.headers["X-Odoo-Database"] == "db1"


def test_unsupported_version_is_flagged():
    report = make(FakeOdoo({}, version="17.0")).check_connection()
    assert report.authenticated and report.version_supported is False and not report.ok


def test_authentication_failure(fake):
    connector = make(fake, key="wrong")
    assert connector.check_connection().authenticated is False
    with pytest.raises(AuthenticationError):
        list(connector.fetch_pages("hr.employee", FULL))
    assert len(fake.requests) == 2 + 1  # version + context_get + one search (no retries on 401)


def test_full_extraction_includes_archived_records(fake):
    pages = list(make(fake).fetch_pages("hr.employee", FULL))
    ids = [r["id"] for p in pages for r in p.records]
    assert ids == list(range(101, 114))  # archived 108, 109, 113 included via active_test=False
    body = fake.bodies()[0]
    assert body["context"] == {"active_test": False}
    assert body["order"] == "id asc"
    assert set(body["fields"]) == set(make(fake).contract.entity("hr.employee").fields)


def test_without_active_test_context_archived_records_would_be_missed(fake):
    # Documents WHY the contract sets active_test=False (behaviour of Odoo's ORM).
    import json

    response = fake.handle(
        __import__("httpx").Request(
            "POST",
            "http://odoo.test/json/2/hr.employee/search_read",
            headers={"Authorization": f"bearer {ODOO_KEY}"},
            content=json.dumps({"domain": [], "fields": ["id", "active"]}),
        )
    )
    assert all(r["active"] for r in response.json())


def test_pagination_uses_keyset_and_stops_on_short_page(fake):
    pages = list(make(fake, page_size=5).fetch_pages("hr.employee", FULL))
    assert [len(p.records) for p in pages] == [5, 5, 3]
    assert [p.last_source_id for p in pages] == ["105", "110", "113"]
    domains = [b["domain"] for b in fake.bodies()]
    assert ["id", ">", 105] in domains[1] and ["id", ">", 110] in domains[2]
    assert all(b["limit"] == 5 for b in fake.bodies())


def test_exact_multiple_of_page_size_needs_one_empty_request(fake):
    fake.records["hr.department"] = fake.records["hr.department"][:4]
    pages = list(make(fake, page_size=2).fetch_pages("hr.department", FULL))
    assert [len(p.records) for p in pages] == [2, 2]
    assert len(fake.bodies()) == 3  # third request returns [] and ends the extraction


def test_empty_result_yields_no_pages(fake):
    fake.records["hr.leave"] = []
    assert list(make(fake).fetch_pages("hr.leave", FULL)) == []


def test_incremental_window_and_base_domain_are_sent(fake):
    after = datetime(2026, 9, 30, 17, 20, tzinfo=UTC)
    pages = list(make(fake).fetch_pages("account.move", ExtractionWindow(after, UNTIL)))
    domain = fake.bodies()[0]["domain"]
    assert ["move_type", "in", ["out_invoice", "out_refund", "in_invoice", "in_refund"]] in domain
    assert ["write_date", ">", "2026-09-30 17:20:00"] in domain
    assert ["write_date", "<=", "2026-10-31 17:30:00"] in domain
    changed = {r["id"] for p in pages for r in p.records}
    assert changed == {402, 403, 404, 408, 409, 413, 414, 451, 453, 455, 456, 457}


def test_invalid_field_is_reported_not_retried(fake):
    fake.hidden_fields["hr.employee"] = {"employee_type"}
    connector = make(fake)
    with pytest.raises(InvalidRequestError, match="Invalid field 'employee_type'"):
        list(connector.fetch_pages("hr.employee", FULL))
    check = connector.validate_entity("hr.employee")
    assert not check.available and check.missing_fields == ["employee_type"]


def test_timeouts_are_retried_then_succeed(fake):
    fake.failures = ["timeout", 503]
    pages = list(make(fake).fetch_pages("res.company", FULL))
    assert len(pages[0].records) == 2 and len(fake.requests) == 3


def test_persistent_timeout_raises_after_retries(fake):
    fake.failures = ["timeout"] * 5
    with pytest.raises(RetryExhaustedError):
        list(make(fake).fetch_pages("res.company", FULL))
    assert len(fake.requests) == 3


def test_validate_all_contracted_entities(fake):
    checks = make(fake).validate_entities()
    assert [c.entity for c in checks if not c.available] == []
    assert "account.partial.reconcile" not in [c.entity for c in checks]  # deferred


def test_write_methods_are_refused_before_any_request(fake):
    connector = make(fake)
    for method in ("write", "create", "unlink", "action_post", "message_post"):
        with pytest.raises(ReadOnlyViolationError):
            connector._call("hr.employee", method, ids=[101], vals={"name": "x"})
    assert fake.requests == []


def test_deferred_and_unknown_entities_are_rejected(fake):
    connector = make(fake)
    for entity in ("account.partial.reconcile", "sale.order"):
        with pytest.raises(UnsupportedEntityError):
            list(connector.fetch_pages(entity, FULL))
