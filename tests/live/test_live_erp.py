"""LIVE read-only tests against real Odoo / ERPNext instances configured in .env.

Skipped automatically when a source is not configured. Run explicitly with:
    pytest -m live -v

These tests are the only evidence of real connectivity. Mocked tests are not.
"""

import uuid
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest

from connectors import create_connector, load_source_config
from connectors.base import ExtractionWindow
from druksmart_common.config import ConfigError, load_settings
from druksmart_common.contracts import has_errors, validate_record
from druksmart_common.db import connect
from ingestion.migrate import apply_migrations
from ingestion.runner import run_module
from ingestion.store import RawStore

pytestmark = pytest.mark.live


@pytest.fixture(scope="module", params=["odoo", "erpnext"])
def config(request):
    try:
        return load_source_config(request.param)
    except ConfigError as exc:
        pytest.skip(f"{request.param} not configured: {exc}")


@pytest.fixture(scope="module")
def connector(config):
    with create_connector(config) as c:
        report = c.check_connection()
        if not report.reachable:
            pytest.skip(f"{config.source_system} not reachable at {config.base_url}")
        yield c


@pytest.fixture(scope="module")
def available(connector):
    """Entities that exist on this instance (e.g. Leave Application needs the hrms app)."""
    return {c.entity: c for c in connector.validate_entities()}


def test_connection_authentication_and_version(connector):
    report = connector.check_connection()
    assert report.authenticated, report.details
    assert report.version_supported, f"version {report.server_version}: {report.details}"


def test_every_contracted_field_is_readable(connector, available):
    problems = {e: c.missing_fields or c.detail for e, c in available.items() if not c.available}
    if connector.source_system == "erpnext" and set(problems) == {"Leave Application"}:
        pytest.xfail("hrms app not installed on this ERPNext instance")
    assert problems == {}


def test_live_payloads_satisfy_the_contracts(connector, available):
    """Verifies the documented 'assumption' items (formats, empty values, references)."""
    window = ExtractionWindow(None, datetime.now(UTC))
    errors, counts = {}, {}
    for entity, check in available.items():
        if not check.available:
            continue
        records = [r for page in connector.fetch_pages(entity, window) for r in page.records]
        counts[entity] = len(records)
        for rec in records:
            issues = validate_record(connector.contract, entity, rec)
            if has_errors(issues):
                errors.setdefault(entity, []).append([f"{i.field}: {i.message}" for i in issues])
    print(f"\nlive record counts: {counts}")
    assert errors == {}, errors
    assert sum(counts.values()) > 0, "sandbox has no data; run the seed script"


def test_pagination_returns_every_record_once(connector, available):
    entity = "hr.employee" if connector.source_system == "odoo" else "Employee"
    window = ExtractionWindow(None, datetime.now(UTC))
    pk = connector.contract.entity(entity).primary_key
    one_page = [r[pk] for p in connector.fetch_pages(entity, window) for r in p.records]
    small = list(connector.fetch_pages(entity, window, page_size=2))
    paged = [r[pk] for p in small for r in p.records]
    assert len(one_page) >= 3, "need at least 3 employees to exercise paging"
    assert len(small) >= 2 and paged == one_page and len(set(paged)) == len(paged)


def test_incremental_window_in_the_future_returns_nothing(connector):
    entity = "hr.employee" if connector.source_system == "odoo" else "Employee"
    now = datetime.now(UTC)
    assert list(connector.fetch_pages(entity, ExtractionWindow(now, now))) == []


def test_read_only_user_cannot_write(config):
    """Bypasses the connector on purpose: proves the ERP itself refuses writes for this user."""
    if config.source_system == "odoo":
        headers = {"Authorization": f"bearer {config.api_key}", "X-Odoo-Database": config.database}
        attempts = [
            ("POST", "/json/2/res.company/write", {"ids": [1], "vals": {"name": "HACKED"}}),
            ("POST", "/json/2/account.move/create", {"vals_list": [{"move_type": "entry"}]}),
        ]
    else:
        headers = {"Authorization": f"token {config.api_key}:{config.api_secret}"}
        attempts = [
            ("POST", "/api/resource/Branch", {"branch": f"HACK-{uuid.uuid4().hex[:6]}"}),
            ("PUT", "/api/resource/Department/All Departments", {"disabled": 1}),
        ]
    with httpx.Client(base_url=config.base_url, headers=headers, timeout=30) as client:
        for method, path, body in attempts:
            response = client.request(method, path, json=body)
            assert response.status_code in (401, 403, 404, 417, 422), (
                f"{method} {path} was NOT refused (HTTP {response.status_code})"
            )


def test_end_to_end_extraction_into_raw(config, available):
    """Real API -> raw tables, twice: the second run must add no record versions."""
    instance = f"live-test-{uuid.uuid4().hex[:8]}"
    entities = [e for e, c in available.items() if c.available]
    with (
        create_connector(replace(config, instance_id=instance)) as c,
        connect(load_settings().pipeline(), autocommit=True) as conn,
    ):
        apply_migrations(conn)
        try:
            first = run_module(c, RawStore(conn), None, entities=entities)
            second = run_module(c, RawStore(conn), None, entities=entities, full=True)
            assert all(r.status == "succeeded" for r in first + second), [
                r.error for r in first + second
            ]
            assert sum(r.inserted for r in first) > 0
            assert sum(r.inserted for r in second) == 0
            assert sum(r.unchanged for r in second) == sum(r.inserted for r in first)
        finally:
            with conn.transaction():
                for table in (
                    "quarantined_record",
                    "extraction_checkpoint",
                    "source_record",
                    "extraction_run",
                ):
                    conn.execute(f"DELETE FROM raw.{table} WHERE source_instance = %s", (instance,))
