"""Live situation summary ("Lage", spec 2.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pandas as pd

from gridpulse.adapters.registry import license_for
from gridpulse.domain.co2 import co2_intensity
from gridpulse.domain.indicators import renewable_share
from gridpulse.domain.metrics import GENERATION_METRICS, MetricId, unit_of
from gridpulse.domain.residual_load import residual_load_value
from gridpulse.domain.rules.catalog import deviation_in_mhz, frequency_status
from gridpulse.domain.rules.config import RuleConfig
from gridpulse.schemas import (
    Attribution,
    FlowOut,
    FrequencyPoint,
    FrequencySummary,
    Meta,
    SummaryNow,
    Value,
)
from gridpulse.services.series import SOURCE_PRIORITY, best_source, fetch_frame, pick_series
from gridpulse.storage.repository import QueryResolution, Repository

FREQUENCY_STALE = timedelta(minutes=10)
PRICE_STALE = timedelta(hours=1)
SPARKLINE_POINTS = 360
WINDOW = timedelta(hours=12)


@dataclass
class _Context:
    now: datetime
    stale: timedelta
    sources: set[str] = field(default_factory=set)

    def value(
        self,
        value: float | None,
        metric: MetricId,
        ts: datetime | None,
        source: str | None,
        stale_after: timedelta | None = None,
    ) -> Value:
        if value is None:
            ts = None
        age = (self.now - ts).total_seconds() if ts is not None else None
        limit = (stale_after or self.stale).total_seconds()
        if value is not None and source:
            self.sources.update(s for s in source.split("|") if s != "gridpulse")
        return Value(
            value=value,
            unit=unit_of(metric).value,
            ts=ts,
            source=source,
            age_seconds=age,
            stale=age is None or age > limit,
        )


def _at(series: pd.Series, ts: pd.Timestamp) -> float | None:
    return float(series.loc[ts]) if ts in series.index else None


def _last(series: pd.Series) -> tuple[float | None, datetime | None]:
    if series.empty:
        return None, None
    return float(series.iloc[-1]), pd.Timestamp(series.index[-1]).to_pydatetime()


@dataclass
class _Mix:
    source: str | None = None
    as_of: pd.Timestamp | None = None
    values: dict[MetricId, float] = field(default_factory=dict)
    load: float | None = None


def _complete_at(own: pd.DataFrame) -> pd.Timestamp | None:
    """Newest timestamp at which a source has both load and wind (sources publish
    metrics with different delays, e.g. SMARD load lags generation by one interval)."""
    load = pick_series(own, MetricId.LOAD_ACTUAL)
    wind = pick_series(own, MetricId.GENERATION_WIND_ONSHORE)
    common = load.index.intersection(wind.index)
    if len(common):
        return pd.Timestamp(common.max())
    anchor = wind if not wind.empty else load
    return pd.Timestamp(anchor.index.max()) if not anchor.empty else None


def _mix(frame: pd.DataFrame) -> _Mix:
    rank = {s: i for i, s in enumerate(SOURCE_PRIORITY)}
    candidates = []
    for source in {str(s) for s in frame["source"]}:
        ts = _complete_at(frame[frame["source"] == source])
        if ts is not None:
            candidates.append((-ts.value, rank.get(source, 99), source, ts))
    if not candidates:
        return _Mix()
    _, _, source, as_of = min(candidates)
    own = frame[frame["source"] == source]
    values = {
        m: v for m in GENERATION_METRICS if (v := _at(pick_series(own, m), as_of)) is not None
    }
    return _Mix(source, as_of, values, _at(pick_series(own, MetricId.LOAD_ACTUAL), as_of))


def _frequency(frame: pd.DataFrame, ctx: _Context, config: RuleConfig) -> FrequencySummary:
    source = best_source(frame, MetricId.GRID_FREQUENCY)
    series = pick_series(frame, MetricId.GRID_FREQUENCY, source)
    last, last_ts = _last(series)
    current = ctx.value(last, MetricId.GRID_FREQUENCY, last_ts, source, FREQUENCY_STALE)
    if last is None:
        return FrequencySummary(current=current, deviation_mhz=None, status=None, sparkline=[])
    spark = series.iloc[:: max(1, len(series) // SPARKLINE_POINTS)]
    points = [
        FrequencyPoint(ts=t, value=float(v))
        for t, v in zip(
            pd.DatetimeIndex(spark.index).to_pydatetime(), spark.to_numpy(), strict=True
        )
    ]
    return FrequencySummary(
        current=current,
        deviation_mhz=deviation_in_mhz(last),
        status=frequency_status(last, config).value,
        sparkline=points,
    )


def _flows(frame: pd.DataFrame, ctx: _Context) -> tuple[Value, list[FlowOut]]:
    total = frame[frame["area"] == "DE"]
    source = best_source(total, MetricId.FLOW_NET_IMPORT)
    value, ts = _last(pick_series(total, MetricId.FLOW_NET_IMPORT, source))
    net = ctx.value(value, MetricId.FLOW_NET_IMPORT, ts, source)
    borders = frame[frame["area"].astype(str).str.startswith("BORDER:DE:")]
    if borders.empty:
        return net, []
    latest = (
        borders[borders["ts"] == borders["ts"].max()].drop_duplicates("area").sort_values("area")
    )
    flows = [
        FlowOut(neighbour=str(area).rsplit(":", 1)[-1], value=float(v), ts=t)
        for area, v, t in zip(
            latest["area"],
            latest["value"],
            pd.DatetimeIndex(latest["ts"]).to_pydatetime(),
            strict=True,
        )
    ]
    return net, flows


def _price(frame: pd.DataFrame, ctx: _Context) -> Value:
    source = best_source(frame, MetricId.PRICE_DAY_AHEAD)
    series = pick_series(frame, MetricId.PRICE_DAY_AHEAD, source)
    value, ts = _last(series[series.index <= pd.Timestamp(ctx.now)])
    # The day-ahead price of the current interval is current regardless of publication time.
    return ctx.value(value, MetricId.PRICE_DAY_AHEAD, ts, source, PRICE_STALE)


async def build_summary(repo: Repository, now: datetime, config: RuleConfig) -> SummaryNow:
    soon = now + timedelta(minutes=15)
    ctx = _Context(now=now, stale=config.stale_after)
    frame = await fetch_frame(repo, [*GENERATION_METRICS, MetricId.LOAD_ACTUAL], now - WINDOW, soon)
    prices = await fetch_frame(
        repo, [MetricId.PRICE_DAY_AHEAD], now - timedelta(hours=2), soon, areas=["DE-LU"]
    )
    flows = await fetch_frame(repo, [MetricId.FLOW_NET_IMPORT], now - WINDOW, soon, areas=None)
    freq = await fetch_frame(
        repo,
        [MetricId.GRID_FREQUENCY],
        now - timedelta(minutes=60),
        now,
        resolution=QueryResolution.RAW,
    )

    mix = _mix(frame)
    as_of = mix.as_of.to_pydatetime() if mix.as_of is not None else None
    generation = {m.value: ctx.value(v, m, as_of, mix.source) for m, v in mix.values.items()}
    residual = None
    if mix.load is not None:
        residual = residual_load_value(
            mix.load,
            mix.values.get(MetricId.GENERATION_WIND_ONSHORE, 0.0),
            mix.values.get(MetricId.GENERATION_WIND_OFFSHORE, 0.0),
            mix.values.get(MetricId.GENERATION_SOLAR, 0.0),
        )
    derived = f"gridpulse|{mix.source}" if mix.source else None
    price = _price(prices, ctx)
    net_import, flow_list = _flows(flows, ctx)
    frequency = _frequency(freq, ctx, config)

    used = sorted(ctx.sources)
    lic, attr = license_for("|".join(used) or "gridpulse")
    return SummaryNow(
        meta=Meta(source="|".join(used) or "none", license=lic, attribution=attr, generated_at=now),
        as_of=as_of,
        generation=generation,
        load=ctx.value(mix.load, MetricId.LOAD_ACTUAL, as_of, mix.source),
        residual_load=ctx.value(residual, MetricId.LOAD_RESIDUAL, as_of, derived),
        renewable_share=ctx.value(
            renewable_share(mix.values), MetricId.INDICATOR_RENEWABLE_SHARE, as_of, derived
        ),
        co2_intensity=ctx.value(
            co2_intensity(mix.values), MetricId.INDICATOR_CO2_INTENSITY, as_of, derived
        ),
        price=price,
        price_negative=None if price.value is None else price.value < 0,
        net_import=net_import,
        flows=flow_list,
        frequency=frequency,
        sources=[
            Attribution(source=s, license=license_for(s)[0], attribution=license_for(s)[1])
            for s in used
        ],
    )
