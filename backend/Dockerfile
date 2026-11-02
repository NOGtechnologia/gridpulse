# syntax=docker/dockerfile:1.7
# GridPulse backend image (api + worker). Hardened: non-root, read-only root FS
# compatible, no build tools in the runtime stage.

FROM ghcr.io/astral-sh/uv:0.13.6 AS uv

FROM python:3.12.15-slim-trixie AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

FROM python:3.12.15-slim-trixie AS runtime
LABEL org.opencontainers.image.title="gridpulse-backend" \
      org.opencontainers.image.description="GridPulse API and worker" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://github.com/NOGtechnologia/gridpulse"
RUN groupadd --system --gid 10001 gridpulse \
    && useradd --system --uid 10001 --gid gridpulse --no-create-home --shell /usr/sbin/nologin gridpulse
WORKDIR /app
COPY --from=build --chown=root:root /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
USER 10001:10001
EXPOSE 8000 9101
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"]
CMD ["gridpulse-api"]
