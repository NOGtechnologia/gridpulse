"""Runtime plausibility checks (spec 7.4).

Violations are never dropped silently: every check returns :class:`Violation` objects
that the worker records as ``data_quality`` events. The checks do not modify data.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from gridpulse.domain.metrics import CATALOG, GENERATION_METRICS, Kind, MetricId
from gridpulse.domain.observations import iter_observations
from gridpulse.domain.rules.model import Event, EventCategory, Severity
from gridpulse.domain.solar import is_night


@dataclass(frozen=True, slots=True)
class PlausibilityConfig:
    frequency_min_hz: float = 49.0
    frequency_max_hz: float = 51.0
    pv_night_tolerance_mw: float = 50.0
    balance_tolerance: float = 0.15
    # SDAC harmonised maximum and minimum clearing price for the single day-ahead
    # coupling (HMMCP): -500 / +4000 EUR/MWh (ACER Decision 01/2023, applied since
    # 2023). Configurable because the HMMCP is raised automatically after spikes.
    price_min_eur_mwh: float = -500.0
    price_max_eur_mwh: float = 4000.0


@dataclass(frozen=True, slots=True)
class Violation:
    rule_id: str
    ts: datetime
    metric: str
    area: str
    source: str
    value: float | None
    threshold: float | None
    message: str

    def to_event(self) -> Event:
        return Event(
            ts=self.ts,
            rule_id=self.rule_id,
            severity=Severity.WARNING,
            category=EventCategory.DATA_QUALITY,
            metric=self.metric,
            area=self.area,
            value=self.value,
            threshold=self.threshold,
            source=self.source,
            message=self.message,
        )


def _violations(
    frame: pd.DataFrame, mask: pd.Series, rule_id: str, threshold: float | None, template: str
) -> list[Violation]:
    return [
        Violation(
            rule_id=rule_id,
            ts=obs.ts,
            metric=obs.metric.value,
            area=obs.area,
            source=obs.source,
            value=obs.value,
            threshold=threshold,
            message=template.format(value=obs.value, metric=obs.metric.value),
        )
        for obs in iter_observations(frame[mask])
    ]


def check_frequency_range(frame: pd.DataFrame, cfg: PlausibilityConfig) -> list[Violation]:
    """PLAUS-001: grid frequency within 49.0-51.0 Hz."""
    sel = frame["metric"] == MetricId.GRID_FREQUENCY.value
    low = sel & (frame["value"] < cfg.frequency_min_hz)
    high = sel & (frame["value"] > cfg.frequency_max_hz)
    return _violations(
        frame, low, "PLAUS-001", cfg.frequency_min_hz, "Frequency {value} Hz below plausible range"
    ) + _violations(
        frame, high, "PLAUS-001", cfg.frequency_max_hz, "Frequency {value} Hz above plausible range"
    )


def check_non_negative(frame: pd.DataFrame) -> list[Violation]:
    """PLAUS-002: values >= 0 unless negative values are meaningful for the metric.

    Pumped-storage consumption is a separate, non-negative metric; net import, residual
    load, price and temperature may be negative.
    """
    allowed_negative = {m.value for m, info in CATALOG.items() if info.may_be_negative}
    mask = (~frame["metric"].isin(allowed_negative)) & (frame["value"] < 0)
    return _violations(frame, mask, "PLAUS-002", 0.0, "Negative value {value} for {metric}")


def check_pv_at_night(frame: pd.DataFrame, cfg: PlausibilityConfig) -> list[Violation]:
    """PLAUS-003: solar generation ~0 at night (sun below civil twilight over Germany)."""
    sel = (
        (frame["metric"] == MetricId.GENERATION_SOLAR.value)
        & (frame["kind"] == Kind.ACTUAL.value)
        & (frame["area"].isin(["DE", "DE-LU"]))
        & (frame["value"] > cfg.pv_night_tolerance_mw)
    )
    if not sel.any():
        return []
    night = pd.Series(
        [is_night(t) for t in pd.DatetimeIndex(frame["ts"]).to_pydatetime()],
        index=frame.index,
        dtype=bool,
    )
    return _violations(
        frame,
        sel & night,
        "PLAUS-003",
        cfg.pv_night_tolerance_mw,
        "Solar generation {value} MW at night",
    )


def check_price_range(frame: pd.DataFrame, cfg: PlausibilityConfig) -> list[Violation]:
    """PLAUS-004: day-ahead price within the harmonised clearing price limits."""
    sel = frame["metric"] == MetricId.PRICE_DAY_AHEAD.value
    mask = sel & (
        (frame["value"] < cfg.price_min_eur_mwh) | (frame["value"] > cfg.price_max_eur_mwh)
    )
    return _violations(
        frame,
        mask,
        "PLAUS-004",
        cfg.price_max_eur_mwh,
        "Price {value} EUR/MWh outside clearing limits",
    )


def check_time_axis(frame: pd.DataFrame) -> list[Violation]:
    """PLAUS-005: per series, no duplicate timestamps and no gaps on the resolution grid."""
    out: list[Violation] = []
    for key, group in frame.groupby(["metric", "area", "kind", "source"], sort=True):
        metric, area, kind, source = (str(k) for k in key)
        ts = pd.DatetimeIndex(group["ts"])
        for stamp in ts[ts.duplicated(keep="first")].to_pydatetime():
            out.append(
                Violation(
                    "PLAUS-005",
                    stamp,
                    metric,
                    area,
                    source,
                    None,
                    None,
                    f"Duplicate timestamp in {metric} ({kind})",
                )
            )
        ordered = ts.drop_duplicates().sort_values().to_pydatetime()
        step = pd.Timedelta(group["resolution"].iloc[0]).to_pytimedelta()
        for prev, stamp in itertools.pairwise(ordered):
            if stamp - prev <= step:
                continue
            missing = int((stamp - prev) / step) - 1
            out.append(
                Violation(
                    "PLAUS-005",
                    stamp,
                    metric,
                    area,
                    source,
                    float(missing),
                    0.0,
                    f"Gap of {missing} interval(s) before this point in {metric} ({kind})",
                )
            )
    return out


def check_balance(frame: pd.DataFrame, cfg: PlausibilityConfig) -> list[Violation]:
    """PLAUS-006: generation + net import - pumped consumption ~= load (relative tolerance).

    Only evaluated for timestamps where load, net import and at least one generation
    value of the same source and area are present.
    """
    actual = frame[frame["kind"] == Kind.ACTUAL.value]
    gen_values = {m.value for m in GENERATION_METRICS}
    out: list[Violation] = []
    for key, group in actual.groupby(["area", "source"], sort=True):
        area, source = (str(k) for k in key)
        wide = group.pivot_table(index="ts", columns="metric", values="value", aggfunc="first")
        needed = {MetricId.LOAD_ACTUAL.value, MetricId.FLOW_NET_IMPORT.value}
        gen_cols = [c for c in wide.columns if c in gen_values]
        if not needed.issubset(wide.columns) or not gen_cols:
            continue
        pumped = (
            wide[MetricId.CONSUMPTION_PUMPED_STORAGE.value].fillna(0.0)
            if MetricId.CONSUMPTION_PUMPED_STORAGE.value in wide.columns
            else 0.0
        )
        supply = (
            wide[gen_cols].sum(axis=1, min_count=1) + wide[MetricId.FLOW_NET_IMPORT.value] - pumped
        )
        load = wide[MetricId.LOAD_ACTUAL.value]
        rel = ((supply - load) / load).dropna()
        bad = rel[rel.abs() > cfg.balance_tolerance]
        for stamp, value in zip(
            pd.DatetimeIndex(bad.index).to_pydatetime(), bad.to_numpy(dtype=float), strict=True
        ):
            out.append(
                Violation(
                    "PLAUS-006",
                    stamp,
                    MetricId.LOAD_ACTUAL.value,
                    area,
                    source,
                    float(value),
                    cfg.balance_tolerance,
                    f"Supply/load imbalance {value:+.1%} exceeds +-{cfg.balance_tolerance:.0%}",
                )
            )
    return out


def run_all(frame: pd.DataFrame, cfg: PlausibilityConfig | None = None) -> list[Violation]:
    """Run every plausibility check on a canonical frame."""
    cfg = cfg or PlausibilityConfig()
    if frame.empty:
        return []
    return [
        *check_frequency_range(frame, cfg),
        *check_non_negative(frame),
        *check_pv_at_night(frame, cfg),
        *check_price_range(frame, cfg),
        *check_time_axis(frame),
        *check_balance(frame, cfg),
    ]
