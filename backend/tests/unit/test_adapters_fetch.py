"""Adapter fetch logic with mocked HTTP (respx) and ENTSO-E parsing."""

from __future__ import annotations

import random
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import pandas as pd
import pytest
import respx

from gridpulse.adapters.base import (
    USER_AGENT,
    HttpFetcher,
    RawPayload,
    SourceAdapter,
    SourceUnavailableError,
    UnsupportedMetricError,
)
from gridpulse.adapters.energy_charts import EnergyChartsAdapter
from gridpulse.adapters.entsoe import EntsoeAdapter, parse_resolution
from gridpulse.adapters.open_meteo import Location, OpenMeteoAdapter
from gridpulse.adapters.registry import build_adapters, license_for
from gridpulse.adapters.smard import SmardAdapter, chunks_needed
from gridpulse.domain.metrics import Kind, MetricId
from gridpulse.validation.schemas import validate_frame

Loader = Callable[[str, str], Any]
NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as c:
        yield c


def _fetcher(client: httpx.AsyncClient, attempts: int = 3) -> HttpFetcher:
    return HttpFetcher(
        client, max_attempts=attempts, base_delay=0.0, max_delay=0.0, rng=random.Random(1)
    )


# --- HttpFetcher ------------------------------------------------------------------


@respx.mock
async def test_fetcher_retries_then_succeeds(client: httpx.AsyncClient) -> None:
    route = respx.get("https://x.test/a").mock(
        side_effect=[
            httpx.Response(503),
            httpx.ConnectError("boom"),
            httpx.Response(200, json={"ok": 1}),
        ]
    )
    assert await _fetcher(client).get_json("https://x.test/a") == {"ok": 1}
    assert route.call_count == 3
    assert route.calls[0].request.headers["User-Agent"] == USER_AGENT


@respx.mock
async def test_fetcher_gives_up(client: httpx.AsyncClient) -> None:
    respx.get("https://x.test/a").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "0"})
    )
    with pytest.raises(SourceUnavailableError):
        await _fetcher(client, attempts=2).get("https://x.test/a")


@respx.mock
async def test_fetcher_does_not_retry_client_errors(client: httpx.AsyncClient) -> None:
    route = respx.get("https://x.test/a").mock(return_value=httpx.Response(404))
    with pytest.raises(httpx.HTTPStatusError):
        await _fetcher(client).get("https://x.test/a")
    assert route.call_count == 1


def test_fetcher_delay_bounds() -> None:
    fetcher = HttpFetcher(
        cast("httpx.AsyncClient", None), base_delay=1.0, max_delay=8.0, rng=random.Random(0)
    )
    assert fetcher._delay(0, "5") == 5.0
    assert fetcher._delay(0, "999") == 8.0
    assert all(0 <= fetcher._delay(a, None) <= min(8.0, 2**a) for a in range(6))


# --- SMARD -----------------------------------------------------------------------


def test_chunks_needed() -> None:
    week = 7 * 24 * 3600 * 1000
    index = [0, week, 2 * week]
    start = datetime.fromtimestamp(week / 1000 + 10, tz=UTC)
    end = datetime.fromtimestamp(2 * week / 1000 + 10, tz=UTC)
    assert chunks_needed(index, start, end) == [week, 2 * week]
    assert (
        chunks_needed(index, datetime(1960, 1, 1, tzinfo=UTC), datetime(1960, 1, 2, tzinfo=UTC))
        == []
    )


@respx.mock
async def test_smard_fetch_and_parse(client: httpx.AsyncClient, load_fixture: Loader) -> None:
    series = load_fixture("smard", "series_4067_DE_quarterhour.json")
    first_ms = series["series"][0][0]
    respx.get("https://www.smard.de/app/chart_data/4067/DE/index_quarterhour.json").mock(
        return_value=httpx.Response(200, json={"timestamps": [first_ms]})
    )
    respx.get(
        f"https://www.smard.de/app/chart_data/4067/DE/4067_DE_quarterhour_{first_ms}.json"
    ).mock(return_value=httpx.Response(200, json=series))
    adapter = SmardAdapter(_fetcher(client))
    start = datetime.fromtimestamp(first_ms / 1000, tz=UTC)
    payload = await adapter.fetch(
        MetricId.GENERATION_WIND_ONSHORE, start, start + timedelta(hours=2)
    )
    frame = adapter.parse(payload)
    validate_frame(frame)
    assert len(frame) == 8
    assert adapter.parse(
        RawPayload("smard", MetricId.GENERATION_WIND_ONSHORE, start, start, [series])
    ).empty


