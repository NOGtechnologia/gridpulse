"""Worker analysis: derived indicators, rule evaluation and source cross-checks."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from gridpulse.domain.indicators import co2_intensity_series, generation_mix, renewable_share_series
from gridpulse.domain.metrics import GENERATION_METRICS, Kind, MetricId
from gridpulse.domain.observations import concat_frames, make_frame
from gridpulse.domain.rules import (
    Event,
    RuleConfig,
    dunkelflaute_outlook,
    forecast_error,
    frequency_deviation,
    merge_episodes,
    negative_price_outlook,
    price_spike,
    stale_data,
    statistical_anomaly,
)
from gridpulse.services.series import SOURCE_PRIORITY, best_source, fetch_frame, pick_series
from gridpulse.storage.repository import QueryResolution, Repository
from gridpulse.validation.crosscheck import crosscheck

Q = timedelta(minutes=15)
# Consecutive violations closer than this are reported as one episode (no alert spam).
EPISODE_GAP = timedelta(minutes=30)
EPISODE_GAP_FREQUENCY = timedelta(minutes=1)
DERIVED_SOURCE = "gridpulse"
# Key metric per source used for the staleness rule DATA-001.
STALENESS_KEYS: dict[str, tuple[MetricId, str, Kind]] = {
    "smard": (MetricId.LOAD_ACTUAL, "DE", Kind.ACTUAL),
    "energy_charts": (MetricId.GENERATION_WIND_ONSHORE, "DE", Kind.ACTUAL),
    "open_meteo": (MetricId.WEATHER_TEMPERATURE, "WX:kassel", Kind.FORECAST),
    "entsoe": (MetricId.LOAD_ACTUAL, "DE-LU", Kind.ACTUAL),
}
CROSSCHECK_METRICS: tuple[tuple[MetricId, str, float], ...] = (
    (MetricId.LOAD_ACTUAL, "DE", 100.0),
    (MetricId.GENERATION_WIND_ONSHORE, "DE", 100.0),
    (MetricId.GENERATION_SOLAR, "DE", 100.0),
    (MetricId.PRICE_DAY_AHEAD, "DE-LU", 1.0),
)


async def derive_indicators(
    repo: Repository, now: datetime, lookback: timedelta = timedelta(hours=48)
) -> int:
    """Store renewable share and CO2 intensity (source ``gridpulse``) computed from the mix."""
    frame = await fetch_frame(repo, list(GENERATION_METRICS), now - lookback, now)
    source = best_source(frame, MetricId.GENERATION_WIND_ONSHORE)
    if source is None:
        return 0
    mix = generation_mix(frame[frame["source"] == source])
    # Require most of the mix to be present, otherwise shares would be biased.
    mix = mix[mix.notna().sum(axis=1) >= max(3, int(0.6 * mix.shape[1]))]
    if mix.empty:
        return 0
    stamps = list(pd.DatetimeIndex(mix.index).to_pydatetime())
    frames = [
        make_frame(
            timestamps=stamps,
            values=list(series.to_numpy()),
            metric=metric,
            area="DE",
            kind=Kind.ACTUAL,
            source=DERIVED_SOURCE,
            resolution=Q,
        )
        for metric, series in (
            (MetricId.INDICATOR_RENEWABLE_SHARE, renewable_share_series(mix)),
            (MetricId.INDICATOR_CO2_INTENSITY, co2_intensity_series(mix)),
        )
    ]
    return await repo.upsert_observations(concat_frames(frames))


async def evaluate_rules(
    repo: Repository, now: datetime, config: RuleConfig, sources: tuple[str, ...] = SOURCE_PRIORITY
) -> list[Event]:
    events: list[Event] = []

    freq = await fetch_frame(
        repo,
        [MetricId.GRID_FREQUENCY],
        now - timedelta(minutes=30),
        now,
        resolution=QueryResolution.RAW,
    )
    for src in sorted(set(freq["source"])):
        series = pick_series(freq, MetricId.GRID_FREQUENCY, src)
        events += merge_episodes(
            frequency_deviation(series, config, area="DE", source=src), EPISODE_GAP_FREQUENCY
        )
        events += merge_episodes(
            statistical_anomaly(
                series,
                config,
                metric=MetricId.GRID_FREQUENCY,
                area="DE",
                source=src,
                method="zscore",
            ),
            EPISODE_GAP_FREQUENCY,
        )

    prices = await fetch_frame(
        repo,
        [MetricId.PRICE_DAY_AHEAD],
        now - timedelta(hours=1),
        now + timedelta(hours=48),
        areas=["DE-LU"],
    )
    price_src = best_source(prices, MetricId.PRICE_DAY_AHEAD)
    if price_src:
        price = pick_series(prices, MetricId.PRICE_DAY_AHEAD, price_src)
        events += merge_episodes(
            price_spike(price, config, area="DE-LU", source=price_src), EPISODE_GAP
        )
        events += negative_price_outlook(price, step=Q, area="DE-LU", source=price_src)

    fc_metrics = [
        MetricId.LOAD_ACTUAL,
        MetricId.GENERATION_WIND_ONSHORE,
        MetricId.GENERATION_SOLAR,
        MetricId.GENERATION_WIND_OFFSHORE,
    ]
    actual = await fetch_frame(repo, fc_metrics, now - timedelta(hours=24), now)
    forecast = await fetch_frame(
        repo, fc_metrics, now - timedelta(hours=24), now + timedelta(hours=48), kind=Kind.FORECAST
    )
    for metric in fc_metrics[:3]:
        src = best_source(forecast, metric)
        if src is None:
            continue
        a, f = pick_series(actual, metric, src), pick_series(forecast, metric, src)
        events += merge_episodes(
            forecast_error(a, f, config, metric=metric, area="DE", source=src), EPISODE_GAP
        )

    fc_src = best_source(forecast, MetricId.LOAD_ACTUAL)
    if fc_src:
        load = pick_series(forecast, MetricId.LOAD_ACTUAL, fc_src)
        future = load[load.index >= pd.Timestamp(now)]
        vre = sum(
            (
                pick_series(forecast, m, fc_src).reindex(future.index).fillna(0.0)
                for m in fc_metrics[1:]
            ),
            pd.Series(0.0, index=future.index),
        )
        events += dunkelflaute_outlook(future, vre, config, step=Q, area="DE", source=fc_src)

    residual = await fetch_frame(repo, [MetricId.LOAD_RESIDUAL], now - timedelta(days=3), now)
    res_src = best_source(residual, MetricId.LOAD_RESIDUAL)
    if res_src:
        series = pick_series(residual, MetricId.LOAD_RESIDUAL, res_src)
        recent = series[series.index >= pd.Timestamp(now - timedelta(hours=6))]
        scored = statistical_anomaly(
            series, config, metric=MetricId.LOAD_RESIDUAL, area="DE", source=res_src
        )
        events += merge_episodes(
            [e for e in scored if pd.Timestamp(e.ts) in recent.index], EPISODE_GAP
        )

    status = {s.source for s in await repo.list_source_status()}
    for src in sources:
        if src not in status or src not in STALENESS_KEYS:
            continue
        metric, area, kind = STALENESS_KEYS[src]
        last = await repo.latest_timestamp(metric.value, area, kind.value, src)
        events += stale_data(last, now, config, metric=metric, area=area, source=src)

    events += await cross_check_sources(repo, now, config)
    return events


async def cross_check_sources(
    repo: Repository,
    now: datetime,
    config: RuleConfig,
    primary: str = "smard",
    secondary: str = "energy_charts",
) -> list[Event]:
    """XCHK-001: compare SMARD and Energy-Charts for the same metrics (spec 7.4)."""
    events: list[Event] = []
    for metric, area, floor in CROSSCHECK_METRICS:
        frame = await fetch_frame(
            repo,
            [metric],
            now - timedelta(hours=24),
            now,
            areas=[area],
            sources=[primary, secondary],
        )
        a, b = pick_series(frame, metric, primary), pick_series(frame, metric, secondary)
        if a.empty or b.empty:
            continue
        result = crosscheck(
            a,
            b,
            metric=metric,
            area=area,
            primary_source=primary,
            secondary_source=secondary,
            tolerance=config.crosscheck_tolerance,
            floor=floor,
        )
        events += merge_episodes([v.to_event() for v in result.violations], EPISODE_GAP)
    return events
