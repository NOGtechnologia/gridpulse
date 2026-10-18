from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pandera.errors
import pytest

from gridpulse.domain.metrics import Kind, MetricId
from gridpulse.domain.observations import concat_frames, empty_frame, make_frame
from gridpulse.domain.rules import EventCategory
from gridpulse.validation.crosscheck import crosscheck
from gridpulse.validation.plausibility import (
    PlausibilityConfig,
    check_balance,
    check_frequency_range,
    check_non_negative,
    check_price_range,
    check_pv_at_night,
    check_time_axis,
    run_all,
)
from gridpulse.validation.schemas import validate_frame

NIGHT = datetime(2026, 1, 15, 0, tzinfo=UTC)
NOON = datetime(2026, 6, 21, 11, tzinfo=UTC)
Q = timedelta(minutes=15)
CFG = PlausibilityConfig()


def _frame(
    metric: MetricId,
    values: list[float],
    *,
    start: datetime = NOON,
    area: str = "DE",
    source: str = "test",
    kind: Kind = Kind.ACTUAL,
    step: timedelta = Q,
) -> pd.DataFrame:
    return make_frame(
        timestamps=[start + i * step for i in range(len(values))],
        values=values,
        metric=metric,
        area=area,
        kind=kind,
        source=source,
        resolution=step,
    )


# --- schema --------------------------------------------------------------------


def test_schema_accepts_canonical_frame() -> None:
    frame = _frame(MetricId.LOAD_ACTUAL, [1.0, 2.0])
    assert validate_frame(frame).equals(frame)
    assert validate_frame(empty_frame()).empty


def test_schema_rejects_wrong_unit_and_metric() -> None:
    frame = _frame(MetricId.LOAD_ACTUAL, [1.0, 2.0])
    frame.loc[0, "unit"] = "GW"
    frame.loc[1, "metric"] = "nonsense"
    with pytest.raises(pandera.errors.SchemaErrors) as info:
        validate_frame(frame)
    text = str(info.value)
    assert "isin" in text or "nonsense" in text
    assert "unit does not match" in text


def test_schema_rejects_non_finite_and_naive_ts() -> None:
    frame = _frame(MetricId.LOAD_ACTUAL, [1.0])
    frame.loc[0, "value"] = float("inf")
    with pytest.raises(pandera.errors.SchemaErrors):
        validate_frame(frame)
    naive = _frame(MetricId.LOAD_ACTUAL, [1.0])
    naive["ts"] = naive["ts"].dt.tz_localize(None)
    with pytest.raises(pandera.errors.SchemaErrors):
        validate_frame(naive)


# --- plausibility ---------------------------------------------------------------


def test_frequency_range() -> None:
    frame = _frame(MetricId.GRID_FREQUENCY, [50.0, 48.9, 51.2])
    violations = check_frequency_range(frame, CFG)
    assert [v.threshold for v in violations] == [49.0, 51.0]
    assert all(v.rule_id == "PLAUS-001" for v in violations)


def test_non_negative_allows_flows_and_prices() -> None:
    frame = concat_frames(
        [
            _frame(MetricId.GENERATION_WIND_ONSHORE, [-1.0, 5.0]),
            _frame(MetricId.FLOW_NET_IMPORT, [-3000.0]),
            _frame(MetricId.PRICE_DAY_AHEAD, [-50.0]),
            _frame(MetricId.CONSUMPTION_PUMPED_STORAGE, [-2.0]),
        ]
    )
    violations = check_non_negative(frame)
    assert sorted(v.metric for v in violations) == [
        "consumption.pumped_storage",
        "generation.wind_onshore",
    ]


