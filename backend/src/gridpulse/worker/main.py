"""Worker process entry point: migrations, demo seeding, scheduler, /metrics."""

from __future__ import annotations

import asyncio
import contextlib
import signal
from datetime import UTC, datetime, timedelta

import httpx
from prometheus_client import start_http_server

from gridpulse.alerts.dispatcher import AlertDispatcher, channels_from_settings
from gridpulse.demo import generate
from gridpulse.observability import configure_logging, get_logger
from gridpulse.settings import Settings, get_settings
from gridpulse.storage import create_repository, migrate
from gridpulse.storage.repository import Repository, SourceStatus
from gridpulse.worker.scheduler import Worker, build_scheduler

log = get_logger(__name__)
METRICS_PORT = 9101


async def seed_demo(repo: Repository, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    rows = await repo.upsert_observations(generate(now))
    await repo.save_source_status(
        SourceStatus(
            source="demo",
            last_attempt=now,
            last_success=now,
            rows_last_run=rows,
            newest_data=now - timedelta(minutes=15),
        )
    )
    return rows


async def prepare(settings: Settings) -> Repository:
    if not settings.database_url.startswith("memory://"):
        await asyncio.to_thread(migrate.upgrade, settings.database_url)
    repo = create_repository(settings.database_url)
    apply = getattr(repo, "apply_retention", None)
    if apply is not None:
        await apply(
            settings.retention_raw_days,
            settings.retention_frequency_days,
            settings.compress_after_days,
        )
    if settings.demo:
        rows = await seed_demo(repo)
        log.info("demo_seeded", rows=rows)
    return repo


async def main(settings: Settings) -> None:
    repo = await prepare(settings)
    async with httpx.AsyncClient(
        timeout=settings.http_timeout_seconds, follow_redirects=True
    ) as client:
        dispatcher = AlertDispatcher(
            repo,
            await channels_from_settings(repo, client, settings),
            timedelta(minutes=settings.alert_debounce_minutes),
        )
        worker = Worker(repo, settings, client, dispatcher)
        scheduler = build_scheduler(worker)
        if settings.demo:
            # Demo mode never calls external sources; it only refreshes the demo data.
            for job in scheduler.get_jobs():
                if job.id != "analysis":
                    job.remove()
            scheduler.add_job(seed_demo, "interval", minutes=15, args=[repo], id="demo:refresh")
        scheduler.start()
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):  # not available on Windows
                loop.add_signal_handler(sig, stop.set)
        log.info("worker_started", sources=sorted(worker.jobs), demo=settings.demo)
        try:
            await stop.wait()
        finally:
            scheduler.shutdown(wait=False)
            await repo.close()


def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    start_http_server(METRICS_PORT)
    asyncio.run(main(settings))


if __name__ == "__main__":
    run()
