"""Public read-only REST API, version 1 (spec 2.6)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import AfterValidator, AwareDatetime, BeforeValidator

from gridpulse.adapters.registry import license_for
from gridpulse.alerts.dispatcher import AlertDispatcher, channels_from_settings
from gridpulse.api.deps import NowDep, RepoDep, StateDep, guard, require_admin
from gridpulse.api.export import to_csv, to_parquet
from gridpulse.domain.colors import color_of
from gridpulse.domain.metrics import CATALOG, Kind, MetricId
from gridpulse.domain.rules.model import EventCategory, Severity
from gridpulse.domain.timeutils import ensure_utc
from gridpulse.schemas import (
    AlertTestResult,
    ErrorOut,
    EventOut,
    EventsResponse,
    ForecastResponse,
    Meta,
    MetricOut,
    MetricsCatalog,
    ObservationOut,
    ObservationsResponse,
    SourcesResponse,
    SourceStatusOut,
    SummaryNow,
)
from gridpulse.services.forecast import build_forecast
from gridpulse.services.summary import build_summary
from gridpulse.storage.repository import EventQuery, ObservationQuery, QueryResolution

router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(guard)],
    responses={
        401: {"model": ErrorOut, "description": "Missing or invalid API key"},
        429: {"model": ErrorOut, "description": "Rate limit exceeded (see Retry-After)"},
    },
)

EXAMPLE_START = "2026-10-17T00:00:00Z"
EXAMPLE_END = "2026-10-18T00:00:00Z"
ISO_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
EARLIEST = datetime(1970, 1, 1, tzinfo=UTC)
LATEST = datetime(2200, 1, 1, tzinfo=UTC)


def _iso_only(value: object) -> object:
    """Reject numbers such as ``0.5`` that pydantic would read as Unix timestamps."""
    if not isinstance(value, str) or not ISO_DATETIME.match(value):
        raise ValueError("expected ISO 8601 date-time with offset, e.g. 2026-01-01T00:00:00Z")
    return value


def _clamp(value: datetime) -> datetime:
    """Data exists only within 1970-2200; out-of-range bounds are clamped, not rejected."""
    return min(max(ensure_utc(value), EARLIEST), LATEST)


# AwareDatetime rejects naive values with a regular 422 validation error.
IsoDateTime = Annotated[AwareDatetime, BeforeValidator(_iso_only), AfterValidator(_clamp)]


class ExportFormat(StrEnum):
    CSV = "csv"
    PARQUET = "parquet"


def _window(
    start: datetime | None,
    end: datetime | None,
    now: datetime,
    default: timedelta = timedelta(hours=24),
) -> tuple[datetime, datetime]:
    """Resolve the query window. ``start >= end`` is an empty window (no error)."""
    end_utc = end or now
    start_utc = start or max(end_utc - default, EARLIEST)
    return start_utc, end_utc


MetricsQ = Annotated[
    list[MetricId],
    Query(alias="metric", description="Repeat for several metrics", examples=[["load.actual"]]),
]
StartQ = Annotated[
    IsoDateTime | None,
    Query(description="Inclusive, ISO 8601 with offset", examples=[EXAMPLE_START]),
]
EndQ = Annotated[
    IsoDateTime | None,
    Query(description="Exclusive, ISO 8601 with offset", examples=[EXAMPLE_END]),
]
AreaQ = Annotated[list[str] | None, Query(alias="area", max_length=20, examples=[["DE"]])]
SourceQ = Annotated[list[str] | None, Query(alias="source", max_length=10, examples=[["smard"]])]


def _observation_query(
    metrics: list[MetricId],
    start: datetime,
    end: datetime,
    area: list[str] | None,
    kind: Kind | None,
    source: list[str] | None,
    resolution: QueryResolution,
    limit: int,
    offset: int,
) -> ObservationQuery:
    return ObservationQuery(
        metrics=[m.value for m in metrics],
        start=start,
        end=end,
        areas=area,
        kind=kind.value if kind else None,
        sources=source,
        resolution=resolution,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/observations",
    response_model=ObservationsResponse,
    summary="Time series",
    description="Canonical observations. `resolution` 15min/1h/1d are means per bucket; daily "
    "buckets follow Europe/Berlin calendar days. Paginate with `offset`.",
)
async def observations(
    repo: RepoDep,
    now: NowDep,
    s: StateDep,
    metric: MetricsQ,
    start: StartQ = None,
    end: EndQ = None,
    area: AreaQ = None,
    kind: Kind | None = None,
    source: SourceQ = None,
    resolution: QueryResolution = QueryResolution.QUARTER_HOUR,
    limit: Annotated[int, Query(ge=1, le=10_000)] = 1_000,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ObservationsResponse:
    begin, finish = _window(start, end, now)
    limit = min(limit, s.settings.max_page_size)
    query = _observation_query(metric, begin, finish, area, kind, source, resolution, limit, offset)
    frame = await repo.query_observations(query)
    total = await repo.count_observations(query)
    sources = "|".join(sorted({str(x) for x in frame["source"]})) or "none"
    lic, attr = license_for(sources)
    data = [
        ObservationOut(
            ts=ts,
            metric=str(m),
            area=str(a),
            kind=str(k),
            source=str(src),
            unit=str(u),
            value=float(v),
        )
        for ts, m, a, k, src, u, v in zip(
            frame["ts"].dt.to_pydatetime(),
            frame["metric"],
            frame["area"],
            frame["kind"],
            frame["source"],
            frame["unit"],
            frame["value"],
            strict=True,
        )
    ]
    next_offset = offset + len(data) if offset + len(data) < total else None
    return ObservationsResponse(
        meta=Meta(
            source=sources,
            license=lic,
            attribution=attr,
            generated_at=now,
            count=len(data),
            total=total,
            next_offset=next_offset,
        ),
        data=data,
    )


@router.get("/summary/now", response_model=SummaryNow, summary="Live situation (Lage)")
async def summary_now(repo: RepoDep, now: NowDep, s: StateDep) -> SummaryNow:
    return await build_summary(repo, now, s.settings.rule_config())


@router.get(
    "/forecast/residual-load", response_model=ForecastResponse, summary="Residual load outlook"
)
async def forecast_residual_load(
    repo: RepoDep, now: NowDep, s: StateDep, hours: Annotated[int, Query(ge=1, le=168)] = 48
) -> ForecastResponse:
    return await build_forecast(repo, now, hours, s.settings.rule_config())


@router.get("/events", response_model=EventsResponse, summary="Detected events")
async def list_events(
    repo: RepoDep,
    now: NowDep,
    start: StartQ = None,
    end: EndQ = None,
    min_severity: Severity | None = None,
    rule_id: Annotated[list[str] | None, Query(max_length=20, examples=[["FREQ-001"]])] = None,
    category: Annotated[list[EventCategory] | None, Query(max_length=10)] = None,
    limit: Annotated[int, Query(ge=1, le=1_000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EventsResponse:
    begin, finish = _window(start, end, now, default=timedelta(days=7))
    items = await repo.list_events(
        EventQuery(
            start=begin,
            end=finish + timedelta(days=3),
            min_severity=min_severity,
            rule_ids=rule_id,
            categories=[c.value for c in category] if category else None,
            limit=limit,
            offset=offset,
        )
    )
    sources = "|".join(sorted({e.source for e in items})) or "gridpulse"
    lic, attr = license_for(sources)
    return EventsResponse(
        meta=Meta(
            source=sources, license=lic, attribution=attr, generated_at=now, count=len(items)
        ),
        data=[
            EventOut(
                id=e.id,
                ts=e.ts,
                rule_id=e.rule_id,
                severity=e.severity.value,
                category=e.category.value,
                metric=e.metric,
                area=e.area,
                value=e.value,
                threshold=e.threshold,
                unit=e.unit,
                source=e.source,
                message=e.message,
            )
            for e in items
        ],
    )


@router.get("/sources/status", response_model=SourcesResponse, summary="Data quality per source")
async def sources_status(repo: RepoDep, now: NowDep, s: StateDep) -> SourcesResponse:
    stale = s.settings.rule_config().stale_after
    out = []
    for st in await repo.list_source_status():
        lic, attr = license_for(st.source.removesuffix("_frequency"))
        age = (now - st.newest_data).total_seconds() if st.newest_data else None
        healthy = st.consecutive_failures == 0 and age is not None and age <= stale.total_seconds()
        out.append(
            SourceStatusOut(
                source=st.source,
                license=lic,
                attribution=attr,
                last_attempt=st.last_attempt,
                last_success=st.last_success,
                last_error=st.last_error,
                latency_ms=st.latency_ms,
                rows_last_run=st.rows_last_run,
                gap_ratio=round(st.gap_ratio, 4),
                plausibility_violations=st.plausibility_violations,
                consecutive_failures=st.consecutive_failures,
                newest_data=st.newest_data,
                data_age_seconds=age,
                healthy=healthy,
            )
        )
    return SourcesResponse(
        meta=Meta(
            source="gridpulse",
            license="CC BY 4.0 (derived)",
            attribution="GridPulse",
            generated_at=now,
            count=len(out),
        ),
        data=out,
    )


@router.get(
    "/metrics", response_model=MetricsCatalog, summary="Metric catalogue with units and colours"
)
async def metric_catalog() -> MetricsCatalog:
    return MetricsCatalog(
        data=[
            MetricOut(
                id=m.value,
                unit=i.unit.value,
                category=i.category.value,
                renewable=i.renewable,
                color=color_of(m),
            )
            for m, i in CATALOG.items()
        ]
    )


@router.get(
    "/export",
    summary="Export as CSV or Parquet",
    response_class=Response,
    responses={
        200: {
            "content": {
                "text/csv": {"schema": {"type": "string"}},
                "application/vnd.apache.parquet": {
                    "schema": {"type": "string", "format": "binary"}
                },
            }
        },
        413: {"model": ErrorOut, "description": "Too many rows; narrow the query"},
    },
)
async def export(
    repo: RepoDep,
    now: NowDep,
    s: StateDep,
    metric: MetricsQ,
    start: StartQ = None,
    end: EndQ = None,
    area: AreaQ = None,
    kind: Kind | None = None,
    source: SourceQ = None,
    resolution: QueryResolution = QueryResolution.HOUR,
    fmt: Annotated[ExportFormat, Query(alias="format")] = ExportFormat.CSV,
) -> Response:
    begin, finish = _window(start, end, now, default=timedelta(days=7))
    query = _observation_query(
        metric, begin, finish, area, kind, source, resolution, s.settings.max_export_rows + 1, 0
    )
    frame = await repo.query_observations(query)
    if len(frame) > s.settings.max_export_rows:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"more than {s.settings.max_export_rows} rows; narrow the query",
        )
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    if fmt is ExportFormat.PARQUET:
        return Response(
            to_parquet(frame, now),
            media_type="application/vnd.apache.parquet",
            headers={"Content-Disposition": f'attachment; filename="gridpulse_{stamp}.parquet"'},
        )
    return Response(
        to_csv(frame, now),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="gridpulse_{stamp}.csv"'},
    )


@router.post(
    "/alerts/test",
    response_model=AlertTestResult,
    dependencies=[Depends(require_admin)],
    summary="Send a test notification to all channels (needs X-Admin-Token)",
    responses={403: {"model": ErrorOut, "description": "Admin endpoints disabled"}},
)
async def alerts_test(repo: RepoDep, now: NowDep, s: StateDep) -> AlertTestResult:
    async with httpx.AsyncClient(timeout=15) as client:
        channels = await channels_from_settings(repo, client, s.settings)
        dispatcher = AlertDispatcher(repo, channels, timedelta(0))
        return AlertTestResult(results=await dispatcher.send_test(now))
