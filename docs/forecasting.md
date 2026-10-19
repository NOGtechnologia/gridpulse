# Own forecasting model (phase 7, optional)

GridPulse can train its own residual-load model and compares it with the official
day-ahead forecast. The model is **only shown in the outlook ("Ausblick") when it
beats the official forecast on both MAE and MAPE** in the latest backtest. The
backtest metrics are always shown, whether or not the model is. Design decisions
are recorded in [ADR 0010](adr/0010-forecasting-model.md).

## Model

| | |
|---|---|
| Target | Hourly mean of the actual residual load DE (`load.residual`, SMARD; load minus wind and PV) |
| Benchmark | Official day-ahead residual-load forecast (`load.residual`, kind `forecast`, SMARD), hourly mean |
| Algorithm | scikit-learn `HistGradientBoostingRegressor` (histogram gradient boosting like LightGBM), `max_iter=300`, `learning_rate=0.05`, `early_stopping=False`, **seed 42** |
| Weather features | `weather.temperature_2m`, `weather.wind_speed_100m`, `weather.shortwave_radiation`, `weather.cloud_cover` from Open-Meteo at Hamburg, Kassel and Munich (12 columns) |
| Calendar features | Europe/Berlin hour of day, weekday and German nationwide public holiday (`domain/calendar.py`, Easter-based dates computed, no extra dependency) |
| Code | `domain/calendar.py`, `domain/scores.py` (100 % covered), `forecasting/` (features, model), `services/model_forecast.py` |

Sub-hourly series are averaged per hour; hours that are still incomplete (being
published) are dropped instead of being averaged from fewer quarter-hours.

## Backtest

* **Split:** chronological holdout. The last 7 days with actuals *and* an official
  forecast are the test window; the model is trained on everything before it. At
  least 14 days of training data (≥ 75 % of the hours) are required; otherwise no
  run is recorded and the outlook says so.
* **Metrics:** MAE in MW over all test hours; MAPE in % over the test hours with
  |actual| ≥ 1 000 MW (residual load can approach 0 MW, where percentage errors
  explode). Both forecasts are scored on exactly the same hours.
* **Gate:** shown only if `MAE_model < MAE_official` **and** `MAPE_model < MAPE_official`.
* **Operation:** the worker retrains once a day (`GRIDPULSE_FORECAST_MODEL_*`
  settings, job `forecast_model`), stores the run in `model_runs` and the 48 h
  forecast as observations with source `gridpulse_model`. `GET
  /api/v1/forecast/residual-load` returns the latest run as `model`; points carry
  `model_residual_load` only while the run is active.

### Reproducing

```bash
uv run --project backend python scripts/train_forecast.py --backfill-days 92 --report docs/forecasting-backtest.json
```

`--backfill-days` loads the inputs through the regular ingest pipeline (SMARD
residual load actual + forecast, Open-Meteo weather with `past_days`), then the
script runs exactly the worker's training code. The result depends only on the
stored data and `--as-of`; re-running with the same `--as-of` produced a
byte-identical report. `--store` additionally saves the run and the forecast.

## Results (2026-10-19)

Data: SMARD and Open-Meteo, backfilled on 2026-10-19 into the local database.
Open-Meteo returns past hours only back to 2026-08-17 18:00 UTC, which bounds
the training window. Report: [`forecasting-backtest.json`](forecasting-backtest.json).

Latest run (`--as-of 2026-10-19T06:00Z`, training 2026-08-17 18:00 – 2026-10-12
05:00 UTC, test 2026-10-12 05:00 – 2026-10-19 05:00 UTC, 168 hours):

| | MAE | MAPE |
|---|---|---|
| Own model | 5 060 MW | 21.2 % |
| Official forecast (SMARD) | **1 722 MW** | **6.9 %** |

**Verdict: the own model is clearly worse and is not shown in the outlook.**

Earlier cut-offs (same data, training always from 2026-08-17):

| Test window (UTC) | MAE model | MAE official | MAPE model | MAPE official | Shown |
|---|---|---|---|---|---|
| 09-21 → 09-28 | 4 572 MW | 2 860 MW | 27.2 % | 32.7 % | no (MAE worse) |
| 09-28 → 10-05 | 6 605 MW | 2 749 MW | 25.2 % | 14.0 % | no |
| 10-05 → 10-12 | 5 616 MW | 1 772 MW | 81.5 % | 27.0 % | no |
| 10-12 → 10-19 | 5 060 MW | 1 722 MW | 21.2 % | 6.9 % | no |

The first row shows why both metrics are required: a lower MAPE alone came with
a 60 % higher MAE.

## Interpretation and limitations

* **Too little information.** Three weather points cannot describe German wind
  and PV infeed, which the TSOs forecast from full numerical weather models and
  installed-capacity data. With only ~8 weeks of history the model also cannot
  learn the seasonal rise of load from summer into autumn: the test week always
  lies outside the range it was trained on.
* **The backtest flatters the own model.** For past hours Open-Meteo returns
  values close to observations (stitched short-range forecasts), not the forecast
  that was available a day ahead, whereas the SMARD forecast is a genuine
  day-ahead forecast. Passing the gate would therefore be a necessary, not a
  sufficient, sign of a better forecast. The UI states this next to the metrics.
* **Ways to improve** (not implemented): more weather points weighted by installed
  wind/PV capacity, a longer history (the worker keeps collecting; retention is
  730 days), lagged actuals that are available at forecast time, and archived
  day-ahead weather forecasts for an honest backtest.
