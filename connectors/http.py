"""HTTP client with timeouts and retry/backoff, shared by the ERP adapters.

Only transport-level problems and HTTP 429/502/503/504 are retried. Every other response is
returned to the adapter, which maps it to a specific ConnectorError. Credentials are sent in
headers and never logged.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from connectors.base import RetryExhaustedError

log = logging.getLogger(__name__)

USER_AGENT = "druksmart-connector/0.1 (+read-only analytics extraction)"


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    base_delay: float = 1.0  # seconds; doubles each attempt
    max_delay: float = 30.0
    retry_statuses: tuple[int, ...] = (429, 502, 503, 504)

    def delay(self, attempt: int, jitter: float) -> float:
        return min(self.max_delay, self.base_delay * 2 ** (attempt - 1)) + jitter


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    if value.isdigit():
        return float(value)
    try:
        return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
    except (TypeError, ValueError):
        return None


class ApiClient:
    def __init__(
        self,
        base_url: str,
        headers: Mapping[str, str],
        *,
        timeout: float = 30.0,
        retry: RetryPolicy | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] | None = None,
    ):
        self.retry = retry or RetryPolicy()
        self._sleep = sleep
        self._jitter = jitter or (lambda: random.uniform(0, 0.5))
        self._client = httpx.Client(
            base_url=base_url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json", **headers},
            timeout=httpx.Timeout(timeout, connect=min(10.0, timeout)),
            transport=transport,
            follow_redirects=False,
        )

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Send a request, retrying transient failures. Raises RetryExhaustedError."""
        last_problem = ""
        for attempt in range(1, self.retry.max_attempts + 1):
            wait = None
            try:
                response = self._client.request(method, path, **kwargs)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_problem = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code not in self.retry.retry_statuses:
                    return response
                last_problem = f"HTTP {response.status_code}"
                wait = _retry_after_seconds(response)

            if attempt == self.retry.max_attempts:
                break
            delay = wait if wait is not None else self.retry.delay(attempt, self._jitter())
            delay = min(delay, self.retry.max_delay)
            log.warning(
                "%s %s failed (%s); retry %d/%d in %.1fs",
                method,
                path,
                last_problem,
                attempt,
                self.retry.max_attempts - 1,
                delay,
            )
            self._sleep(delay)

        raise RetryExhaustedError(
            f"{method} {path} failed after {self.retry.max_attempts} attempts: {last_problem}"
        )

    def close(self) -> None:
        self._client.close()
