"""Repository interface. Implementations: SQL (TimescaleDB) and in-memory (tests/demo)."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

import pandas as pd

from gridpulse.domain.rules.model import Event, Severity


class QueryResolution(StrEnum):
    RAW = "raw"
    QUARTER_HOUR = "15min"
    HOUR = "1h"
    DAY = "1d"


@dataclass(frozen=True, slots=True)
class ObservationQuery:
    metrics: Sequence[str]
    start: datetime
    end: datetime
    areas: Sequence[str] | None = None
    kind: str | None = None
    sources: Sequence[str] | None = None
    resolution: QueryResolution = QueryResolution.QUARTER_HOUR
    limit: int = 10_000
    offset: int = 0


@dataclass(frozen=True, slots=True)
class EventQuery:
    start: datetime | None = None
    end: datetime | None = None
    min_severity: Severity | None = None
    rule_ids: Sequence[str] | None = None
    categories: Sequence[str] | None = None
    limit: int = 100
    offset: int = 0


@dataclass(slots=True)
class SourceStatus:
    source: str
    last_attempt: datetime | None = None
    last_success: datetime | None = None
    last_error: str | None = None
    latency_ms: float | None = None
    rows_last_run: int = 0
    expected_points: int = 0
    received_points: int = 0
    plausibility_violations: int = 0
    consecutive_failures: int = 0
    newest_data: datetime | None = None

    @property
    def gap_ratio(self) -> float:
        if self.expected_points <= 0:
            return 0.0
        return max(0.0, 1.0 - self.received_points / self.expected_points)


@dataclass(frozen=True, slots=True)
class AlertChannel:
    name: str
    kind: str
    target: str
    min_severity: Severity = Severity.WARNING
    enabled: bool = True
    id: int | None = field(default=None, compare=False)


def hash_api_key(key: str) -> str:
    """API keys are stored as SHA-256 hashes only (spec 5.3)."""
    return hashlib.sha256(key.encode()).hexdigest()


OBS_RESULT_COLUMNS = ["ts", "metric", "area", "kind", "source", "unit", "value"]


def empty_result() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": pd.Series([], dtype="datetime64[ns, UTC]"),
            **{c: pd.Series([], dtype=object) for c in OBS_RESULT_COLUMNS[1:-1]},
            "value": pd.Series([], dtype="float64"),
        }
    )


class Repository(Protocol):
    async def upsert_observations(self, frame: pd.DataFrame) -> int: ...

    async def query_observations(self, query: ObservationQuery) -> pd.DataFrame: ...

    async def count_observations(self, query: ObservationQuery) -> int: ...

    async def latest_timestamp(
        self, metric: str, area: str, kind: str, source: str
    ) -> datetime | None: ...

    async def upsert_events(self, events: Sequence[Event]) -> list[Event]:
        """Insert events; returns only the ones that were new."""
        ...

    async def list_events(self, query: EventQuery) -> list[Event]: ...

    async def mark_notified(self, event_ids: Sequence[str], at: datetime) -> None: ...

    async def last_notified(self, rule_id: str, area: str, metric: str) -> datetime | None: ...

    async def save_source_status(self, status: SourceStatus) -> None: ...

    async def list_source_status(self) -> list[SourceStatus]: ...

    async def list_alert_channels(self) -> list[AlertChannel]: ...

    async def add_alert_channel(self, channel: AlertChannel) -> AlertChannel: ...

    async def add_api_key(self, name: str, key: str) -> None: ...

    async def is_valid_api_key(self, key: str) -> bool: ...

    async def ping(self) -> bool: ...

    async def close(self) -> None: ...
