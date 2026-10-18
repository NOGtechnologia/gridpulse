"""Integration tests against a real TimescaleDB (spec 7.2): migrations, upsert, aggregates."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from gridpulse.domain.metrics import Kind, MetricId
from gridpulse.domain.observations import concat_frames, make_frame
from gridpulse.domain.rules import Event, EventCategory, Severity
from gridpulse.domain.timeutils import local_day_bounds
from gridpulse.storage import migrate
from gridpulse.storage.repository import (
    AlertChannel,
    EventQuery,
    ObservationQuery,
    QueryResolution,
    SourceStatus,
)
from gridpulse.storage.sql import SqlRepository

pytestmark = pytest.mark.integration
Q = timedelta(minutes=15)
T0 = datetime(2026, 10, 24, 22, tzinfo=UTC)  # local midnight before the 25 h day


def _frame(
    values: list[float],
    metric: MetricId = MetricId.LOAD_ACTUAL,
    start: datetime = T0,
    source: str = "smard",
    step: timedelta = Q,
):
    return make_frame(
        timestamps=[start + i * step for i in range(len(values))],
        values=values,
        metric=metric,
        area="DE",
        kind=Kind.ACTUAL,
        source=source,
        resolution=step,
    )


async def _tables(url: str) -> set[str]:
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))
        names = {r[0] for r in rows}
    await engine.dispose()
    return names


def test_migration_up_down_up(migrated_url: str) -> None:
    assert {"observations", "events", "source_status", "api_keys"} <= asyncio.run(
        _tables(migrated_url)
    )
    migrate.downgrade(migrated_url, "base")
    assert "observations" not in asyncio.run(_tables(migrated_url))
    migrate.upgrade(migrated_url)
    assert "observations" in asyncio.run(_tables(migrated_url))


async def test_observations_is_hypertable(repo: SqlRepository) -> None:
    async with repo.engine.connect() as conn:
        names = (
            (
                await conn.execute(
                    text("SELECT hypertable_name FROM timescaledb_information.hypertables")
                )
            )
            .scalars()
            .all()
        )
        caggs = (
            (
                await conn.execute(
                    text("SELECT view_name FROM timescaledb_information.continuous_aggregates")
                )
            )
            .scalars()
            .all()
        )
    assert "observations" in names
    assert {"observations_1h", "observations_1d"} <= set(caggs)


async def test_upsert_is_idempotent(repo: SqlRepository) -> None:
    frame = _frame([1.0, 2.0, 3.0])
    assert await repo.upsert_observations(frame) == 3
    assert await repo.upsert_observations(frame) == 3
    corrected = _frame([1.0, 20.0, 3.0])
    await repo.upsert_observations(corrected)
    query = ObservationQuery(metrics=["load.actual"], start=T0, end=T0 + timedelta(hours=1))
    result = await repo.query_observations(query)
    assert result["value"].tolist() == [1.0, 20.0, 3.0]
    assert await repo.count_observations(query) == 3
    assert await repo.upsert_observations(_frame([])) == 0


async def test_query_filters_paging_and_buckets(repo: SqlRepository) -> None:
    await repo.upsert_observations(
        concat_frames(
            [
                _frame([float(i) for i in range(8)]),
                _frame([100.0] * 8, source="energy_charts"),
                _frame([49.9, 50.1], metric=MetricId.GRID_FREQUENCY, step=timedelta(seconds=10)),
            ]
        )
    )
    base = ObservationQuery(
        metrics=["load.actual"],
        start=T0,
        end=T0 + timedelta(hours=2),
        sources=["smard"],
        areas=["DE"],
        kind="actual",
    )
    page = await repo.query_observations(replace(base, limit=3, offset=2))
    assert page["value"].tolist() == [2.0, 3.0, 4.0]
    freq = await repo.query_observations(
        ObservationQuery(
            metrics=["grid.frequency"],
            start=T0,
            end=T0 + Q,
            resolution=QueryResolution.QUARTER_HOUR,
        )
    )
    assert freq["value"].tolist() == pytest.approx([50.0])
    raw = await repo.query_observations(
        ObservationQuery(
            metrics=["grid.frequency"], start=T0, end=T0 + Q, resolution=QueryResolution.RAW
        )
    )
    assert len(raw) == 2
    hourly = await repo.query_observations(replace(base, resolution=QueryResolution.HOUR))
    assert hourly["value"].tolist() == [1.5, 5.5]  # real-time aggregation, not yet materialised


async def test_daily_aggregate_on_25h_day(repo: SqlRepository) -> None:
    start, end = local_day_bounds(date(2026, 10, 25))
    n = int((end - start) / timedelta(hours=1))
    assert n == 25
    await repo.upsert_observations(_frame([2.0] * n, start=start, step=timedelta(hours=1)))
    daily = await repo.query_observations(
        ObservationQuery(
            metrics=["load.actual"], start=start, end=end, resolution=QueryResolution.DAY
        )
    )
    assert len(daily) == 1
    assert daily["ts"].iloc[0].to_pydatetime() == start
    assert daily["value"].iloc[0] == 2.0


async def test_latest_timestamp(repo: SqlRepository) -> None:
    await repo.upsert_observations(_frame([1.0, 2.0]))
    assert await repo.latest_timestamp("load.actual", "DE", "actual", "smard") == T0 + Q
    assert await repo.latest_timestamp("load.actual", "DE", "actual", "nope") is None


async def test_events_roundtrip(repo: SqlRepository) -> None:
    def event(rule: str, sev: Severity, minutes: int) -> Event:
        return Event(
            ts=T0 + timedelta(minutes=minutes),
            rule_id=rule,
            severity=sev,
            category=EventCategory.GRID,
            metric="grid.frequency",
            area="DE",
            value=1.0,
            threshold=2.0,
            source="ec",
            message="m",
            unit="Hz",
        )

    items = [
        event("FREQ-001", Severity.WARNING, 0),
        event("FREQ-001", Severity.CRITICAL, 1),
        event("PRICE-001", Severity.INFO, 2),
    ]
    assert len(await repo.upsert_events(items)) == 3
    assert await repo.upsert_events(items) == []
    assert await repo.upsert_events([]) == []
    listed = await repo.list_events(EventQuery(min_severity=Severity.WARNING))
    assert [e.severity for e in listed] == [Severity.CRITICAL, Severity.WARNING]
    filtered = await repo.list_events(
        EventQuery(
            rule_ids=["PRICE-001"], categories=["grid"], start=T0, end=T0 + timedelta(hours=1)
        )
    )
    assert [e.id for e in filtered] == [items[2].id]
    assert filtered[0] == items[2]
    await repo.mark_notified([items[0].id], T0)
    await repo.mark_notified([], T0)
    assert await repo.last_notified("FREQ-001", "DE", "grid.frequency") == T0
    assert await repo.last_notified("PRICE-001", "DE", "grid.frequency") is None


async def test_source_status_channels_and_keys(repo: SqlRepository) -> None:
    status = SourceStatus(
        source="smard",
        last_attempt=T0,
        last_success=T0,
        latency_ms=12.5,
        rows_last_run=10,
        expected_points=10,
        received_points=9,
    )
    await repo.save_source_status(status)
    status.consecutive_failures = 2
    await repo.save_source_status(status)
    stored = await repo.list_source_status()
    assert stored[0].consecutive_failures == 2
    assert stored[0].gap_ratio == pytest.approx(0.1)

    channel = await repo.add_alert_channel(AlertChannel("ops", "webhook", "https://hooks.test/x"))
    assert channel.id == 1
    with pytest.raises(ValueError, match="exists"):
        await repo.add_alert_channel(AlertChannel("ops", "webhook", "https://hooks.test/y"))
    assert [c.name for c in await repo.list_alert_channels()] == ["ops"]

    await repo.add_api_key("ci", "s3cret-key")
    assert await repo.is_valid_api_key("s3cret-key")
    assert not await repo.is_valid_api_key("wrong")
    async with repo.engine.connect() as conn:
        stored_hash = (await conn.execute(text("SELECT key_hash FROM api_keys"))).scalar_one()
    assert stored_hash != "s3cret-key" and len(stored_hash) == 64
    assert await repo.ping()


async def test_retention_policies(repo: SqlRepository) -> None:
    await repo.upsert_observations(
        _frame(
            [50.0],
            metric=MetricId.GRID_FREQUENCY,
            start=datetime.now(UTC) - timedelta(days=60),
            step=timedelta(seconds=10),
        )
    )
    await repo.apply_retention(raw_days=730, frequency_days=30, compress_after_days=7)
    await repo.apply_retention(raw_days=730, frequency_days=30, compress_after_days=7)
    async with repo.engine.connect() as conn:
        jobs = (
            (
                await conn.execute(
                    text(
                        "SELECT proc_name FROM timescaledb_information.jobs "
                        "WHERE hypertable_name='observations'"
                    )
                )
            )
            .scalars()
            .all()
        )
        left = (await conn.execute(text("SELECT count(*) FROM observations"))).scalar_one()
    assert {"policy_retention", "policy_compression"} <= set(jobs)
    assert left == 0


async def test_ping_failure() -> None:
    bad = SqlRepository("postgresql+asyncpg://nobody:x@127.0.0.1:1/none")
    assert not await bad.ping()
    await bad.close()
