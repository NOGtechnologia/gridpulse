"""Worker composition: adapters, jobs and the APScheduler schedule."""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from gridpulse.adapters.base import HttpFetcher
from gridpulse.adapters.energy_charts import EnergyChartsAdapter
from gridpulse.adapters.entsoe import AREAS, EntsoeAdapter
from gridpulse.adapters.open_meteo import OpenMeteoAdapter
from gridpulse.adapters.smard import SmardAdapter
from gridpulse.alerts.dispatcher import AlertDispatcher
from gridpulse.domain.metrics import Kind
from gridpulse.domain.rules.model import Event
from gridpulse.observability import EVENTS_CREATED, get_logger
from gridpulse.services.analysis import derive_indicators, evaluate_rules
from gridpulse.services.model_forecast import run_model
from gridpulse.settings import Settings
from gridpulse.storage.repository import ModelRun, Repository
from gridpulse.worker.pipeline import (
    Clock,
    IngestJob,
    Ingestor,
    energy_charts_jobs,
    entsoe_jobs,
    frequency_jobs,
    smard_jobs,
    utc_now,
    weather_jobs,
)

log = get_logger(__name__)


@dataclass
class Worker:
    repo: Repository
    settings: Settings
    client: httpx.AsyncClient
    dispatcher: AlertDispatcher | None = None
    clock: Clock = utc_now
    jobs: dict[str, list[IngestJob]] = field(default_factory=dict)
    ec: EnergyChartsAdapter | None = None

    def __post_init__(self) -> None:
        fetcher = HttpFetcher(self.client)
        backfill = timedelta(hours=self.settings.backfill_hours)
        horizon = timedelta(hours=self.settings.forecast_horizon_hours)
        self.ec = EnergyChartsAdapter(fetcher)
        self.jobs = {
            "smard": smard_jobs(
                SmardAdapter(fetcher), SmardAdapter(fetcher, kind=Kind.FORECAST), backfill, horizon
            ),
            "energy_charts": energy_charts_jobs(self.ec, backfill, horizon),
            "open_meteo": weather_jobs(OpenMeteoAdapter(fetcher), horizon),
        }
        token = self.settings.entsoe_token
        if token is not None and token.get_secret_value():
            zones = [EntsoeAdapter(fetcher, token.get_secret_value(), area) for area in AREAS]
            self.jobs["entsoe"] = entsoe_jobs(zones, backfill, horizon)
        self.frequency = frequency_jobs(self.ec)
        self.ingestor = Ingestor(self.repo, self.settings.plausibility_config(), self.clock)

    async def _notify(self, events: list[Event]) -> None:
        if self.dispatcher and events:
            await self.dispatcher.dispatch(events, self.clock())

    async def ingest(self, source: str) -> list[Event]:
        if self.ec is not None and source == "energy_charts":
            self.ec.clear_cache()
        _, events = await self.ingestor.run_source(source, self.jobs[source])
        await self._notify(events)
        return events

    async def ingest_frequency(self) -> list[Event]:
        if self.ec is not None:
            self.ec.clear_cache()
        _, events = await self.ingestor.run_source("energy_charts_frequency", self.frequency)
        return events

    async def train_model(self) -> ModelRun | None:
        run, _ = await run_model(self.repo, self.clock(), self.settings.forecast_model_config())
        return run

    async def analyse(self) -> list[Event]:
        now = self.clock()
        await derive_indicators(self.repo, now)
        new = await self.repo.upsert_events(
            await evaluate_rules(self.repo, now, self.settings.rule_config())
        )
        for e in new:
            EVENTS_CREATED.labels(e.rule_id, e.severity.value).inc()
        await self._notify(new)
        log.info("analysis_done", new_events=len(new))
        return new


def _safe(name: str, fn: Callable[[], Awaitable[object]]) -> Callable[[], Awaitable[None]]:
    async def run() -> None:
        try:
            await fn()
        except Exception:
            log.exception("job_failed", job=name)

    return run


def build_scheduler(worker: Worker) -> AsyncIOScheduler:
    s = worker.settings
    scheduler = AsyncIOScheduler(
        timezone="UTC",
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
    )
    first = datetime.now(UTC) + timedelta(seconds=5)
    for source in worker.jobs:
        interval = (
            s.weather_interval_minutes if source == "open_meteo" else s.ingest_interval_minutes
        )
        scheduler.add_job(
            _safe(source, functools.partial(worker.ingest, source)),
            "interval",
            minutes=interval,
            jitter=30,
            next_run_time=first,
            id=f"ingest:{source}",
        )
    scheduler.add_job(
        _safe("frequency", worker.ingest_frequency),
        "interval",
        minutes=s.frequency_interval_minutes,
        jitter=5,
        next_run_time=first,
        id="ingest:frequency",
    )
    scheduler.add_job(
        _safe("analysis", worker.analyse),
        "interval",
        minutes=5,
        next_run_time=first + timedelta(seconds=60),
        id="analysis",
    )
    if s.forecast_model_enabled:
        # Daily retraining; the first run waits until the initial ingest has finished.
        scheduler.add_job(
            _safe("forecast_model", worker.train_model),
            "interval",
            hours=s.forecast_model_interval_hours,
            next_run_time=first + timedelta(minutes=3),
            id="forecast_model",
        )
    return scheduler
