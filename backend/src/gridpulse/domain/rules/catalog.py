"""Deterministic event rules. Every rule has a stable ID documented in docs/rules.md."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime, timedelta
from enum import StrEnum

import pandas as pd

from gridpulse.domain.indicators import Window, dunkelflaute_windows, negative_price_windows
from gridpulse.domain.metrics import MetricId
from gridpulse.domain.rules.config import RuleConfig
from gridpulse.domain.rules.model import Event, EventCategory, Severity
from gridpulse.domain.stats import rolling_mad_score, rolling_zscore
from gridpulse.domain.timeutils import ensure_utc

NOMINAL_FREQUENCY_HZ = 50.0


class TrafficLight(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


def deviation_in_mhz(frequency_hz: float) -> float:
    """|f - 50 Hz| in mHz, rounded to 1 uHz so that 50.1 Hz is exactly 100 mHz."""
    return round(abs(frequency_hz - NOMINAL_FREQUENCY_HZ) * 1000, 3)


def frequency_status(frequency_hz: float, config: RuleConfig) -> TrafficLight:
    """Traffic light for a frequency reading (spec 2.1)."""
    deviation_mhz = deviation_in_mhz(frequency_hz)
    if deviation_mhz <= config.frequency_green_mhz:
        return TrafficLight.GREEN
    if deviation_mhz <= config.frequency_yellow_mhz:
        return TrafficLight.YELLOW
    return TrafficLight.RED


def _excess(event: Event) -> float:
    """How far an event's value exceeds its threshold (for picking the worst point)."""
    if event.value is None:
        return 0.0
    return abs(event.value) - abs(event.threshold or 0.0)


def merge_episodes(events: Iterable[Event], max_gap: timedelta) -> list[Event]:
    """Collapse consecutive point events into one event per episode (no alert spam).

    Events of the same rule, metric, area, source and severity whose timestamps are at
    most ``max_gap`` apart form an episode. The merged event keeps the episode *start*
    as timestamp (so its id stays stable while the episode grows) and the value of the
    worst point; the message notes the episode length.
    """
    groups: dict[tuple[str, str, str, str, Severity], list[Event]] = {}
    for e in sorted(events, key=lambda e: e.ts):
        groups.setdefault((e.rule_id, e.metric, e.area, e.source, e.severity), []).append(e)
    merged: list[Event] = []
    for items in groups.values():
        episode = [items[0]]
        for e in items[1:]:
            if e.ts - episode[-1].ts <= max_gap:
                episode.append(e)
                continue
            merged.append(_collapse(episode))
            episode = [e]
        merged.append(_collapse(episode))
    return sorted(merged, key=lambda e: (e.ts, e.rule_id))


def _collapse(episode: list[Event]) -> Event:
    if len(episode) == 1:
        return episode[0]
    worst = max(episode, key=_excess)
    first, last = episode[0], episode[-1]
    return replace(
        worst,
        ts=first.ts,
        id="",
        message=(
            f"{worst.message} [episode {first.ts:%H:%M}-{last.ts:%H:%M}Z, {len(episode)} points]"
        ),
    )


def _items(series: pd.Series) -> Iterable[tuple[datetime, float]]:
    clean = series.dropna().sort_index()
    return zip(
        pd.DatetimeIndex(clean.index).to_pydatetime(), clean.to_numpy(dtype=float), strict=True
    )


def frequency_deviation(
    series: pd.Series, config: RuleConfig, *, area: str, source: str
) -> list[Event]:
    """FREQ-001: |f - 50 Hz| beyond the yellow band; critical beyond the critical band."""
    events: list[Event] = []
    for ts, value in _items(series):
        deviation_mhz = deviation_in_mhz(value)
        if deviation_mhz <= config.frequency_yellow_mhz:
            continue
        critical = deviation_mhz > config.frequency_critical_mhz
        threshold = config.frequency_critical_mhz if critical else config.frequency_yellow_mhz
        events.append(
            Event(
                ts=ts,
                rule_id="FREQ-001",
                severity=Severity.CRITICAL if critical else Severity.WARNING,
                category=EventCategory.GRID,
                metric=MetricId.GRID_FREQUENCY.value,
                area=area,
                value=value,
                threshold=threshold,
                source=source,
                unit="Hz",
                message=f"Frequency deviation {deviation_mhz:.0f} mHz exceeds {threshold:.0f} mHz",
            )
        )
    return events


def forecast_error(
    actual: pd.Series,
    forecast: pd.Series,
    config: RuleConfig,
    *,
    metric: MetricId,
    area: str,
    source: str,
) -> list[Event]:
    """FCST-001: |actual - forecast| above a relative threshold of max(forecast, floor)."""
    joined = pd.concat({"a": actual, "f": forecast}, axis=1, join="inner").dropna().sort_index()
    events: list[Event] = []
    for ts, a, f in zip(
        pd.DatetimeIndex(joined.index).to_pydatetime(),
        joined["a"].to_numpy(dtype=float),
        joined["f"].to_numpy(dtype=float),
        strict=True,
    ):
        reference = max(abs(f), config.forecast_error_floor_mw)
        error = (a - f) / reference
        if abs(error) <= config.forecast_error_relative:
            continue
        events.append(
            Event(
                ts=ts,
                rule_id="FCST-001",
                severity=Severity.WARNING,
                category=EventCategory.FORECAST,
                metric=metric.value,
                area=area,
                value=a - f,
                threshold=config.forecast_error_relative * reference,
                source=source,
                unit="MW",
                message=(
                    f"Forecast error {error:+.0%} for {metric.value} "
                    f"(actual {a:.0f} MW, forecast {f:.0f} MW)"
                ),
            )
        )
    return events


