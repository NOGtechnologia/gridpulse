"""Residual load = load - wind (onshore + offshore) - solar (spec 2.1)."""

from __future__ import annotations

import pandas as pd


def residual_load_value(
    load: float, wind_onshore: float, wind_offshore: float, solar: float
) -> float:
    """Scalar residual load in MW."""
    return load - wind_onshore - wind_offshore - solar


def residual_load(
    load: pd.Series, wind_onshore: pd.Series, wind_offshore: pd.Series, solar: pd.Series
) -> pd.Series:
    """Residual load series in MW on the timestamps where all four inputs exist."""
    frame = pd.concat(
        {"load": load, "on": wind_onshore, "off": wind_offshore, "pv": solar}, axis=1, join="inner"
    ).dropna()
    result = frame["load"] - frame["on"] - frame["off"] - frame["pv"]
    result.name = "load.residual"
    return result.astype("float64")
