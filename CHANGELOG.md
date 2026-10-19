# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses
[Semantic Versioning](https://semver.org/). From the first release on, this file is
maintained by release-please from Conventional Commits.

## [1.0.0](https://github.com/NOGtechnologia/gridpulse/compare/v0.1.0...v1.0.0) (2026-10-19)


### Features

* **adapter:** Open-Meteo past_days follows the requested window ([65d2b14](https://github.com/NOGtechnologia/gridpulse/commit/65d2b14469e284a733e3d7ef191b310a7ccd22a1))
* **adapter:** SMARD, Energy-Charts, Open-Meteo and ENTSO-E adapters with verified fixtures ([4bf28d7](https://github.com/NOGtechnologia/gridpulse/commit/4bf28d7b33e8432f0722415fdda57bc101c92f6c))
* **api:** backtest of the own model in the residual load outlook ([8891a9c](https://github.com/NOGtechnologia/gridpulse/commit/8891a9c658f49831c047af10df295c5b1bb115b9))
* **api:** read-only /api/v1 with rate limiting, API keys, export and OpenAPI 3.1 ([6115729](https://github.com/NOGtechnologia/gridpulse/commit/61157291da9925f4073630d16b60ad24f84f1163))
* **domain:** calendar features and forecast scores for the own model ([2393af1](https://github.com/NOGtechnologia/gridpulse/commit/2393af182b9b9db1a45f01b1c5afb8d69215df4d))
* **domain:** metric catalogue, time handling, residual load, CO2 intensity and rule engine ([aa31af2](https://github.com/NOGtechnologia/gridpulse/commit/aa31af2f4080b70ec026e658df74e01a32e04a40))
* **storage:** model_runs table and feature pipeline with gradient-boosted model ([5615602](https://github.com/NOGtechnologia/gridpulse/commit/56156020aafb8b8f00e9aade0c741cd04afae779))
* **storage:** TimescaleDB hypertable, continuous aggregates, repositories and migrations ([e05f000](https://github.com/NOGtechnologia/gridpulse/commit/e05f00023782f7372c766deea4469a1108a56054))
* **validation:** pandera schema, plausibility checks and source cross-check ([a9b3796](https://github.com/NOGtechnologia/gridpulse/commit/a9b37968d0577c745aa6c47d35bf7410247aafef))
* **web:** backtest tile in Ausblick, own model shown only when it wins ([76b1560](https://github.com/NOGtechnologia/gridpulse/commit/76b156088d8d3c27b9763a1f0e50b1c0d2f26709))
* **web:** country comparison page (Länder) for load and prices per bidding zone ([b02cd83](https://github.com/NOGtechnologia/gridpulse/commit/b02cd838d40cecd92852ee19fc281e8650993df2))
* **web:** Next.js dashboard with situation, outlook, events, history, status and kiosk ([15867d0](https://github.com/NOGtechnologia/gridpulse/commit/15867d0f9d937daff86dc2570c8f47ae5eecb4bd))
* **worker:** daily training job and reproducible training script for the own model ([7fa1fbd](https://github.com/NOGtechnologia/gridpulse/commit/7fa1fbd965bd8fda6f1e6c2545f38bf01276eb64))
* **worker:** ingest pipeline, analysis, alerts, demo data and scheduler ([e0d28c0](https://github.com/NOGtechnologia/gridpulse/commit/e0d28c05014f5930749e814b86a74b1f7596582c))
* **worker:** load and day-ahead prices for all neighbouring bidding zones via ENTSO-E ([84fee04](https://github.com/NOGtechnologia/gridpulse/commit/84fee0403861ae1795907e235e50bfdf91c7331e))


### Bug Fixes

* **docker:** web image on Debian trixie, numeric user, without npm ([7e640ba](https://github.com/NOGtechnologia/gridpulse/commit/7e640baa53998cd721eb909ff84f14b9d59c90c1))
* **web:** exclude vendored MapLibre worker from ESLint ([da3f7f4](https://github.com/NOGtechnologia/gridpulse/commit/da3f7f4259efc3a584a70cc3afa62833cf85e0a2))
* **web:** keep the backtest status badge at content width ([ee07d11](https://github.com/NOGtechnologia/gridpulse/commit/ee07d11f3a2bd52a762d3eef62af2684c844e4cc))
* **web:** mark stale tiles with a dashed border instead of dimming them ([25904b3](https://github.com/NOGtechnologia/gridpulse/commit/25904b30160f7cdd8262985292e9ca94a07e795f))
* **web:** no 'source unknown' footer on loading zone tiles ([4721d21](https://github.com/NOGtechnologia/gridpulse/commit/4721d21db253253114bfd2d24060706a77b3052c))
* **web:** reserve tile heights while loading to avoid layout shift ([49c18f9](https://github.com/NOGtechnologia/gridpulse/commit/49c18f908c6084a5d96f744bdbc19743911c6a93))


### Miscellaneous Chores

* **release:** first release is v1.0.0 ([6a97e3a](https://github.com/NOGtechnologia/gridpulse/commit/6a97e3a1845626565ee79939f91d9aca52ff27de))

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
