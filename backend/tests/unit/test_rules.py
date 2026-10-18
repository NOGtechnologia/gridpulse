from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from gridpulse.domain.metrics import MetricId
from gridpulse.domain.rules import (
    Event,
    EventCategory,
    RuleConfig,
    Severity,
    TrafficLight,
    dunkelflaute_outlook,
    event_id,
    forecast_error,
    frequency_deviation,
    frequency_status,
    negative_price_outlook,
    price_spike,
    stale_data,
    statistical_anomaly,
)

T0 = datetime(2026, 1, 10, 0, tzinfo=UTC)
CFG = RuleConfig()


def _s(values: list[float], freq: str = "15min") -> pd.Series:
    return pd.Series(
        values, index=pd.date_range(T0, periods=len(values), freq=freq), dtype="float64"
    )


@pytest.mark.parametrize(
    ("hz", "light"),
    [
        (50.0, TrafficLight.GREEN),
        (50.05, TrafficLight.GREEN),
        (49.93, TrafficLight.YELLOW),
        (50.1, TrafficLight.YELLOW),
        (50.101, TrafficLight.RED),
        (49.7, TrafficLight.RED),
    ],
)
def test_frequency_status(hz: float, light: TrafficLight) -> None:
    assert frequency_status(hz, CFG) is light


def test_frequency_deviation_severity() -> None:
    events = frequency_deviation(
        _s([50.0, 49.85, 50.25, float("nan")]), CFG, area="DE", source="ec"
    )
    assert [e.severity for e in events] == [Severity.WARNING, Severity.CRITICAL]
    assert all(e.rule_id == "FREQ-001" and e.category is EventCategory.GRID for e in events)
    assert events[0].threshold == 100.0
    assert events[1].threshold == 200.0
    assert "150 mHz" in events[0].message


def test_forecast_error_uses_floor() -> None:
    actual = _s([100.0, 20_000.0, 10_000.0])
    forecast = _s([500.0, 15_000.0, 10_500.0])
    events = forecast_error(
        actual, forecast, CFG, metric=MetricId.GENERATION_SOLAR, area="DE", source="smard"
    )
    # Row 1: 400 MW error vs. reference max(500, floor 1000) -> 40 % -> event.
    # Row 3: 500 MW error vs. 10500 MW -> 4.8 % -> no event.
    assert [e.ts for e in events] == [T0, T0 + timedelta(minutes=15)]
    assert events[1].value == 5000.0
    assert events[1].threshold == pytest.approx(1500.0)


def test_price_spike() -> None:
    events = price_spike(_s([100.0, 600.0, 1500.0]), CFG, area="DE-LU", source="smard")
    assert [e.severity for e in events] == [Severity.WARNING, Severity.CRITICAL]
    assert events[0].unit == "EUR/MWh"


def test_negative_price_outlook() -> None:
    events = negative_price_outlook(
        _s([10.0, -5.0, -20.0, 3.0, -1.0]), step=timedelta(minutes=15), area="DE-LU", source="smard"
    )
    assert [e.value for e in events] == [0.5, 0.25]
    assert events[0].rule_id == "OUT-001"
    assert "min -20.00" in events[0].message


def test_dunkelflaute_outlook() -> None:
    load = _s([50_000.0] * 8, freq="1h")
    vre = _s([1000.0] * 7 + [40_000.0], freq="1h")
    events = dunkelflaute_outlook(
        load, vre, CFG, step=timedelta(hours=1), area="DE", source="smard"
    )
    assert len(events) == 1
    assert events[0].value == 7.0
    assert events[0].severity is Severity.WARNING
    assert events[0].threshold == pytest.approx(10.0)


@pytest.mark.parametrize(("method", "rule"), [("mad", "STAT-001"), ("zscore", "STAT-002")])
def test_statistical_anomaly(method: str, rule: str) -> None:
    values = [100.0 + (i % 5) for i in range(120)]
    values[110] = 400.0
    events = statistical_anomaly(
        _s(values),
        RuleConfig(stat_window=96),
        metric=MetricId.LOAD_RESIDUAL,
        area="DE",
        source="smard",
        method=method,
    )
    assert [e.rule_id for e in events] == [rule]
    assert events[0].value == 400.0


def test_statistical_anomaly_unknown_method() -> None:
    with pytest.raises(ValueError, match="unknown method"):
        statistical_anomaly(
            _s([1.0]), CFG, metric=MetricId.LOAD_RESIDUAL, area="DE", source="x", method="magic"
        )


def test_stale_data() -> None:
    now = T0 + timedelta(hours=10)

    def check(last: datetime | None) -> list[Event]:
        return stale_data(last, now, CFG, metric=MetricId.LOAD_ACTUAL, area="DE", source="smard")

    assert check(now - timedelta(hours=1)) == []
    old = check(now - timedelta(hours=5))
    assert old[0].value == pytest.approx(5.0)
    missing = check(None)
    assert missing[0].value is None
    assert "No data" in missing[0].message


def test_event_id_is_deterministic_and_utc() -> None:
    a = Event(
        ts=T0,
        rule_id="X",
        severity=Severity.INFO,
        category=EventCategory.GRID,
        metric="m",
        area="DE",
        value=1.0,
        threshold=None,
        source="s",
        message="hi",
    )
    b = Event(
        ts=T0.astimezone(),
        rule_id="X",
        severity=Severity.INFO,
        category=EventCategory.GRID,
        metric="m",
        area="DE",
        value=2.0,
        threshold=None,
        source="s",
        message="other",
    )
    assert a.id == b.id == event_id("X", T0, "m", "DE", "s")
    assert len(a.id) == 32
    explicit = Event(
        ts=T0,
        rule_id="X",
        severity=Severity.INFO,
        category=EventCategory.GRID,
        metric="m",
        area="DE",
        value=None,
        threshold=None,
        source="s",
        message="",
        id="custom",
    )
    assert explicit.id == "custom"
    assert Severity.CRITICAL.rank > Severity.WARNING.rank > Severity.INFO.rank
