"""Contract tests: adapter ``parse()`` against stored original responses (spec 7.2).

The fixtures were recorded with ``scripts/verify_sources.py --save-fixtures``. Every
test validates the parsed frame against the canonical pandera schema.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pandas as pd
import pytest

from gridpulse.adapters.base import HttpFetcher, RawPayload
from gridpulse.adapters.energy_charts import EnergyChartsAdapter, border_area
from gridpulse.adapters.open_meteo import OpenMeteoAdapter, weather_area
from gridpulse.adapters.smard import SmardAdapter
from gridpulse.domain.metrics import Kind, MetricId
from gridpulse.validation.schemas import validate_frame

Loader = Callable[[str, str], Any]
ALL_TIME = (datetime(2000, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC))
# parse() is pure and never touches the fetcher.
FETCHER = cast("HttpFetcher", None)


def _payload(source: str, metric: MetricId, docs: list[Any], **params: Any) -> RawPayload:
    return RawPayload(source, metric, ALL_TIME[0], ALL_TIME[1], docs, params)


# --- SMARD ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fixture", "metric", "kind", "region"),
    [
        ("series_4067_DE_quarterhour.json", MetricId.GENERATION_WIND_ONSHORE, Kind.ACTUAL, "DE"),
        ("series_4068_DE_quarterhour.json", MetricId.GENERATION_SOLAR, Kind.ACTUAL, "DE"),
        ("series_4071_DE_quarterhour.json", MetricId.GENERATION_GAS, Kind.ACTUAL, "DE"),
        ("series_410_DE_quarterhour.json", MetricId.LOAD_ACTUAL, Kind.ACTUAL, "DE"),
        ("series_4359_DE_quarterhour.json", MetricId.LOAD_RESIDUAL, Kind.ACTUAL, "DE"),
        ("series_411_DE_quarterhour.json", MetricId.LOAD_ACTUAL, Kind.FORECAST, "DE"),
        ("series_123_DE_quarterhour.json", MetricId.GENERATION_WIND_ONSHORE, Kind.FORECAST, "DE"),
        ("series_125_DE_quarterhour.json", MetricId.GENERATION_SOLAR, Kind.FORECAST, "DE"),
        ("series_4169_DE-LU_quarterhour.json", MetricId.PRICE_DAY_AHEAD, Kind.ACTUAL, "DE-LU"),
    ],
)
def test_smard_parse_quarterhour(
    load_fixture: Loader, fixture: str, metric: MetricId, kind: Kind, region: str
) -> None:
    raw = load_fixture("smard", fixture)
    adapter = SmardAdapter(FETCHER, kind=kind)
    frame = adapter.parse(
        _payload("smard", metric, [raw], resolution="quarterhour", region=region, kind=kind.value)
    )
    validate_frame(frame)
    non_null = [v for _, v in raw["series"] if v is not None]
    assert len(frame) == len(non_null) > 0
    assert set(frame["kind"]) == {kind.value}
    assert set(frame["area"]) == {region}
    assert (frame["resolution"] == pd.Timedelta(minutes=15)).all()
    factor = 1.0 if metric is MetricId.PRICE_DAY_AHEAD else 4.0  # MWh per 15 min -> MW
    assert frame["value"].iloc[0] == pytest.approx(non_null[0] * factor)


def test_smard_hourly_values_equal_mw(load_fixture: Loader) -> None:
    raw = load_fixture("smard", "series_4067_DE_hour.json")
    frame = SmardAdapter(FETCHER, resolution="hour").parse(
        _payload("smard", MetricId.GENERATION_WIND_ONSHORE, [raw], resolution="hour")
    )
    validate_frame(frame)
    first = next(v for _, v in raw["series"] if v is not None)
    assert frame["value"].iloc[0] == pytest.approx(first)
    assert (frame["resolution"] == pd.Timedelta(hours=1)).all()


def test_smard_parse_respects_window(load_fixture: Loader) -> None:
    raw = load_fixture("smard", "series_410_DE_quarterhour.json")
    start = datetime.fromtimestamp(raw["series"][10][0] / 1000, tz=UTC)
    payload = RawPayload(
        "smard",
        MetricId.LOAD_ACTUAL,
        start,
        start + timedelta(hours=1),
        [raw],
        {"resolution": "quarterhour"},
    )
    frame = SmardAdapter(FETCHER).parse(payload)
    assert len(frame) == 4
    assert frame["ts"].iloc[0] == pd.Timestamp(start)


def test_smard_index_fixture_shape(load_fixture: Loader) -> None:
    index = load_fixture("smard", "index_4067_DE_quarterhour.json")
    stamps = index["timestamps"]
    assert stamps == sorted(stamps)
    # Chunks start at local Monday midnight -> spacing of exactly 7 days in local time.
    assert all(
        timedelta(days=6, hours=23) <= timedelta(milliseconds=b - a) <= timedelta(days=7, hours=1)
        for a, b in zip(stamps[-10:], stamps[-9:], strict=False)
    )


# --- Energy-Charts ------------------------------------------------------------------


def _ec(load_fixture: Loader, name: str, metric: MetricId, endpoint: str) -> pd.DataFrame:
    raw = load_fixture("energy_charts", f"{name}.json")
    adapter = EnergyChartsAdapter(FETCHER)
    frame = adapter.parse(
        _payload("energy_charts", metric, [raw], endpoint=endpoint, area="DE", bidding_zone="DE-LU")
    )
    validate_frame(frame)
    return frame


def _production(load_fixture: Loader, name: str) -> list[float | None]:
    raw = load_fixture("energy_charts", "public_power.json")
    return next(p["data"] for p in raw["production_types"] if p["name"] == name)


@pytest.mark.parametrize(
    ("metric", "source_name"),
    [
        (MetricId.GENERATION_WIND_ONSHORE, "Wind onshore"),
        (MetricId.GENERATION_SOLAR, "Solar"),
        (MetricId.GENERATION_LIGNITE, "Fossil brown coal / lignite"),
        (MetricId.LOAD_ACTUAL, "Load"),
        (MetricId.FLOW_NET_IMPORT, "Cross border electricity trading"),
    ],
)
def test_energy_charts_public_power(
    load_fixture: Loader, metric: MetricId, source_name: str
) -> None:
    frame = _ec(load_fixture, "public_power", metric, "public_power")
    expected = [v for v in _production(load_fixture, source_name) if v is not None]
    assert frame["value"].tolist() == pytest.approx(expected)
    assert (frame["resolution"] == pd.Timedelta(minutes=15)).all()


def test_energy_charts_sums_hydro_and_flips_pumped_consumption(load_fixture: Loader) -> None:
    hydro = _ec(load_fixture, "public_power", MetricId.GENERATION_HYDRO, "public_power")
    ror = _production(load_fixture, "Hydro Run-of-River")
    res = _production(load_fixture, "Hydro water reservoir")
    assert hydro["value"].iloc[0] == pytest.approx((ror[0] or 0) + (res[0] or 0))
    pumped = _ec(load_fixture, "public_power", MetricId.CONSUMPTION_PUMPED_STORAGE, "public_power")
    assert (pumped["value"] >= 0).all()


def test_energy_charts_price(load_fixture: Loader) -> None:
    frame = _ec(load_fixture, "price", MetricId.PRICE_DAY_AHEAD, "price")
    raw = load_fixture("energy_charts", "price.json")
    assert raw["unit"] == "EUR / MWh"
    assert frame["value"].tolist() == pytest.approx([v for v in raw["price"] if v is not None])
    assert set(frame["area"]) == {"DE-LU"}


def test_energy_charts_frequency_keeps_worst_sample(load_fixture: Loader) -> None:
    frame = _ec(load_fixture, "frequency", MetricId.GRID_FREQUENCY, "frequency")
    raw = load_fixture("energy_charts", "frequency.json")
    assert len(frame) == pytest.approx(len(raw["data"]) / 10, abs=2)
    first_bucket = [
        v
        for s, v in zip(raw["unix_seconds"], raw["data"], strict=True)
        if s - s % 10 == raw["unix_seconds"][0] - raw["unix_seconds"][0] % 10 and v is not None
    ]
    worst = max(first_bucket, key=lambda v: abs(v - 50))
    assert frame["value"].iloc[0] == pytest.approx(worst)
    assert frame["value"].between(49, 51).all()


def test_energy_charts_cbet_in_mw_with_border_areas(load_fixture: Loader) -> None:
    raw = load_fixture("energy_charts", "cbet.json")
    adapter = EnergyChartsAdapter(FETCHER)
    frame = adapter.parse(
        _payload("energy_charts", MetricId.FLOW_NET_IMPORT, [raw], endpoint="cbet", area="DE")
    )
    validate_frame(frame)
    france = frame[frame["area"] == border_area("DE", "FR")]
    fr_raw = next(c["data"] for c in raw["countries"] if c["name"] == "France")
    assert france["value"].iloc[0] == pytest.approx(fr_raw[0] * 1000)
    total = frame[frame["area"] == "DE"]["value"].iloc[0]
    public = _production(load_fixture, "Cross border electricity trading")[0]
    assert total == pytest.approx(public, abs=1.0)  # both endpoints agree on the net flow


def test_energy_charts_ren_share_forecast(load_fixture: Loader) -> None:
    frame = _ec(
        load_fixture, "ren_share_forecast", MetricId.INDICATOR_RENEWABLE_SHARE, "ren_share_forecast"
    )
    assert set(frame["kind"]) == {"forecast"}
    assert frame["value"].between(0, 100).all()


def test_energy_charts_unknown_endpoint() -> None:
    with pytest.raises(ValueError, match="unknown endpoint"):
        EnergyChartsAdapter(FETCHER).parse(
            _payload("energy_charts", MetricId.LOAD_ACTUAL, [{}], endpoint="nope")
        )


# --- Open-Meteo ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "metric",
    [
        MetricId.WEATHER_TEMPERATURE,
        MetricId.WEATHER_WIND_SPEED_100M,
        MetricId.WEATHER_SHORTWAVE_RADIATION,
        MetricId.WEATHER_CLOUD_COVER,
    ],
)
def test_open_meteo_parse(load_fixture: Loader, metric: MetricId) -> None:
    raw = load_fixture("open_meteo", "forecast_multi.json")
    names = ["hamburg", "kassel", "munich"]
    frame = OpenMeteoAdapter(FETCHER).parse(_payload("open_meteo", metric, [raw], locations=names))
    validate_frame(frame)
    assert set(frame["area"]) == {weather_area(n) for n in names}
    assert len(frame) == 3 * len(raw[0]["hourly"]["time"])
    assert set(frame["kind"]) == {"forecast"}


def test_open_meteo_past_days_drops_null_history(load_fixture: Loader) -> None:
    """past_days=92 returns null for hours older than the ~2 months the API keeps."""
    raw = load_fixture("open_meteo", "forecast_past_days.json")
    temps = raw["hourly"]["temperature_2m"]
    frame = OpenMeteoAdapter(FETCHER).parse(
        _payload("open_meteo", MetricId.WEATHER_TEMPERATURE, [raw], locations=["hamburg"])
    )
    validate_frame(frame)
    assert temps[0] is None
    assert len(frame) == sum(v is not None for v in temps) > 24 * 50
    assert frame["value"].notna().all()
    assert set(frame["area"]) == {weather_area("hamburg")}


def test_open_meteo_rejects_location_mismatch_and_non_utc(load_fixture: Loader) -> None:
    raw = load_fixture("open_meteo", "forecast_multi.json")
    adapter = OpenMeteoAdapter(FETCHER)
    with pytest.raises(ValueError, match="expected 2 locations"):
        adapter.parse(
            _payload("open_meteo", MetricId.WEATHER_TEMPERATURE, [raw], locations=["a", "b"])
        )
    shifted = {**raw[0], "utc_offset_seconds": 3600}
    with pytest.raises(ValueError, match="UTC"):
        adapter.parse(
            _payload("open_meteo", MetricId.WEATHER_TEMPERATURE, [shifted], locations=["a"])
        )
