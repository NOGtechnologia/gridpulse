"""Training/backtest runs of the own forecasting model (phase 7, ADR 0010).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "model_runs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("trained_at", TS, nullable=False),
        sa.Column("algorithm", sa.Text, nullable=False),
        sa.Column("seed", sa.Integer, nullable=False),
        sa.Column("target", sa.Text, nullable=False),
        sa.Column("features", sa.Text, nullable=False),
        sa.Column("train_start", TS, nullable=False),
        sa.Column("train_end", TS, nullable=False),
        sa.Column("test_start", TS, nullable=False),
        sa.Column("test_end", TS, nullable=False),
        sa.Column("test_points", sa.Integer, nullable=False),
        sa.Column("mae_model", sa.Double, nullable=False),
        sa.Column("mape_model", sa.Double),
        sa.Column("mae_official", sa.Double, nullable=False),
        sa.Column("mape_official", sa.Double),
        sa.Column("active", sa.Boolean, nullable=False),
    )
    op.create_index("ix_model_runs_trained_at", "model_runs", ["trained_at"])


def downgrade() -> None:
    op.drop_table("model_runs")
