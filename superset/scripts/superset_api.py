"""Minimal Superset REST API client (JWT login + CSRF), shared by the bootstrap and the tests.

    with SupersetClient.login(base_url, username, password) as api:
        api.get("/api/v1/dataset/")

Superset protects state-changing requests with a CSRF token tied to the session cookie, so the
client fetches /api/v1/security/csrf_token/ once and sends it (with the Referer header Flask-WTF
checks) on every POST/PUT/DELETE. Passwords are never logged or included in error messages.
"""

from __future__ import annotations

import json
from typing import Any

import httpx


class SupersetError(RuntimeError):
    def __init__(self, method: str, path: str, status: int, body: str):
        super().__init__(f"{method} {path} -> HTTP {status}: {body[:500]}")
        self.status = status


class SupersetClient:
    def __init__(self, base_url: str, http: httpx.Client):
        self.base_url = base_url.rstrip("/")
        self.http = http
        self.csrf_token: str | None = None

    @classmethod
    def login(
        cls, base_url: str, username: str, password: str, timeout: float = 60
    ) -> SupersetClient:
        http = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)
        resp = http.post(
            "/api/v1/security/login",
            json={"username": username, "password": password, "provider": "db", "refresh": False},
        )
        if resp.status_code != 200:
            http.close()
            # Never echo the request (it holds the password); the status is enough to diagnose.
            raise SupersetError("POST", "/api/v1/security/login", resp.status_code, resp.text)
        http.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
        client = cls(base_url, http)
        client.csrf_token = client.get("/api/v1/security/csrf_token/")["result"]
        http.headers["X-CSRFToken"] = client.csrf_token
        http.headers["Referer"] = client.base_url
        return client

    def __enter__(self) -> SupersetClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.http.close()

    # ------------------------------------------------------------------ raw requests
    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        return self.http.request(method, path, **kwargs)

    def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        resp = self.request(method, path, **kwargs)
        if resp.status_code >= 400:
            raise SupersetError(method, path, resp.status_code, resp.text)
        return resp.json() if resp.content else None

    def get(self, path: str, **kwargs: Any) -> Any:
        return self._json("GET", path, **kwargs)

    def post(self, path: str, payload: Any = None, **kwargs: Any) -> Any:
        return self._json("POST", path, json=payload, **kwargs)

    def put(self, path: str, payload: Any = None, **kwargs: Any) -> Any:
        return self._json("PUT", path, json=payload, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self._json("DELETE", path, **kwargs)

    # ------------------------------------------------------------------ helpers
    def list_all(self, resource: str, filters: list[dict] | None = None) -> list[dict]:
        """Every row of a list endpoint (follows pagination)."""
        rows: list[dict] = []
        page = 0
        while True:
            q = {"page": page, "page_size": 100}
            if filters:
                q["filters"] = filters
            result = self.get(f"/api/v1/{resource}/", params={"q": rison(q)})
            rows.extend(result["result"])
            if len(rows) >= result.get("count", 0) or not result["result"]:
                return rows
            page += 1

    def find_one(self, resource: str, column: str, value: Any) -> dict | None:
        rows = self.list_all(resource, [{"col": column, "opr": "eq", "value": value}])
        return rows[0] if rows else None


def rison(value: Any) -> str:
    """Encode a value as Rison, the URL format Superset's `q=` parameters use."""
    if value is True:
        return "!t"
    if value is False:
        return "!f"
    if value is None:
        return "!n"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, str):
        safe = value.replace("!", "!!").replace("'", "!'")
        if safe and all(c.isalnum() or c in "-_./~" for c in safe) and not safe[0].isdigit():
            return safe
        return f"'{safe}'"
    if isinstance(value, (list, tuple)):
        return "!(" + ",".join(rison(v) for v in value) + ")"
    if isinstance(value, dict):
        return "(" + ",".join(f"{rison(str(k))}:{rison(v)}" for k, v in value.items()) + ")"
    raise TypeError(f"cannot encode {type(value).__name__} as rison")
