"""ENTSO-E Transparency Platform adapter (optional, needs a security token).

REST endpoint ``https://web-api.tp.entsoe.eu/api`` returning IEC 62325 XML documents:

* Actual total load: ``documentType=A65, processType=A16`` -> ``GL_MarketDocument``
* Day-ahead prices: ``documentType=A44`` -> ``Publication_MarketDocument``

Each ``TimeSeries`` holds ``Period``s with ``timeInterval/start``, ``resolution``
(ISO 8601, e.g. ``PT15M``) and ``Point``s with 1-based ``position`` and
``quantity`` or ``price.amount``. Positions may be omitted when the value repeats
(curve type A03); ``parse`` forward-fills such gaps.

The token is read from ``GRIDPULSE_ENTSOE_TOKEN`` and never logged.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pandas as pd
from defusedxml import ElementTree

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element

from gridpulse.adapters.base import HttpFetcher, RawPayload, UnsupportedMetricError
from gridpulse.domain.metrics import Kind, MetricId
from gridpulse.domain.observations import KEY_COLUMNS, concat_frames, make_frame
from gridpulse.domain.timeutils import ensure_utc

BASE_URL = "https://web-api.tp.entsoe.eu/api"

# EIC codes of bidding zones / control areas.
AREAS: dict[str, str] = {
    "DE-LU": "10Y1001A1001A82H",
    "FR": "10YFR-RTE------C",
    "NL": "10YNL----------L",
    "BE": "10YBE----------2",
    "AT": "10YAT-APG------L",
    "PL": "10YPL-AREA-----S",
    "CZ": "10YCZ-CEPS-----N",
    "CH": "10YCH-SWISSGRIDZ",
    "DK1": "10YDK-1--------W",
}

DOCUMENTS: dict[MetricId, dict[str, str]] = {
    MetricId.LOAD_ACTUAL: {"documentType": "A65", "processType": "A16"},
    MetricId.PRICE_DAY_AHEAD: {"documentType": "A44"},
}

_DURATION = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?$|^P1D$")


def parse_resolution(text: str) -> timedelta:
    """ISO 8601 durations used by ENTSO-E: PT15M, PT30M, PT60M, PT1H, P1D."""
    match = _DURATION.match(text)
    if not match:
        raise ValueError(f"unsupported resolution {text!r}")
    if text == "P1D":
        return timedelta(days=1)
    hours, minutes = match.groups()
    return timedelta(hours=int(hours or 0), minutes=int(minutes or 0))


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(element: Element, name: str) -> Element | None:
    for child in element.iter():
        if _local(child.tag) == name:
            return child
    return None


def _children(element: Element, name: str) -> list[Element]:
    return [c for c in element if _local(c.tag) == name]


class EntsoeAdapter:
    source_id = "entsoe"
    license = "ENTSO-E Transparency Platform Terms and Conditions"
    attribution = "ENTSO-E Transparency Platform"

    def __init__(self, fetcher: HttpFetcher, token: str, area: str = "DE-LU") -> None:
        if not token:
            raise ValueError("ENTSO-E token required")
        if area not in AREAS:
            raise ValueError(f"unknown area {area!r}")
        self._fetcher = fetcher
        self._token = token
        self.area = area

    def supported_metrics(self) -> frozenset[MetricId]:
        return frozenset(DOCUMENTS)

    async def fetch(self, metric: MetricId, start: datetime, end: datetime) -> RawPayload:
        if metric not in DOCUMENTS:
            raise UnsupportedMetricError(f"entsoe does not provide {metric}")
        start, end = ensure_utc(start), ensure_utc(end)
        eic = AREAS[self.area]
        params = {
            **DOCUMENTS[metric],
            "securityToken": self._token,
            "periodStart": start.strftime("%Y%m%d%H%M"),
            "periodEnd": end.strftime("%Y%m%d%H%M"),
        }
        if metric is MetricId.PRICE_DAY_AHEAD:
            params |= {"in_Domain": eic, "out_Domain": eic}
        else:
            params |= {"outBiddingZone_Domain": eic}
        response = await self._fetcher.get(BASE_URL, params)
        return RawPayload(self.source_id, metric, start, end, [response.text], {"area": self.area})

    def parse(self, payload: RawPayload) -> pd.DataFrame:
        frames = []
        for xml in payload.documents:
            root = ElementTree.fromstring(xml)
            if _local(root.tag) == "Acknowledgement_MarketDocument":
                reason = _find(root, "text")
                raise ValueError(
                    f"ENTSO-E acknowledgement: {reason.text if reason is not None else '?'}"
                )
            value_tag = "price.amount" if payload.metric is MetricId.PRICE_DAY_AHEAD else "quantity"
            for series in (e for e in root.iter() if _local(e.tag) == "TimeSeries"):
                for period in _children(series, "Period"):
                    frames.append(self._parse_period(period, value_tag, payload))
        frame = concat_frames(frames)
        # Since the 15-min day-ahead MTU some zones publish an hourly and a quarter-hourly
        # series for the same day; keep the finest one so the upsert key stays unique.
        frame = frame.sort_values(["ts", "resolution"], kind="stable")
        frame = frame.drop_duplicates(subset=list(KEY_COLUMNS), keep="first")
        return frame.reset_index(drop=True)

    def _parse_period(self, period: Element, value_tag: str, payload: RawPayload) -> pd.DataFrame:
        interval = _find(period, "timeInterval")
        res_el = _find(period, "resolution")
        if interval is None or res_el is None or res_el.text is None:
            raise ValueError("Period without timeInterval/resolution")
        start_el, end_el = _find(interval, "start"), _find(interval, "end")
        if start_el is None or start_el.text is None or end_el is None or end_el.text is None:
            raise ValueError("timeInterval without start/end")
        start = ensure_utc(datetime.fromisoformat(start_el.text.replace("Z", "+00:00")))
        end = ensure_utc(datetime.fromisoformat(end_el.text.replace("Z", "+00:00")))
        step = parse_resolution(res_el.text)
        values: dict[int, float] = {}
        for point in _children(period, "Point"):
            pos_el, val_el = _find(point, "position"), _find(point, value_tag)
            if pos_el is None or pos_el.text is None or val_el is None or val_el.text is None:
                continue
            values[int(pos_el.text)] = float(val_el.text)
        count = int((end - start) / step)
        stamps, vals, last = [], [], None
        for pos in range(1, count + 1):
            last = values.get(pos, last)  # A03 curves omit repeated values
            ts = start + (pos - 1) * step
            if payload.start <= ts < payload.end:
                stamps.append(ts)
                vals.append(last)
        return make_frame(
            timestamps=stamps,
            values=vals,
            metric=payload.metric,
            area=str(payload.params.get("area", self.area)),
            kind=Kind.ACTUAL,
            source=self.source_id,
            resolution=step,
        )
