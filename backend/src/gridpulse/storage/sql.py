"""TimescaleDB repository (SQLAlchemy 2 async + asyncpg)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sqlalchemy import Select, and_, column, func, select, table, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.sql.elements import ColumnElement

from gridpulse.domain.observations import iter_observations
from gridpulse.domain.rules.model import Event, EventCategory, Severity
from gridpulse.storage.models import alert_channels, api_keys, events, observations, source_status
from gridpulse.storage.repository import (
    OBS_RESULT_COLUMNS,
    AlertChannel,
    EventQuery,
    ObservationQuery,
    QueryResolution,
    SourceStatus,
    empty_result,
    hash_api_key,
)

BATCH = 2_000
SEVERITY_ORDER = [s.value for s in sorted(Severity, key=lambda s: s.rank)]


def _view(resolution: QueryResolution) -> str:
    return {QueryResolution.HOUR: "observations_1h", QueryResolution.DAY: "observations_1d"}.get(
        resolution, "observations"
    )


class SqlRepository:
    def __init__(self, url: str, *, engine: AsyncEngine | None = None) -> None:
        self.engine = engine or create_async_engine(
            url, pool_pre_ping=True, pool_size=5, max_overflow=5
        )

    # --- observations -------------------------------------------------------------

    async def upsert_observations(self, frame: pd.DataFrame) -> int:
        if frame.empty:
            return 0
        now = datetime.now(UTC)
        rows = [
            {
                "ts": o.ts,
                "resolution": o.resolution,
                "metric": o.metric.value,
                "area": o.area,
                "value": o.value,
                "unit": o.unit,
                "kind": o.kind.value,
                "source": o.source,
                "ingested_at": now,
            }
            for o in iter_observations(frame)
        ]
        stmt = insert(observations)
        stmt = stmt.on_conflict_do_update(
            constraint="observations_pkey",
            set_={
                "value": stmt.excluded.value,
                "unit": stmt.excluded.unit,
                "resolution": stmt.excluded.resolution,
                "ingested_at": stmt.excluded.ingested_at,
            },
        )
        async with self.engine.begin() as conn:
            for i in range(0, len(rows), BATCH):
                await conn.execute(stmt, rows[i : i + BATCH])
        return len(rows)

    def _select(self, query: ObservationQuery) -> Select[Any]:
        source = table(_view(query.resolution), *(column(name) for name in OBS_RESULT_COLUMNS))
        cols = {name: source.c[name] for name in OBS_RESULT_COLUMNS}
        if query.resolution is QueryResolution.QUARTER_HOUR:
            ts_expr: ColumnElement[Any] = func.time_bucket(
                text("INTERVAL '15 minutes'"), cols["ts"]
            )
            value_expr: ColumnElement[Any] = func.avg(cols["value"])
        else:
            ts_expr, value_expr = cols["ts"], cols["value"]
        conditions = [
            cols["metric"].in_(list(query.metrics)),
            cols["ts"] >= query.start,
            cols["ts"] < query.end,
        ]
        if query.areas:
            conditions.append(cols["area"].in_(list(query.areas)))
        if query.kind:
            conditions.append(cols["kind"] == query.kind)
        if query.sources:
            conditions.append(cols["source"].in_(list(query.sources)))
        keys = [cols[k] for k in ("metric", "area", "kind", "source", "unit")]
        stmt = select(ts_expr.label("ts"), *keys, value_expr.label("value")).where(
            and_(*conditions)
        )
        if query.resolution is QueryResolution.QUARTER_HOUR:
            stmt = stmt.group_by(text("1"), *keys)
        return stmt

    async def query_observations(self, query: ObservationQuery) -> pd.DataFrame:
        stmt = self._select(query).order_by(text("ts, metric, area, kind, source"))
        stmt = stmt.limit(query.limit).offset(query.offset)
        async with self.engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        if not rows:
            return empty_result()
        frame = pd.DataFrame([dict(r) for r in rows], columns=OBS_RESULT_COLUMNS)
        frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
        frame["value"] = frame["value"].astype("float64")
        return frame

    async def count_observations(self, query: ObservationQuery) -> int:
        sub = self._select(query).subquery()
        async with self.engine.connect() as conn:
            return int((await conn.execute(select(func.count()).select_from(sub))).scalar_one())

    async def latest_timestamp(
        self, metric: str, area: str, kind: str, source: str
    ) -> datetime | None:
        stmt = select(func.max(observations.c.ts)).where(
            observations.c.metric == metric,
            observations.c.area == area,
            observations.c.kind == kind,
            observations.c.source == source,
        )
        async with self.engine.connect() as conn:
            value = (await conn.execute(stmt)).scalar_one_or_none()
        return value if isinstance(value, datetime) else None

    async def apply_retention(
        self, raw_days: int, frequency_days: int, compress_after_days: int
    ) -> None:
        """Configure TimescaleDB policies from settings (idempotent)."""
        async with self.engine.begin() as conn:
            await conn.execute(
                text("SELECT remove_retention_policy('observations', if_exists => true)")
            )
            await conn.execute(
                text("SELECT add_retention_policy('observations', make_interval(days => :d))"),
                {"d": raw_days},
            )
            await conn.execute(
                text("SELECT remove_compression_policy('observations', if_exists => true)")
            )
            await conn.execute(
                text("SELECT add_compression_policy('observations', make_interval(days => :d))"),
                {"d": compress_after_days},
            )
            # High-resolution frequency data is kept for a shorter time than other raw data.
            await conn.execute(
                text(
                    "DELETE FROM observations WHERE metric = 'grid.frequency' "
                    "AND ts < now() - make_interval(days => :d)"
                ),
                {"d": frequency_days},
            )

    # --- events -----------------------------------------------------------------

    async def upsert_events(self, items: Sequence[Event]) -> list[Event]:
        if not items:
            return []
        by_id = {e.id: e for e in items}
        rows = [
            {
                "id": e.id,
                "ts": e.ts,
                "rule_id": e.rule_id,
                "severity": e.severity.value,
                "category": e.category.value,
                "metric": e.metric,
                "area": e.area,
                "value": e.value,
                "threshold": e.threshold,
                "unit": e.unit,
                "source": e.source,
                "message": e.message,
            }
            for e in by_id.values()
        ]
        stmt = insert(events).values(rows).on_conflict_do_nothing(index_elements=["id"])
        async with self.engine.begin() as conn:
            inserted = (await conn.execute(stmt.returning(events.c.id))).scalars().all()
        return [by_id[i] for i in inserted]

    async def list_events(self, query: EventQuery) -> list[Event]:
        stmt = select(events).order_by(events.c.ts.desc(), events.c.id.desc())
        if query.start:
            stmt = stmt.where(events.c.ts >= query.start)
        if query.end:
            stmt = stmt.where(events.c.ts < query.end)
        if query.min_severity:
            allowed = SEVERITY_ORDER[SEVERITY_ORDER.index(query.min_severity.value) :]
            stmt = stmt.where(events.c.severity.in_(allowed))
        if query.rule_ids:
            stmt = stmt.where(events.c.rule_id.in_(list(query.rule_ids)))
        if query.categories:
            stmt = stmt.where(events.c.category.in_(list(query.categories)))
        stmt = stmt.limit(query.limit).offset(query.offset)
        async with self.engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [
            Event(
                ts=r["ts"],
                rule_id=r["rule_id"],
                severity=Severity(r["severity"]),
                category=EventCategory(r["category"]),
                metric=r["metric"],
                area=r["area"],
                value=r["value"],
                threshold=r["threshold"],
                source=r["source"],
                message=r["message"],
                unit=r["unit"],
                id=r["id"],
            )
            for r in rows
        ]

    async def mark_notified(self, event_ids: Sequence[str], at: datetime) -> None:
        if not event_ids:
            return
        async with self.engine.begin() as conn:
            await conn.execute(
                update(events).where(events.c.id.in_(list(event_ids))).values(notified_at=at)
            )

    async def last_notified(self, rule_id: str, area: str, metric: str) -> datetime | None:
        stmt = select(func.max(events.c.notified_at)).where(
            events.c.rule_id == rule_id, events.c.area == area, events.c.metric == metric
        )
        async with self.engine.connect() as conn:
            value = (await conn.execute(stmt)).scalar_one_or_none()
        return value if isinstance(value, datetime) else None

    # --- source status -------------------------------------------------------------

    async def save_source_status(self, status: SourceStatus) -> None:
        values = {
            "source": status.source,
            "last_attempt": status.last_attempt,
            "last_success": status.last_success,
            "last_error": status.last_error,
            "latency_ms": status.latency_ms,
            "rows_last_run": status.rows_last_run,
            "expected_points": status.expected_points,
            "received_points": status.received_points,
            "plausibility_violations": status.plausibility_violations,
            "consecutive_failures": status.consecutive_failures,
            "newest_data": status.newest_data,
        }
        stmt = insert(source_status).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["source"], set_={k: v for k, v in values.items() if k != "source"}
        )
        async with self.engine.begin() as conn:
            await conn.execute(stmt)

    async def list_source_status(self) -> list[SourceStatus]:
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(select(source_status).order_by(source_status.c.source))
            ).mappings()
            return [SourceStatus(**dict(r)) for r in rows.all()]

    # --- alert channels & API keys ---------------------------------------------------

    async def list_alert_channels(self) -> list[AlertChannel]:
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(select(alert_channels).order_by(alert_channels.c.id))
            ).mappings()
            return [
                AlertChannel(
                    name=r["name"],
                    kind=r["kind"],
                    target=r["target"],
                    min_severity=Severity(r["min_severity"]),
                    enabled=r["enabled"],
                    id=r["id"],
                )
                for r in rows.all()
            ]

    async def add_alert_channel(self, channel: AlertChannel) -> AlertChannel:
        stmt = (
            insert(alert_channels)
            .values(
                name=channel.name,
                kind=channel.kind,
                target=channel.target,
                min_severity=channel.min_severity.value,
                enabled=channel.enabled,
            )
            .on_conflict_do_nothing(index_elements=["name"])
            .returning(alert_channels.c.id)
        )
        async with self.engine.begin() as conn:
            new_id = (await conn.execute(stmt)).scalar_one_or_none()
        if new_id is None:
            raise ValueError(f"channel {channel.name!r} exists")
        return AlertChannel(
            channel.name,
            channel.kind,
            channel.target,
            channel.min_severity,
            channel.enabled,
            id=int(new_id),
        )

    async def add_api_key(self, name: str, key: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(insert(api_keys).values(name=name, key_hash=hash_api_key(key)))

    async def is_valid_api_key(self, key: str) -> bool:
        stmt = select(api_keys.c.id).where(
            api_keys.c.key_hash == hash_api_key(key), api_keys.c.revoked.is_(False)
        )
        async with self.engine.connect() as conn:
            return (await conn.execute(stmt)).first() is not None

    async def ping(self) -> bool:
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            return False
        return True

    async def close(self) -> None:
        await self.engine.dispose()
