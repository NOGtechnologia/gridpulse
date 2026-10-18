# Progress report

Status as of **2026-10-18**. Build machine: Windows Server 2022 **without Docker and
without GNU make**; the tools were installed into the user profile (uv 0.13.1,
CPython 3.12.15, Node 22.23.3, pnpm 9.15.4, MinGit, PostgreSQL 16.15 + TimescaleDB
2.30.2 from the official binaries). Everything below marked *verified* was executed
on this machine; items marked *CI only* are configured and enforced in GitHub
Actions but could not run locally.

## Test results (local, last run)

| Check | Result |
|---|---|
| `scripts/tasks.py check` (≙ `make check`) | **all green** |
| ruff format/check, mypy --strict (58 modules) | 0 findings |
| Backend unit + property + contract (incl. Schemathesis) | 176 passed |
| Backend integration (real TimescaleDB 2.30.2, Postgres 16) | 10 passed |
| Backend coverage | **99 %** total, **100 %** `domain/` + `validation/` |
| ESLint strict, Prettier, `tsc --noEmit` (strict, noUncheckedIndexedAccess) | 0 findings |
| Vitest | 29 passed, **96.5 %** statements |
| OpenAPI drift + generated TS types | up to date |
| pip-audit (locked versions), pnpm audit --prod | no known vulnerabilities |
| Licence checks (Python allow-list, npm `license-checker`) | passed |
| gitleaks over the full git history | no leaks |
| Playwright E2E (Chromium) incl. axe dark + light, against **live data** | 12 passed |
| `scripts/verify_sources.py` (live) | SMARD, Energy-Charts, Open-Meteo OK; ENTSO-E skipped (no token) |

Real defects found and fixed by the gates during the build (selection): MAD score
became NaN with gaps; 50.1 Hz classified "red" due to float rounding; renewable
share 100.000000001 %; numbers like `start=0.5` accepted as Unix time; undocumented
401/429 responses (Schemathesis); SMARD load lagging generation left the load tile
empty; day-ahead prices for tomorrow made sources look fresh; event spam per 15-min
interval (→ episodes, ADR 0008); WCAG contrast of flow labels in light mode and
ARIA issues of the map (axe); critical XSS in maplibre-gl ≤ 6.4.0, ECharts XSS and
PostCSS advisories (pnpm audit → upgraded / overridden).

## Phase checklist (Definition of Done)

### Phase 0 – Foundation & source verification ✅
- [x] Repository layout per spec §6, Makefile, pre-commit, `.env.example`, licence files, `CLAUDE.md`
- [x] `scripts/verify_sources.py` – live checks + fixtures; `docs/data-sources.md` with verified endpoints
- [x] Fixtures for SMARD, Energy-Charts, Open-Meteo; ENTSO-E documented as skipped (no token)
- [x] CI base pipeline – *CI only* (workflows written, SHA-pinned; first run happens on push)

### Phase 1 – Data core ✅
- [x] Canonical model, Alembic migration, hypertable, 1 h + Berlin-1 d continuous aggregates
- [x] SMARD + Energy-Charts adapters, Pandera schema, plausibility rules (§7.4)
- [x] Worker with scheduler, idempotent upsert, backoff with jitter, `source_status`
- [x] SMARD ↔ Energy-Charts cross-check (XCHK-001)
- [x] Coverage targets; integration tests on real TimescaleDB; DST property tests (23/25 h)

### Phase 2 – Domain logic ✅ (mutation score: *CI only*)
- [x] Residual load, renewable share, CO₂ intensity with sources, aggregation
- [x] Deterministic rule engine with rule IDs (`docs/rules.md`)
- [x] 100 % coverage in `domain/`
- [ ] Mutation score ≥ 80 % – configured (`nightly.yml`, mutmut on `domain/`); mutmut does not run on Windows, **not yet measured**

