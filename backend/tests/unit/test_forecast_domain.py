"""Calendar features and forecast scores for the own forecasting model (phase 7)."""

from __future__ import annotations

import math
from datetime import date

import pandas as pd
import pytest

from gridpulse.domain.calendar import calendar_features, easter_sunday, german_public_holidays
from gridpulse.domain.scores import MAPE_FLOOR_MW, Scores, beats, score


@pytest.mark.parametrize(
    ("year", "expected"),
    [
        (2024, date(2024, 3, 31)),
        (2025, date(2025, 4, 20)),
        (2026, date(2026, 4, 5)),
        (2038, date(2038, 4, 25)),  # latest possible date
        (2285, date(2285, 3, 22)),  # earliest possible date
    ],
)
def test_easter_sunday(year: int, expected: date) -> None:
    assert easter_sunday(year) == expected


def test_german_public_holidays_2026() -> None:
    assert german_public_holidays(2026) == {
        date(2026, 1, 1),
        date(2026, 4, 3),  # Karfreitag
        date(2026, 4, 6),  # Ostermontag
        date(2026, 5, 1),
        date(2026, 5, 14),  # Christi Himmelfahrt
        date(2026, 5, 25),  # Pfingstmontag
        date(2026, 10, 3),
        date(2026, 12, 25),
        date(2026, 12, 26),
    }


def test_calendar_features_use_berlin_local_time() -> None:
    # 2026-10-02 22:00 UTC is already Saturday 2026-10-03 00:00 in Berlin (holiday).
    index = pd.DatetimeIndex(["2026-10-02T21:00Z", "2026-10-02T22:00Z", "2026-10-05T10:00Z"])
    features = calendar_features(index)
    assert list(features.columns) == ["hour", "weekday", "holiday"]
    assert features["hour"].tolist() == [23, 0, 12]
    assert features["weekday"].tolist() == [4, 5, 0]
    assert features["holiday"].tolist() == [0, 1, 0]
    assert features.index.equals(index)


def test_calendar_features_on_dst_change() -> None:
    # Fall-back day 2026-10-25: Berlin 02:00 occurs twice (00:00 and 01:00 UTC).
    index = pd.date_range("2026-10-25T00:00Z", periods=3, freq="h")
    assert calendar_features(index)["hour"].tolist() == [2, 2, 3]


def test_calendar_features_reject_naive_index() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        calendar_features(pd.DatetimeIndex(["2026-01-01T00:00"]))


def _s(values: list[float], start: str = "2026-01-01T00:00Z") -> pd.Series:
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="h"))


def test_score_mae_and_mape_on_common_hours() -> None:
    actual = _s([10_000.0, 20_000.0, 500.0, float("nan")])
    predicted = _s([11_000.0, 18_000.0, 700.0, 1.0])
    result = score(actual, predicted)
    assert result.points == 3
    assert result.mae == pytest.approx((1000 + 2000 + 200) / 3)
    # 500 MW is below the MAPE floor and excluded from MAPE only.
    assert result.mape == pytest.approx((10.0 + 10.0) / 2)


def test_score_aligns_indexes() -> None:
    actual = _s([10_000.0, 10_000.0])
    predicted = _s([12_000.0], start="2026-01-01T01:00Z")
    assert score(actual, predicted) == Scores(mae=2000.0, mape=20.0, points=1)


def test_score_without_hours_above_floor_has_nan_mape() -> None:
    result = score(_s([100.0]), _s([150.0]))
    assert result.mae == 50.0
    assert math.isnan(result.mape)
    assert MAPE_FLOOR_MW == 1000.0


def test_score_requires_overlap() -> None:
    with pytest.raises(ValueError, match="no common"):
        score(_s([1.0]), _s([1.0], start="2027-01-01T00:00Z"))


def test_beats_needs_both_metrics_better() -> None:
    official = Scores(mae=1000.0, mape=5.0, points=10)
    assert beats(Scores(900.0, 4.0, 10), official)
    assert not beats(Scores(900.0, 6.0, 10), official)
    assert not beats(Scores(1100.0, 4.0, 10), official)
    assert not beats(Scores(900.0, float("nan"), 10), official)
