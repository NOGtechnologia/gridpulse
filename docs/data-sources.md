# Data sources

All endpoints were **verified live on 2026-10-18** with `scripts/verify_sources.py`;
raw responses are stored as contract-test fixtures in `backend/tests/fixtures/`.
The nightly workflow re-runs the verification to detect upstream changes early.

| Source | Licence | Key needed | Adapter |
|---|---|---|---|
| SMARD (Bundesnetzagentur) | CC BY 4.0 | no | `adapters/smard.py` |
| Energy-Charts API (Fraunhofer ISE) | CC BY 4.0 | no | `adapters/energy_charts.py` |
| Open-Meteo | CC BY 4.0 | no | `adapters/open_meteo.py` |
| ENTSO-E Transparency Platform | ENTSO-E T&C | security token | `adapters/entsoe.py` (optional) |

## SMARD

* Index: `https://www.smard.de/app/chart_data/{filter}/{region}/index_{resolution}.json`
  → `{"timestamps": [ms, …]}` – start of each **weekly chunk** (Monday 00:00 Europe/Berlin).
* Series: `…/{filter}/{region}/{filter}_{region}_{resolution}_{timestamp}.json`
  → `{"meta_data": {...}, "series": [[ms, value|null], …]}`.
* Resolutions used: `quarterhour`, `hour`.

**Quirk (deviation from the spec's assumptions):** generation and load are published
as **energy per interval (MWh per quarter hour/hour)**, not power. `parse()` converts
to mean power in MW by dividing by the interval length (×4 for quarter hours).
Prices (EUR/MWh) are used unchanged. Future intervals are `null` and dropped.
Since 1 Oct 2025 the day-ahead price (4169, region `DE-LU`) is quarter-hourly.

| Filter | Canonical metric | Kind |
|---|---|---|
| 1223 | generation.lignite | actual |
| 1224 | generation.nuclear | actual (history; phase-out 2023-04-15, not ingested) |
| 1225 | generation.wind_offshore | actual |
| 1226 | generation.hydro | actual |
| 1227 | generation.other_conventional | actual |
| 1228 | generation.other_renewable | actual |
| 4066 | generation.biomass | actual |
| 4067 | generation.wind_onshore | actual |
| 4068 | generation.solar | actual |
| 4069 | generation.hard_coal | actual |
| 4070 | generation.pumped_storage | actual |
| 4071 | generation.gas | actual |
| 410 | load.actual | actual |
| 4359 | load.residual | actual |
| 4387 | consumption.pumped_storage | actual |
| 4169 (DE-LU) | price.day_ahead | actual (incl. next day) |
| 411 | load.actual | forecast |
| 4362 | load.residual | forecast |
| 123 | generation.wind_onshore | forecast |
| 3791 | generation.wind_offshore | forecast |
| 125 | generation.solar | forecast |

Observed delays: generation ≈ 1 h; load one quarter hour later than generation;
biomass up to a few days. The summary therefore uses the newest timestamp at which
load *and* wind exist (see `services/summary.py`).

## Energy-Charts

Base URL `https://api.energy-charts.info`, all series indexed by `unix_seconds`.

| Endpoint | Content | Unit | Notes |
|---|---|---|---|
| `/public_power?country=de&start&end` | `production_types[{name, data}]` | MW | names mapped below |
| `/price?bzn=DE-LU&start&end` | `price` | EUR/MWh | carries `license_info` of the original publisher |
| `/frequency?region=DE-Freiburg&start&end` | `data` | Hz | **1 s resolution** |
| `/cbet?country=de&start&end` | `countries[{name, data}]` | **GW** | positive = import; `sum` = total net flow |
| `/ren_share_forecast?country=de` | `ren_share`, `solar_share`, … | % | stored as forecast |

`public_power` names → metrics: Wind onshore/offshore, Solar, Biomass, Fossil brown
coal / lignite, Fossil hard coal, Fossil gas, Fossil oil, Nuclear (if present);
Hydro Run-of-River + Hydro water reservoir → `generation.hydro`; Others + Waste +
Fossil coal-derived gas → `generation.other_conventional`; Geothermal →
`generation.other_renewable`; Hydro pumped storage → `generation.pumped_storage`;
Hydro pumped storage consumption (negative) → `consumption.pumped_storage`
(sign flipped); Cross border electricity trading → `flow.net_import` (area `DE`);
Load, Residual load, Renewable share of generation.

`cbet` values are converted GW → MW. Border areas are encoded as
`BORDER:DE:<ISO>` (net import of DE from that neighbour). The contract test checks
that `cbet.sum` equals `public_power` "Cross border electricity trading".

Frequency is reduced to **10 s buckets keeping the sample with the largest
|f − 50 Hz|** (ADR 0003), which is conservative for alerting.

## Open-Meteo

`https://api.open-meteo.com/v1/forecast?latitude=a,b&longitude=x,y&hourly=temperature_2m,wind_speed_100m,shortwave_radiation,cloud_cover&timezone=UTC`
returns a JSON **list** (one object per location) when several coordinates are
requested. Units: °C, km/h, W/m², %. Areas: `WX:hamburg`, `WX:kassel`, `WX:munich`.

`past_days` (max. 92) follows the requested window so that the forecasting model can
be backfilled. Verified 2026-10-19: the API keeps only about two months of past
hours; older hours inside `past_days` are returned as `null` and dropped by `parse()`
(fixture `forecast_past_days.json`). These past values are close to observations,
not archived day-ahead forecasts (see [forecasting.md](forecasting.md)).

## ENTSO-E

`https://web-api.tp.entsoe.eu/api` with `securityToken`:
`documentType=A65&processType=A16&outBiddingZone_Domain=<EIC>` (actual load,
`GL_MarketDocument`) and `documentType=A44&in_Domain=out_Domain=<EIC>`
(day-ahead prices, `Publication_MarketDocument`). Points use 1-based `position`;
curve type A03 omits repeated values, which `parse()` forward-fills. If a zone
publishes an hourly and a quarter-hourly day-ahead series for the same day (15-min
MTU transition), the finest resolution is kept.

The worker loads both documents for every zone in `AREAS` (DE-LU, FR, NL, BE, AT,
PL, CZ, CH, DK1) for the country comparison page ("Länder"); job names carry the
zone (`entsoe:load.actual:actual@FR`). That is 18 requests per ingest interval,
well below the platform limit of 400 requests per minute.

**Not verified live** – no token was available on 2026-10-18 (allowed by the spec).
The fixtures in `backend/tests/fixtures/entsoe/` are constructed from the official
implementation guide and must be replaced with recorded responses once a token is
configured (`GRIDPULSE_ENTSOE_TOKEN=… make verify-sources` with `--save-fixtures`).

## Plausibility limits

* Grid frequency 49.0–51.0 Hz.
* Day-ahead price within the SDAC harmonised maximum/minimum clearing price
  **−500 / +4000 EUR/MWh** (ACER decision on HMMCP; the maximum is raised
  automatically after price spikes – therefore configurable via
  `GRIDPULSE_PRICE_MIN_EUR_MWH` / `GRIDPULSE_PRICE_MAX_EUR_MWH`).
* Generation + net import − pumped consumption vs. load: ±15 % (statistical
  differences between published load and generation are normal).
