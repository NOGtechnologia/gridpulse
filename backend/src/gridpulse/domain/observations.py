"""The canonical observation frame produced by every adapter (spec 5.3)."""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from gridpulse.domain.metrics import Kind, MetricId, unit_of
from gridpulse.domain.timeutils import ensure_utc

COLUMNS: tuple[str, ...] = ("ts", "resolution", "metric", "area", "value", "unit", "kind", "source")
KEY_COLUMNS: tuple[str, ...] = ("ts", "metric", "area", "kind", "source")


@dataclass(frozen=True, slots=True)
class Observation:
    ts: datetime
    resolution: timedelta
    metric: MetricId
    area: str
    value: float
    kind: Kind
    source: str

    @property
    def unit(self) -> str:
        return unit_of(self.metric).value


def empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": pd.Series([], dtype="datetime64[ns, UTC]"),
            "resolution": pd.Series([], dtype="timedelta64[ns]"),
            "metric": pd.Series([], dtype=object),
            "area": pd.Series([], dtype=object),
            "value": pd.Series([], dtype="float64"),
            "unit": pd.Series([], dtype=object),
            "kind": pd.Series([], dtype=object),
            "source": pd.Series([], dtype=object),
        }
    )


def make_frame(
    *,
    timestamps: Iterable[datetime],
    values: Iterable[float | None],
    metric: MetricId,
    area: str,
    kind: Kind,
    source: str,
    resolution: timedelta,
) -> pd.DataFrame:
    """Build a canonical frame for one series. ``None``/NaN values are dropped."""
    ts = [ensure_utc(t) for t in timestamps]
    vals = list(values)
    if len(ts) != len(vals):
        raise ValueError(f"length mismatch: {len(ts)} timestamps vs {len(vals)} values")
    pairs = [
        (t, float(v)) for t, v in zip(ts, vals, strict=True) if v is not None and not math.isnan(v)
    ]
    if not pairs:
        return empty_frame()
    frame = pd.DataFrame(
        {
            "ts": pd.to_datetime([p[0] for p in pairs], utc=True).as_unit("ns"),
            "resolution": pd.to_timedelta([resolution] * len(pairs)).as_unit("ns"),
            "metric": pd.Series([metric.value] * len(pairs), dtype=object),
            "area": pd.Series([area] * len(pairs), dtype=object),
            "value": pd.Series([p[1] for p in pairs], dtype="float64"),
            "unit": pd.Series([unit_of(metric).value] * len(pairs), dtype=object),
            "kind": pd.Series([kind.value] * len(pairs), dtype=object),
            "source": pd.Series([source] * len(pairs), dtype=object),
        }
    )
    return frame


def concat_frames(frames: Iterable[pd.DataFrame]) -> pd.DataFrame:
    non_empty = [f for f in frames if not f.empty]
    if not non_empty:
        return empty_frame()
    out = pd.concat(non_empty, ignore_index=True)
    return out.sort_values(list(KEY_COLUMNS), kind="stable").reset_index(drop=True)


def iter_observations(frame: pd.DataFrame) -> Iterator[Observation]:
    """Typed row iteration over a canonical frame."""
    columns = zip(
        pd.DatetimeIndex(frame["ts"]).to_pydatetime(),
        pd.TimedeltaIndex(frame["resolution"]).to_pytimedelta(),
        frame["metric"].astype(str),
        frame["area"].astype(str),
        frame["value"].to_numpy(dtype=float),
        frame["kind"].astype(str),
        frame["source"].astype(str),
        strict=True,
    )
    for ts, resolution, metric, area, value, kind, source in columns:
        yield Observation(
            ts=ts,
            resolution=resolution,
            metric=MetricId(metric),
            area=area,
            value=float(value),
            kind=Kind(kind),
            source=source,
        )


def to_observations(frame: pd.DataFrame) -> list[Observation]:
    return list(iter_observations(frame))


def series_of(
    frame: pd.DataFrame, metric: MetricId, *, kind: Kind = Kind.ACTUAL, area: str | None = None
) -> pd.Series:
    """Extract one metric as a ts-indexed float series (first source wins on duplicates)."""
    mask = (frame["metric"] == metric.value) & (frame["kind"] == kind.value)
    if area is not None:
        mask &= frame["area"] == area
    sub = frame.loc[mask].drop_duplicates(subset="ts", keep="first")
    series = pd.Series(
        sub["value"].to_numpy(dtype=float),
        index=pd.DatetimeIndex(sub["ts"]),
        name=metric.value,
        dtype="float64",
    )
    return series.sort_index()
