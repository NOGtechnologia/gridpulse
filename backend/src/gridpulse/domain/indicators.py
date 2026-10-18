"""Derived indicators: renewable share, CO2 series, aggregation and outlook windows."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

import pandas as pd

from gridpulse.domain.co2 import co2_intensity
from gridpulse.domain.metrics import GENERATION_METRICS, RENEWABLE_METRICS, Kind, MetricId
from gridpulse.domain.timeutils import BERLIN


class Resolution(StrEnum):
    QUARTER_HOUR = "15min"
    HOUR = "1h"
    DAY = "1d"

    @property
    def delta(self) -> timedelta:
        return {
            Resolution.QUARTER_HOUR: timedelta(minutes=15),
            Resolution.HOUR: timedelta(hours=1),
            Resolution.DAY: timedelta(days=1),
        }[self]


def renewable_share(mix_mw: Mapping[MetricId, float]) -> float | None:
    """Share of renewable generation in total generation, in percent."""
    total = 0.0
    renewable = 0.0
    for metric, value in mix_mw.items():
        if metric not in GENERATION_METRICS:
            continue
        mw = max(value, 0.0)
        total += mw
        if metric in RENEWABLE_METRICS:
            renewable += mw
    if total <= 0.0:
        return None
    # Clamp: floating point rounding can otherwise yield 100.00000000000001 %.
    return min(100.0, 100.0 * renewable / total)


def generation_mix(frame: pd.DataFrame, *, kind: Kind = Kind.ACTUAL) -> pd.DataFrame:
    """Wide frame: ts index x generation metric columns (MW). Duplicate sources: first wins."""
    gen_values = {m.value for m in GENERATION_METRICS}
    sub = frame[(frame["kind"] == kind.value) & (frame["metric"].isin(gen_values))]
    sub = sub.drop_duplicates(subset=["ts", "metric"], keep="first")
    wide = sub.pivot(index="ts", columns="metric", values="value").sort_index()
    wide.columns = [str(c) for c in wide.columns]
    return wide.astype("float64")


def _row_mix(row: pd.Series) -> dict[MetricId, float]:
    return {MetricId(str(k)): float(v) for k, v in row.items() if pd.notna(v)}


def renewable_share_series(mix: pd.DataFrame) -> pd.Series:
    values = [renewable_share(_row_mix(row)) for _, row in mix.iterrows()]
    return pd.Series(
        values, index=mix.index, dtype="float64", name=MetricId.INDICATOR_RENEWABLE_SHARE.value
    )


def co2_intensity_series(mix: pd.DataFrame) -> pd.Series:
    values = [co2_intensity(_row_mix(row)) for _, row in mix.iterrows()]
    return pd.Series(
        values, index=mix.index, dtype="float64", name=MetricId.INDICATOR_CO2_INTENSITY.value
    )


def aggregate(series: pd.Series, resolution: Resolution) -> pd.Series:
    """Mean-aggregate a UTC-indexed series.

    Daily buckets follow Europe/Berlin calendar days (23 h / 25 h on DST change days)
    and are labelled with the UTC instant of local midnight.
    """
    if series.empty:
        return series.astype("float64")
    if resolution is Resolution.DAY:
        local = series.tz_convert(BERLIN)
        grouped = local.groupby(pd.DatetimeIndex(local.index).normalize()).mean()
        grouped.index = pd.DatetimeIndex(grouped.index).tz_convert("UTC")
        return grouped.astype("float64")
    return series.resample(resolution.delta, label="left", closed="left").mean().dropna()


@dataclass(frozen=True, slots=True)
class Window:
    start: datetime
    end: datetime  # exclusive

    @property
    def duration(self) -> timedelta:
        return self.end - self.start


def windows_where(
    mask: pd.Series, step: timedelta, min_duration: timedelta = timedelta(0)
) -> list[Window]:
    """Contiguous windows where a boolean ts-indexed mask is True.

    Gaps in the index larger than ``step`` split windows.
    """
    ordered = mask.sort_index()
    windows: list[Window] = []
    start: datetime | None = None
    prev: datetime | None = None
    for stamp, flag in zip(
        pd.DatetimeIndex(ordered.index).to_pydatetime(), ordered.to_numpy(), strict=True
    ):
        gap = prev is None or stamp - prev != step
        if start is not None and prev is not None and (not flag or gap):
            windows.append(Window(start, prev + step))
            start = None
        if flag and start is None:
            start = stamp
        prev = stamp
    if start is not None and prev is not None:
        windows.append(Window(start, prev + step))
    return [w for w in windows if w.duration >= min_duration]


def negative_price_windows(price: pd.Series, step: timedelta) -> list[Window]:
    """Windows with day-ahead price strictly below zero."""
    return windows_where(price < 0, step)


def dunkelflaute_windows(
    load: pd.Series,
    variable_renewables: pd.Series,
    *,
    step: timedelta,
    share_threshold: float,
    min_duration: timedelta,
) -> list[Window]:
    """Windows where wind+PV cover less than ``share_threshold`` (0..1) of load for long enough."""
    frame = pd.concat({"load": load, "vre": variable_renewables}, axis=1, join="inner").dropna()
    frame = frame[frame["load"] > 0]
    mask = (frame["vre"] / frame["load"]) < share_threshold
    return windows_where(mask, step, min_duration)
