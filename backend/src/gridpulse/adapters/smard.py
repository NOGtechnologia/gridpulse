"""SMARD (Bundesnetzagentur) chart data adapter.

Endpoints (verified 2026-10-18, see docs/data-sources.md)::

    /app/chart_data/{filter}/{region}/index_{resolution}.json
        -> {"timestamps": [ms, ...]}  start of each weekly chunk
    /app/chart_data/{filter}/{region}/{filter}_{region}_{resolution}_{ts}.json
        -> {"meta_data": {...}, "series": [[ms, value|null], ...]}

Quirk: generation and load values are *energy per interval* (MWh per quarter hour
or per hour), not power. ``parse`` converts them to mean power in MW by dividing by
the interval length in hours. Prices (EUR/MWh) are used as is.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from gridpulse.adapters.base import HttpFetcher, RawPayload, UnsupportedMetricError
from gridpulse.domain.metrics import Kind, MetricId, Unit, unit_of
from gridpulse.domain.observations import concat_frames, empty_frame, make_frame
from gridpulse.domain.timeutils import ensure_utc, from_unix_millis, to_unix_millis

BASE_URL = "https://www.smard.de/app/chart_data"

# (filter id, region, kind) per canonical metric.
ACTUAL_FILTERS: dict[MetricId, int] = {
    MetricId.GENERATION_LIGNITE: 1223,
    MetricId.GENERATION_NUCLEAR: 1224,
    MetricId.GENERATION_WIND_OFFSHORE: 1225,
    MetricId.GENERATION_HYDRO: 1226,
    MetricId.GENERATION_OTHER_CONVENTIONAL: 1227,
    MetricId.GENERATION_OTHER_RENEWABLE: 1228,
    MetricId.GENERATION_BIOMASS: 4066,
    MetricId.GENERATION_WIND_ONSHORE: 4067,
    MetricId.GENERATION_SOLAR: 4068,
    MetricId.GENERATION_HARD_COAL: 4069,
    MetricId.GENERATION_PUMPED_STORAGE: 4070,
    MetricId.GENERATION_GAS: 4071,
    MetricId.LOAD_ACTUAL: 410,
    MetricId.LOAD_RESIDUAL: 4359,
    MetricId.CONSUMPTION_PUMPED_STORAGE: 4387,
    MetricId.PRICE_DAY_AHEAD: 4169,
}
FORECAST_FILTERS: dict[MetricId, int] = {
    MetricId.LOAD_ACTUAL: 411,
    MetricId.LOAD_RESIDUAL: 4362,
    MetricId.GENERATION_WIND_ONSHORE: 123,
    MetricId.GENERATION_WIND_OFFSHORE: 3791,
    MetricId.GENERATION_SOLAR: 125,
}
RESOLUTIONS = {"quarterhour": timedelta(minutes=15), "hour": timedelta(hours=1)}
CHUNK = timedelta(days=7)


def region_for(metric: MetricId) -> str:
    return "DE-LU" if metric is MetricId.PRICE_DAY_AHEAD else "DE"


def chunks_needed(index_ms: list[int], start: datetime, end: datetime) -> list[int]:
    """Weekly chunk start timestamps (ms) that overlap ``[start, end)``."""
    start_ms, end_ms = to_unix_millis(start), to_unix_millis(end)
    ordered = sorted(index_ms)
    needed = []
    for i, ts in enumerate(ordered):
        nxt = ordered[i + 1] if i + 1 < len(ordered) else ts + int(CHUNK.total_seconds() * 1000)
        if ts < end_ms and nxt > start_ms:
            needed.append(ts)
    return needed


class SmardAdapter:
    source_id = "smard"
    license = "CC BY 4.0"
    attribution = "Bundesnetzagentur | SMARD.de"

    def __init__(
        self, fetcher: HttpFetcher, resolution: str = "quarterhour", kind: Kind = Kind.ACTUAL
    ):
        if resolution not in RESOLUTIONS:
            raise ValueError(f"unsupported resolution {resolution!r}")
        self._fetcher = fetcher
        self.resolution = resolution
        self.kind = kind

    @property
    def filters(self) -> dict[MetricId, int]:
        return ACTUAL_FILTERS if self.kind is Kind.ACTUAL else FORECAST_FILTERS

    def supported_metrics(self) -> frozenset[MetricId]:
        return frozenset(self.filters)

    async def fetch(self, metric: MetricId, start: datetime, end: datetime) -> RawPayload:
        if metric not in self.filters:
            raise UnsupportedMetricError(f"smard ({self.kind}) does not provide {metric}")
        start, end = ensure_utc(start), ensure_utc(end)
        filter_id, region = self.filters[metric], region_for(metric)
        prefix = f"{BASE_URL}/{filter_id}/{region}"
        index = await self._fetcher.get_json(f"{prefix}/index_{self.resolution}.json")
        docs = []
        for ts in chunks_needed(list(index["timestamps"]), start, end):
            docs.append(
                await self._fetcher.get_json(
                    f"{prefix}/{filter_id}_{region}_{self.resolution}_{ts}.json"
                )
            )
        return RawPayload(
            self.source_id,
            metric,
            start,
            end,
            docs,
            {"resolution": self.resolution, "region": region, "kind": self.kind.value},
        )

    def parse(self, payload: RawPayload) -> pd.DataFrame:
        resolution = RESOLUTIONS[str(payload.params.get("resolution", "quarterhour"))]
        kind = Kind(str(payload.params.get("kind", Kind.ACTUAL.value)))
        region = str(payload.params.get("region", region_for(payload.metric)))
        is_energy = unit_of(payload.metric) is Unit.MW
        factor = 1.0 / (resolution / timedelta(hours=1)) if is_energy else 1.0
        frames = []
        for doc in payload.documents:
            rows = [
                (from_unix_millis(ms), None if v is None else float(v) * factor)
                for ms, v in doc["series"]
            ]
            rows = [(t, v) for t, v in rows if payload.start <= t < payload.end]
            if not rows:
                continue
            frames.append(
                make_frame(
                    timestamps=[r[0] for r in rows],
                    values=[r[1] for r in rows],
                    metric=payload.metric,
                    area=region,
                    kind=kind,
                    source=self.source_id,
                    resolution=resolution,
                )
            )
        return concat_frames(frames) if frames else empty_frame()
