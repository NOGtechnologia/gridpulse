"""Common adapter interface and polite HTTP helper (spec 3, 5.2)."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

import httpx
import pandas as pd

from gridpulse.domain.metrics import MetricId

USER_AGENT = "GridPulse/0.1 (+https://github.com/NOGtechnologia/gridpulse)"


@dataclass(frozen=True, slots=True)
class RawPayload:
    """Raw response(s) of one fetch, plus the context ``parse`` needs."""

    source_id: str
    metric: MetricId
    start: datetime
    end: datetime
    documents: list[Any]
    params: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class SourceAdapter(Protocol):
    source_id: str
    license: str
    attribution: str

    def supported_metrics(self) -> frozenset[MetricId]: ...

    async def fetch(self, metric: MetricId, start: datetime, end: datetime) -> RawPayload: ...

    def parse(self, payload: RawPayload) -> pd.DataFrame: ...


class UnsupportedMetricError(ValueError):
    pass


class SourceUnavailableError(RuntimeError):
    """The source could not be reached after all retries."""


@dataclass(slots=True)
class HttpFetcher:
    """GET with retry, exponential backoff and full jitter on 429/5xx/transport errors."""

    client: httpx.AsyncClient
    max_attempts: int = 4
    base_delay: float = 1.0
    max_delay: float = 30.0
    rng: random.Random = field(default_factory=random.Random)

    def _delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after is not None and retry_after.isdigit():
            return min(float(retry_after), self.max_delay)
        return self.rng.uniform(0, min(self.max_delay, self.base_delay * 2**attempt))

    async def get(self, url: str, params: Mapping[str, Any] | None = None) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            retry_after: str | None = None
            try:
                response = await self.client.get(
                    url, params=dict(params or {}), headers={"User-Agent": USER_AGENT}
                )
                if response.status_code == 429 or response.status_code >= 500:
                    retry_after = response.headers.get("Retry-After")
                    last_error = httpx.HTTPStatusError(
                        f"HTTP {response.status_code}", request=response.request, response=response
                    )
                else:
                    response.raise_for_status()
                    return response
            except httpx.TransportError as exc:
                last_error = exc
            if attempt + 1 < self.max_attempts:
                await asyncio.sleep(self._delay(attempt, retry_after))
        raise SourceUnavailableError(f"{url}: {last_error!r}") from last_error

    async def get_json(self, url: str, params: Mapping[str, Any] | None = None) -> Any:
        return (await self.get(url, params)).json()
