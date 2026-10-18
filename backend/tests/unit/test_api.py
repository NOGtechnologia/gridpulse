"""API tests with the in-memory repository and demo data."""

from __future__ import annotations

import io
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pyarrow.parquet as pq
import pytest
import respx

from gridpulse.api.deps import RateLimiter, client_ip
from gridpulse.api.main import create_app
from gridpulse.demo import generate
from gridpulse.domain.rules import Event, EventCategory, Severity
from gridpulse.settings import Settings
from gridpulse.storage.memory import MemoryRepository
from gridpulse.storage.repository import SourceStatus

NOW = datetime(2026, 10, 18, 12, 7, tzinfo=UTC)


async def _client(
    settings: Settings | None = None, repo: MemoryRepository | None = None, seed: bool = True
) -> tuple[httpx.AsyncClient, MemoryRepository]:
    repo = repo or MemoryRepository()
    if seed:
        await repo.upsert_observations(generate(NOW, days=3))
        await repo.save_source_status(
            SourceStatus("demo", last_success=NOW, newest_data=NOW - timedelta(minutes=5))
        )
        await repo.upsert_events(
            [
                Event(
                    ts=NOW,
                    rule_id="FREQ-001",
                    severity=Severity.WARNING,
                    category=EventCategory.GRID,
                    metric="grid.frequency",
                    area="DE",
                    value=49.85,
                    threshold=100.0,
                    source="demo",
                    message="m",
                    unit="Hz",
                )
            ]
        )
    app = create_app(settings or Settings(database_url="memory://"), repo=repo, clock=lambda: NOW)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test"), repo


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    c, _ = await _client()
    async with c:
        yield c


async def test_health_and_ready(client: httpx.AsyncClient) -> None:
    assert (await client.get("/healthz")).json() == {"status": "ok", "checks": {}}
    ready = await client.get("/readyz")
    assert ready.status_code == 200 and ready.json()["checks"]["ingest"] == "ok"
    metrics = await client.get("/metrics")
    assert "gridpulse_api_request_duration_seconds" in metrics.text


async def test_ready_degraded_without_ingest() -> None:
    c, _ = await _client(seed=False)
    async with c:
        ready = await c.get("/readyz")
    assert ready.status_code == 503 and ready.json()["status"] == "degraded"


async def test_observations_paging_and_meta(client: httpx.AsyncClient) -> None:
    params = {
        "metric": "load.actual",
        "start": "2026-10-18T00:00:00Z",
        "end": "2026-10-18T06:00:00Z",
        "kind": "actual",
        "limit": 10,
    }
    first = (await client.get("/api/v1/observations", params=params)).json()
    assert first["meta"]["total"] == 24
    assert first["meta"]["next_offset"] == 10
    assert first["meta"]["license"] == "CC0 1.0"
    assert first["data"][0]["unit"] == "MW"
    assert first["data"][0]["ts"] == "2026-10-18T00:00:00Z"
    last = (await client.get("/api/v1/observations", params={**params, "offset": 20})).json()
    assert len(last["data"]) == 4 and last["meta"]["next_offset"] is None
    hourly = (
        await client.get("/api/v1/observations", params={**params, "resolution": "1h"})
    ).json()
    assert hourly["meta"]["total"] == 6


async def test_observations_validation(client: httpx.AsyncClient) -> None:
    assert (
        await client.get("/api/v1/observations", params={"metric": "nonsense"})
    ).status_code == 422
    naive = {"metric": "load.actual", "start": "2026-10-18T00:00:00"}
    assert (await client.get("/api/v1/observations", params=naive)).status_code == 422
    reversed_ = {
        "metric": "load.actual",
        "start": "2026-10-18T06:00:00Z",
        "end": "2026-10-18T00:00:00Z",
    }
    empty = await client.get("/api/v1/observations", params=reversed_)
    assert empty.status_code == 200 and empty.json()["data"] == []
    numeric = {"metric": "load.actual", "start": "0.5"}
    assert (await client.get("/api/v1/observations", params=numeric)).status_code == 422
    ancient = {
        "metric": "load.actual",
        "start": "0074-01-01T00:00:00Z",
        "end": "0075-01-01T00:00:00Z",
    }
    assert (await client.get("/api/v1/observations", params=ancient)).json()["data"] == []


async def test_summary_forecast_events_sources_catalog(client: httpx.AsyncClient) -> None:
    summary = (await client.get("/api/v1/summary/now")).json()
    assert summary["load"]["unit"] == "MW" and summary["load"]["source"] == "demo"
    assert "disclaimer" in summary["meta"]
    forecast = (await client.get("/api/v1/forecast/residual-load", params={"hours": 24})).json()
    assert forecast["unit"] == "MW" and len(forecast["points"]) > 50
    events = (await client.get("/api/v1/events", params={"min_severity": "warning"})).json()
    assert events["data"][0]["rule_id"] == "FREQ-001"
    sources = (await client.get("/api/v1/sources/status")).json()
    assert sources["data"][0]["healthy"] is True
    catalog = (await client.get("/api/v1/metrics")).json()
    wind = next(m for m in catalog["data"] if m["id"] == "generation.wind_onshore")
    assert wind["color"] == "#0072B2" and wind["renewable"] is True


