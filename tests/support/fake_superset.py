"""A fake Superset REST API (httpx MockTransport) for the website backend tests."""

from __future__ import annotations

import base64
import json
import time

import httpx

DATASETS = {
    "druksmart-hr": [
        ("kpi_headcount", 1),
        ("kpi_approved_leave_monthly", 2),
        ("data_freshness", 4),
    ],
    "druksmart-accounts": [("kpi_receivables_payables", 3), ("data_freshness", 4)],
}


def fake_jwt(exp: float) -> str:
    body = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"x.{body}.y"


class FakeSuperset:
    def __init__(self):
        self.datasets = {k: list(v) for k, v in DATASETS.items()}
        self.guest_requests: list[dict] = []
        self.down = False
        self.logins = 0
        self.embedding_enabled: list[tuple[str, list[str]]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        path = request.url.path
        if path == "/api/v1/security/login":
            self.logins += 1
            return httpx.Response(200, json={"access_token": fake_jwt(time.time() + 900)})
        if path == "/api/v1/security/csrf_token/":
            return httpx.Response(200, json={"result": "csrf123"})
        if path == "/api/v1/security/guest_token/":
            assert request.headers["X-CSRFToken"] == "csrf123"
            assert request.headers["Authorization"].startswith("Bearer ")
            self.guest_requests.append(json.loads(request.content))
            return httpx.Response(200, json={"token": "guest-token-abc"})
        if path == "/health":
            return httpx.Response(200, text="OK")
        parts = path.strip("/").split("/")  # api v1 dashboard <ref> [embedded|datasets]
        ref = parts[3]
        if ref not in self.datasets:
            return httpx.Response(404, json={"message": "Not found"})
        if len(parts) == 4:
            return httpx.Response(
                200, json={"result": {"id": 1, "slug": ref, "dashboard_title": ref}}
            )
        if parts[4] == "embedded":
            if request.method == "PUT":
                self.embedding_enabled.append((ref, json.loads(request.content)["allowed_domains"]))
            return httpx.Response(200, json={"result": {"uuid": f"uuid-{ref}"}})
        return httpx.Response(
            200, json={"result": [{"table_name": t, "id": i} for t, i in self.datasets[ref]]}
        )
