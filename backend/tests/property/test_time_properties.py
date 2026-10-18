"""Property tests for time zone logic, aggregation, residual load and CO2 (spec 7.2)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from gridpulse.domain.co2 import EMISSION_FACTORS_G_PER_KWH, co2_intensity
from gridpulse.domain.indicators import Resolution, aggregate, renewable_share
from gridpulse.domain.metrics import GENERATION_METRICS, MetricId
from gridpulse.domain.residual_load import residual_load, residual_load_value
from gridpulse.domain.timeutils import (
    BERLIN,
    ensure_utc,
    floor_to,
    local_day_bounds,
    local_day_length,
)

aware = st.datetimes(
    min_value=datetime(2000, 1, 1),  # noqa: DTZ001 - hypothesis bounds must be naive
    max_value=datetime(2060, 1, 1),  # noqa: DTZ001 - hypothesis bounds must be naive
    timezones=st.just(UTC),
)
days = st.dates(min_value=date(2000, 1, 1), max_value=date(2060, 1, 1))
power = st.floats(min_value=0, max_value=100_000, allow_nan=False)
# Physically meaningful generation values: exactly zero or at least 1 kW (avoids
# subnormal floats that underflow to 0 when scaled).
gen_power = st.one_of(st.just(0.0), st.floats(min_value=1e-3, max_value=100_000))


@given(days)
def test_local_day_is_23_24_or_25_hours(day: date) -> None:
    assert local_day_length(day) in {timedelta(hours=h) for h in (23, 24, 25)}


@given(days)
def test_local_days_tile_the_time_axis(day: date) -> None:
    _, end = local_day_bounds(day)
    next_start, _ = local_day_bounds(day + timedelta(days=1))
    assert end == next_start


@given(aware)
def test_berlin_roundtrip_preserves_instant(value: datetime) -> None:
    assert ensure_utc(value.astimezone(BERLIN)) == value


@given(aware, st.sampled_from([timedelta(seconds=10), timedelta(minutes=15), timedelta(hours=1)]))
def test_floor_is_idempotent_and_not_after(value: datetime, step: timedelta) -> None:
    floored = floor_to(value, step)
    assert floored <= value < floored + step
    assert floor_to(floored, step) == floored


@settings(max_examples=50, deadline=None)
@given(days, st.floats(min_value=-1000, max_value=1000, allow_nan=False))
def test_daily_aggregate_of_constant_is_constant_on_dst_days(day: date, value: float) -> None:
    start, end = local_day_bounds(day)
    index = pd.date_range(start, end, freq="15min", inclusive="left")
    series = pd.Series(value, index=index, dtype="float64")
    daily = aggregate(series, Resolution.DAY)
    assert len(daily) == 1
    assert daily.index[0] == pd.Timestamp(start)
    assert abs(float(daily.iloc[0]) - value) < 1e-9


@settings(max_examples=50, deadline=None)
@given(st.lists(st.floats(min_value=-1e4, max_value=1e4, allow_nan=False), min_size=4, max_size=96))
def test_hourly_aggregate_preserves_mean_of_full_hours(values: list[float]) -> None:
    n = len(values) - len(values) % 4
    index = pd.date_range("2026-03-29T00:00Z", periods=n, freq="15min")
    series = pd.Series(values[:n], index=index, dtype="float64")
    hourly = aggregate(series, Resolution.HOUR)
    assert len(hourly) == n // 4
    assert abs(float(hourly.mean()) - float(series.mean())) < 1e-6


@given(power, power, power, power)
def test_residual_load_identity(load: float, on: float, off: float, pv: float) -> None:
    value = residual_load_value(load, on, off, pv)
    assert abs(value + on + off + pv - load) < 1e-6


@settings(max_examples=30, deadline=None)
@given(st.lists(st.tuples(power, power, power, power), min_size=1, max_size=20))
def test_residual_series_matches_scalar(rows: list[tuple[float, float, float, float]]) -> None:
    index = pd.date_range("2026-01-01T00:00Z", periods=len(rows), freq="15min")
    cols = list(zip(*rows, strict=True))
    result = residual_load(*(pd.Series(c, index=index, dtype="float64") for c in cols))
    for i, row in enumerate(rows):
        assert abs(float(result.iloc[i]) - residual_load_value(*row)) < 1e-6


mixes = st.dictionaries(st.sampled_from(GENERATION_METRICS), gen_power, min_size=1)


@given(mixes)
def test_co2_intensity_is_bounded_by_factors(mix: dict[MetricId, float]) -> None:
    result = co2_intensity(mix)
    if sum(mix.values()) <= 0:
        assert result is None
        return
    assert result is not None
    used = [EMISSION_FACTORS_G_PER_KWH[m] for m, v in mix.items() if v > 0]
    assert min(used) - 1e-6 <= result <= max(used) + 1e-6


@given(mixes, st.floats(min_value=0.01, max_value=100, allow_nan=False))
def test_co2_and_share_are_scale_invariant(mix: dict[MetricId, float], factor: float) -> None:
    scaled = {m: v * factor for m, v in mix.items()}
    a, b = co2_intensity(mix), co2_intensity(scaled)
    assert (a is None) == (b is None)
    if a is not None and b is not None:
        assert abs(a - b) <= 1e-6 * max(1.0, a)
    share = renewable_share(mix)
    if share is not None:
        assert 0.0 <= share <= 100.0