async def test_smard_rejects_unsupported() -> None:
    adapter = SmardAdapter(cast("HttpFetcher", None), kind=Kind.FORECAST)
    assert MetricId.LOAD_ACTUAL in adapter.supported_metrics()
    with pytest.raises(UnsupportedMetricError):
        await adapter.fetch(MetricId.GRID_FREQUENCY, NOW, NOW)
    with pytest.raises(ValueError, match="resolution"):
        SmardAdapter(cast("HttpFetcher", None), resolution="minute")


# --- Energy-Charts -------------------------------------------------------------------


@respx.mock
async def test_energy_charts_fetch_uses_cache(
    client: httpx.AsyncClient, load_fixture: Loader
) -> None:
    route = respx.get("https://api.energy-charts.info/public_power").mock(
        return_value=httpx.Response(200, json=load_fixture("energy_charts", "public_power.json"))
    )
    adapter = EnergyChartsAdapter(_fetcher(client))
    start = datetime(2000, 1, 1, tzinfo=UTC)
    end = datetime(2100, 1, 1, tzinfo=UTC)
    wind = adapter.parse(await adapter.fetch(MetricId.GENERATION_WIND_ONSHORE, start, end))
    solar = adapter.parse(await adapter.fetch(MetricId.GENERATION_SOLAR, start, end))
    assert route.call_count == 1
    assert not wind.empty and not solar.empty
    assert route.calls[0].request.url.params["start"] == "2000-01-01T00:00Z"
    adapter.clear_cache()
    await adapter.fetch(MetricId.GENERATION_SOLAR, start, end)
    assert route.call_count == 2


@respx.mock
async def test_energy_charts_endpoints(client: httpx.AsyncClient, load_fixture: Loader) -> None:
    for name in ("price", "frequency", "cbet", "ren_share_forecast"):
        respx.get(f"https://api.energy-charts.info/{name}").mock(
            return_value=httpx.Response(200, json=load_fixture("energy_charts", f"{name}.json"))
        )
    adapter = EnergyChartsAdapter(_fetcher(client))
    start, end = datetime(2000, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC)
    assert not adapter.parse(await adapter.fetch(MetricId.PRICE_DAY_AHEAD, start, end)).empty
    assert not adapter.parse(await adapter.fetch(MetricId.GRID_FREQUENCY, start, end)).empty
    assert not adapter.parse(await adapter.fetch_border_flows(start, end)).empty
    fc = adapter.parse(
        await adapter.fetch(MetricId.INDICATOR_RENEWABLE_SHARE, start, end, Kind.FORECAST)
    )
    assert set(fc["kind"]) == {"forecast"}
    with pytest.raises(UnsupportedMetricError):
        adapter.endpoint_for(MetricId.LOAD_ACTUAL, Kind.FORECAST)
    with pytest.raises(UnsupportedMetricError):
        adapter.endpoint_for(MetricId.WEATHER_TEMPERATURE)
    assert MetricId.GRID_FREQUENCY in adapter.supported_metrics()


def test_energy_charts_parse_edge_cases() -> None:
    adapter = EnergyChartsAdapter(cast("HttpFetcher", None))
    start, end = datetime(2000, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC)
    doc = {
        "unix_seconds": [946684800],
        "production_types": [
            {"name": "Solar", "data": [None]},
            {"name": "Unknown thing", "data": [1.0]},
        ],
    }
    solar = RawPayload(
        "energy_charts", MetricId.GENERATION_SOLAR, start, end, [doc], {"endpoint": "public_power"}
    )
    assert adapter.parse(solar).empty
    gas = RawPayload(
        "energy_charts", MetricId.GENERATION_GAS, start, end, [doc], {"endpoint": "public_power"}
    )
    assert adapter.parse(gas).empty
    freq = RawPayload(
        "energy_charts",
        MetricId.GRID_FREQUENCY,
        start,
        end,
        [{"unix_seconds": [946684800], "data": [None]}],
        {"endpoint": "frequency"},
    )
    assert adapter.parse(freq).empty
    cbet = RawPayload(
        "energy_charts",
        MetricId.FLOW_NET_IMPORT,
        start,
        end,
        [{"unix_seconds": [946684800], "countries": [{"name": "Atlantis", "data": [1.0]}]}],
        {"endpoint": "cbet"},
    )
    assert adapter.parse(cbet).empty


# --- Open-Meteo ------------------------------------------------------------------


