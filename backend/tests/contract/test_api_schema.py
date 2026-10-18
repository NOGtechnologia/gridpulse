"""Schemathesis: property-based API tests against the generated OpenAPI (spec 7.2).

Checks: no 5xx responses, responses conform to the documented schema, documented
status codes/content types. Runs in-process against the ASGI app with demo data.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import schemathesis
from fastapi import FastAPI
from hypothesis import HealthCheck, settings

from gridpulse.api.main import create_app
from gridpulse.demo import generate
from gridpulse.settings import Settings
from gridpulse.storage.memory import MemoryRepository
from gridpulse.storage.repository import SourceStatus

NOW = datetime(2026, 10, 18, 12, 7, tzinfo=UTC)


def _app() -> FastAPI:
    repo = MemoryRepository()
    asyncio.run(repo.upsert_observations(generate(NOW, days=2)))
    asyncio.run(
        repo.save_source_status(
            SourceStatus("demo", last_success=NOW, newest_data=NOW - timedelta(minutes=5))
        )
    )
    return create_app(
        Settings(database_url="memory://", rate_limit_per_minute=1_000_000),
        repo=repo,
        clock=lambda: NOW,
    )


schema = schemathesis.openapi.from_asgi("/api/v1/openapi.json", _app())


@schema.exclude(method="POST").parametrize()
@settings(max_examples=25, deadline=None, suppress_health_check=list(HealthCheck))
def test_api_conforms_to_schema(case: schemathesis.Case) -> None:
    case.call_and_validate()