def test_pv_at_night() -> None:
    night = _frame(MetricId.GENERATION_SOLAR, [10.0, 500.0], start=NIGHT)
    day = _frame(MetricId.GENERATION_SOLAR, [30_000.0], start=NOON)
    fr = _frame(MetricId.GENERATION_SOLAR, [500.0], start=NIGHT, area="FR")
    violations = check_pv_at_night(concat_frames([night, day, fr]), CFG)
    assert [v.value for v in violations] == [500.0]
    assert violations[0].rule_id == "PLAUS-003"
    assert check_pv_at_night(_frame(MetricId.GENERATION_SOLAR, [1.0], start=NIGHT), CFG) == []


def test_price_range() -> None:
    violations = check_price_range(_frame(MetricId.PRICE_DAY_AHEAD, [-501.0, 0.0, 4001.0]), CFG)
    assert len(violations) == 2


def test_time_axis_duplicates_and_gaps() -> None:
    frame = _frame(MetricId.LOAD_ACTUAL, [1.0, 2.0, 3.0, 4.0])
    frame.loc[1, "ts"] = frame.loc[0, "ts"]  # ts: 0, 0, 2Q, 3Q
    gap = _frame(MetricId.LOAD_ACTUAL, [1.0], start=NOON + 10 * Q)
    violations = check_time_axis(concat_frames([frame, gap]))
    messages = [v.message for v in violations]
    assert any("Duplicate" in m for m in messages)
    gaps = [v for v in violations if v.message.startswith("Gap")]
    assert [g.value for g in gaps] == [1.0, 6.0]


def test_balance() -> None:
    ok = concat_frames(
        [
            _frame(MetricId.GENERATION_GAS, [40_000.0, 40_000.0]),
            _frame(MetricId.FLOW_NET_IMPORT, [5_000.0, 5_000.0]),
            _frame(MetricId.CONSUMPTION_PUMPED_STORAGE, [1_000.0, 1_000.0]),
            _frame(MetricId.LOAD_ACTUAL, [44_000.0, 30_000.0]),
        ]
    )
    violations = check_balance(ok, CFG)
    assert len(violations) == 1
    assert violations[0].value == pytest.approx(14_000 / 30_000)
    no_import = concat_frames(
        [_frame(MetricId.GENERATION_GAS, [1.0]), _frame(MetricId.LOAD_ACTUAL, [9.0])]
    )
    assert check_balance(no_import, CFG) == []
    no_pumped = concat_frames(
        [
            _frame(MetricId.GENERATION_GAS, [10.0]),
            _frame(MetricId.FLOW_NET_IMPORT, [0.0]),
            _frame(MetricId.LOAD_ACTUAL, [10.0]),
        ]
    )
    assert check_balance(no_pumped, CFG) == []


def test_run_all_and_event_conversion() -> None:
    assert run_all(empty_frame()) == []
    violations = run_all(_frame(MetricId.GRID_FREQUENCY, [10.0]))
    event = violations[0].to_event()
    assert event.category is EventCategory.DATA_QUALITY
    assert event.rule_id == "PLAUS-001"


# --- crosscheck -------------------------------------------------------------------


def test_crosscheck() -> None:
    idx = pd.date_range(NOON, periods=4, freq="15min")
    a = pd.Series([100.0, 100.0, 0.2, 50.0], index=idx)
    b = pd.Series([102.0, 120.0, 0.0], index=idx[:3])
    result = crosscheck(
        a,
        b,
        metric=MetricId.LOAD_ACTUAL,
        area="DE",
        primary_source="smard",
        secondary_source="energy_charts",
        tolerance=0.05,
        floor=10.0,
    )
    assert result.compared_points == 3
    assert [v.ts for v in result.violations] == [idx[1].to_pydatetime()]
    assert result.violations[0].source == "smard|energy_charts"
    assert result.deviation_ratio == pytest.approx(1 / 3)
    empty = crosscheck(
        a.iloc[:0],
        b,
        metric=MetricId.LOAD_ACTUAL,
        area="DE",
        primary_source="a",
        secondary_source="b",
        tolerance=0.05,
    )
    assert empty.deviation_ratio == 0.0
