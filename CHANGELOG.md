# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses
[Semantic Versioning](https://semver.org/). From the first release on, this file is
maintained by release-please from Conventional Commits.

## [Unreleased]

### Added

- Data core: adapters for SMARD, Energy-Charts, Open-Meteo and ENTSO-E (optional),
  canonical observation model on TimescaleDB (hypertable, hourly and Berlin-daily
  continuous aggregates), idempotent upserts, retention/compression policies.
- Validation: Pandera schema, plausibility checks (frequency range, non-negative
  generation, PV at night, supply/load balance, price limits, time axis) and the
  SMARD ↔ Energy-Charts cross-check; violations are recorded as events.
- Domain: residual load, renewable share, CO₂ intensity (IPCC AR5 factors),
  Berlin-day aggregation, deterministic rule engine with stable rule IDs and
  episode merging, rolling z-score/MAD anomaly detection, outlook windows.
- Worker with APScheduler, backoff with jitter, source status, alerts via webhook,
  Slack/Teams-compatible webhooks and SMTP with debouncing.
- Read-only REST API `/api/v1` (OpenAPI 3.1), pagination, rate limiting, hashed API
  keys, CSV/Parquet export with licence metadata, health and Prometheus endpoints.
- Next.js dashboard: Lage, Ausblick, Ereignisse, Historie, Status, Kiosk; DE/EN,
  dark/light theme, colour-blind-safe carrier colours, offline MapLibre border map.
- Quality gate: `make check`, CI, E2E with axe and Lighthouse, CodeQL, Trivy,
  gitleaks, Dependabot, release pipeline with signed multi-arch images and SBOM.