async def test_export_csv_and_parquet(client: httpx.AsyncClient) -> None:
    params = {
        "metric": "generation.solar",
        "start": "2026-10-17T00:00:00Z",
        "end": "2026-10-18T00:00:00Z",
        "kind": "actual",
    }
    csv = await client.get("/api/v1/export", params=params)
    assert csv.headers["content-type"].startswith("text/csv")
    lines = csv.text.splitlines()
    assert lines[0] == "# source: demo"
    assert lines[1] == "# license: CC0 1.0"
    header = next(line for line in lines if not line.startswith("#"))
    assert header == "ts,metric,area,kind,source,unit,value"
    parquet = await client.get("/api/v1/export", params={**params, "format": "parquet"})
    table = pq.read_table(io.BytesIO(parquet.content))
    assert table.schema.metadata[b"gridpulse.license"] == b"CC0 1.0"
    assert table.num_rows == 24


async def test_export_too_large() -> None:
    c, _ = await _client(Settings(database_url="memory://", max_export_rows=5))
    async with c:
        r = await c.get(
            "/api/v1/export",
            params={
                "metric": "load.actual",
                "start": "2026-10-17T00:00:00Z",
                "end": "2026-10-18T00:00:00Z",
                "resolution": "15min",
            },
        )
    assert r.status_code == 413


async def test_api_keys_and_rate_limit() -> None:
    settings = Settings(database_url="memory://", require_api_key=True, rate_limit_per_minute=2)
    c, repo = await _client(settings)
    await repo.add_api_key("ci", "good-key")
    async with c:
        assert (await c.get("/api/v1/metrics")).status_code == 401
        assert (await c.get("/api/v1/metrics", headers={"X-API-Key": "bad"})).status_code == 401
        for _ in range(20):
            assert (
                await c.get("/api/v1/metrics", headers={"X-API-Key": "good-key"})
            ).status_code == 200
        limited = await c.get("/api/v1/metrics", headers={"X-API-Key": "good-key"})
        assert limited.status_code == 429 and int(limited.headers["Retry-After"]) >= 1


async def test_anonymous_rate_limit() -> None:
    c, _ = await _client(Settings(database_url="memory://", rate_limit_per_minute=1))
    async with c:
        assert (await c.get("/api/v1/metrics")).status_code == 200
        assert (await c.get("/api/v1/metrics")).status_code == 429


def test_rate_limiter_window_and_cleanup() -> None:
    t = [0.0]
    limiter = RateLimiter(per_minute=1, clock=lambda: t[0])
    assert limiter.hit("a") == (True, 0)
    assert limiter.hit("a") == (False, 60)
    t[0] = 61.0
    assert limiter.hit("a")[0]
    limiter._hits = {f"k{i}": (0.0, 1) for i in range(50_001)}
    t[0] = 200.0
    limiter.hit("fresh")
    assert set(limiter._hits) == {"fresh"}


def test_client_ip_proxy_header() -> None:
    from starlette.requests import Request  # noqa: PLC0415

    scope = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"1.2.3.4, 10.0.0.1")],
        "client": ("9.9.9.9", 1),
    }
    request = Request(scope)
    assert client_ip(request, trust_proxy=True) == "1.2.3.4"
    assert client_ip(request, trust_proxy=False) == "9.9.9.9"
    assert (
        client_ip(Request({"type": "http", "headers": [], "client": None}), trust_proxy=True)
        == "unknown"
    )


@respx.mock
async def test_alert_test_endpoint() -> None:
    hook = respx.post("https://hooks.test/x").mock(return_value=httpx.Response(200))
    disabled, _ = await _client(Settings(database_url="memory://"), seed=False)
    async with disabled:
        assert (await disabled.post("/api/v1/alerts/test")).status_code == 403
    settings = Settings(
        database_url="memory://", admin_token="t0ken", alert_webhook_urls=["https://hooks.test/x"]
    )
    c, _ = await _client(settings, seed=False)
    async with c:
        assert (
            await c.post("/api/v1/alerts/test", headers={"X-Admin-Token": "wrong"})
        ).status_code == 401
        ok = await c.post("/api/v1/alerts/test", headers={"X-Admin-Token": "t0ken"})
    assert ok.json() == {"results": {"env-webhook-0": "ok"}}
    assert hook.call_count == 1


async def test_unhandled_errors_are_json() -> None:
    class Broken(MemoryRepository):
        async def list_source_status(self) -> list[SourceStatus]:
            raise RuntimeError("db exploded with secret details")

    repo = Broken()
    app = create_app(Settings(database_url="memory://"), repo=repo, clock=lambda: NOW)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/v1/sources/status")
    assert r.status_code == 500
    assert r.json() == {"detail": "internal error", "type": "RuntimeError"}


async def test_openapi_is_31_and_documents_examples(client: httpx.AsyncClient) -> None:
    spec = (await client.get("/api/v1/openapi.json")).json()
    assert spec["openapi"].startswith("3.1")
    assert spec["info"]["license"]["identifier"] == "Apache-2.0"
    params = {p["name"]: p for p in spec["paths"]["/api/v1/observations"]["get"]["parameters"]}
    assert params["start"]["schema"]["examples"] == ["2026-10-17T00:00:00Z"]
