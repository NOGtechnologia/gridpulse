"""Pandera schema of the canonical observation frame (spec 5.3)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pandera.pandas as pa

from gridpulse.domain.metrics import CATALOG, Kind, MetricId

_METRICS = sorted(m.value for m in MetricId)
_KINDS = sorted(k.value for k in Kind)
_UNIT_BY_METRIC = {m.value: info.unit.value for m, info in CATALOG.items()}


def _unit_matches_metric(frame: pd.DataFrame) -> pd.Series:
    expected = frame["metric"].map(_UNIT_BY_METRIC)
    return frame["unit"] == expected


OBSERVATION_SCHEMA = pa.DataFrameSchema(
    {
        "ts": pa.Column(pd.DatetimeTZDtype(tz="UTC"), nullable=False),
        "resolution": pa.Column(
            "timedelta64[ns]", pa.Check(lambda s: s > pd.Timedelta(0), error="resolution > 0")
        ),
        "metric": pa.Column(None, pa.Check.isin(_METRICS), nullable=False),
        "area": pa.Column(None, pa.Check.str_length(min_value=1), nullable=False),
        "value": pa.Column(
            "float64",
            pa.Check(np.isfinite, error="value must be finite"),
            nullable=False,
        ),
        "unit": pa.Column(None, nullable=False),
        "kind": pa.Column(None, pa.Check.isin(_KINDS), nullable=False),
        "source": pa.Column(None, pa.Check.str_length(min_value=1), nullable=False),
    },
    checks=[pa.Check(_unit_matches_metric, error="unit does not match metric catalogue")],
    strict=True,
    ordered=False,
)


def validate_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate structure; raises ``pandera.errors.SchemaErrors`` listing all failures."""
    return OBSERVATION_SCHEMA.validate(frame, lazy=True)