@respx.mock
async def test_open_meteo_fetch(client: httpx.AsyncClient, load_fixture: Loader) -> None:
    route = respx.get("https://api.open-meteo.com/v1/forecast").mock(
        return_value=httpx.Response(200, json=load_fixture("open_meteo", "forecast_multi.json"))
    )
    locations = [Location("a", 1.0, 2.0), Location("b", 3.0, 4.0), Location("c", 5.0, 6.0)]
    adapter = OpenMeteoAdapter(_fetcher(client), locations)
    now = datetime.now(UTC)
    payload = await adapter.fetch(
        MetricId.WEATHER_TEMPERATURE, now - timedelta(days=2), now + timedelta(days=3)
    )
    params = route.calls[0].request.url.params
    assert params["latitude"] == "1.0,3.0,5.0"
    assert params["past_days"] == "3"
    assert set(adapter.parse(payload)["area"]) == {"WX:a", "WX:b", "WX:c"}
    # History for the forecasting model: past_days follows the window, capped at the API's 92.
    await adapter.fetch(MetricId.WEATHER_TEMPERATURE, now - timedelta(days=400), now)
    assert route.calls[1].request.url.params["past_days"] == "92"
    await adapter.fetch(MetricId.WEATHER_TEMPERATURE, now, now + timedelta(hours=1))
    assert route.calls[2].request.url.params["past_days"] == "1"
    with pytest.raises(UnsupportedMetricError):
        await adapter.fetch(MetricId.LOAD_ACTUAL, now, now)
    assert MetricId.WEATHER_TEMPERATURE in adapter.supported_metrics()
    with pytest.raises(ValueError, match="location"):
        OpenMeteoAdapter(_fetcher(client), [])
    single = OpenMeteoAdapter(_fetcher(client), locations[:1])
    one = load_fixture("open_meteo", "forecast_multi.json")[0]
    frame = single.parse(
        RawPayload(
            "open_meteo",
            MetricId.WEATHER_CLOUD_COVER,
            now - timedelta(days=9),
            now + timedelta(days=9),
            [one],
        )
    )
    assert set(frame["area"]) == {"WX:a"}


# --- ENTSO-E -------------------------------------------------------------------------


def _entsoe_payload(metric: MetricId, xml: str) -> RawPayload:
    return RawPayload(
        "entsoe",
        metric,
        datetime(2000, 1, 1, tzinfo=UTC),
        datetime(2100, 1, 1, tzinfo=UTC),
        [xml],
        {"area": "DE-LU"},
    )


def test_entsoe_parse_load(load_fixture: Loader) -> None:
    adapter = EntsoeAdapter(cast("HttpFetcher", None), "token")
    frame = adapter.parse(
        _entsoe_payload(MetricId.LOAD_ACTUAL, load_fixture("entsoe", "actual_load_A65.xml"))
    )
    validate_frame(frame)
    assert frame["value"].tolist() == [44185.0, 43508.0, 42870.0, 42311.0]
    assert frame["ts"].iloc[0].isoformat() == "2026-10-17T22:00:00+00:00"


def test_entsoe_parse_prices_fills_a03_gaps(load_fixture: Loader) -> None:
    adapter = EntsoeAdapter(cast("HttpFetcher", None), "token")
    frame = adapter.parse(
        _entsoe_payload(MetricId.PRICE_DAY_AHEAD, load_fixture("entsoe", "day_ahead_A44.xml"))
    )
    validate_frame(frame)
    assert frame["value"].tolist() == [209.27, -1.5, -1.5, 199.67]


def test_entsoe_acknowledgement_and_errors(load_fixture: Loader) -> None:
    adapter = EntsoeAdapter(cast("HttpFetcher", None), "token")
    with pytest.raises(ValueError, match="No matching data"):
        adapter.parse(
            _entsoe_payload(
                MetricId.LOAD_ACTUAL, load_fixture("entsoe", "acknowledgement_no_data.xml")
            )
        )
    broken = "<GL_MarketDocument><TimeSeries><Period></Period></TimeSeries></GL_MarketDocument>"
    with pytest.raises(ValueError, match="Period without"):
        adapter.parse(_entsoe_payload(MetricId.LOAD_ACTUAL, broken))
    no_start = (
        "<GL_MarketDocument><TimeSeries><Period><timeInterval></timeInterval>"
        "<resolution>PT15M</resolution></Period></TimeSeries></GL_MarketDocument>"
    )
    with pytest.raises(ValueError, match="without start"):
        adapter.parse(_entsoe_payload(MetricId.LOAD_ACTUAL, no_start))
    with pytest.raises(ValueError, match="token"):
        EntsoeAdapter(cast("HttpFetcher", None), "")
    with pytest.raises(ValueError, match="area"):
        EntsoeAdapter(cast("HttpFetcher", None), "t", area="XX")


