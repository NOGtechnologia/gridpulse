from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from gridpulse.storage.repository import ModelRun

FIXTURES = Path(__file__).parent / "fixtures"


def read_fixture(source: str, name: str) -> Any:
    path = FIXTURES / source / name
    text = path.read_text(encoding="utf-8")
    return text if path.suffix == ".xml" else json.loads(text)


@pytest.fixture
def load_fixture() -> Callable[[str, str], Any]:
    return read_fixture


def _model_run(
    trained_at: datetime,
    *,
    active: bool = True,
    mape_model: float | None = 4.0,
) -> ModelRun:
    return ModelRun(
        trained_at=trained_at,
        algorithm="test",
        seed=42,
        target="load.residual",
        features=("weather.temperature_2m@WX:a", "hour"),
        train_start=trained_at - timedelta(days=30),
        train_end=trained_at - timedelta(days=7),
        test_start=trained_at - timedelta(days=7),
        test_end=trained_at,
        test_points=168,
        mae_model=900.0,
        mape_model=mape_model,
        mae_official=1000.0,
        mape_official=5.0,
        active=active,
    )


@pytest.fixture
def model_run() -> Callable[..., ModelRun]:
    """Factory for stored backtest runs of the own forecasting model."""
    return _model_run
