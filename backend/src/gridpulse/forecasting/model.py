"""Gradient-boosted residual-load model and its backtest against the official forecast."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from gridpulse.domain.scores import Scores, beats, score

SEED = 42
ALGORITHM = "scikit-learn HistGradientBoostingRegressor"
HOUR = timedelta(hours=1)
# Gaps in the stored history are tolerated as long as 3/4 of the hours are present.
MIN_COVERAGE = 0.75


def make_model() -> HistGradientBoostingRegressor:
    # early_stopping=False: no random validation split, so a fixed seed fully
    # determines the model (ADR 0010).
    return HistGradientBoostingRegressor(
        max_iter=300, learning_rate=0.05, random_state=SEED, early_stopping=False
    )


@dataclass(frozen=True, slots=True)
class BacktestResult:
    train_start: datetime
    train_end: datetime  # exclusive
    test_start: datetime
    test_end: datetime  # exclusive
    model: Scores
    official: Scores
    active: bool  # own model beats the official forecast on MAE *and* MAPE


def fit_predict(features: pd.DataFrame, target: pd.Series, future: pd.DataFrame) -> pd.Series:
    """Fit on all rows that have features and a target, predict ``future``."""
    rows = features.index.intersection(target.dropna().index)
    if rows.empty:
        raise ValueError("no training rows with features and target")
    model = make_model()
    model.fit(features.loc[rows].to_numpy(), target.loc[rows].to_numpy())
    predicted = np.asarray(model.predict(future.to_numpy()), dtype="float64")
    return pd.Series(predicted, index=future.index, name="prediction")


def backtest(
    features: pd.DataFrame,
    target: pd.Series,
    official: pd.Series,
    *,
    test_days: int,
    min_train_days: int,
) -> BacktestResult | None:
    """Chronological holdout: the last ``test_days`` days with an official forecast are
    the test window, everything before it is training. ``None`` if history is too short."""
    rows = features.index.intersection(target.dropna().index)
    scored = rows.intersection(official.dropna().index)
    if scored.empty:
        return None
    test_end = scored.max() + HOUR
    test_start = test_end - timedelta(days=test_days)
    test = scored[scored >= test_start]
    train = rows[rows < test_start]
    if len(train) < min_train_days * 24 * MIN_COVERAGE:
        return None
    predicted = fit_predict(features.loc[train], target.loc[train], features.loc[test])
    model_scores = score(target.loc[test], predicted)
    official_scores = score(target.loc[test], official.loc[test])
    return BacktestResult(
        train_start=train.min().to_pydatetime(),
        train_end=(train.max() + HOUR).to_pydatetime(),
        test_start=test_start.to_pydatetime(),
        test_end=test_end.to_pydatetime(),
        model=model_scores,
        official=official_scores,
        active=beats(model_scores, official_scores),
    )
