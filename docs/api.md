# API

Read-only REST API, versioned under `/api/v1`. The OpenAPI 3.1 document is
generated from the code and committed as [`docs/openapi.json`](openapi.json)
(`make openapi`; `make build` fails on drift). Interactive docs: `/api/docs`.

* Timestamps are ISO 8601 **UTC**, interval start. Inputs must carry an offset
  (`2026-10-18T00:00:00Z`); numbers like `0.5` are rejected.
* Every response contains `meta` with `source`, `license`, `attribution`,
  `generated_at` and the disclaimer.
* Rate limit per client IP (default 120/min). With a valid `X-API-Key` the limit is
  ten times higher. `GRIDPULSE_REQUIRE_API_KEY=1` makes keys mandatory. Keys are
  stored only as SHA-256 hashes.
* Errors: `401` (key), `422` (validation), `429` (rate limit, `Retry-After`).

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/observations` | time series, filters + pagination |
| GET | `/api/v1/summary/now` | live situation |
| GET | `/api/v1/forecast/residual-load` | residual load outlook + notice windows; `model` = latest backtest of the own model (see [forecasting.md](forecasting.md)), `model_residual_load` only while it beats the official forecast |
| GET | `/api/v1/events` | detected events |
| GET | `/api/v1/sources/status` | data quality per source |
| GET | `/api/v1/metrics` | metric catalogue (units, colours) |
| GET | `/api/v1/export` | CSV or Parquet with licence metadata |
| POST | `/api/v1/alerts/test` | test notification (needs `X-Admin-Token`) |
| GET | `/healthz`, `/readyz`, `/metrics` | operations |

## Examples

```bash
# Grid load and wind onshore of yesterday, hourly means
curl "http://localhost:8000/api/v1/observations?metric=load.actual&metric=generation.wind_onshore&area=DE&kind=actual&resolution=1h&start=2026-10-17T00:00:00Z&end=2026-10-18T00:00:00Z"
```

```json
{
  "meta": {"source": "energy_charts|smard", "license": "CC BY 4.0", "attribution": "…",
           "generated_at": "2026-10-18T12:00:00Z", "count": 48, "total": 96, "next_offset": 48},
  "data": [{"ts": "2026-10-17T00:00:00Z", "metric": "generation.wind_onshore", "area": "DE",
            "kind": "actual", "source": "smard", "unit": "MW", "value": 13004.5}]
}
```

```bash
curl http://localhost:8000/api/v1/summary/now          # live situation
curl "http://localhost:8000/api/v1/forecast/residual-load?hours=48"
curl "http://localhost:8000/api/v1/events?min_severity=warning&limit=50"
curl "http://localhost:8000/api/v1/export?metric=generation.solar&format=parquet&start=2026-10-01T00:00:00Z&end=2026-10-08T00:00:00Z" -o solar.parquet
curl -X POST -H "X-Admin-Token: $GRIDPULSE_ADMIN_TOKEN" http://localhost:8000/api/v1/alerts/test
```

CSV exports start with `#`-comment lines (`source`, `license`, `attribution`,
`generated_at`, `time_basis`, `disclaimer`); Parquet files carry the same values as
schema metadata (`gridpulse.license`, …).

## Metrics and areas

Metric IDs and units: `GET /api/v1/metrics` (e.g. `generation.solar` MW,
`price.day_ahead` EUR/MWh, `grid.frequency` Hz, `indicator.co2_intensity` gCO2/kWh).
Areas: `DE`, `DE-LU` (prices), `BORDER:DE:<ISO>` (net import from a neighbour),
`WX:<location>` (weather).
