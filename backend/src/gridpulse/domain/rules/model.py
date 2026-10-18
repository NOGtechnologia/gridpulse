"""Event model shared by all rules (spec 2.3)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from gridpulse.domain.timeutils import ensure_utc


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return {Severity.INFO: 0, Severity.WARNING: 1, Severity.CRITICAL: 2}[self]


class EventCategory(StrEnum):
    GRID = "grid"
    FORECAST = "forecast"
    PRICE = "price"
    DATA_QUALITY = "data_quality"
    STATISTICAL = "statistical"
    OUTLOOK = "outlook"


@dataclass(frozen=True, slots=True)
class Event:
    ts: datetime
    rule_id: str
    severity: Severity
    category: EventCategory
    metric: str
    area: str
    value: float | None
    threshold: float | None
    source: str
    message: str
    unit: str | None = None
    id: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "ts", ensure_utc(self.ts))
        if not self.id:
            object.__setattr__(
                self, "id", event_id(self.rule_id, self.ts, self.metric, self.area, self.source)
            )


def event_id(rule_id: str, ts: datetime, metric: str, area: str, source: str) -> str:
    """Deterministic id so that re-evaluating the same data never duplicates events."""
    key = f"{rule_id}|{ensure_utc(ts).isoformat()}|{metric}|{area}|{source}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]
