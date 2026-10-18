"""Open-Meteo forecast adapter (weather features for the forecasting model).

Endpoint (verified 2026-10-18): ``/v1/forecast?latitude=a,b&longitude=x,y&hourly=...``.
With several coordinates the response is a JSON *list* with one object per location.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd

from gridpulse.adapters.base import HttpFetcher, RawPayload, UnsupportedMetricError
from gridpulse.domain.metrics import Kind, MetricId
from gridpulse.domain.observations import concat_frames, make_frame
from gridpulse.domain.timeutils import ensure_utc

BASE_URL = "https://api.open-meteo.com/v1/forecast"

VARIABLES: dict[MetricId, str] = {
    MetricId.WEATHER_TEMPERATURE: "temperature_2m",
    MetricId.WEATHER_WIND_SPEED_100M: "wind_speed_100m",
    MetricId.WEATHER_SHORTWAVE_RADIATION: "shortwave_radiation",
    MetricId.WEATHER_CLOUD_COVER: "cloud_cover",
}


@dataclass(frozen=True, slots=True)
class Location:
    name: str
    lat: float
    lon: float


DEFAULT_LOCATIONS: tuple[Location, ...] = (
    Location("hamburg", 53.55, 9.99),
    Location("kassel", 51.0, 10.0),
    Location("munich", 48.14, 11.58),
)


def weather_area(name: str) -> str:
    return f"WX:{name}"


class OpenMeteoAdapter:
    source_id = "open_meteo"
    license = "CC BY 4.0"
    attribution = "Weather data by Open-Meteo.com"

    def __init__(
        self, fetcher: HttpFetcher, locations: Sequence[Location] = DEFAULT_LOCATIONS
    ) -> None:
        if not locations:
            raise ValueError("at least one location required")
        self._fetcher = fetcher
        self.locations = tuple(locations)

    def supported_metrics(self) -> frozenset[MetricId]:
        return frozenset(VARIABLES)

    async def fetch(self, metric: MetricId, start: datetime, end: datetime) -> RawPayload:
        if metric not in VARIABLES:
            raise UnsupportedMetricError(f"open_meteo does not provide {metric}")
        start, end = ensure_utc(start), ensure_utc(end)
        days = max(1, min(16, int((end - datetime.now(UTC)) / timedelta(days=1)) + 1))
        params = {
            "latitude": ",".join(f"{loc.lat}" for loc in self.locations),
            "longitude": ",".join(f"{loc.lon}" for loc in self.locations),
            "hourly": ",".join(VARIABLES.values()),
            "timezone": "UTC",
            "past_days": 1,
            "forecast_days": days,
        }
        doc = await self._fetcher.get_json(BASE_URL, params)
        return RawPayload(
            self.source_id,
            metric,
            start,
            end,
            [doc],
            {"locations": [loc.name for loc in self.locations]},
        )

    def parse(self, payload: RawPayload) -> pd.DataFrame:
        variable = VARIABLES[payload.metric]
        names = list(payload.params.get("locations", [loc.name for loc in self.locations]))
        frames = []
        for doc in payload.documents:
            per_location: list[Mapping[str, Any]] = doc if isinstance(doc, list) else [doc]
            if len(per_location) != len(names):
                raise ValueError(f"expected {len(names)} locations, got {len(per_location)}")
            for name, loc_doc in zip(names, per_location, strict=True):
                hourly = loc_doc["hourly"]
                if loc_doc.get("utc_offset_seconds", 0) != 0:
                    raise ValueError("open-meteo response must be requested in UTC")
                stamps = [datetime.fromisoformat(t).replace(tzinfo=UTC) for t in hourly["time"]]
                pairs = [
                    (t, v)
                    for t, v in zip(stamps, hourly[variable], strict=True)
                    if payload.start <= t < payload.end
                ]
                frames.append(
                    make_frame(
                        timestamps=[p[0] for p in pairs],
                        values=[p[1] for p in pairs],
                        metric=payload.metric,
                        area=weather_area(name),
                        kind=Kind.FORECAST,
                        source=self.source_id,
                        resolution=timedelta(hours=1),
                    )
                )
        return concat_frames(frames)