### Phase 3 – API ✅
- [x] `/observations`, `/summary/now`, `/forecast/residual-load`, `/events`, `/sources/status`, `/export` (+ `/metrics` catalogue, `/alerts/test`)
- [x] Pagination, filters, rate limit, optional hashed API keys, configurable CORS
- [x] OpenAPI generated and drift-checked in `make build`; Schemathesis green; examples in `docs/api.md`

### Phase 4 – Frontend ✅ (Lighthouse/visual baselines: *CI only*)
- [x] Pages Lage, Ausblick, Ereignisse, Historie, Status, Kiosk; component library; theme; DE/EN
- [x] Typed API client generated from OpenAPI (`openapi-typescript` + `openapi-fetch`)
- [x] Vitest coverage ≥ 80 % (96.5 %); axe 0 serious/critical (verified, dark + light)
- [ ] Lighthouse ≥ 90/95/95 – configured in `e2e.yml` (`lighthouserc.json`), **not run locally**
- [ ] Visual regression baselines – tests written (masked dynamic values, 0.2 %); baselines must be generated once in CI (`e2e.yml` → *Run workflow* with `update_snapshots`) so they match the Linux renderer

### Phase 5 – Alerts & operations ✅ (container items: *CI only*)
- [x] Webhook, Slack/Teams and SMTP channels, debouncing + episodes, UI test button (server-side admin token)
- [x] Prometheus metrics, `/healthz`, `/readyz`, structured JSON logs
- [x] Hardened Dockerfiles (non-root, read-only root FS, cap_drop, healthchecks), Compose stack, demo mode
- [ ] E2E pipeline with full Compose stack + Trivy – configured (`e2e.yml`, `docker.yml`); **Docker unavailable locally**, so images were not built here

### Phase 6 – ENTSO-E & Europe ◐
- [x] ENTSO-E adapter (XML via defusedxml, A03 gap filling, token via ENV, never logged), system runs without token
- [x] Border-flow map (Energy-Charts cross-border data, offline MapLibre)
- [x] Contract tests with ENTSO-E fixtures – **constructed** from the implementation guide (no token); replace with recorded responses
- [ ] Country comparison view (load/price per bidding zone via ENTSO-E) – not built yet

### Phase 7 – Own forecasting model (optional) ☐
- Not started. Open-Meteo weather features are already ingested (`weather.*`, 3 locations) as the basis. The UI states that no custom model is active.

### Phase 8 – Release readiness ◐
- [x] README with Playwright screenshots, badges, quick start; release-please, multi-arch + cosign + SBOM workflow, Scorecard
- [x] Final audit (this document)
- [ ] Tag `v1.0.0` / GHCR release – requires the GitHub repository (no remote configured here)
- [ ] Fresh clone + `docker compose up` in an empty environment – requires Docker

## Acceptance criteria (§13)

| Criterion | Status |
|---|---|
| Fresh clone → `make check` green | ✅ verified on Windows via `tasks.py check`; Linux via CI on first push |
| `docker compose up` → demo dashboard < 2 min | ☐ not verifiable here (no Docker); compose file + demo mode are in place |
| Live data from SMARD and Energy-Charts, auto refresh | ✅ verified (worker ran against live sources; UI polls every 60 s) |
| All §7 thresholds enforced in CI | ✅ configured; ◐ mutation score, Lighthouse, visual baselines get their first run in CI |
| Every number has unit, data timestamp and source | ✅ (tile footers; E2E asserts it) |
| No secrets in the repo (gitleaks, full history) | ✅ |
| Disclaimer and data licences in README, UI footer, NOTICE | ✅ |

## Open points

1. Push to GitHub, enable branch protection, run all workflows once; generate visual baselines via `e2e.yml` (`update_snapshots`).
2. Configure `GRIDPULSE_ENTSOE_TOKEN` (repo secret + `.env`), re-record ENTSO-E fixtures, build the country comparison view.
3. First nightly mutation run – raise tests if the score is < 80 %.
4. Phase 7 (optional) forecasting model with backtest against the official forecast.
5. Replace the placeholder organisation `github.com/gridpulse/gridpulse` in README/NOTICE/workflows with the real repository URL.
