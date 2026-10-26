"""Retry / backoff behaviour of the shared HTTP client (controlled responses)."""

import httpx
import pytest

from connectors.base import RetryExhaustedError
from connectors.http import ApiClient, RetryPolicy


def client(handler, sleeps, attempts=4):
    return ApiClient(
        "http://erp.test",
        {},
        transport=httpx.MockTransport(handler),
        retry=RetryPolicy(max_attempts=attempts, base_delay=1, max_delay=8),
        sleep=sleeps.append,
        jitter=lambda: 0.0,
    )


def sequence(*steps):
    """Handler returning/raising each step in turn, then 200."""
    remaining = list(steps)

    def handler(request):
        if not remaining:
            return httpx.Response(200, json={"ok": True})
        step = remaining.pop(0)
        if step == "timeout":
            raise httpx.ReadTimeout("t", request=request)
        if step == "connect":
            raise httpx.ConnectError("c", request=request)
        return httpx.Response(step, headers={"Retry-After": "3"} if step == 429 else {})

    return handler


def test_timeout_then_success_uses_exponential_backoff():
    sleeps = []
    response = client(sequence("timeout", "connect", 503), sleeps).request("GET", "/x")
    assert response.status_code == 200
    assert sleeps == [1, 2, 4]


def test_retry_after_header_is_honoured():
    sleeps = []
    assert client(sequence(429), sleeps).request("GET", "/x").status_code == 200
    assert sleeps == [3]


def test_retries_are_bounded():
    sleeps = []
    with pytest.raises(RetryExhaustedError, match="after 4 attempts: ReadTimeout"):
        client(sequence(*["timeout"] * 10), sleeps).request("GET", "/x")
    assert sleeps == [1, 2, 4]  # no sleep after the final attempt


@pytest.mark.parametrize("status", [400, 401, 403, 404, 417, 500])
def test_non_transient_statuses_are_not_retried(status):
    sleeps = []
    assert client(sequence(status), sleeps).request("GET", "/x").status_code == status
    assert sleeps == []


def test_backoff_is_capped():
    assert RetryPolicy(base_delay=1, max_delay=8).delay(10, 0.0) == 8
