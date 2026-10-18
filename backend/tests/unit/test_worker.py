"""Worker composition, scheduler and start-up (mocked HTTP, in-memory repository)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx

from gridpulse.alerts.dispatcher import AlertDispatcher
from gridpulse.observability import configure_logging, get_logger
from gridpulse.settings import Settings
from gridpulse.storage.memory import MemoryRepository
from gridpulse.worker import main as worker_main
from gridpulse.worker.scheduler import Worker, _safe, build_scheduler

Loader = Callable[[str, str], Any]


def _mock_sources(load_fixture: Loader) -> None:
    smard_series = load_fixture("smard", "series_4067_DE_quarterhour.json")
    first = smard_series["series"][0][0]
    respx.get(
        url__regex=r"https://www\.smard\.de/app/chart_data/\d+/[A-Z-]+/index_quarterhour\.json"
    ).mock(return_value=httpx.Response(200, json={"timestamps": [first]}))
    respx.get(url__regex=r"https://www\.smard\.de/app/chart_data/.*_quarterhour_\d+\.json").mock(
        return_value=httpx.Response(200, json=smard_series)
    )
    for name in ("public_power", "price", "cbet", "frequency", "ren_share_forecast"):
        respx.get(f"https://api.energy-charts.info/{name}").mock(
            return_value=httpx.Response(200, json=load_fixture("energy_charts", f"{name}.json"))
        )
    respx.get("https://api.open-meteo.com/v1/forecast").mock(
        return_value=httpx.Response(200, json=load_fixture("open_meteo", "forecast_multi.json"))
    )
    respx.get("https://web-api.tp.entsoe.eu/api").mock(
        return_value=httpx.Response(200, text=load_fixture("entsoe", "actual_load_A65.xml"))
    )


@respx.mock
async def test_worker_ingests_all_sources(load_fixture: Loader) -> None:
    _mock_sources(load_fixture)
    first = datetime.fromtimestamp(
        load_fixture("energy_charts", "public_power.json")["unix_seconds"][0], tz=UTC
    )
    now = first + timedelta(hours=20)
    repo = MemoryRepository()
    settings = Settings(database_url="memory://", entsoe_token="tok")
    async with httpx.AsyncClient() as client:
        worker = Worker(
            repo, settings, client, AlertDispatcher(repo, [], timedelta(0)), clock=lambda: now
        )
        assert set(worker.jobs) == {"smard", "energy_charts", "open_meteo", "entsoe"}
        for source in worker.jobs:
            await worker.ingest(source)
        await worker.ingest_frequency()
        await worker.analyse()
    statuses = {s.source: s for s in await repo.list_source_status()}
    assert statuses["energy_charts"].rows_last_run > 1000
    assert statuses["energy_charts"].last_error is None
    assert statuses["smard"].rows_last_run > 0
    assert "energy_charts_frequency" in statuses


async def test_scheduler_jobs_and_safe_wrapper() -> None:
    async with httpx.AsyncClient() as client:
        worker = Worker(MemoryRepository(), Settings(database_url="memory://"), client)
        scheduler = build_scheduler(worker)
        ids = {job.id for job in scheduler.get_jobs()}
    assert ids == {
        "ingest:smard",
        "ingest:energy_charts",
        "ingest:open_meteo",
        "ingest:frequency",
        "analysis",
    }

    async def boom() -> None:
        raise RuntimeError("x")

    await _safe("boom", boom)()  # must not raise


async def test_prepare_and_seed_memory() -> None:
    repo = await worker_main.prepare(Settings(database_url="memory://", demo=True))
    statuses = await repo.list_source_status()
    assert statuses[0].source == "demo" and statuses[0].rows_last_run > 1000


async def test_prepare_sql_runs_migrations(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(worker_main.migrate, "upgrade", calls.append)

    class FakeSql(MemoryRepository):
        async def apply_retention(self, raw: int, freq: int, compress: int) -> None:
            calls.append(f"retention:{raw}:{freq}:{compress}")

    monkeypatch.setattr(worker_main, "create_repository", lambda url: FakeSql())
    await worker_main.prepare(Settings(database_url="postgresql+asyncpg://x/y"))
    assert calls == ["postgresql+asyncpg://x/y", "retention:730:30:7"]


async def test_main_starts_and_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    stop_holder: dict[str, asyncio.Event] = {}
    real_event = asyncio.Event

    def capture_event() -> asyncio.Event:
        event = real_event()
        stop_holder["e"] = event
        return event

    monkeypatch.setattr(worker_main.asyncio, "Event", capture_event)
    task = asyncio.create_task(worker_main.main(Settings(database_url="memory://", demo=True)))
    for _ in range(200):
        await asyncio.sleep(0.01)
        if "e" in stop_holder:
            break
    stop_holder["e"].set()
    await asyncio.wait_for(task, timeout=10)


def test_run_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[object] = []
    monkeypatch.setattr(worker_main, "start_http_server", seen.append)
    monkeypatch.setattr(worker_main.asyncio, "run", lambda coro: (seen.append("run"), coro.close()))
    monkeypatch.setattr(
        worker_main, "get_settings", lambda: Settings(database_url="memory://", log_json=False)
    )
    worker_main.run()
    assert seen == [9101, "run"]


def test_logging_configuration(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("DEBUG", json=True)
    get_logger("t").info("hello", answer=42)
    out = capsys.readouterr().out
    assert '"answer": 42' in out and '"event": "hello"' in out
    configure_logging("INFO", json=False)
