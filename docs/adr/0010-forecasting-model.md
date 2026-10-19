# 0010 – Own residual-load model: scikit-learn HGB, gated by a backtest

* Status: accepted · Date: 2026-10-18

## Context

Phase 7 (optional) asks for an own forecasting model from the stored Open-Meteo
weather features plus calendar features, LightGBM or an equivalent, with a fixed
seed, a reproducible training script and a backtest (MAE, MAPE) against the
official forecast. The model may only appear in the outlook when it beats the
official forecast; the metrics are always visible.

Open questions the spec leaves open:

1. **Library.** LightGBM's manylinux wheels link against the system `libgomp`,
   which the hardened, slim backend image does not contain (it would need an extra
   `apt-get` layer); multi-threaded LightGBM is also only reproducible with
   `deterministic=True` + `force_row_wise`. scikit-learn's
   `HistGradientBoostingRegressor` implements the same histogram-based gradient
   boosting, ships its OpenMP runtime inside the wheel (Windows, Linux, macOS,
   arm64), is BSD-3 licensed and deterministic for a fixed `random_state`.
2. **Target.** The outlook is about residual load, and SMARD publishes an official
   day-ahead residual-load forecast (`load.residual`, kind `forecast`), so the
   target is the hourly mean of the actual residual load DE (SMARD).
3. **MAPE near zero.** Residual load can approach 0 MW on sunny, windy days, where
   MAPE explodes. MAPE is computed over hours with |actual| ≥ 1 000 MW only; MAE
   uses all hours. Both models are scored on exactly the same hours.
4. **"Beats".** The model is shown only if *both* MAE and MAPE are lower than the
   official forecast's on the backtest window.

## Decision

* `HistGradientBoostingRegressor(random_state=42, early_stopping=False)`, hourly
  resolution, features: `weather.*` (temperature, wind speed 100 m, shortwave
  radiation, cloud cover) at the three Open-Meteo locations + Europe/Berlin hour,
  weekday and German nationwide public holiday (computed in `domain/calendar.py`,
  no extra dependency).
* Chronological holdout: the last 7 days with actuals *and* an official forecast
  are the test window, everything before is training (at least 14 days required,
  otherwise no run is recorded and the UI says so). The final model is refit on
  all data and predicts the next 48 h from the stored weather forecast.
* The worker retrains once a day (and on start-up); every run is stored in the
  `model_runs` table, predictions as observations (`load.residual`, kind
  `forecast`, source `gridpulse_model`). `scripts/train_forecast.py` runs the same
  code reproducibly (`--as-of`, optional backfill, JSON report).

## Consequences

* Weather values for past hours are what Open-Meteo stores for those hours, i.e.
  close to an analysis, while the official forecast is a genuine day-ahead
  forecast. The backtest therefore flatters the own model; passing the gate is a
  necessary, not a sufficient, sign of a better forecast. This is stated in
  `docs/forecasting.md` and in the UI.
* Open-Meteo keeps about two months of past hours, which bounds the training
  window unless the database has been collecting longer.
* scikit-learn adds numpy/scipy (~60 MB) to the backend image.
