"""Cross-check the same metric from two independent sources (spec 7.4).

SMARD and Energy-Charts both publish German generation, load and prices. Comparing
them is the automatic sanity check of the data itself.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from gridpulse.domain.metrics import MetricId
from gridpulse.validation.plausibility import Violation


@dataclass(frozen=True, slots=True)
class CrosscheckResult:
    metric: str
    compared_points: int
    violations: list[Violation]

    @property
    def deviation_ratio(self) -> float:
        return len(self.violations) / self.compared_points if self.compared_points else 0.0


def crosscheck(
    primary: pd.Series,
    secondary: pd.Series,
    *,
    metric: MetricId,
    area: str,
    primary_source: str,
    secondary_source: str,
    tolerance: float,
    floor: float = 1.0,
) -> CrosscheckResult:
    """XCHK-001: relative deviation |a - b| / max(|a|, |b|, floor) above ``tolerance``.

    ``floor`` avoids huge relative errors for values near zero (e.g. PV at night
    or prices around 0 EUR/MWh).
    """
    joined = pd.concat({"a": primary, "b": secondary}, axis=1, join="inner").dropna().sort_index()
    violations = []
    for stamp, a, b in zip(
        pd.DatetimeIndex(joined.index).to_pydatetime(),
        joined["a"].to_numpy(dtype=float),
        joined["b"].to_numpy(dtype=float),
        strict=True,
    ):
        reference = max(abs(a), abs(b), floor)
        deviation = abs(a - b) / reference
        if deviation > tolerance:
            violations.append(
                Violation(
                    rule_id="XCHK-001",
                    ts=stamp,
                    metric=metric.value,
                    area=area,
                    source=f"{primary_source}|{secondary_source}",
                    value=deviation,
                    threshold=tolerance,
                    message=(
                        f"{metric.value}: {primary_source}={a:.2f} vs {secondary_source}={b:.2f} "
                        f"deviates {deviation:.1%} (> {tolerance:.0%})"
                    ),
                )
            )
    return CrosscheckResult(metric.value, len(joined), violations)