def price_spike(series: pd.Series, config: RuleConfig, *, area: str, source: str) -> list[Event]:
    """PRICE-001: day-ahead price above the warning / critical threshold."""
    events: list[Event] = []
    for ts, value in _items(series):
        if value <= config.price_spike_warning:
            continue
        critical = value > config.price_spike_critical
        threshold = config.price_spike_critical if critical else config.price_spike_warning
        events.append(
            Event(
                ts=ts,
                rule_id="PRICE-001",
                severity=Severity.CRITICAL if critical else Severity.WARNING,
                category=EventCategory.PRICE,
                metric=MetricId.PRICE_DAY_AHEAD.value,
                area=area,
                value=value,
                threshold=threshold,
                source=source,
                unit="EUR/MWh",
                message=f"Day-ahead price {value:.2f} EUR/MWh above {threshold:.0f} EUR/MWh",
            )
        )
    return events


def _hours(window: Window) -> float:
    return window.duration / timedelta(hours=1)


def negative_price_outlook(
    price: pd.Series, *, step: timedelta, area: str, source: str
) -> list[Event]:
    """OUT-001: windows with negative day-ahead prices (value = hours)."""
    events = []
    for w in negative_price_windows(price, step):
        hours = _hours(w)
        minimum = float(price[(price.index >= w.start) & (price.index < w.end)].min())
        events.append(
            Event(
                ts=w.start,
                rule_id="OUT-001",
                severity=Severity.INFO,
                category=EventCategory.OUTLOOK,
                metric=MetricId.PRICE_DAY_AHEAD.value,
                area=area,
                value=hours,
                threshold=0.0,
                source=source,
                unit="h",
                message=(
                    f"Negative prices for {hours:g} h from {w.start.isoformat()} "
                    f"(min {minimum:.2f} EUR/MWh)"
                ),
            )
        )
    return events


def dunkelflaute_outlook(
    load: pd.Series,
    variable_renewables: pd.Series,
    config: RuleConfig,
    *,
    step: timedelta,
    area: str,
    source: str,
) -> list[Event]:
    """OUT-002: wind + PV below ``dunkelflaute_share`` of load for >= min duration."""
    events = []
    for w in dunkelflaute_windows(
        load,
        variable_renewables,
        step=step,
        share_threshold=config.dunkelflaute_share,
        min_duration=config.dunkelflaute_min_duration,
    ):
        hours = _hours(w)
        events.append(
            Event(
                ts=w.start,
                rule_id="OUT-002",
                severity=Severity.WARNING,
                category=EventCategory.OUTLOOK,
                metric=MetricId.LOAD_RESIDUAL.value,
                area=area,
                value=hours,
                threshold=config.dunkelflaute_share * 100,
                source=source,
                unit="h",
                message=(
                    f"Dunkelflaute risk: wind+PV below {config.dunkelflaute_share:.0%} of load "
                    f"for {hours:g} h from {w.start.isoformat()}"
                ),
            )
        )
    return events


def statistical_anomaly(
    series: pd.Series,
    config: RuleConfig,
    *,
    metric: MetricId,
    area: str,
    source: str,
    method: str = "mad",
) -> list[Event]:
    """STAT-001 (MAD) / STAT-002 (z-score): robust outlier against the preceding window."""
    if method == "mad":
        rule_id, scores = "STAT-001", rolling_mad_score(series, config.stat_window)
    elif method == "zscore":
        rule_id, scores = "STAT-002", rolling_zscore(series, config.stat_window)
    else:
        raise ValueError(f"unknown method {method!r}")
    events = []
    for ts, score in _items(scores):
        if abs(score) <= config.stat_threshold:
            continue
        value = float(series.loc[ts])
        events.append(
            Event(
                ts=ts,
                rule_id=rule_id,
                severity=Severity.WARNING,
                category=EventCategory.STATISTICAL,
                metric=metric.value,
                area=area,
                value=value,
                threshold=config.stat_threshold,
                source=source,
                message=(
                    f"{metric.value}: robust score {score:+.1f} exceeds +-{config.stat_threshold:g}"
                ),
            )
        )
    return events


def stale_data(
    last_ts: datetime | None,
    now: datetime,
    config: RuleConfig,
    *,
    metric: MetricId,
    area: str,
    source: str,
) -> list[Event]:
    """DATA-001: newest data point older than ``stale_after`` (or no data at all)."""
    now = ensure_utc(now)
    if last_ts is not None and now - ensure_utc(last_ts) <= config.stale_after:
        return []
    age_h = None if last_ts is None else (now - ensure_utc(last_ts)) / timedelta(hours=1)
    message = (
        f"No data for {metric.value} from {source}"
        if age_h is None
        else f"Data for {metric.value} from {source} is {age_h:.1f} h old"
    )
    return [
        Event(
            ts=now,
            rule_id="DATA-001",
            severity=Severity.WARNING,
            category=EventCategory.DATA_QUALITY,
            metric=metric.value,
            area=area,
            value=age_h,
            threshold=config.stale_after / timedelta(hours=1),
            source=source,
            unit="h",
            message=message,
        )
    ]
