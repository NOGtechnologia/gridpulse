"""Own forecasting model on stored observations: training job and outlook gating (phase 7)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx
import numpy as np
import pandas as pd

from gridpulse.adapters.open_meteo import DEFAULT_LOCATIONS, weather_area
from gridpulse.domain.metrics import Kind, MetricId
from gridpulse.domain.observations import concat_frames, make_frame
from gridpulse.forecasting.config import ModelConfig
from gridpulse.forecasting.features import WEATHER_METRICS
from gridpulse.services.forecast import build_forecast
from gridpulse.services.model_forecast import MODEL_SOURCE, run_model
from gridpulse.settings import Settings
from gridpulse.storage.memory import MemoryRepository
from gridpulse.storage.repository import ModelRun, ObservationQuery
from gridpulse.worker.scheduler import Worker, build_scheduler

NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)
CONFIG = ModelConfig(history=timedelta(days=40), test_days=7, min_train_days=14)
Q = timedelta(minutes=15)


def _series(start: datetime, values: np.ndarray, step: timedelta) -> list[datetime]:
    return [start + i * step for i in range(len(values))]


async def _seed(repo: MemoryRepository, *, days: int, official_noise: float) -> None:
    """Weather -> residual load relation the model can learn; official forecast with noise."""
    start = NOW - timedelta(days=days)
    hours = days * 24 + 48
    rng = np.random.default_rng(7)
    weather = {
        (metric, loc.name): rng.uniform(0, 30, hours)
        for metric in WEATHER_METRICS
        for loc in DEFAULT_LOCATIONS
    }
    hourly_stamps = [start + timedelta(hours=h) for h in range(hours)]
    frames = [
        make_frame(
            timestamps=hourly_stamps,
            values=values.tolist(),
            metric=metric,
            area=weather_area(name),
            kind=Kind.FORECAST,
            source="open_meteo",
            resolution=timedelta(hours=1),
        )
        for (metric, name), values in weather.items()
    ]
    wind = weather[(MetricId.WEATHER_WIND_SPEED_100M, "hamburg")]
    truth_hourly = 40_000 - 900 * wind
    truth = np.repeat(truth_hourly, 4)  # quarter-hours
    stamps = _series(start, truth, Q)
    past = [i for i, t in enumerate(stamps) if t < NOW]
    frames.append(
        make_frame(
            timestamps=[stamps[i] for i in past],
            values=(truth[past] + rng.normal(0, 100, len(past))).tolist(),
            metric=MetricId.LOAD_RESIDUAL,
            area="DE",
            kind=Kind.ACTUAL,
            source="smard",
            resolution=Q,
        )
    )
    frames.append(
        make_frame(
            timestamps=stamps,
            values=(truth + rng.normal(0, official_noise, len(truth))).tolist(),
            metric=MetricId.LOAD_RESIDUAL,
            area="DE",
            kind=Kind.FORECAST,
            source="smard",
            resolution=Q,
        )
    )
    # Inputs of the regular outlook (official load/wind/PV forecasts) for the next hours.
    future = [NOW + i * Q for i in range(8)]
    for metric, value in (
        (MetricId.LOAD_ACTUAL, 50_000.0),
        (MetricId.GENERATION_WIND_ONSHORE, 10_000.0),
        (MetricId.GENERATION_SOLAR, 5_000.0),
    ):
        frames.append(
            make_frame(
                timestamps=future,
                values=[value] * len(future),
                metric=metric,
                area="DE",
                kind=Kind.FORECAST,
                source="smard",
                resolution=Q,
            )
        )
    await repo.upsert_observations(concat_frames(frames))


async def _model_rows(repo: MemoryRepository) -> pd.DataFrame:
    return await repo.query_observations(
        ObservationQuery(
            metrics=["load.residual"],
            start=NOW - timedelta(days=60),
            end=NOW + timedelta(days=3),
            sources=[MODEL_SOURCE],
        )
    )


async def test_model_beating_the_official_forecast_is_shown() -> None:
    repo = MemoryRepository()
    await _seed(repo, days=30, official_noise=5_000)
    run, prediction = await run_model(repo, NOW, CONFIG)
    assert run is not None and run.active
    assert run.mae_model < run.mae_official
    assert run.test_points == 7 * 24
    assert len(run.features) == len(WEATHER_METRICS) * len(DEFAULT_LOCATIONS) + 3
    # Forecast from the first hour without actuals up to the 48 h horizon.
    assert prediction.index.min() == pd.Timestamp(NOW)
    assert len(prediction) == 48
    assert len(await _model_rows(repo)) == 48
    assert await repo.latest_model_run() == run

    outlook = await build_forecast(repo, NOW, 2, Settings().rule_config())
    assert outlook.model is not None and outlook.model.active
    with_model = [p for p in outlook.points if p.model_residual_load is not None]
    assert [p.ts for p in with_model] == [NOW, NOW + timedelta(hours=1)]
    assert MODEL_SOURCE in outlook.meta.source
    assert "forecasting model" in outlook.meta.attribution


async def test_model_worse_than_official_is_reported_but_hidden() -> None:
    repo = MemoryRepository()
    await _seed(repo, days=30, official_noise=10)
    run, _ = await run_model(repo, NOW, CONFIG)
    assert run is not None and not run.active
    outlook = await build_forecast(repo, NOW, 2, Settings().rule_config())
    assert outlook.model is not None
    assert not outlook.model.active
    assert outlook.model.mae_official < outlook.model.mae_model
    assert all(p.model_residual_load is None for p in outlook.points)
    assert MODEL_SOURCE not in outlook.meta.source


async def test_model_needs_enough_history_and_dry_run_stores_nothing() -> None:
    repo = MemoryRepository()
    await _seed(repo, days=10, official_noise=1_000)
    run, prediction = await run_model(repo, NOW, CONFIG)
    assert run is None and prediction.empty
    assert (await build_forecast(repo, NOW, 2, Settings().rule_config())).model is None

    await _seed(repo, days=30, official_noise=1_000)
    run, prediction = await run_model(repo, NOW, CONFIG, store=False)
    assert run is not None and not prediction.empty
    assert await repo.latest_model_run() is None
    assert (await _model_rows(repo)).empty


async def test_active_run_without_stored_values_adds_nothing(
    model_run: Callable[..., ModelRun],
) -> None:
    repo = MemoryRepository()
    await _seed(repo, days=1, official_noise=0)
    await repo.save_model_run(model_run(NOW, active=True))
    outlook = await build_forecast(repo, NOW, 2, Settings().rule_config())
    assert outlook.model is not None and outlook.model.active
    assert all(p.model_residual_load is None for p in outlook.points)


async def test_worker_schedules_and_runs_the_model_job() -> None:
    repo = MemoryRepository()
    await _seed(repo, days=30, official_noise=5_000)
    settings = Settings(database_url="memory://", forecast_model_history_days=40)
    async with httpx.AsyncClient() as client:
        worker = Worker(repo, settings, client, clock=lambda: NOW)
        assert "forecast_model" in {j.id for j in build_scheduler(worker).get_jobs()}
        run = await worker.train_model()
        assert run is not None
        disabled = Worker(
            repo, Settings(database_url="memory://", forecast_model_enabled=False), client
        )
        assert "forecast_model" not in {j.id for j in build_scheduler(disabled).get_jobs()}
