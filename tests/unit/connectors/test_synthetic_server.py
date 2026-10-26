"""The synthetic-mode HTTP service works with the REAL connectors over real HTTP."""

from datetime import UTC, datetime

import pytest

from connectors.base import ExtractionWindow
from connectors.config import SourceConfig
from connectors.erpnext import ERPNextConnector
from connectors.odoo import OdooConnector
from connectors.synthetic import fake_api, server


@pytest.fixture(scope="module")
def ports():
    servers = server.serve(0, 0, host="127.0.0.1")  # port 0 = any free port
    yield [s.server_address[1] for s in servers]
    for s in servers:
        s.shutdown()


def odoo(port):
    return OdooConnector(
        SourceConfig(
            "odoo", "odoo-dtg-retail", f"http://127.0.0.1:{port}", api_key=fake_api.ODOO_KEY
        )
    )


def erpnext(port):
    return ERPNextConnector(
        SourceConfig(
            "erpnext",
            "erpnext-dtg-services",
            f"http://127.0.0.1:{port}",
            api_key=fake_api.ERP_KEY,
            api_secret=fake_api.ERP_SECRET,
            timezone="Asia/Thimphu",
        )
    )


def ids(connector, entity, until):
    pk = connector.contract.entity(entity).primary_key
    window = ExtractionWindow(None, until)
    return {str(r[pk]) for p in connector.fetch_pages(entity, window) for r in p.records}


def test_connection_checks_pass_over_http(ports):
    for connector in (odoo(ports[0]), erpnext(ports[1])):
        with connector:
            assert connector.check_connection().ok
            assert all(c.available for c in connector.validate_entities())


def test_server_time_travels_with_the_extraction_window(ports):
    sep = datetime(2026, 9, 30, 17, 30, tzinfo=UTC)
    oct_ = datetime(2026, 10, 31, 17, 30, tzinfo=UTC)
    with odoo(ports[0]) as c:
        assert "408" not in ids(c, "account.move", sep)  # created in October
        assert "408" in ids(c, "account.move", oct_)
    with erpnext(ports[1]) as c:
        assert "ACC-SINV-2026-00007" in ids(c, "Sales Invoice", oct_)
        assert "ACC-SINV-2026-00007" not in ids(c, "Sales Invoice", sep)


def test_child_tables_are_served(ports):
    with erpnext(ports[1]) as c:
        window = ExtractionWindow(None, datetime(2026, 10, 31, 17, 30, tzinfo=UTC))
        docs = [r for p in c.fetch_pages("Payment Entry", window) for r in p.records]
        assert any(d["references"] for d in docs)
