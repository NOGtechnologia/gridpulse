"""Energy-Charts API (Fraunhofer ISE) adapter.

Endpoints (verified 2026-10-18, see docs/data-sources.md), all ``unix_seconds`` based:

* ``/public_power?country=de&start&end`` -> ``production_types[{name, data}]`` in MW
* ``/price?bzn=DE-LU&start&end`` -> ``price`` in EUR/MWh
* ``/frequency?region=DE-Freiburg&start&end`` -> ``data`` in Hz, 1 s resolution
* ``/cbet?country=de&start&end`` -> ``countries[{name, data}]`` in **GW**, positive = import
* ``/ren_share_forecast?country=de`` -> ``ren_share`` forecast in %
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from gridpulse.adapters.base import HttpFetcher, RawPayload, UnsupportedMetricError
from gridpulse.domain.metrics import Kind, MetricId
from gridpulse.domain.observations import concat_frames, empty_frame, make_frame
from gridpulse.domain.timeutils import ensure_utc, from_unix_seconds

BASE_URL = "https://api.energy-charts.info"

# Energy-Charts production type -> canonical metric. Several types may map to one
# metric; their values are summed. Sign is applied after summing.
PUBLIC_POWER_MAP: dict[str, MetricId] = {
    "Hydro pumped storage consumption": MetricId.CONSUMPTION_PUMPED_STORAGE,
    "Cross border electricity trading": MetricId.FLOW_NET_IMPORT,
    "Hydro Run-of-River": MetricId.GENERATION_HYDRO,
    "Hydro water reservoir": MetricId.GENERATION_HYDRO,
    "Biomass": MetricId.GENERATION_BIOMASS,
    "Fossil brown coal / lignite": MetricId.GENERATION_LIGNITE,
    "Fossil hard coal": MetricId.GENERATION_HARD_COAL,
    "Fossil oil": MetricId.GENERATION_OIL,
    "Fossil coal-derived gas": MetricId.GENERATION_OTHER_CONVENTIONAL,
    "Fossil gas": MetricId.GENERATION_GAS,
    "Geothermal": MetricId.GENERATION_OTHER_RENEWABLE,
    "Hydro pumped storage": MetricId.GENERATION_PUMPED_STORAGE,
    "Others": MetricId.GENERATION_OTHER_CONVENTIONAL,
    "Waste": MetricId.GENERATION_OTHER_CONVENTIONAL,
    "Nuclear": MetricId.GENERATION_NUCLEAR,
    "Wind offshore": MetricId.GENERATION_WIND_OFFSHORE,
    "Wind onshore": MetricId.GENERATION_WIND_ONSHORE,
    "Solar": MetricId.GENERATION_SOLAR,
    "Load": MetricId.LOAD_ACTUAL,
    "Residual load": MetricId.LOAD_RESIDUAL,
    "Renewable share of generation": MetricId.INDICATOR_RENEWABLE_SHARE,
}
# Energy-Charts reports pumped-storage consumption as negative generation; the
# canonical metric is a non-negative consumption.
NEGATE: frozenset[MetricId] = frozenset({MetricId.CONSUMPTION_PUMPED_STORAGE})

CBET_COUNTRIES: dict[str, str] = {
    "Austria": "AT",
    "Belgium": "BE",
    "Czech Republic": "CZ",
    "Denmark": "DK",
    "France": "FR",
    "Luxembourg": "LU",
    "Netherlands": "NL",
    "Norway": "NO",
    "Poland": "PL",
    "Sweden": "SE",
    "Switzerland": "CH",
}

FREQUENCY_BUCKET = timedelta(seconds=10)


def border_area(home: str, neighbour: str) -> str:
    """Area code for a border: net import of ``home`` from ``neighbour``."""
    return f"BORDER:{home}:{neighbour}"


def _infer_resolution(seconds: list[int], default: timedelta) -> timedelta:
    if len(seconds) < 2:
        return default
    return timedelta(seconds=float(np.median(np.diff(np.asarray(seconds, dtype=float)))))


def _fmt(t: datetime) -> str:
    return ensure_utc(t).strftime("%Y-%m-%dT%H:%MZ")


class EnergyChartsAdapter:
    source_id = "energy_charts"
    license = "CC BY 4.0"
    attribution = "Energy-Charts.info (Fraunhofer ISE)"

    def __init__(
        self,
        fetcher: HttpFetcher,
        country: str = "de",
        bidding_zone: str = "DE-LU",
        frequency_region: str = "DE-Freiburg",
    ) -> None:
        self._fetcher = fetcher
        self.country = country
        self.area = country.upper()
        self.bidding_zone = bidding_zone
        self.frequency_region = frequency_region
        self._cache: dict[tuple[str, tuple[tuple[str, str], ...]], Any] = {}

    def supported_metrics(self) -> frozenset[MetricId]:
        return frozenset(PUBLIC_POWER_MAP.values()) | {
            MetricId.PRICE_DAY_AHEAD,
            MetricId.GRID_FREQUENCY,
        }

    def endpoint_for(
        self, metric: MetricId, kind: Kind = Kind.ACTUAL
    ) -> tuple[str, dict[str, str]]:
        if kind is Kind.FORECAST:
            if metric is MetricId.INDICATOR_RENEWABLE_SHARE:
                return "ren_share_forecast", {"country": self.country}
            raise UnsupportedMetricError(f"energy_charts has no forecast for {metric}")
        if metric is MetricId.PRICE_DAY_AHEAD:
            return "price", {"bzn": self.bidding_zone}
        if metric is MetricId.GRID_FREQUENCY:
            return "frequency", {"region": self.frequency_region}
        if metric in PUBLIC_POWER_MAP.values():
            return "public_power", {"country": self.country}
        raise UnsupportedMetricError(f"energy_charts does not provide {metric}")

    def clear_cache(self) -> None:
        self._cache.clear()

    async def _cached(self, path: str, params: Mapping[str, str]) -> Any:
        key = (path, tuple(sorted(params.items())))
        if key not in self._cache:
            self._cache[key] = await self._fetcher.get_json(f"{BASE_URL}/{path}", params)
        return self._cache[key]

    async def fetch(
        self, metric: MetricId, start: datetime, end: datetime, kind: Kind = Kind.ACTUAL
    ) -> RawPayload:
        start, end = ensure_utc(start), ensure_utc(end)
        path, params = self.endpoint_for(metric, kind)
        if path != "ren_share_forecast":
            params = {**params, "start": _fmt(start), "end": _fmt(end)}
        doc = await self._cached(path, params)
        return RawPayload(
            self.source_id,
            metric,
            start,
            end,
            [doc],
            {"endpoint": path, "area": self.area, "bidding_zone": self.bidding_zone},
        )

    async def fetch_border_flows(self, start: datetime, end: datetime) -> RawPayload:
        start, end = ensure_utc(start), ensure_utc(end)
        params = {"country": self.country, "start": _fmt(start), "end": _fmt(end)}
        doc = await self._cached("cbet", params)
        return RawPayload(
            self.source_id,
            MetricId.FLOW_NET_IMPORT,
            start,
            end,
            [doc],
            {"endpoint": "cbet", "area": self.area},
        )

    def parse(self, payload: RawPayload) -> pd.DataFrame:
        endpoint = str(payload.params.get("endpoint", "public_power"))
        parsers = {
            "public_power": self._parse_public_power,
            "price": self._parse_price,
            "frequency": self._parse_frequency,
            "cbet": self._parse_cbet,
            "ren_share_forecast": self._parse_ren_share_forecast,
        }
        if endpoint not in parsers:
            raise ValueError(f"unknown endpoint {endpoint!r}")
        frames = [parsers[endpoint](doc, payload) for doc in payload.documents]
        return concat_frames(frames)

    @staticmethod
    def _window(
        payload: RawPayload, seconds: list[int], values: list[float | None]
    ) -> tuple[list[datetime], list[float | None]]:
        pairs = [
            (from_unix_seconds(s), v)
            for s, v in zip(seconds, values, strict=True)
            if payload.start <= from_unix_seconds(s) < payload.end
        ]
        return [p[0] for p in pairs], [p[1] for p in pairs]

    def _parse_public_power(self, doc: Mapping[str, Any], payload: RawPayload) -> pd.DataFrame:
        seconds: list[int] = list(doc["unix_seconds"])
        resolution = _infer_resolution(seconds, timedelta(minutes=15))
        area = str(payload.params.get("area", self.area))
        sums: dict[MetricId, list[float | None]] = {}
        for production in doc["production_types"]:
            metric = PUBLIC_POWER_MAP.get(production["name"])
            if metric is None or metric is not payload.metric:
                continue
            current = sums.setdefault(metric, [None] * len(seconds))
            for i, v in enumerate(production["data"]):
                if v is None:
                    continue
                current[i] = (current[i] or 0.0) + float(v)
        values = sums.get(payload.metric)
        if values is None:
            return empty_frame()
        if payload.metric in NEGATE:
            values = [None if v is None else abs(v) for v in values]
        ts, vals = self._window(payload, seconds, values)
        return make_frame(
            timestamps=ts,
            values=vals,
            metric=payload.metric,
            area=area,
            kind=Kind.ACTUAL,
            source=self.source_id,
            resolution=resolution,
        )

    def _parse_price(self, doc: Mapping[str, Any], payload: RawPayload) -> pd.DataFrame:
        seconds: list[int] = list(doc["unix_seconds"])
        ts, vals = self._window(payload, seconds, list(doc["price"]))
        return make_frame(
            timestamps=ts,
            values=vals,
            metric=MetricId.PRICE_DAY_AHEAD,
            area=str(payload.params.get("bidding_zone", self.bidding_zone)),
            kind=Kind.ACTUAL,
            source=self.source_id,
            resolution=_infer_resolution(seconds, timedelta(minutes=15)),
        )

    def _parse_frequency(self, doc: Mapping[str, Any], payload: RawPayload) -> pd.DataFrame:
        """1 s samples are reduced to 10 s buckets keeping the *worst* deviation from 50 Hz.

        Keeping the extreme instead of the mean makes downsampling conservative for
        alerting (see docs/adr/0003-frequency-downsampling.md).
        """
        ts, vals = self._window(payload, list(doc["unix_seconds"]), list(doc["data"]))
        series = pd.Series(vals, index=pd.DatetimeIndex(ts), dtype="float64").dropna()
        if series.empty:
            return empty_frame()
        buckets = pd.DatetimeIndex(series.index).floor(FREQUENCY_BUCKET)
        deviation = (series - 50.0).abs()
        worst_idx = deviation.groupby(buckets).idxmax()
        reduced = series.loc[worst_idx.to_numpy()]
        reduced.index = pd.DatetimeIndex(worst_idx.index)
        return make_frame(
            timestamps=list(reduced.index.to_pydatetime()),
            values=list(reduced.to_numpy()),
            metric=MetricId.GRID_FREQUENCY,
            area=str(payload.params.get("area", self.area)),
            kind=Kind.ACTUAL,
            source=self.source_id,
            resolution=FREQUENCY_BUCKET,
        )

    def _parse_cbet(self, doc: Mapping[str, Any], payload: RawPayload) -> pd.DataFrame:
        seconds: list[int] = list(doc["unix_seconds"])
        resolution = _infer_resolution(seconds, timedelta(minutes=15))
        home = str(payload.params.get("area", self.area))
        frames = []
        for country in doc["countries"]:
            name = country["name"]
            area = (
                home
                if name == "sum"
                else (border_area(home, CBET_COUNTRIES[name]) if name in CBET_COUNTRIES else None)
            )
            if area is None:
                continue
            mw = [None if v is None else float(v) * 1000.0 for v in country["data"]]
            ts, vals = self._window(payload, seconds, mw)
            frames.append(
                make_frame(
                    timestamps=ts,
                    values=vals,
                    metric=MetricId.FLOW_NET_IMPORT,
                    area=area,
                    kind=Kind.ACTUAL,
                    source=self.source_id,
                    resolution=resolution,
                )
            )
        return concat_frames(frames)

    def _parse_ren_share_forecast(
        self, doc: Mapping[str, Any], payload: RawPayload
    ) -> pd.DataFrame:
        seconds: list[int] = list(doc["unix_seconds"])
        ts, vals = self._window(payload, seconds, list(doc["ren_share"]))
        return make_frame(
            timestamps=ts,
            values=vals,
            metric=MetricId.INDICATOR_RENEWABLE_SHARE,
            area=str(payload.params.get("area", self.area)),
            kind=Kind.FORECAST,
            source=self.source_id,
            resolution=_infer_resolution(seconds, timedelta(minutes=15)),
        )
