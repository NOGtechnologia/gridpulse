from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from gridpulse.domain.co2 import co2_intensity
from gridpulse.domain.indicators import (
    Resolution,
    Window,
    aggregate,
    co2_intensity_series,
    dunkelflaute_windows,
    generation_mix,
    negative_price_windows,
    renewable_share,
    renewable_share_series,
    windows_where,
)
from gridpulse.domain.metrics import (
    CATALOG,
    GENERATION_METRICS,
    RENEWABLE_METRICS,
    Kind,
    MetricId,
    Unit,
    may_be_negative,
    unit_of,
)
from gridpulse.domain.observations import (
    COLUMNS,
    concat_frames,
    empty_frame,
    make_frame,
    series_of,
    to_observations,
)
from gridpulse.domain.residual_load import residual_load
from gridpulse.domain.solar import is_night, solar_elevation_deg
from gridpulse.domain.stats import rolling_mad_score, rolling_zscore
from gridpulse.domain.timeutils import local_day_bounds

T0 = datetime(2026, 6, 21, 0, tzinfo=UTC)
Q = timedelta(minutes=15)


def _frame(
    metric: MetricId,
    values: list[float | None],
    *,
    kind: Kind = Kind.ACTUAL,
    source: str = "test",
    area: str = "DE",
    start: datetime = T0,
) -> pd.DataFrame:
    return make_frame(
        timestamps=[start + i * Q for i in range(len(values))],
        values=values,
        metric=metric,
        area=area,
        kind=kind,
        source=source,
        resolution=Q,
    )


# --- metrics ---------------------------------------------------------------


def test_catalog_covers_every_metric() -> None:
    assert set(CATALOG) == set(MetricId)
    assert unit_of(MetricId.PRICE_DAY_AHEAD) is Unit.EUR_PER_MWH
    assert may_be_negative(MetricId.FLOW_NET_IMPORT)
    assert not may_be_negative(MetricId.GENERATION_SOLAR)
    assert MetricId.GENERATION_SOLAR in RENEWABLE_METRICS
    assert MetricId.GENERATION_GAS not in RENEWABLE_METRICS
    assert MetricId.CONSUMPTION_PUMPED_STORAGE not in GENERATION_METRICS


# --- observations ------------------------------------------------------------


def test_make_frame_drops_missing_and_sets_unit() -> None:
    frame = _frame(MetricId.GENERATION_SOLAR, [1.0, None, math.nan, 4.0])
    assert list(frame.columns) == list(COLUMNS)
    assert frame["value"].tolist() == [1.0, 4.0]
    assert set(frame["unit"]) == {"MW"}
    assert str(frame["ts"].dtype) == "datetime64[ns, UTC]"


def test_make_frame_all_missing_is_empty() -> None:
    assert _frame(MetricId.GENERATION_SOLAR, [None, None]).empty


def test_make_frame_length_mismatch() -> None:
    with pytest.raises(ValueError, match="length mismatch"):
        make_frame(
            timestamps=[T0],
            values=[1.0, 2.0],
            metric=MetricId.LOAD_ACTUAL,
            area="DE",
            kind=Kind.ACTUAL,
            source="x",
            resolution=Q,
        )


def test_concat_and_roundtrip() -> None:
    assert concat_frames([empty_frame(), empty_frame()]).empty
    frame = concat_frames(
        [_frame(MetricId.LOAD_ACTUAL, [2.0]), _frame(MetricId.GENERATION_GAS, [1.0])]
    )
    obs = to_observations(frame)
    assert [o.metric for o in obs] == [MetricId.GENERATION_GAS, MetricId.LOAD_ACTUAL]
    assert obs[0].unit == "MW"
    assert obs[0].resolution == Q
    assert obs[0].ts == T0


def test_series_of_filters_area_and_kind() -> None:
    frame = concat_frames(
        [
            _frame(MetricId.LOAD_ACTUAL, [1.0, 2.0]),
            _frame(MetricId.LOAD_ACTUAL, [9.0], area="FR"),
            _frame(MetricId.LOAD_ACTUAL, [5.0], kind=Kind.FORECAST),
        ]
    )
    assert series_of(frame, MetricId.LOAD_ACTUAL, area="DE").tolist() == [1.0, 2.0]
    assert series_of(frame, MetricId.LOAD_ACTUAL, kind=Kind.FORECAST).tolist() == [5.0]
    assert len(series_of(frame, MetricId.LOAD_ACTUAL)) == 2  # duplicate ts across areas


# --- co2 / shares ----------------------------------------------------------------


def test_co2_intensity_known_mix() -> None:
    mix = {MetricId.GENERATION_GAS: 100.0, MetricId.GENERATION_WIND_ONSHORE: 100.0}
    assert co2_intensity(mix) == pytest.approx((490 + 11) / 2)


def test_co2_ignores_unknown_and_negative() -> None:
    mix = {
        MetricId.LOAD_ACTUAL: 500.0,
        MetricId.GENERATION_GAS: -10.0,
        MetricId.GENERATION_SOLAR: 10.0,
    }
    assert co2_intensity(mix) == pytest.approx(48.0)
    assert co2_intensity({MetricId.LOAD_ACTUAL: 1.0}) is None


def test_renewable_share() -> None:
    mix = {
        MetricId.GENERATION_SOLAR: 30.0,
        MetricId.GENERATION_LIGNITE: 70.0,
        MetricId.LOAD_ACTUAL: 1e6,
    }
    assert renewable_share(mix) == pytest.approx(30.0)
    assert renewable_share({}) is None


