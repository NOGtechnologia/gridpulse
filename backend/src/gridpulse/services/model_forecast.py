"""Train, backtest and run the own residual-load model on stored data (phase 7, ADR 0010)."""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from gridpulse.domain.metrics import Kind, MetricId
from gridpulse.domain.observations import make_frame
from gridpulse.domain.timeutils import floor_to
from gridpulse.forecasting.config import ModelConfig
from gridpulse.forecasting.features import (
    WEATHER_METRICS,
    build_features,
    hourly_mean,
    weather_matrix,
)
from gridpulse.forecasting.model import ALGORITHM, SEED, backtest, fit_predict
from gridpulse.observability import get_logger
from gridpulse.services.series import fetch_frame, pick_series
from gridpulse.storage.repository import ModelRun, QueryResolution, Repository

log = get_logger(__name__)

MODEL_SOURCE = "gridpulse_model"
TARGET = MetricId.LOAD_RESIDUAL
# Target and benchmark come from the same publisher, so both use one definition of
# residual load (SMARD: load minus wind and PV).
TARGET_SOURCE = "smard"
HOUR = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class Dataset:
    features: pd.DataFrame
    target: pd.Series
    official: pd.Series


async def load_dataset(repo: Repository, now: datetime, config: ModelConfig) -> Dataset:
    start = floor_to(now - config.history, HOUR)
    end = floor_to(now + config.horizon, HOUR)
    actual = await fetch_frame(repo, [TARGET], start, now, sources=[TARGET_SOURCE])
    official = await fetch_frame(
        repo, [TARGET], start, end, kind=Kind.FORECAST, sources=[TARGET_SOURCE]
    )
    weather = await fetch_frame(
        repo,
        WEATHER_METRICS,
        start,
        end,
        kind=Kind.FORECAST,
        areas=None,
        sources=["open_meteo"],
        resolution=QueryResolution.RAW,
    )
    index = pd.date_range(start, end, freq="1h", inclusive="left")
    return Dataset(
        features=build_features(weather_matrix(weather), index),
        target=hourly_mean(pick_series(actual, TARGET)),
        official=hourly_mean(pick_series(official, TARGET)),
    )


def _finite(value: float) -> float | None:
    return None if math.isnan(value) else value


async def run_model(
    repo: Repository, now: datetime, config: ModelConfig, *, store: bool = True
) -> tuple[ModelRun | None, pd.Series]:
    """Backtest, refit on all history and forecast; ``(None, empty)`` without enough data.

    With ``store`` the run is saved and the forecast written as observations
    (``load.residual``/``forecast``/``gridpulse_model``).
    """
    data = await load_dataset(repo, now, config)
    result = await asyncio.to_thread(
        backtest,
        data.features,
        data.target,
        data.official,
        test_days=config.test_days,
        min_train_days=config.min_train_days,
    )
    if result is None:
        log.info(
            "forecast_model_skipped",
            reason="not enough history with weather, actuals and official forecast",
            hours_with_target=len(data.target),
            hours_with_features=len(data.features),
        )
        return None, pd.Series(dtype="float64")
    future = data.features[data.features.index > data.target.index.max()]
    prediction = await asyncio.to_thread(fit_predict, data.features, data.target, future)
    run = ModelRun(
        trained_at=now,
        algorithm=ALGORITHM,
        seed=SEED,
        target=TARGET.value,
        features=tuple(str(c) for c in data.features.columns),
        train_start=result.train_start,
        train_end=result.train_end,
        test_start=result.test_start,
        test_end=result.test_end,
        test_points=result.model.points,
        mae_model=result.model.mae,
        mape_model=_finite(result.model.mape),
        mae_official=result.official.mae,
        mape_official=_finite(result.official.mape),
        active=result.active,
    )
    if store:
        await repo.upsert_observations(
            make_frame(
                timestamps=[t.to_pydatetime() for t in prediction.index],
                values=prediction.tolist(),
                metric=TARGET,
                area="DE",
                kind=Kind.FORECAST,
                source=MODEL_SOURCE,
                resolution=HOUR,
            )
        )
        await repo.save_model_run(run)
    log.info(
        "forecast_model_trained",
        active=run.active,
        mae_model=round(run.mae_model, 1),
        mae_official=round(run.mae_official, 1),
        predicted_hours=len(prediction),
    )
    return run, prediction
