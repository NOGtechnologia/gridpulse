"""Feature pipeline: stored Open-Meteo weather (``weather.*``) + calendar, hourly."""

from __future__ import annotations

import pandas as pd

from gridpulse.domain.calendar import calendar_features
from gridpulse.domain.metrics import MetricId

WEATHER_METRICS: tuple[MetricId, ...] = (
    MetricId.WEATHER_TEMPERATURE,
    MetricId.WEATHER_WIND_SPEED_100M,
    MetricId.WEATHER_SHORTWAVE_RADIATION,
    MetricId.WEATHER_CLOUD_COVER,
)
HOUR = pd.Timedelta(hours=1)


def hourly_mean(series: pd.Series) -> pd.Series:
    """Hourly means of a sub-hourly series; incomplete hours (still being published) are dropped."""
    if series.empty:
        return series.astype("float64")
    diffs = pd.Series(series.index).diff().dropna()
    step = pd.Timedelta(diffs.median()) if not diffs.empty else HOUR
    expected = max(1, int(HOUR / step))
    grouped = series.resample("1h")
    means, counts = grouped.mean(), grouped.count()
    return means[counts >= expected].astype("float64")


def weather_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    """Wide table, one column ``<metric>@<area>`` per weather metric and location."""
    weather = frame[frame["metric"].isin([m.value for m in WEATHER_METRICS])]
    if weather.empty:
        return pd.DataFrame(index=pd.DatetimeIndex([], tz="UTC"))
    keyed = weather.assign(
        column=weather["metric"].astype(str) + "@" + weather["area"].astype(str),
        ts=pd.DatetimeIndex(weather["ts"]).floor("1h"),
    )
    wide = keyed.pivot_table(index="ts", columns="column", values="value", aggfunc="mean")
    return wide.reindex(sorted(wide.columns), axis=1)


def build_features(weather: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """Weather columns plus ``hour``/``weekday``/``holiday``; rows without weather are dropped."""
    joined = weather.reindex(index).join(calendar_features(index))
    return joined.dropna()
