"""Extraction runner + raw store against the real PostgreSQL container, fed by fake ERP APIs.

Requires: docker compose up -d  and  python -m ingestion migrate
Every test uses a unique source_instance and deletes its own rows afterwards.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from fake_erp import ERP_KEY, ERP_SECRET, ODOO_KEY, FakeFrappe, FakeOdoo, fixture_records
from kpi_reference import latest

from connectors.base import ExtractionWindow, Page, SourceConnector
from connectors.config import SourceConfig
from connectors.erpnext import ERPNextConnector
from connectors.http import RetryPolicy
from connectors.odoo import OdooConnector
from druksmart_common.config import load_settings
from druksmart_common.contracts import has_errors, load_source_contract, validate_record
from druksmart_common.db import connect
from ingestion.migrate import apply_migrations
from ingestion.runner import run_extraction, run_module
from ingestion.store import ExtractionAlreadyRunningError, RawStore

pytestmark = pytest.mark.db

SEP = datetime(2026, 9, 30, 17, 30, tzinfo=UTC)
OCT = datetime(2026, 10, 31, 17, 30, tzinfo=UTC)
NO_RETRY_WAIT = {"retry": RetryPolicy(max_attempts=2, base_delay=0), "sleep": lambda s: None}


@pytest.fixture(scope="module")
def conn():
    with connect(load_settings().pipeline(), autocommit=True) as c:
        apply_migrations(c)
        yield c


@pytest.fixture
def instance(conn):
    name = f"test-{uuid.uuid4().hex[:10]}"
    yield name
    with conn.transaction():
        for table in ("quarantined_record", "extraction_checkpoint", "source_record"):
            conn.execute(f"DELETE FROM raw.{table} WHERE source_instance = %s", (name,))
        conn.execute("DELETE FROM raw.extraction_run WHERE source_instance = %s", (name,))


@pytest.fixture
def store(conn):
    return RawStore(conn)


def odoo(fake, instance, page_size=200):
    cfg = SourceConfig("odoo", instance, "http://odoo.test", api_key=ODOO_KEY, page_size=page_size)
    return OdooConnector(cfg, transport=fake.transport(), **NO_RETRY_WAIT)


def erpnext(fake, instance, page_size=200):
    cfg = SourceConfig(
        "erpnext",
        instance,
        "http://erp.test",
        api_key=ERP_KEY,
        api_secret=ERP_SECRET,
        timezone="Asia/Thimphu",
        page_size=page_size,
    )
    return ERPNextConnector(cfg, transport=fake.transport(), **NO_RETRY_WAIT)


def count(conn, sql, *params):
    return conn.execute(sql, params).fetchone()[0]


def versions(conn, instance, entity):
    return count(
        conn,
        "SELECT count(*) FROM raw.source_record WHERE source_instance = %s AND source_entity = %s",
        instance,
        entity,
    )


# ---------------------------------------------------------------------------------------


def test_migrations_are_idempotent(conn):
    assert apply_migrations(conn) == []


def test_first_run_stores_records_with_provenance(conn, store, instance):
    fake = FakeOdoo(fixture_records("odoo", date(2026, 10, 31)))
    result = run_extraction(odoo(fake, instance), store, "hr.employee", now=lambda: OCT)

    assert (result.status, result.mode, result.fetched) == ("succeeded", "full", 13)
    assert (result.inserted, result.quarantined, result.with_warnings) == (12, 1, 1)
    row = conn.execute(
        "SELECT source_system, source_entity, payload->>'name', source_modified_at, "
        "first_run_id::text, contract_version, length(payload_sha256) "
        "FROM raw.source_record WHERE source_instance = %s AND source_id = '109'",
        (instance,),
    ).fetchone()
    assert row == (
        "odoo",
        "hr.employee",
        "Yeshey Dema",
        datetime(2026, 10, 21, 4, 0, tzinfo=UTC),
        result.run_id,
        "1.0.0",
        64,
    )
    quarantined = conn.execute(
        "SELECT source_id, issues->0->>'field' FROM raw.quarantined_record WHERE run_id = %s",
        (result.run_id,),
    ).fetchall()
    assert quarantined == [("112", "employee_type")]
    checkpoint = store.get_checkpoint("odoo", instance, "hr.employee")
    assert checkpoint == OCT


def test_rerun_is_idempotent(conn, store, instance):
    fake = FakeOdoo(fixture_records("odoo", date(2026, 10, 31)))
    first = run_extraction(odoo(fake, instance), store, "hr.employee", full=True, now=lambda: OCT)
    second = run_extraction(
        odoo(fake, instance), store, "hr.employee", full=True, now=lambda: OCT + timedelta(hours=1)
    )
    assert first.inserted == 12
    assert (second.inserted, second.unchanged) == (0, 12)
    assert versions(conn, instance, "hr.employee") == 12
    assert (
        count(
            conn,
            "SELECT min(times_seen) FROM raw.source_record WHERE source_instance = %s",
            instance,
        )
        == 2
    )


def test_incremental_run_fetches_only_changes_and_keeps_history(conn, store, instance):
    fake = FakeOdoo(fixture_records("odoo", date(2026, 10, 31)))
    run_extraction(odoo(fake, instance), store, "hr.employee", now=lambda: OCT)
    employee = next(r for r in fake.records["hr.employee"] if r["id"] == 104)
    employee.update(departure_date="2026-12-31", write_date="2026-11-02 05:00:00")
    later = datetime(2026, 11, 3, tzinfo=UTC)
    fake.requests.clear()

    result = run_extraction(odoo(fake, instance), store, "hr.employee", now=lambda: later)

    assert (result.mode, result.fetched, result.inserted) == ("incremental", 1, 1)
    domain = fake.bodies()[0]["domain"]
    assert ["write_date", ">", "2026-10-31 17:20:00"] in domain  # checkpoint minus 10 min overlap
    assert versions(conn, instance, "hr.employee") == 13
    current = conn.execute(
        "SELECT payload->>'departure_date' FROM raw.current_source_record "
        "WHERE source_instance = %s AND source_id = '104'",
        (instance,),
    ).fetchone()[0]
    assert current == "2026-12-31"


def test_interrupted_run_recovers_without_duplicates(conn, store, instance):
    fake = FakeOdoo(fixture_records("odoo", date(2026, 10, 31)))

    def break_after_first_page(request):
        if len(fake.requests) == 2:  # second search_read: the connection drops for good
            fake.failures = ["connect"] * 5

    fake.on_request = break_after_first_page
    failed = run_extraction(
        odoo(fake, instance, page_size=5), store, "hr.employee", now=lambda: OCT
    )
    assert failed.status == "failed" and "RetryExhaustedError" in failed.error
    assert (failed.pages, failed.inserted) == (1, 5)  # first page was committed
    assert store.get_checkpoint("odoo", instance, "hr.employee") is None  # not advanced

    fake.on_request, fake.failures = None, []
    recovered = run_extraction(
        odoo(fake, instance, page_size=5),
        store,
        "hr.employee",
        now=lambda: OCT + timedelta(minutes=5),
    )
    assert recovered.status == "succeeded"
    assert (recovered.inserted, recovered.unchanged) == (7, 5)
    assert versions(conn, instance, "hr.employee") == 12
    statuses = conn.execute(
        "SELECT status FROM raw.extraction_run WHERE source_instance = %s ORDER BY started_at",
        (instance,),
    ).fetchall()
    assert statuses == [("failed",), ("succeeded",)]


def test_authentication_failure_is_logged_as_failed_run(conn, store, instance):
    fake = FakeOdoo(fixture_records("odoo", date(2026, 10, 31)))
    connector = odoo(fake, instance)
    connector.api._client.headers["Authorization"] = "bearer wrong"
    result = run_extraction(connector, store, "res.company", now=lambda: OCT)
    assert result.status == "failed" and result.error.startswith("AuthenticationError")
    assert len(fake.requests) == 1


def test_concurrent_extraction_of_same_entity_is_refused(conn, store, instance):
    fake = FakeOdoo(fixture_records("odoo", date(2026, 10, 31)))
    with connect(load_settings().pipeline(), autocommit=True) as other:
        with RawStore(other).entity_lock("odoo", instance, "hr.employee"):
            with pytest.raises(ExtractionAlreadyRunningError):
                run_extraction(odoo(fake, instance), store, "hr.employee", now=lambda: OCT)
    assert (
        run_extraction(odoo(fake, instance), store, "hr.employee", now=lambda: OCT).status
        == "succeeded"
    )


class DuplicatingConnector(SourceConnector):
    """Simulates a source that returns the same record twice within one run."""

    source_system = "odoo"
    supported_major_versions = ("19",)

    def __init__(self, instance):
        super().__init__(SourceConfig("odoo", instance, "http://x", api_key="k"))
        self.rows = fixture_records("odoo", date(2026, 10, 31))["res.company"]

    def check_connection(self): ...
    def validate_entity(self, entity): ...
    def close(self): ...

    def fetch_pages(
        self, entity, window: ExtractionWindow, *, page_size=None, start_after=None
    ) -> Iterator[Page]:
        yield Page(entity, 1, self.rows, "2")
        yield Page(entity, 2, [self.rows[1]], "2")


def test_duplicate_records_in_one_run_are_stored_once(conn, store, instance):
    result = run_extraction(DuplicatingConnector(instance), store, "res.company", now=lambda: OCT)
    assert (result.fetched, result.inserted, result.duplicate) == (3, 2, 1)
    assert versions(conn, instance, "res.company") == 2


def _expected_current(system: str, entity: str, as_of: date) -> set[str]:
    contract = load_source_contract(system)
    return {
        sid
        for sid, rec in latest(system, entity, as_of, include_invalid=True).items()
        if not has_errors(validate_record(contract, entity, rec))
    }


@pytest.mark.parametrize("system", ["odoo", "erpnext"])
def test_replay_of_both_synthetic_snapshots(conn, store, instance, system):
    """September full extraction, then October incremental: raw mirrors the fixtures."""
    make_fake, make_conn = (FakeOdoo, odoo) if system == "odoo" else (FakeFrappe, erpnext)
    fake = make_fake(fixture_records(system, date(2026, 9, 30)))
    sep = run_module(make_conn(fake, instance, page_size=3), store, None, now=lambda: SEP)
    assert all(r.status == "succeeded" for r in sep)

    fake.records = fixture_records(system, date(2026, 10, 31))
    oct_ = run_module(make_conn(fake, instance, page_size=3), store, None, now=lambda: OCT)
    assert all(r.status == "succeeded" for r in oct_)
    accounts_entity = "account.move" if system == "odoo" else "Sales Invoice"
    assert next(r for r in oct_ if r.entity == accounts_entity).mode == "incremental"

    for result in oct_:
        current = {
            row[0]
            for row in conn.execute(
                "SELECT source_id FROM raw.current_source_record WHERE source_instance = %s "
                "AND source_entity = %s",
                (instance, result.entity),
            )
        }
        assert current == _expected_current(system, result.entity, date(2026, 10, 31)), (
            result.entity
        )

    # Running October again changes nothing
    again = run_module(make_conn(fake, instance), store, None, now=lambda: OCT + timedelta(hours=1))
    assert sum(r.inserted for r in again) == 0
