"""Initial schema: observations hypertable, continuous aggregates, support tables.

Revision ID: 0001
Revises:
Create Date: 2026-10-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)

CAGG = """
CREATE MATERIALIZED VIEW {name}
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket(INTERVAL '{width}', ts{tz}) AS ts,
       metric, area, kind, source, unit,
       avg(value) AS value, min(value) AS value_min, max(value) AS value_max,
       count(*) AS samples
FROM observations
GROUP BY 1, metric, area, kind, source, unit
WITH NO DATA
"""


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.create_table(
        "observations",
        sa.Column("ts", TS, nullable=False),
        sa.Column("resolution", sa.Interval, nullable=False),
        sa.Column("metric", sa.Text, nullable=False),
        sa.Column("area", sa.Text, nullable=False),
        sa.Column("value", sa.Double, nullable=False),
        sa.Column("unit", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("ingested_at", TS, nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("ts", "metric", "area", "kind", "source", name="observations_pkey"),
    )
    op.execute("SELECT create_hypertable('observations', by_range('ts', INTERVAL '7 days'))")
    op.create_index("ix_observations_metric_ts", "observations", ["metric", "area", "kind", "ts"])
    op.execute(
        "ALTER TABLE observations SET (timescaledb.compress, "
        "timescaledb.compress_segmentby = 'metric, area, kind, source', "
        "timescaledb.compress_orderby = 'ts DESC')"
    )
    op.execute(CAGG.format(name="observations_1h", width="1 hour", tz=""))
    # Daily buckets follow local calendar days in Europe/Berlin (23 h / 25 h on DST days).
    op.execute(CAGG.format(name="observations_1d", width="1 day", tz=", 'Europe/Berlin'"))
    for view, start, end, every in (
        ("observations_1h", "7 days", "1 hour", "30 minutes"),
        ("observations_1d", "30 days", "1 day", "6 hours"),
    ):
        op.execute(
            f"SELECT add_continuous_aggregate_policy('{view}', start_offset => INTERVAL '{start}', "
            f"end_offset => INTERVAL '{end}', schedule_interval => INTERVAL '{every}')"
        )

    op.create_table(
        "events",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("ts", TS, nullable=False),
        sa.Column("rule_id", sa.Text, nullable=False),
        sa.Column("severity", sa.Text, nullable=False),
        sa.Column("category", sa.Text, nullable=False),
        sa.Column("metric", sa.Text, nullable=False),
        sa.Column("area", sa.Text, nullable=False),
        sa.Column("value", sa.Double),
        sa.Column("threshold", sa.Double),
        sa.Column("unit", sa.Text),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("notified_at", TS),
    )
    op.create_index("ix_events_ts", "events", ["ts"])
    op.create_index("ix_events_rule_id", "events", ["rule_id"])

    op.create_table(
        "source_status",
        sa.Column("source", sa.Text, primary_key=True),
        sa.Column("last_attempt", TS),
        sa.Column("last_success", TS),
        sa.Column("last_error", sa.Text),
        sa.Column("latency_ms", sa.Double),
        sa.Column("rows_last_run", sa.Integer, nullable=False, server_default="0"),
        sa.Column("expected_points", sa.Integer, nullable=False, server_default="0"),
        sa.Column("received_points", sa.Integer, nullable=False, server_default="0"),
        sa.Column("plausibility_violations", sa.Integer, nullable=False, server_default="0"),
        sa.Column("consecutive_failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("newest_data", TS),
    )
    op.create_table(
        "alert_channels",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text, nullable=False, unique=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("target", sa.Text, nullable=False),
        sa.Column("min_severity", sa.Text, nullable=False, server_default="warning"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "api_keys",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("revoked", sa.Boolean, nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_table("api_keys")
    op.drop_table("alert_channels")
    op.drop_table("source_status")
    op.drop_table("events")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS observations_1d CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS observations_1h CASCADE")
    op.drop_table("observations")
