"""In-memory repository with the same semantics as the SQL one (tests, offline demo)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

import pandas as pd

from gridpulse.domain.observations import KEY_COLUMNS, empty_frame
from gridpulse.domain.rules.model import Event
from gridpulse.domain.timeutils import BERLIN, ensure_utc
from gridpulse.storage.repository import (
    OBS_RESULT_COLUMNS,
    AlertChannel,
    EventQuery,
    ObservationQuery,
    QueryResolution,
    SourceStatus,
    empty_result,
    hash_api_key,
)

GROUP = ["metric", "area", "kind", "source", "unit"]


def _filter(frame: pd.DataFrame, query: ObservationQuery) -> pd.DataFrame:
    mask = frame["metric"].isin(list(query.metrics))
    mask &= (frame["ts"] >= pd.Timestamp(query.start)) & (frame["ts"] < pd.Timestamp(query.end))
    if query.areas:
        mask &= frame["area"].isin(list(query.areas))
    if query.kind:
        mask &= frame["kind"] == query.kind
    if query.sources:
        mask &= frame["source"].isin(list(query.sources))
    return frame.loc[mask]


def bucket(frame: pd.DataFrame, resolution: QueryResolution) -> pd.DataFrame:
    """Mean per bucket, mirroring time_bucket() and the continuous aggregates."""
    if frame.empty:
        return empty_result()
    if resolution is QueryResolution.RAW:
        return frame[OBS_RESULT_COLUMNS].copy()
    ts = pd.DatetimeIndex(frame["ts"])
    if resolution is QueryResolution.DAY:
        buckets = ts.tz_convert(BERLIN).floor("D", ambiguous=False, nonexistent="shift_forward")
        buckets = buckets.tz_convert("UTC")
    else:
        buckets = ts.floor("15min" if resolution is QueryResolution.QUARTER_HOUR else "1h")
    work = frame.assign(ts=buckets)
    out = work.groupby(["ts", *GROUP], sort=False)["value"].mean().reset_index()
    return out[OBS_RESULT_COLUMNS]


class MemoryRepository:
    def __init__(self) -> None:
        self._obs = empty_frame()
        self._events: dict[str, Event] = {}
        self._notified: dict[str, datetime] = {}
        self._status: dict[str, SourceStatus] = {}
        self._channels: list[AlertChannel] = []
        self._keys: dict[str, bool] = {}

    async def upsert_observations(self, frame: pd.DataFrame) -> int:
        if frame.empty:
            return 0
        combined = (
            pd.concat([self._obs, frame], ignore_index=True) if not self._obs.empty else frame
        )
        self._obs = combined.drop_duplicates(subset=list(KEY_COLUMNS), keep="last").reset_index(
            drop=True
        )
        return len(frame)

    def _query(self, query: ObservationQuery) -> pd.DataFrame:
        result = bucket(_filter(self._obs, query), query.resolution)
        return result.sort_values(["ts", "metric", "area", "kind", "source"], kind="stable")

    async def query_observations(self, query: ObservationQuery) -> pd.DataFrame:
        result = self._query(query)
        return result.iloc[query.offset : query.offset + query.limit].reset_index(drop=True)

    async def count_observations(self, query: ObservationQuery) -> int:
        return len(self._query(query))

    async def latest_timestamp(
        self, metric: str, area: str, kind: str, source: str
    ) -> datetime | None:
        sel = self._obs[
            (self._obs["metric"] == metric)
            & (self._obs["area"] == area)
            & (self._obs["kind"] == kind)
            & (self._obs["source"] == source)
        ]
        if sel.empty:
            return None
        return pd.Timestamp(sel["ts"].max()).to_pydatetime()

    async def upsert_events(self, events: Sequence[Event]) -> list[Event]:
        new = [e for e in events if e.id not in self._events]
        for e in new:
            self._events[e.id] = e
        return new

    async def list_events(self, query: EventQuery) -> list[Event]:
        items = sorted(self._events.values(), key=lambda e: (e.ts, e.id), reverse=True)
        if query.start:
            items = [e for e in items if e.ts >= ensure_utc(query.start)]
        if query.end:
            items = [e for e in items if e.ts < ensure_utc(query.end)]
        if query.min_severity:
            items = [e for e in items if e.severity.rank >= query.min_severity.rank]
        if query.rule_ids:
            items = [e for e in items if e.rule_id in query.rule_ids]
        if query.categories:
            items = [e for e in items if e.category.value in query.categories]
        return items[query.offset : query.offset + query.limit]

    async def mark_notified(self, event_ids: Sequence[str], at: datetime) -> None:
        for event_id in event_ids:
            self._notified[event_id] = ensure_utc(at)

    async def last_notified(self, rule_id: str, area: str, metric: str) -> datetime | None:
        times = [
            self._notified[e.id]
            for e in self._events.values()
            if e.id in self._notified and (e.rule_id, e.area, e.metric) == (rule_id, area, metric)
        ]
        return max(times, default=None)

    async def save_source_status(self, status: SourceStatus) -> None:
        self._status[status.source] = replace(status)

    async def list_source_status(self) -> list[SourceStatus]:
        return [self._status[k] for k in sorted(self._status)]

    async def list_alert_channels(self) -> list[AlertChannel]:
        return list(self._channels)

    async def add_alert_channel(self, channel: AlertChannel) -> AlertChannel:
        if any(c.name == channel.name for c in self._channels):
            raise ValueError(f"channel {channel.name!r} exists")
        stored = replace(channel, id=len(self._channels) + 1)
        self._channels.append(stored)
        return stored

    async def add_api_key(self, name: str, key: str) -> None:
        self._keys[hash_api_key(key)] = True

    async def is_valid_api_key(self, key: str) -> bool:
        return self._keys.get(hash_api_key(key), False)

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None
