"""Structured JSON logging and Prometheus metrics (spec 9)."""

from __future__ import annotations

import logging
import sys

import structlog
from prometheus_client import Counter, Gauge, Histogram

INGEST_DURATION = Histogram(
    "gridpulse_ingest_duration_seconds",
    "Duration of one ingest run",
    ["source"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120),
)
INGEST_ERRORS = Counter("gridpulse_ingest_errors_total", "Failed ingest runs", ["source"])
INGEST_ROWS = Counter("gridpulse_ingest_rows_total", "Rows written", ["source"])
DATA_AGE = Gauge("gridpulse_data_age_seconds", "Age of the newest data point", ["source"])
PLAUSIBILITY_VIOLATIONS = Counter(
    "gridpulse_plausibility_violations_total", "Plausibility violations", ["source", "rule_id"]
)
EVENTS_CREATED = Counter("gridpulse_events_total", "New events", ["rule_id", "severity"])
ALERTS_SENT = Counter("gridpulse_alerts_sent_total", "Notifications sent", ["channel", "outcome"])
API_LATENCY = Histogram(
    "gridpulse_api_request_duration_seconds",
    "API latency",
    ["method", "route", "status"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)


def configure_logging(level: str = "INFO", *, json: bool = True) -> None:
    """Configure structlog; secrets must never be passed as log fields."""
    numeric = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    logging.basicConfig(stream=sys.stdout, level=numeric, format="%(message)s")
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str) -> structlog.typing.FilteringBoundLogger:
    logger: structlog.typing.FilteringBoundLogger = structlog.get_logger(name)
    return logger
