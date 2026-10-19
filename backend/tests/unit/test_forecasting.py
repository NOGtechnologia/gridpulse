"""Feature pipeline, model and backtest of the own residual-load model (phase 7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from gridpulse.adapters.open_meteo import weather_area
from gridpulse.domain.metrics import Kind, MetricId
from gridpulse.domain.observations import concat_frames, make_frame
from gridpulse.forecasting.features import (
    WEATHER_METRICS,
    build_features,
    hourly_mean,
    weather_matrix,
)
from gridpulse.forecasting.model import SEED, backtest, fit_predict

START = datetime(2026, 8, 1, tzinfo=UTC)


def _weather_frame(hours: int, locations: tuple[str, ...] = ("a", "b")) -> pd.DataFrame:
    stamps = [START + timedelta(hours=h) for h in range(hours)]
    rng = np.random.default_rng(1)
    frames = [
        make_frame(
            timestamps=stamps,
            values=rng.uniform(0, 30, hours).tolist(),
            metric=metric,
            area=weather_area(loc),
            kind=Kind.FORECAST,
            source="open_meteo",
            resolution=timedelta(hours=1),
        )
        for metric in WEATHER_METRICS
        for loc in locations
    ]
    return concat_frames(frames)


def test_hourly_mean_requires_complete_hours() -> None:
    index = pd.date_range("2026-08-01T00:00Z", periods=7, freq="15min")
    series = pd.Series([1.0, 2.0, 3.0, 4.0, 10.0, 20.0, 30.0], index=index)
    out = hourly_mean(series)
    # 01:00 has only three quarter-hours (still being published) and is dropped.
    assert out.to_dict() == {pd.Timestamp("2026-08-01T00:00Z"): 2.5}


def test_hourly_mean_keeps_hourly_data_and_handles_empty() -> None:
    index = pd.date_range("2026-08-01T00:00Z", periods=3, freq="h")
    assert hourly_mean(pd.Series([1.0, 2.0, 3.0], index=index)).tolist() == [1.0, 2.0, 3.0]
    empty = pd.Series([], index=pd.DatetimeIndex([], tz="UTC"), dtype="float64")
    assert hourly_mean(empty).empty


def test_weather_matrix_pivots_metric_and_location() -> None:
    frame = _weather_frame(3)
    other = make_frame(
        timestamps=[START],
        values=[1.0],
        metric=MetricId.LOAD_ACTUAL,
        area="DE",
        kind=Kind.ACTUAL,
        source="smard",
        resolution=timedelta(hours=1),
    )
    matrix = weather_matrix(concat_frames([frame, other]))
    assert len(matrix) == 3
    assert list(matrix.columns) == sorted(matrix.columns)
    assert "weather.temperature_2m@WX:a" in matrix.columns
    assert len(matrix.columns) == len(WEATHER_METRICS) * 2


def test_weather_matrix_of_empty_frame() -> None:
    assert weather_matrix(_weather_frame(0)).empty


def test_build_features_joins_calendar_and_drops_incomplete_rows() -> None:
    matrix = weather_matrix(_weather_frame(4))
    index = pd.date_range(START, periods=6, freq="h")
    features = build_features(matrix, index)
    assert len(features) == 4  # hours 4 and 5 have no weather
    assert {"hour", "weekday", "holiday"} <= set(features.columns)
    assert features.columns[-3:].tolist() == ["hour", "weekday", "holiday"]


def _synthetic(
    days: int, official_noise: float, seed: int = 0
) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Residual load = f(wind, radiation, hour) + noise; official forecast = truth + noise."""
    hours = days * 24
    matrix = weather_matrix(_weather_frame(hours))
    index = pd.date_range(START, periods=hours, freq="h")
    features = build_features(matrix, index)
    rng = np.random.default_rng(seed)
    truth = (
        40_000
        - 800 * features["weather.wind_speed_100m@WX:a"]
        - 300 * features["weather.shortwave_radiation@WX:b"]
        + 500 * np.sin(features["hour"] / 24 * 2 * np.pi)
    )
    target = truth + rng.normal(0, 200, hours)
    official = truth + rng.normal(0, official_noise, hours)
    return features, pd.Series(target, index=index), pd.Series(official, index=index)


def test_backtest_detects_a_better_model() -> None:
    features, target, official = _synthetic(28, official_noise=4_000)
    result = backtest(features, target, official, test_days=7, min_train_days=14)
    assert result is not None
    assert result.test_end - result.test_start == timedelta(days=7)
    assert result.train_end <= result.test_start
    assert result.model.points == result.official.points == 7 * 24
    assert result.model.mae < result.official.mae
    assert result.active


def test_backtest_keeps_the_official_forecast_when_it_is_better() -> None:
    features, target, official = _synthetic(28, official_noise=10)
    result = backtest(features, target, official, test_days=7, min_train_days=14)
    assert result is not None
    assert not result.active


def test_backtest_is_reproducible() -> None:
    features, target, official = _synthetic(21, official_noise=1_000)
    first = backtest(features, target, official, test_days=7, min_train_days=7)
    second = backtest(features, target, official, test_days=7, min_train_days=7)
    assert first == second
    assert SEED == 42


def test_backtest_needs_enough_history() -> None:
    features, target, official = _synthetic(14, official_noise=1_000)
    assert backtest(features, target, official, test_days=7, min_train_days=14) is None
    empty = official.iloc[:0]
    assert backtest(features, target, empty, test_days=7, min_train_days=1) is None


def test_fit_predict_returns_one_value_per_future_hour() -> None:
    features, target, _ = _synthetic(10, official_noise=0)
    future = features.iloc[-24:]
    prediction = fit_predict(features.iloc[:-24], target.iloc[:-24], future)
    assert prediction.index.equals(future.index)
    assert prediction.notna().all()
    with pytest.raises(ValueError, match="no training rows"):
        fit_predict(features, target.iloc[:0], future)
