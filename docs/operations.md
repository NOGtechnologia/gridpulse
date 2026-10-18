# Operations

## Start

```bash
cp .env.example .env            # adjust passwords/tokens
docker compose -f deploy/docker-compose.yml up -d
# offline demo with synthetic data:
GRIDPULSE_DEMO=1 docker compose -f deploy/docker-compose.yml up -d
```

The worker runs Alembic migrations on start, applies retention/compression
policies and (demo mode) seeds data. Dashboard: `http://localhost:3000`,
API: `http://localhost:8000/api/docs`.

## Health and monitoring

| Endpoint | Meaning |
|---|---|
| `GET /healthz` (api) | process alive |
| `GET /readyz` (api) | database reachable **and** a source ingested successfully within 2 × `STALE_AFTER_HOURS`; else 503 |
| `GET /metrics` (api :8000, worker :9101) | Prometheus |

Key metrics: `gridpulse_ingest_duration_seconds{source}`,
`gridpulse_ingest_errors_total{source}`, `gridpulse_data_age_seconds{source}`,
`gridpulse_plausibility_violations_total{source,rule_id}`,
`gridpulse_events_total{rule_id,severity}`, `gridpulse_alerts_sent_total{channel,outcome}`,
`gridpulse_api_request_duration_seconds{method,route,status}`.

Suggested alerts: data age > 3 h, ingest errors increasing for 30 min, `/readyz` 503.

Logs are structured JSON on stdout (`GRIDPULSE_LOG_JSON=0` for console format).
Secrets (tokens, webhook URLs, SMTP passwords) are never logged.

## Retention

Configured via ENV and applied by the worker on every start (idempotent):

| Setting | Default | Effect |
|---|---|---|
| `GRIDPULSE_RETENTION_RAW_DAYS` | 730 | TimescaleDB retention policy on `observations` |
| `GRIDPULSE_RETENTION_FREQUENCY_DAYS` | 30 | 10-second frequency data deleted earlier |
| `GRIDPULSE_COMPRESS_AFTER_DAYS` | 7 | compression policy |

Continuous aggregates (`observations_1h`, `observations_1d`) have no retention
policy and are kept indefinitely – they are refreshed by their own policies before
raw data expires.

## Backups

```bash
# logical backup (TimescaleDB-aware restore needs timescaledb_pre_restore / post_restore)
docker compose -f deploy/docker-compose.yml exec -T db \
  pg_dump -U gridpulse -Fc gridpulse > gridpulse_$(date +%F).dump

# restore into an empty database
docker compose -f deploy/docker-compose.yml exec -T db psql -U gridpulse -d gridpulse -c "SELECT timescaledb_pre_restore();"
docker compose -f deploy/docker-compose.yml exec -T db pg_restore -U gridpulse -d gridpulse < gridpulse_2026-10-18.dump
docker compose -f deploy/docker-compose.yml exec -T db psql -U gridpulse -d gridpulse -c "SELECT timescaledb_post_restore();"
```

All data can be re-fetched from the public sources, so the backup mainly protects
history beyond the sources' availability, events and configuration (alert
channels, API key hashes).

## API keys and alert channels

```sql
-- API key: store only the SHA-256 hash
INSERT INTO api_keys (name, key_hash) VALUES ('partner-x', encode(sha256('the-secret-key'), 'hex'));
-- Teams/Slack/webhook channel (in addition to ENV-configured channels)
INSERT INTO alert_channels (name, kind, target, min_severity) VALUES ('ops-teams', 'teams', 'https://…', 'warning');
```

## Licences

Python dependencies must have an OSI licence compatible with Apache-2.0 (allow-list
in `scripts/tasks.py`, checked by `make security`); npm production dependencies
are checked with `license-checker` (`pnpm licenses`).

## Local development without Docker (e.g. Windows)

Use any PostgreSQL 16 with the TimescaleDB extension and set
`GRIDPULSE_TEST_DATABASE_URL` for integration tests; `GRIDPULSE_DATABASE_URL=memory://`
runs the API without a database (tests and quick UI work only).
