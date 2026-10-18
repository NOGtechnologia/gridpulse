"""Configuration exclusively via environment variables (spec 9). See .env.example."""

from __future__ import annotations

from datetime import timedelta
from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from gridpulse.domain.rules.config import RuleConfig
from gridpulse.validation.plausibility import PlausibilityConfig


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GRIDPULSE_", extra="ignore")

    # --- core -------------------------------------------------------------
    database_url: str = "postgresql+asyncpg://gridpulse:gridpulse@localhost:5432/gridpulse"
    demo: bool = False
    log_level: str = "INFO"
    log_json: bool = True
    public_url: str = "http://localhost:3000"

    # --- sources ----------------------------------------------------------------
    entsoe_token: SecretStr | None = None
    http_timeout_seconds: float = 30.0
    ingest_interval_minutes: int = Field(default=15, ge=1)
    frequency_interval_minutes: int = Field(default=1, ge=1)
    weather_interval_minutes: int = Field(default=60, ge=5)
    backfill_hours: int = Field(default=48, ge=1)
    forecast_horizon_hours: int = Field(default=48, ge=1)

    # --- API --------------------------------------------------------------------
    # Containers must listen on all interfaces; for bare-metal use set 127.0.0.1.
    api_host: str = "0.0.0.0"  # noqa: S104 - see comment above
    api_port: int = 8000
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    rate_limit_per_minute: int = Field(default=120, ge=1)
    require_api_key: bool = False
    # Protects the only write-like endpoint (POST /api/v1/alerts/test). Unset = disabled.
    admin_token: SecretStr | None = None
    trust_proxy_headers: bool = False
    max_page_size: int = Field(default=10_000, ge=1)
    max_export_rows: int = Field(default=500_000, ge=1)

    # --- retention (TimescaleDB policies) -----------------------------------------
    retention_raw_days: int = Field(default=730, ge=1)
    retention_frequency_days: int = Field(default=30, ge=1)
    compress_after_days: int = Field(default=7, ge=1)

    # --- rules ------------------------------------------------------------------
    freq_yellow_mhz: float = 100.0
    freq_critical_mhz: float = 200.0
    forecast_error_relative: float = 0.10
    price_spike_warning: float = 500.0
    price_spike_critical: float = 1000.0
    stale_after_hours: float = 3.0
    dunkelflaute_share: float = 0.10
    dunkelflaute_min_hours: float = 6.0
    crosscheck_tolerance: float = 0.05
    stat_threshold: float = 4.0

    # --- plausibility --------------------------------------------------------------
    pv_night_tolerance_mw: float = 50.0
    balance_tolerance: float = 0.15
    price_min_eur_mwh: float = -500.0
    price_max_eur_mwh: float = 4000.0

    # --- alerts -------------------------------------------------------------------
    alert_debounce_minutes: int = Field(default=60, ge=0)
    alert_min_severity: str = "warning"
    alert_webhook_urls: Annotated[list[str], NoDecode] = []
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str = "gridpulse@localhost"
    smtp_to: Annotated[list[str], NoDecode] = []
    smtp_starttls: bool = True

    @field_validator("cors_origins", "alert_webhook_urls", "smtp_to", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Lists are given as comma-separated environment variables."""
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return value

    def rule_config(self) -> RuleConfig:
        return RuleConfig(
            frequency_yellow_mhz=self.freq_yellow_mhz,
            frequency_critical_mhz=self.freq_critical_mhz,
            forecast_error_relative=self.forecast_error_relative,
            price_spike_warning=self.price_spike_warning,
            price_spike_critical=self.price_spike_critical,
            stale_after=timedelta(hours=self.stale_after_hours),
            dunkelflaute_share=self.dunkelflaute_share,
            dunkelflaute_min_duration=timedelta(hours=self.dunkelflaute_min_hours),
            crosscheck_tolerance=self.crosscheck_tolerance,
            stat_threshold=self.stat_threshold,
        )

    def plausibility_config(self) -> PlausibilityConfig:
        return PlausibilityConfig(
            pv_night_tolerance_mw=self.pv_night_tolerance_mw,
            balance_tolerance=self.balance_tolerance,
            price_min_eur_mwh=self.price_min_eur_mwh,
            price_max_eur_mwh=self.price_max_eur_mwh,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
