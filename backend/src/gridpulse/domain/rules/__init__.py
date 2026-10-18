"""Rule engine for events (spec 2.3)."""

from gridpulse.domain.rules.catalog import (
    TrafficLight,
    dunkelflaute_outlook,
    forecast_error,
    frequency_deviation,
    frequency_status,
    merge_episodes,
    negative_price_outlook,
    price_spike,
    stale_data,
    statistical_anomaly,
)
from gridpulse.domain.rules.config import RuleConfig
from gridpulse.domain.rules.model import Event, EventCategory, Severity, event_id

__all__ = [
    "Event",
    "EventCategory",
    "RuleConfig",
    "Severity",
    "TrafficLight",
    "dunkelflaute_outlook",
    "event_id",
    "forecast_error",
    "frequency_deviation",
    "frequency_status",
    "merge_episodes",
    "negative_price_outlook",
    "price_spike",
    "stale_data",
    "statistical_anomaly",
]
