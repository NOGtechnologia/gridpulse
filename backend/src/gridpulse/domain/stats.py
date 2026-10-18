"""Robust rolling statistics for anomaly detection (spec 2.3)."""

from __future__ import annotations

import numpy as np
import pandas as pd

# Scale factor that makes the MAD a consistent estimator of the standard deviation
# for normally distributed data.
MAD_TO_SIGMA = 1.4826


def rolling_zscore(series: pd.Series, window: int, min_periods: int | None = None) -> pd.Series:
    """Z-score of each point against the *preceding* ``window`` points (no look-ahead)."""
    if window < 2:
        raise ValueError("window must be >= 2")
    min_p = window if min_periods is None else min_periods
    past = series.shift(1).rolling(window, min_periods=min_p)
    mean = past.mean()
    std = past.std(ddof=1)
    z = (series - mean) / std.replace(0.0, np.nan)
    return z.astype("float64")


def rolling_mad_score(series: pd.Series, window: int, min_periods: int | None = None) -> pd.Series:
    """Robust score ``(x - median) / (1.4826 * MAD)`` over the preceding ``window`` points."""
    if window < 2:
        raise ValueError("window must be >= 2")
    min_p = window if min_periods is None else min_periods
    past = series.shift(1)

    def _mad(values: np.ndarray) -> float:
        # Windows may contain NaN (gaps); rolling() already enforced min_periods.
        return float(np.nanmedian(np.abs(values - np.nanmedian(values))))

    median = past.rolling(window, min_periods=min_p).median()
    mad = past.rolling(window, min_periods=min_p).apply(_mad, raw=True)
    score = (series - median) / (MAD_TO_SIGMA * mad).replace(0.0, np.nan)
    return score.astype("float64")
