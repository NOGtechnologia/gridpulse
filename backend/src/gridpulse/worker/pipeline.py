"""Ingest pipeline: fetch -> parse -> schema validation -> plausibility -> upsert -> status."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pandas as pd
import pandera.errors

from gridpulse.adapters.base import RawPayload, SourceAdapter
from gridpulse.adapters.energy_charts import EnergyChartsAdapter
from gridpulse.adapters.entsoe import EntsoeAdapter
from gridpulse.adapters.open_meteo import OpenMeteoAdapter
from gridpulse.adapters.smard import ACTUAL_FILTERS, FORECAST_FILTERS, SmardAdapter
from gridpulse.domain.metrics import Kind, MetricId
from gridpulse.domain.rules.model import Event, EventCategory, Severity
from gridpulse.observability import (
    DATA_AGE,
    EVENTS_CREATED,
    INGEST_DURATION,
    INGEST_ERRORS,
    INGEST_ROWS,
    PLAUSIBILITY_VIOLATIONS,
    get_logger,
)
from gridpulse.storage.repository import Repository, SourceStatus
from gridpulse.validation.plausibility import PlausibilityConfig, run_all
from gridpulse.validation.schemas import validate_frame

log = get_logger(__name__)
Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class IngestJob:
    """One fetch of one metric from one adapter over ``[now - lookback, now + lookahead)``."""

    adapter: SourceAdapter
    metric: MetricId
    kind: Kind = Kind.ACTUAL
    lookback: timedelta = timedelta(hours=48)
    lookahead: timedelta = timedelta(0)
    border_flows: bool = False

    @property
    def name(self) -> str:
        suffix = ":borders" if self.border_flows else ""
        return f"{self.adapter.source_id}:{self.metric.value}:{self.kind.value}{suffix}"


@dataclass(slots=True)
class IngestResult:
    job: str
    rows: int = 0
    expected: int = 0
    received: int = 0
    newest: datetime | None = None
    events: list[Event] = field(default_factory=list)
    error: str | None = None


def expected_points(frame: pd.DataFrame) -> int:
    """Points expected between first and last timestamp of each series (gap ratio basis)."""
    total = 0
    for _, group in frame.groupby(["metric", "area", "kind"], sort=False):
        ts = pd.DatetimeIndex(group["ts"])
        step = pd.Timedelta(group["resolution"].iloc[0])
        total += int((ts.max() - ts.min()) / step) + 1
    return total


def schema_event(job: IngestJob, now: datetime, error: Exception) -> Event:
    return Event(
        ts=now,
        rule_id="DATA-002",
        severity=Severity.WARNING,
        category=EventCategory.DATA_QUALITY,
        metric=job.metric.value,
        area="*",
        value=None,
        threshold=None,
        source=job.adapter.source_id,
        message=f"Schema validation failed for {job.name}: {str(error)[:300]}",
    )


async def _fetch(job: IngestJob, start: datetime, end: datetime) -> RawPayload:
    if job.border_flows and isinstance(job.adapter, EnergyChartsAdapter):
        return await job.adapter.fetch_border_flows(start, end)
    if isinstance(job.adapter, EnergyChartsAdapter):
        return await job.adapter.fetch(job.metric, start, end, job.kind)
    return await job.adapter.fetch(job.metric, start, end)


class Ingestor:
    def __init__(
        self, repo: Repository, plausibility: PlausibilityConfig, clock: Clock = utc_now
    ) -> None:
        self.repo = repo
        self.plausibility = plausibility
        self.clock = clock

    async def run_job(self, job: IngestJob) -> IngestResult:
        now = self.clock()
        result = IngestResult(job.name)
        try:
            frame = job.adapter.parse(await _fetch(job, now - job.lookback, now + job.lookahead))
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"[:500]
            return result
        if frame.empty:
            return result
        try:
            validate_frame(frame)
        except pandera.errors.SchemaErrors as exc:
            result.events.append(schema_event(job, now, exc))
            return result
        violations = run_all(frame, self.plausibility)
        for v in violations:
            PLAUSIBILITY_VIOLATIONS.labels(job.adapter.source_id, v.rule_id).inc()
        result.events.extend(v.to_event() for v in violations)
        # Violations are recorded as events; the data itself is stored unchanged so that
        # nothing is dropped silently (spec 7.4).
        result.rows = await self.repo.upsert_observations(frame)
        result.received = len(frame)
        result.expected = expected_points(frame)
        # Data age = newest point not in the future (day-ahead prices and forecasts reach
        # into tomorrow and must not make a source look fresher than it is).
        past = frame[frame["ts"] <= pd.Timestamp(now)]
        actual = past[past["kind"] == Kind.ACTUAL.value]
        basis = actual if not actual.empty else past
        if not basis.empty:
            result.newest = pd.Timestamp(basis["ts"].max()).to_pydatetime()
        return result

    async def run_source(
        self, source: str, jobs: Sequence[IngestJob]
    ) -> tuple[SourceStatus, list[Event]]:
        """Run all jobs of one source and persist an aggregated :class:`SourceStatus`."""
        started = time.perf_counter()
        now = self.clock()
        previous = {s.source: s for s in await self.repo.list_source_status()}.get(source)
        status = SourceStatus(
            source=source,
            last_attempt=now,
            last_success=previous.last_success if previous else None,
            newest_data=previous.newest_data if previous else None,
        )
        events: list[Event] = []
        errors: list[str] = []
        with INGEST_DURATION.labels(source).time():
            for job in jobs:
                res = await self.run_job(job)
                events.extend(res.events)
                status.rows_last_run += res.rows
                status.expected_points += res.expected
                status.received_points += res.received
                if res.newest and (status.newest_data is None or res.newest > status.newest_data):
                    status.newest_data = res.newest
                if res.error:
                    errors.append(f"{res.job}: {res.error}")
        status.latency_ms = (time.perf_counter() - started) * 1000
        status.plausibility_violations = sum(
            1 for e in events if e.category is EventCategory.DATA_QUALITY
        )
        if errors and len(errors) == len(jobs):
            INGEST_ERRORS.labels(source).inc()
            status.consecutive_failures = (previous.consecutive_failures if previous else 0) + 1
        else:
            status.last_success = now
        status.last_error = "; ".join(errors)[:2000] or None
        INGEST_ROWS.labels(source).inc(status.rows_last_run)
        if status.newest_data:
            DATA_AGE.labels(source).set((now - status.newest_data).total_seconds())
        await self.repo.save_source_status(status)
        new_events = await self.repo.upsert_events(events)
        for e in new_events:
            EVENTS_CREATED.labels(e.rule_id, e.severity.value).inc()
        log.info(
            "ingest_done",
            source=source,
            rows=status.rows_last_run,
            errors=len(errors),
            new_events=len(new_events),
            latency_ms=round(status.latency_ms, 1),
        )
        return status, new_events


# --- default job catalogue ---------------------------------------------------------

EC_POWER_METRICS: tuple[MetricId, ...] = (
    MetricId.GENERATION_WIND_ONSHORE,
    MetricId.GENERATION_WIND_OFFSHORE,
    MetricId.GENERATION_SOLAR,
    MetricId.GENERATION_BIOMASS,
    MetricId.GENERATION_HYDRO,
    MetricId.GENERATION_OTHER_RENEWABLE,
    MetricId.GENERATION_LIGNITE,
    MetricId.GENERATION_HARD_COAL,
    MetricId.GENERATION_GAS,
    MetricId.GENERATION_OIL,
    MetricId.GENERATION_PUMPED_STORAGE,
    MetricId.GENERATION_OTHER_CONVENTIONAL,
    MetricId.CONSUMPTION_PUMPED_STORAGE,
    MetricId.LOAD_ACTUAL,
    MetricId.LOAD_RESIDUAL,
    MetricId.FLOW_NET_IMPORT,
)
DAY = timedelta(days=1)


def smard_jobs(
    actual: SmardAdapter, forecast: SmardAdapter, backfill: timedelta, horizon: timedelta
) -> list[IngestJob]:
    jobs = [
        IngestJob(
            actual,
            m,
            Kind.ACTUAL,
            backfill,
            horizon if m is MetricId.PRICE_DAY_AHEAD else timedelta(0),
        )
        for m in ACTUAL_FILTERS
        if m is not MetricId.GENERATION_NUCLEAR  # phased out 2023-04-15; history only
    ]
    jobs += [IngestJob(forecast, m, Kind.FORECAST, DAY, horizon) for m in FORECAST_FILTERS]
    return jobs


def energy_charts_jobs(
    adapter: EnergyChartsAdapter, backfill: timedelta, horizon: timedelta
) -> list[IngestJob]:
    jobs = [IngestJob(adapter, m, Kind.ACTUAL, backfill) for m in EC_POWER_METRICS]
    jobs.append(IngestJob(adapter, MetricId.PRICE_DAY_AHEAD, Kind.ACTUAL, backfill, horizon))
    jobs.append(
        IngestJob(adapter, MetricId.FLOW_NET_IMPORT, Kind.ACTUAL, backfill, border_flows=True)
    )
    jobs.append(IngestJob(adapter, MetricId.INDICATOR_RENEWABLE_SHARE, Kind.FORECAST, DAY, horizon))
    return jobs


def frequency_jobs(adapter: EnergyChartsAdapter) -> list[IngestJob]:
    return [IngestJob(adapter, MetricId.GRID_FREQUENCY, Kind.ACTUAL, timedelta(minutes=15))]


def weather_jobs(adapter: OpenMeteoAdapter, horizon: timedelta) -> list[IngestJob]:
    return [
        IngestJob(adapter, m, Kind.FORECAST, DAY, horizon)
        for m in sorted(adapter.supported_metrics())
    ]


def entsoe_jobs(adapter: EntsoeAdapter, backfill: timedelta, horizon: timedelta) -> list[IngestJob]:
    return [
        IngestJob(adapter, MetricId.LOAD_ACTUAL, Kind.ACTUAL, backfill),
        IngestJob(adapter, MetricId.PRICE_DAY_AHEAD, Kind.ACTUAL, backfill, horizon),
    ]


AsyncTask = Callable[[], Awaitable[object]]
