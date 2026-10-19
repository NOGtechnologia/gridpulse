"""Pydantic response models shared by services and the public API (OpenAPI 3.1)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LIGHT = Literal["green", "yellow", "red"]


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Attribution(Model):
    source: str = Field(description="Adapter id(s), e.g. 'smard' or 'smard|energy_charts'")
    license: str
    attribution: str


class Meta(Model):
    source: str
    license: str
    attribution: str
    generated_at: datetime
    count: int | None = None
    total: int | None = None
    next_offset: int | None = None
    disclaimer: str = (
        "GridPulse is an advisory, read-only tool and no substitute for certified control systems."
    )


class Value(Model):
    value: float | None
    unit: str
    ts: datetime | None = Field(description="Interval start, UTC")
    source: str | None
    age_seconds: float | None = None
    stale: bool = False


class ObservationOut(Model):
    ts: datetime
    metric: str
    area: str
    kind: str
    source: str
    unit: str
    value: float


class ObservationsResponse(Model):
    meta: Meta
    data: list[ObservationOut]


class FrequencyPoint(Model):
    ts: datetime
    value: float


class FrequencySummary(Model):
    current: Value
    deviation_mhz: float | None
    status: LIGHT | None
    sparkline: list[FrequencyPoint]


class FlowOut(Model):
    neighbour: str
    value: float = Field(description="MW, positive = import into DE")
    ts: datetime


class SummaryNow(Model):
    meta: Meta
    as_of: datetime | None
    generation: dict[str, Value]
    load: Value
    residual_load: Value
    renewable_share: Value
    co2_intensity: Value
    price: Value
    price_negative: bool | None
    net_import: Value
    flows: list[FlowOut]
    frequency: FrequencySummary
    sources: list[Attribution]


class ForecastPoint(Model):
    ts: datetime
    load: float
    wind: float
    solar: float
    residual_load: float
    official_residual_load: float | None = None
    model_residual_load: float | None = Field(
        default=None, description="Own model (hourly); only set while `model.active` is true"
    )


class ModelBacktest(Model):
    """Latest backtest of the own model against the official forecast (always reported)."""

    trained_at: datetime
    algorithm: str
    seed: int
    target: str
    features: list[str]
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    test_points: int
    unit: str = "MW"
    mae_model: float
    mape_model: float | None = Field(description="Percent; hours with |actual| >= 1000 MW only")
    mae_official: float
    mape_official: float | None
    active: bool = Field(
        description="True when the model beats the official forecast on MAE and MAPE"
    )


class OutlookWindow(Model):
    kind: Literal["negative_price", "dunkelflaute"]
    start: datetime
    end: datetime
    hours: float
    detail: str


class ForecastResponse(Model):
    meta: Meta
    unit: str = "MW"
    points: list[ForecastPoint]
    windows: list[OutlookWindow]
    model: ModelBacktest | None = Field(
        default=None, description="Own forecasting model (phase 7); null until a backtest ran"
    )


class EventOut(Model):
    id: str
    ts: datetime
    rule_id: str
    severity: str
    category: str
    metric: str
    area: str
    value: float | None
    threshold: float | None
    unit: str | None
    source: str
    message: str


class EventsResponse(Model):
    meta: Meta
    data: list[EventOut]


class SourceStatusOut(Model):
    source: str
    license: str
    attribution: str
    last_attempt: datetime | None
    last_success: datetime | None
    last_error: str | None
    latency_ms: float | None
    rows_last_run: int
    gap_ratio: float
    plausibility_violations: int
    consecutive_failures: int
    newest_data: datetime | None
    data_age_seconds: float | None
    healthy: bool


class SourcesResponse(Model):
    meta: Meta
    data: list[SourceStatusOut]


class MetricOut(Model):
    id: str
    unit: str
    category: str
    renewable: bool
    color: str | None


class MetricsCatalog(Model):
    data: list[MetricOut]


class AlertTestResult(Model):
    results: dict[str, str]


class ErrorOut(Model):
    detail: str


class Health(Model):
    status: Literal["ok", "degraded", "fail"]
    checks: dict[str, str] = {}
