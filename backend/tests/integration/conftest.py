"""Integration fixtures: a real TimescaleDB.

Order of preference:
1. ``GRIDPULSE_TEST_DATABASE_URL`` (an existing, disposable TimescaleDB database),
2. Testcontainers with ``timescale/timescaledb:latest-pg16`` when Docker is available.
Without either, integration tests are skipped with an explicit reason; CI always
provides Docker, so they always run there.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from gridpulse.storage import migrate
from gridpulse.storage.sql import SqlRepository

TIMESCALE_IMAGE = "timescale/timescaledb:latest-pg16"


def _docker_available() -> bool:
    return shutil.which("docker") is not None


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    url = os.environ.get("GRIDPULSE_TEST_DATABASE_URL")
    if url:
        yield url
        return
    if not _docker_available():
        pytest.skip("no GRIDPULSE_TEST_DATABASE_URL and no Docker for Testcontainers")
    from testcontainers.postgres import PostgresContainer  # noqa: PLC0415 - optional dependency

    with PostgresContainer(TIMESCALE_IMAGE, driver="asyncpg") as pg:
        yield pg.get_connection_url()


async def _reset(url: str) -> None:
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        for view in ("observations_1d", "observations_1h"):
            await conn.execute(text(f"DROP MATERIALIZED VIEW IF EXISTS {view} CASCADE"))
        for table in (
            "observations",
            "events",
            "source_status",
            "alert_channels",
            "api_keys",
            "model_runs",
            "alembic_version",
        ):
            await conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
    await engine.dispose()


@pytest.fixture(scope="session")
def migrated_url(database_url: str) -> str:
    asyncio.run(_reset(database_url))
    migrate.upgrade(database_url)
    return database_url


@pytest.fixture
async def repo(migrated_url: str) -> AsyncIterator[SqlRepository]:
    repository = SqlRepository(migrated_url)
    async with repository.engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE observations, events, source_status, alert_channels, api_keys, "
                "model_runs RESTART IDENTITY"
            )
        )
    yield repository
    await repository.close()