def test_entsoe_skips_incomplete_points_and_respects_window() -> None:
    xml = (
        "<GL_MarketDocument><TimeSeries><Period><timeInterval><start>2026-01-01T00:00Z</start>"
        "<end>2026-01-01T01:00Z</end></timeInterval><resolution>PT30M</resolution>"
        "<Point><position>1</position><quantity>5</quantity></Point>"
        "<Point><position>2</position></Point>"
        "</Period></TimeSeries></GL_MarketDocument>"
    )
    adapter = EntsoeAdapter(cast("HttpFetcher", None), "token")
    payload = RawPayload(
        "entsoe",
        MetricId.LOAD_ACTUAL,
        datetime(2026, 1, 1, 0, 30, tzinfo=UTC),
        datetime(2026, 1, 2, tzinfo=UTC),
        [xml],
        {"area": "DE-LU"},
    )
    frame = adapter.parse(payload)
    assert frame["value"].tolist() == [5.0]  # position 2 forward-filled, position 1 outside window
    assert frame["ts"].iloc[0].isoformat() == "2026-01-01T00:30:00+00:00"


def test_entsoe_keeps_finest_resolution_for_overlapping_series() -> None:
    """Since the 15-min day-ahead MTU some zones publish PT60M and PT15M series side by side."""

    def series(resolution: str, values: list[float]) -> str:
        points = "".join(
            f"<Point><position>{i}</position><price.amount>{v}</price.amount></Point>"
            for i, v in enumerate(values, start=1)
        )
        return (
            "<TimeSeries><Period><timeInterval><start>2026-01-01T00:00Z</start>"
            f"<end>2026-01-01T01:00Z</end></timeInterval><resolution>{resolution}</resolution>"
            f"{points}</Period></TimeSeries>"
        )

    xml = (
        "<Publication_MarketDocument>"
        + series("PT60M", [50.0])
        + series("PT15M", [10.0, 20.0, 30.0, 40.0])
        + "</Publication_MarketDocument>"
    )
    frame = EntsoeAdapter(cast("HttpFetcher", None), "token").parse(
        _entsoe_payload(MetricId.PRICE_DAY_AHEAD, xml)
    )
    validate_frame(frame)
    assert frame["value"].tolist() == [10.0, 20.0, 30.0, 40.0]
    assert set(frame["resolution"]) == {pd.Timedelta(minutes=15)}


def test_entsoe_rejects_billion_laughs() -> None:
    adapter = EntsoeAdapter(cast("HttpFetcher", None), "token")
    evil = (
        '<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaa">]>'
        "<GL_MarketDocument>&a;</GL_MarketDocument>"
    )
    with pytest.raises(Exception, match=r"(?i)entit"):
        adapter.parse(_entsoe_payload(MetricId.LOAD_ACTUAL, evil))


@pytest.mark.parametrize(
    ("text", "delta"),
    [
        ("PT15M", timedelta(minutes=15)),
        ("PT60M", timedelta(hours=1)),
        ("PT1H", timedelta(hours=1)),
        ("P1D", timedelta(days=1)),
    ],
)
def test_parse_resolution(text: str, delta: timedelta) -> None:
    assert parse_resolution(text) == delta


def test_parse_resolution_rejects() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        parse_resolution("P1Y")


@respx.mock
async def test_entsoe_fetch_hides_token_in_params(
    client: httpx.AsyncClient, load_fixture: Loader
) -> None:
    route = respx.get("https://web-api.tp.entsoe.eu/api").mock(
        return_value=httpx.Response(200, text=load_fixture("entsoe", "day_ahead_A44.xml"))
    )
    adapter = EntsoeAdapter(_fetcher(client), "secret-token")
    payload = await adapter.fetch(MetricId.PRICE_DAY_AHEAD, NOW, NOW + timedelta(days=1))
    params = route.calls[0].request.url.params
    assert params["in_Domain"] == params["out_Domain"] == "10Y1001A1001A82H"
    assert "secret-token" not in repr(payload.params)
    await adapter.fetch(MetricId.LOAD_ACTUAL, NOW, NOW + timedelta(days=1))
    assert route.calls[1].request.url.params["outBiddingZone_Domain"] == "10Y1001A1001A82H"
    with pytest.raises(UnsupportedMetricError):
        await adapter.fetch(MetricId.GRID_FREQUENCY, NOW, NOW)
    assert adapter.supported_metrics() == {MetricId.LOAD_ACTUAL, MetricId.PRICE_DAY_AHEAD}


# --- registry ---------------------------------------------------------------------


async def test_registry(client: httpx.AsyncClient) -> None:
    ids = [a.source_id for a in build_adapters(client)]
    assert ids == ["smard", "energy_charts", "open_meteo"]
    with_token = build_adapters(client, entsoe_token="t")
    assert [a.source_id for a in with_token][-1] == "entsoe"
    assert all(isinstance(a, SourceAdapter) for a in with_token)
    assert license_for("smard") == ("CC BY 4.0", "Bundesnetzagentur | SMARD.de")
    lic, attr = license_for("smard|energy_charts")
    assert lic == "CC BY 4.0"
    assert "Fraunhofer" in attr
    assert license_for("mystery") == ("unknown", "mystery")
