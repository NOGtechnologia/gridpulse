"""Thresholds for the rule engine. All values are configurable via settings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True, slots=True)
class RuleConfig:
    # Frequency traffic light (spec 2.1): green <= 50 mHz, yellow <= 100 mHz, red above.
    frequency_green_mhz: float = 50.0
    frequency_yellow_mhz: float = 100.0
    # Deviations above 200 mHz exceed the ENTSO-E Continental Europe standard
    # frequency range for normal operation and are treated as critical.
    frequency_critical_mhz: float = 200.0
    forecast_error_relative: float = 0.10
    forecast_error_floor_mw: float = 1000.0
    price_spike_warning: float = 500.0
    price_spike_critical: float = 1000.0
    stat_window: int = 96
    stat_threshold: float = 4.0
    stale_after: timedelta = timedelta(hours=3)
    dunkelflaute_share: float = 0.10
    dunkelflaute_min_duration: timedelta = timedelta(hours=6)
    crosscheck_tolerance: float = 0.05
