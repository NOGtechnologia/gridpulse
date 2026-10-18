"""Helpers to read series from the repository with a source preference order."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import pandas as pd

from gridpulse.domain.metrics import Kind, MetricId
from gridpulse.storage.repository import ObservationQuery, QueryResolution, Repository

# Preference when several sources provide the same metric. Energy-Charts publishes
# the most complete German mix with the lowest latency; SMARD is the official
# BNetzA platform and the fallback; demo data is only used in demo mode.
SOURCE_PRIORITY: tuple[str, ...] = ("energy_charts", "smard", "entsoe", "demo")
INTERNAL_LIMIT = 500_000


async def fetch_frame(
    repo: Repository,
    metrics: Sequence[MetricId],
    start: datetime,
    end: datetime,
    *,
    kind: Kind | None = Kind.ACTUAL,
    areas: Sequence[str] | None = ("DE",),
    sources: Sequence[str] | None = None,
    resolution: QueryResolution = QueryResolution.QUARTER_HOUR,
) -> pd.DataFrame:
    """Internal read (no paging). Callers keep their windows small enough."""
    return await repo.query_observations(
        ObservationQuery(
            metrics=[m.value for m in metrics],
            start=start,
            end=end,
            areas=list(areas) if areas else None,
            kind=kind.value if kind else None,
            sources=list(sources) if sources else None,
            resolution=resolution,
            limit=INTERNAL_LIMIT,
        )
    )


def pick_series(frame: pd.DataFrame, metric: MetricId, source: str | None = None) -> pd.Series:
    sub = frame[frame["metric"] == metric.value]
    if source is not None:
        sub = sub[sub["source"] == source]
    sub = sub.drop_duplicates(subset="ts", keep="first")
    return pd.Series(
        sub["value"].to_numpy(dtype=float), index=pd.DatetimeIndex(sub["ts"]), name=metric.value
    ).sort_index()


def best_source(frame: pd.DataFrame, metric: MetricId) -> str | None:
    """Source with the newest value for ``metric``; ties broken by SOURCE_PRIORITY."""
    sub = frame[frame["metric"] == metric.value]
    if sub.empty:
        return None
    newest = sub.groupby("source")["ts"].max()
    rank = {s: i for i, s in enumerate(SOURCE_PRIORITY)}
    ordered = sorted(
        newest.items(), key=lambda kv: (-pd.Timestamp(kv[1]).value, rank.get(str(kv[0]), 99))
    )
    return str(ordered[0][0])
