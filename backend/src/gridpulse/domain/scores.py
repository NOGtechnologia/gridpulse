"""Forecast accuracy scores for the backtest against the official forecast (ADR 0010)."""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

# Residual load can approach 0 MW, where percentage errors explode. MAPE is computed
# over hours with |actual| >= this floor only; MAE always uses every common hour.
MAPE_FLOOR_MW = 1000.0


@dataclass(frozen=True, slots=True)
class Scores:
    mae: float
    mape: float  # percent
    points: int


def score(actual: pd.Series, predicted: pd.Series, *, mape_floor: float = MAPE_FLOOR_MW) -> Scores:
    """MAE and MAPE (%) over the timestamps where both series have a value."""
    joined = pd.concat({"a": actual, "p": predicted}, axis=1).dropna()
    if joined.empty:
        raise ValueError("no common timestamps between actual and predicted values")
    error = (joined["p"] - joined["a"]).abs()
    relevant = joined["a"].abs() >= mape_floor
    mape = (
        float((error[relevant] / joined["a"][relevant].abs()).mean() * 100)
        if relevant.any()
        else math.nan
    )
    return Scores(mae=float(error.mean()), mape=mape, points=len(joined))


def beats(model: Scores, official: Scores) -> bool:
    """The own model is only shown if it is better on *both* metrics (NaN never wins)."""
    return model.mae < official.mae and model.mape < official.mape
