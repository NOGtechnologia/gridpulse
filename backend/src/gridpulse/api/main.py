"""FastAPI application factory, health endpoints and Prometheus metrics."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.routing import Match

from gridpulse import __version__
from gridpulse.api.deps import AppState, RateLimiter
from gridpulse.api.v1 import router as v1_router
from gridpulse.observability import API_LATENCY, configure_logging
from gridpulse.schemas import Health
from gridpulse.settings import Settings, get_settings
from gridpulse.storage import create_repository
from gridpulse.storage.repository import Repository

DESCRIPTION = """
Read-only API of **GridPulse**, an open-source situational picture of the German and
European power system built exclusively from public, official data sources
(SMARD/Bundesnetzagentur, Energy-Charts/Fraunhofer ISE, Open-Meteo, optional ENTSO-E).

* All timestamps are **UTC** and denote the **start** of the interval.
* Every response carries `meta.source`, `meta.license` and `meta.attribution`.
* Rate limited per client; send `X-API-Key` for a higher limit (if keys are configured).

**Disclaimer:** GridPulse is advisory only. It sends no control commands, is not
connected to SCADA systems and is no substitute for certified control systems.
"""


def _route_template(request: Request) -> str:
    for route in request.app.router.routes:
        match, _ = route.matches(request.scope)
        if match is Match.FULL:
            return str(getattr(route, "path", "unknown"))
    return "unmatched"


def create_app(
    settings: Settings | None = None,
    repo: Repository | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    repository = repo or create_repository(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await repository.close()

    app = FastAPI(
        title="GridPulse API",
        version=__version__,
        description=DESCRIPTION,
        license_info={"name": "Apache-2.0", "identifier": "Apache-2.0"},
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.gridpulse = AppState(
        settings=settings,
        repo=repository,
        clock=clock or (lambda: datetime.now(UTC)),
        limiter=RateLimiter(settings.rate_limit_per_minute),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["X-API-Key", "Content-Type"],
        max_age=600,
    )

    @app.middleware("http")
    async def metrics_and_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        API_LATENCY.labels(
            request.method, _route_template(request), str(response.status_code)
        ).observe(time.perf_counter() - started)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path.startswith("/api/v1"):
            response.headers.setdefault("Cache-Control", "public, max-age=30")
        return response

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            {"detail": "internal error", "type": type(exc).__name__}, status_code=500
        )

    app.include_router(v1_router)

    @app.get("/healthz", response_model=Health, tags=["health"], summary="Liveness")
    async def healthz() -> Health:
        return Health(status="ok")

    @app.get(
        "/readyz",
        response_model=Health,
        tags=["health"],
        summary="Readiness (DB + last ingest)",
        responses={503: {"model": Health}},
    )
    async def readyz(response: Response) -> Health:
        state: AppState = app.state.gridpulse
        checks: dict[str, str] = {}
        db_ok = await state.repo.ping()
        checks["database"] = "ok" if db_ok else "unreachable"
        ingest_ok = False
        if db_ok:
            limit = timedelta(hours=settings.stale_after_hours) * 2
            now = state.clock()
            statuses = await state.repo.list_source_status()
            ingest_ok = any(st.last_success and now - st.last_success <= limit for st in statuses)
            checks["ingest"] = "ok" if ingest_ok else "no successful ingest recently"
        if db_ok and ingest_ok:
            return Health(status="ok", checks=checks)
        response.status_code = 503
        return Health(status="fail" if not db_ok else "degraded", checks=checks)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


def run() -> None:
    import uvicorn  # noqa: PLC0415 - server dependency only needed for the entry point

    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    uvicorn.run(
        create_app(settings),
        host=settings.api_host,
        port=settings.api_port,
        proxy_headers=settings.trust_proxy_headers,
        access_log=False,
    )