def test_generation_mix_and_series() -> None:
    frame = concat_frames(
        [
            _frame(MetricId.GENERATION_SOLAR, [10.0, 0.0]),
            _frame(MetricId.GENERATION_GAS, [10.0, 0.0]),
            _frame(MetricId.LOAD_ACTUAL, [99.0, 99.0]),
        ]
    )
    mix = generation_mix(frame)
    assert sorted(mix.columns) == ["generation.gas", "generation.solar"]
    share = renewable_share_series(mix)
    co2 = co2_intensity_series(mix)
    assert share.iloc[0] == pytest.approx(50.0)
    assert np.isnan(share.iloc[1])
    assert co2.iloc[0] == pytest.approx((48 + 490) / 2)


def test_residual_load_inner_join() -> None:
    idx = pd.date_range(T0, periods=3, freq="15min")
    load = pd.Series([100.0, 100.0, 100.0], index=idx)
    on = pd.Series([10.0, 10.0], index=idx[:2])
    res = residual_load(load, on, on, on)
    assert res.tolist() == [70.0, 70.0]
    assert res.name == "load.residual"


# --- aggregation & windows ---------------------------------------------------------


def test_aggregate_hour_and_empty() -> None:
    idx = pd.date_range(T0, periods=8, freq="15min")
    s = pd.Series(range(8), index=idx, dtype="float64")
    assert aggregate(s, Resolution.HOUR).tolist() == [1.5, 5.5]
    assert aggregate(s, Resolution.QUARTER_HOUR).tolist() == list(range(8))
    assert aggregate(pd.Series([], dtype="float64"), Resolution.DAY).empty


def test_aggregate_day_on_25h_day() -> None:
    start, end = local_day_bounds(date(2026, 10, 25))
    idx = pd.date_range(start, end, freq="1h", inclusive="left")
    assert len(idx) == 25
    daily = aggregate(pd.Series(1.0, index=idx), Resolution.DAY)
    assert daily.index.tolist() == [pd.Timestamp(start)]


def test_resolution_delta() -> None:
    assert Resolution.DAY.delta == timedelta(days=1)
    assert Resolution.HOUR.delta == timedelta(hours=1)
    assert Resolution.QUARTER_HOUR.delta == Q


def test_windows_where_splits_on_false_and_gaps() -> None:
    idx = [T0 + i * Q for i in (0, 1, 2, 3, 5, 6)]
    mask = pd.Series([True, True, False, True, True, True], index=pd.DatetimeIndex(idx))
    windows = windows_where(mask, Q)
    assert windows == [
        Window(T0, T0 + 2 * Q),
        Window(T0 + 3 * Q, T0 + 4 * Q),
        Window(T0 + 5 * Q, T0 + 7 * Q),
    ]
    assert windows_where(mask, Q, min_duration=2 * Q) == [windows[0], windows[2]]
    assert windows_where(pd.Series([], dtype=bool), Q) == []


def test_negative_price_windows() -> None:
    idx = pd.date_range(T0, periods=4, freq="15min")
    price = pd.Series([5.0, -1.0, -2.0, 3.0], index=idx)
    assert negative_price_windows(price, Q) == [Window(T0 + Q, T0 + 3 * Q)]


def test_dunkelflaute_windows() -> None:
    idx = pd.date_range(T0, periods=6, freq="1h")
    load = pd.Series([100.0, 100.0, 100.0, 100.0, 0.0, 100.0], index=idx)
    vre = pd.Series([5.0, 5.0, 5.0, 50.0, 0.0, 1.0], index=idx)
    windows = dunkelflaute_windows(
        load, vre, step=timedelta(hours=1), share_threshold=0.1, min_duration=timedelta(hours=2)
    )
    assert windows == [Window(T0, T0 + timedelta(hours=3))]


# --- solar ---------------------------------------------------------------------


def test_solar_elevation_noon_and_midnight() -> None:
    noon = datetime(2026, 6, 21, 11, 20, tzinfo=UTC)  # ~solar noon at 10.45 E
    assert 60 < solar_elevation_deg(noon) < 64  # 90 - 51.16 + 23.44 ~= 62.3
    assert solar_elevation_deg(datetime(2026, 12, 21, 23, tzinfo=UTC)) < -50
    assert is_night(datetime(2026, 1, 15, 0, tzinfo=UTC))
    assert not is_night(noon)


# --- stats -----------------------------------------------------------------------


def test_rolling_scores_detect_outlier() -> None:
    rng = np.random.default_rng(42)
    values = rng.normal(100, 1, 50)
    values[45] = 150
    s = pd.Series(values)
    assert abs(rolling_zscore(s, 20).iloc[45]) > 10
    assert abs(rolling_mad_score(s, 20).iloc[45]) > 10
    assert np.isnan(rolling_zscore(s, 20).iloc[5])
    assert not np.isnan(rolling_mad_score(s, 20, min_periods=3).iloc[5])
    assert not np.isnan(rolling_zscore(s, 20, min_periods=3).iloc[5])


def test_rolling_scores_constant_gives_nan_not_inf() -> None:
    s = pd.Series([1.0] * 10)
    assert rolling_zscore(s, 3).isna().all()
    assert rolling_mad_score(s, 3).isna().all()


@pytest.mark.parametrize("fn", [rolling_zscore, rolling_mad_score])
def test_rolling_scores_reject_small_window(fn: Callable[[pd.Series, int], pd.Series]) -> None:
    with pytest.raises(ValueError, match="window"):
        fn(pd.Series([1.0, 2.0]), 1)
