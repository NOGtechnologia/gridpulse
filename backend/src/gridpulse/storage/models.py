"""SQLAlchemy table definitions (spec 5.3). Schema changes go through Alembic."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Double,
    Integer,
    Interval,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    func,
)

metadata = MetaData()

observations = Table(
    "observations",
    metadata,
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("resolution", Interval, nullable=False),
    Column("metric", Text, nullable=False),
    Column("area", Text, nullable=False),
    Column("value", Double, nullable=False),
    Column("unit", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("ts", "metric", "area", "kind", "source", name="observations_pkey"),
)

events = Table(
    "events",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("ts", DateTime(timezone=True), nullable=False, index=True),
    Column("rule_id", Text, nullable=False, index=True),
    Column("severity", Text, nullable=False),
    Column("category", Text, nullable=False),
    Column("metric", Text, nullable=False),
    Column("area", Text, nullable=False),
    Column("value", Double),
    Column("threshold", Double),
    Column("unit", Text),
    Column("source", Text, nullable=False),
    Column("message", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("notified_at", DateTime(timezone=True)),
)

source_status = Table(
    "source_status",
    metadata,
    Column("source", Text, primary_key=True),
    Column("last_attempt", DateTime(timezone=True)),
    Column("last_success", DateTime(timezone=True)),
    Column("last_error", Text),
    Column("latency_ms", Double),
    Column("rows_last_run", Integer, nullable=False, server_default="0"),
    Column("expected_points", Integer, nullable=False, server_default="0"),
    Column("received_points", Integer, nullable=False, server_default="0"),
    Column("plausibility_violations", Integer, nullable=False, server_default="0"),
    Column("consecutive_failures", Integer, nullable=False, server_default="0"),
    Column("newest_data", DateTime(timezone=True)),
)

alert_channels = Table(
    "alert_channels",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("name", Text, nullable=False, unique=True),
    Column("kind", Text, nullable=False),  # webhook | slack | teams | smtp
    Column("target", Text, nullable=False),  # URL or e-mail address; never logged
    Column("min_severity", Text, nullable=False, server_default="warning"),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

api_keys = Table(
    "api_keys",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("name", Text, nullable=False),
    Column("key_hash", String(64), nullable=False, unique=True),  # SHA-256 hex, never the key
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("revoked", Boolean, nullable=False, server_default="false"),
)

# Training/backtest runs of the own forecasting model (phase 7, ADR 0010).
model_runs = Table(
    "model_runs",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("trained_at", DateTime(timezone=True), nullable=False, index=True),
    Column("algorithm", Text, nullable=False),
    Column("seed", Integer, nullable=False),
    Column("target", Text, nullable=False),
    Column("features", Text, nullable=False),  # JSON array of feature names
    Column("train_start", DateTime(timezone=True), nullable=False),
    Column("train_end", DateTime(timezone=True), nullable=False),
    Column("test_start", DateTime(timezone=True), nullable=False),
    Column("test_end", DateTime(timezone=True), nullable=False),
    Column("test_points", Integer, nullable=False),
    Column("mae_model", Double, nullable=False),
    Column("mape_model", Double),
    Column("mae_official", Double, nullable=False),
    Column("mape_official", Double),
    Column("active", Boolean, nullable=False),
)
