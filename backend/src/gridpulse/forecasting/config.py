"""Configuration of the own forecasting model (from GRIDPULSE_FORECAST_MODEL_* settings)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True, slots=True)
class ModelConfig:
    history: timedelta = timedelta(days=90)
    test_days: int = 7
    min_train_days: int = 14
    horizon: timedelta = timedelta(hours=48)
