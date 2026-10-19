"""48 h residual load outlook from official forecasts ("Ausblick", spec 2.2)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from gridpulse.adapters.registry import license_for
from gridpulse.domain.indicators import dunkelflaute_windows, negative_price_windows
from gridpulse.domain.metrics import Kind, MetricId
from gridpulse.domain.residual_load import residual_load
from gridpulse.domain.rules.config import RuleConfig
from gridpulse.schemas import (
    ForecastPoint,
    ForecastResponse,
    Meta,
    ModelBacktest,
    OutlookWindow,
)
from gridpulse.services.model_forecast import MODEL_SOURCE
from gridpulse.services.series import best_source, fetch_frame, pick_series
from gridpulse.storage.repository import ModelRun, Repository

Q = timedelta(minutes=15)
FORECAST_METRICS = [
    MetricId.LOAD_ACTUAL,
    MetricId.GENERATION_WIND_ONSHORE,
    MetricId.GENERATION_WIND_OFFSHORE,
    MetricId.GENERATION_SOLAR,
    MetricId.LOAD_RESIDUAL,
]


def _hours(start: datetime, end: datetime) -> float:
    return (end - start) / timedelta(hours=1)


async def build_forecast(
    repo: Repository, now: datetime, hours: int, config: RuleConfig
) -> ForecastResponse:
    start = now - timedelta(hours=1)
    end = now + timedelta(hours=hours)
    frame = await fetch_frame(repo, FORECAST_METRICS, start, end, kind=Kind.FORECAST)
    source = best_source(frame, MetricId.LOAD_ACTUAL)
    points: list[ForecastPoint] = []
    windows: list[OutlookWindow] = []
    if source is not None:
        own = frame[frame["source"] == source]
        load = pick_series(own, MetricId.LOAD_ACTUAL)
        on = pick_series(own, MetricId.GENERATION_WIND_ONSHORE)
        off = pick_series(own, MetricId.GENERATION_WIND_OFFSHORE)
        pv = pick_series(own, MetricId.GENERATION_SOLAR)
        if off.empty:
            off = pd.Series(0.0, index=load.index)
        official = pick_series(own, MetricId.LOAD_RESIDUAL)
        residual = residual_load(load, on, off, pv)
        for ts in residual.index:
            stamp = pd.Timestamp(ts)
            points.append(
                ForecastPoint(
                    ts=stamp.to_pydatetime(),
                    load=float(load.loc[stamp]),
                    wind=float(on.loc[stamp] + off.loc[stamp]),
                    solar=float(pv.loc[stamp]),
                    residual_load=float(residual.loc[stamp]),
                    official_residual_load=float(official.loc[stamp])
                    if stamp in official.index
                    else None,
                )
            )
        vre = (on + off).reindex(load.index) + pv.reindex(load.index)
        for w in dunkelflaute_windows(
            load,
            vre.dropna(),
            step=Q,
            share_threshold=config.dunkelflaute_share,
            min_duration=config.dunkelflaute_min_duration,
        ):
            windows.append(
                OutlookWindow(
                    kind="dunkelflaute",
                    start=w.start,
                    end=w.end,
                    hours=_hours(w.start, w.end),
                    detail=f"wind+PV < {config.dunkelflaute_share:.0%} of load",
                )
            )
    price_frame = await fetch_frame(repo, [MetricId.PRICE_DAY_AHEAD], start, end, areas=["DE-LU"])
    price_source = best_source(price_frame, MetricId.PRICE_DAY_AHEAD)
    if price_source is not None:
        price = pick_series(price_frame, MetricId.PRICE_DAY_AHEAD, price_source)
        step = (
            pd.Timedelta(pd.Series(price.index).diff().median()).to_pytimedelta()
            if len(price) > 1
            else Q
        )
        for w in negative_price_windows(price, step):
            low = float(price[(price.index >= w.start) & (price.index < w.end)].min())
            windows.append(
                OutlookWindow(
                    kind="negative_price",
                    start=w.start,
                    end=w.end,
                    hours=_hours(w.start, w.end),
                    detail=f"min {low:.2f} EUR/MWh",
                )
            )
    run = await repo.latest_model_run()
    model_source = None
    if run is not None and run.active and points:
        model_frame = await fetch_frame(
            repo, [MetricId.LOAD_RESIDUAL], start, end, kind=Kind.FORECAST, sources=[MODEL_SOURCE]
        )
        model = pick_series(model_frame, MetricId.LOAD_RESIDUAL)
        if not model.empty:
            model_source = MODEL_SOURCE
            points = [
                p.model_copy(update={"model_residual_load": float(model.loc[pd.Timestamp(p.ts)])})
                if pd.Timestamp(p.ts) in model.index
                else p
                for p in points
            ]
    sources = "|".join(s for s in (source, price_source, model_source) if s) or "none"
    lic, attr = license_for(sources)
    return ForecastResponse(
        meta=Meta(
            source=sources, license=lic, attribution=attr, generated_at=now, count=len(points)
        ),
        points=points,
        windows=sorted(windows, key=lambda w: w.start),
        model=_backtest_out(run) if run is not None else None,
    )


def _backtest_out(run: ModelRun) -> ModelBacktest:
    return ModelBacktest(
        trained_at=run.trained_at,
        algorithm=run.algorithm,
        seed=run.seed,
        target=run.target,
        features=list(run.features),
        train_start=run.train_start,
        train_end=run.train_end,
        test_start=run.test_start,
        test_end=run.test_end,
        test_points=run.test_points,
        mae_model=run.mae_model,
        mape_model=run.mape_model,
        mae_official=run.mae_official,
        mape_official=run.mape_official,
        active=run.active,
    )
