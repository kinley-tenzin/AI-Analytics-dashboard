"""HTTP server for the pipeline's SYNTHETIC SOURCE MODE (synthetic data only).

    python -m connectors.synthetic.server --odoo-port 8901 --erpnext-port 8902

Serves the fake Odoo JSON-2 and Frappe REST APIs (connectors/synthetic/fake_api.py) over real
HTTP, so the unchanged connectors and ingestion code can be exercised end to end without ERP
sandboxes. The data is the fictional fixture set in tests/fixtures/synthetic/.

Time travel: list requests carry the extraction window's upper bound (Odoo `write_date <= T`,
ERPNext `modified <= T`); the server answers with the synthetic ERP state at T's date, so the
pipeline can replay 2026-09-30 and 2026-10-31 with `--as-of`.
"""

from __future__ import annotations

import argparse
import json
import logging
import threading
from datetime import date
from functools import cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import httpx

from connectors.synthetic.fake_api import FakeFrappe, FakeOdoo, fixture_records

log = logging.getLogger("synthetic-erp")
LATEST = date(2026, 10, 31)  # newest synthetic batch


@cache
def odoo_at(day: date) -> FakeOdoo:
    return FakeOdoo(fixture_records("odoo", day))


@cache
def erpnext_at(day: date) -> FakeFrappe:
    return FakeFrappe(fixture_records("erpnext", day))


def _bound_from_odoo(body: bytes) -> date | None:
    try:
        for field, op, value in json.loads(body or b"{}").get("domain", []):
            if field == "write_date" and op == "<=":
                return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        pass
    return None


def _bound_from_frappe(query: str) -> date | None:
    try:
        filters = json.loads(parse_qs(query).get("filters", ["[]"])[0])
        for field, op, value in filters:
            if field == "modified" and op == "<=":
                return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        pass
    return None


def make_handler(system: str):
    state = {"as_of": LATEST}  # used for requests without a window (versions, details)

    class Handler(BaseHTTPRequestHandler):
        server_version = f"druksmart-synthetic-{system}/1.0"

        def _serve(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            url = urlsplit(self.path)
            bound = _bound_from_odoo(body) if system == "odoo" else _bound_from_frappe(url.query)
            if bound:
                state["as_of"] = min(bound, LATEST)
            fake = (odoo_at if system == "odoo" else erpnext_at)(state["as_of"])
            request = httpx.Request(
                self.command,
                f"http://synthetic{self.path}",
                headers=dict(self.headers.items()),
                content=body,
            )
            response = fake.handle(request)
            payload = response.content
            self.send_response(response.status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST = do_PUT = do_DELETE = _serve

        def log_message(self, fmt, *args):  # route access logs through logging
            log.info("%s %s", system, fmt % args)

    return Handler


def serve(odoo_port: int, erpnext_port: int, host: str = "0.0.0.0") -> list[ThreadingHTTPServer]:
    servers = [
        ThreadingHTTPServer((host, odoo_port), make_handler("odoo")),
        ThreadingHTTPServer((host, erpnext_port), make_handler("erpnext")),
    ]
    for srv in servers:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    return servers


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--odoo-port", type=int, default=8901)
    parser.add_argument("--erpnext-port", type=int, default=8902)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    servers = serve(args.odoo_port, args.erpnext_port, args.host)
    log.info(
        "SYNTHETIC ERP APIs: odoo :%d, erpnext :%d (fictional data)",
        args.odoo_port,
        args.erpnext_port,
    )
    threading.Event().wait() if servers else None


if __name__ == "__main__":
    main()
