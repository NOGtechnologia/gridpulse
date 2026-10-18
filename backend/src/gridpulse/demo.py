"""Synthetic, realistic-looking demo data (GRIDPULSE_DEMO=1, spec 9).

Lets screenshots and E2E tests run without internet. Deterministic for a given
``now`` and ``seed``. All series are labelled with source ``demo`` (CC0) so they can
never be confused with real data.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from gridpulse.adapters.energy_charts import border_area
from gridpulse.adapters.open_meteo import DEFAULT_LOCATIONS, weather_area
from gridpulse.domain.metrics import Kind, MetricId
from gridpulse.domain.observations import concat_frames, make_frame
from gridpulse.domain.solar import solar_elevation_deg
from gridpulse.domain.timeutils import BERLIN, floor_to

SOURCE = "demo"
Q = timedelta(minutes=15)
BORDER_SHARES = {
    "AT": -0.25,
    "CH": -0.15,
    "CZ": 0.05,
    "DK": 0.3,
    "FR": 0.25,
    "NL": 0.2,
    "NO": 0.15,
    "PL": -0.05,
    "SE": 0.05,
    "BE": 0.1,
    "LU": -0.05,
}


def _smooth_noise(rng: np.random.Generator, n: int, phi: float, sigma: float) -> np.ndarray:
    out = np.zeros(n)
    for i in range(1, n):
        out[i] = phi * out[i - 1] + rng.normal(0, sigma)
    return out


def _frame(
    index: pd.DatetimeIndex,
    values: np.ndarray,
    metric: MetricId,
    kind: Kind = Kind.ACTUAL,
    area: str = "DE",
    resolution: timedelta = Q,
) -> pd.DataFrame:
    return make_frame(
        timestamps=list(index.to_pydatetime()),
        values=[float(v) for v in values],
        metric=metric,
        area=area,
        kind=kind,
        source=SOURCE,
        resolution=resolution,
    )


def _profiles(index: pd.DatetimeIndex, rng: np.random.Generator) -> dict[str, np.ndarray]:
    local = index.tz_convert(BERLIN)
    hour = local.hour.to_numpy() + local.minute.to_numpy() / 60
    weekend = (local.dayofweek.to_numpy() >= 5).astype(float)
    n = len(index)
    load = (
        55_000
        + 9_000 * np.sin((hour - 6) / 24 * 2 * np.pi)
        + 3_000 * np.sin((hour - 9) / 12 * 2 * np.pi)
        - 7_000 * weekend
        + _smooth_noise(rng, n, 0.97, 250)
    )
    elevation = np.array([solar_elevation_deg(t) for t in index.to_pydatetime()])
    daily_clear = np.repeat(rng.uniform(0.25, 1.0, n // 96 + 2), 96)[:n]
    solar = 38_000 * daily_clear * np.clip(np.sin(np.radians(elevation)), 0, None) ** 1.2
    wind_base = 18_000 + _smooth_noise(rng, n, 0.995, 600)
    wind_on = np.clip(wind_base, 1_500, 48_000)
    wind_off = np.clip(0.18 * wind_on + _smooth_noise(rng, n, 0.99, 120), 200, 8_000)
    return {"load": load, "solar": solar, "wind_on": wind_on, "wind_off": wind_off}


def _dispatch(p: dict[str, np.ndarray], rng: np.random.Generator) -> dict[MetricId, np.ndarray]:
    n = len(p["load"])
    biomass = 4_300 + _smooth_noise(rng, n, 0.99, 15)
    hydro = 1_600 + _smooth_noise(rng, n, 0.99, 20)
    other_ren = np.full(n, 160.0)
    residual = p["load"] - p["wind_on"] - p["wind_off"] - p["solar"]
    remaining = residual - biomass - hydro - other_ren
    lignite = np.clip(4_500 + 0.35 * remaining, 3_500, 15_500)
    hard_coal = np.clip(0.15 * (remaining - 8_000), 600, 9_000)
    pumped = np.clip(0.1 * (remaining - 20_000), 0, 6_000)
    pumped_consumption = np.clip(-0.15 * remaining, 0, 6_500)
    other_conv = np.full(n, 1_900.0)
    oil = np.full(n, 300.0)
    gas_target = remaining - lignite - hard_coal - pumped - other_conv - oil
    gas = np.clip(gas_target * 0.85, 2_000, 25_000)
    supply = biomass + hydro + other_ren + lignite + hard_coal + pumped + other_conv + oil + gas
    supply = supply + p["wind_on"] + p["wind_off"] + p["solar"]
    net_import = p["load"] + pumped_consumption - supply
    return {
        MetricId.GENERATION_WIND_ONSHORE: p["wind_on"],
        MetricId.GENERATION_WIND_OFFSHORE: p["wind_off"],
        MetricId.GENERATION_SOLAR: p["solar"],
        MetricId.GENERATION_BIOMASS: biomass,
        MetricId.GENERATION_HYDRO: hydro,
        MetricId.GENERATION_OTHER_RENEWABLE: other_ren,
        MetricId.GENERATION_LIGNITE: lignite,
        MetricId.GENERATION_HARD_COAL: hard_coal,
        MetricId.GENERATION_GAS: gas,
        MetricId.GENERATION_OIL: oil,
        MetricId.GENERATION_PUMPED_STORAGE: pumped,
        MetricId.GENERATION_OTHER_CONVENTIONAL: other_conv,
        MetricId.CONSUMPTION_PUMPED_STORAGE: pumped_consumption,
        MetricId.LOAD_ACTUAL: p["load"],
        MetricId.LOAD_RESIDUAL: residual,
        MetricId.FLOW_NET_IMPORT: net_import,
    }


def _price(residual: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    base = 25 + 3.2 * residual / 1_000 + _smooth_noise(rng, len(residual), 0.9, 4)
    spikes = np.where(residual > 45_000, (residual - 45_000) / 30, 0)
    return np.asarray(np.round(base + spikes, 2), dtype=float)


def generate(
    now: datetime, *, days: int = 14, horizon_hours: int = 48, seed: int = 20260101
) -> pd.DataFrame:
    """History of ``days`` days up to ``now`` plus forecasts for ``horizon_hours``."""
    rng = np.random.default_rng(seed)
    end = floor_to(now, Q)
    hist = pd.date_range(end - timedelta(days=days), end, freq="15min", inclusive="left")
    future = pd.date_range(
        end - timedelta(hours=24),
        end + timedelta(hours=horizon_hours),
        freq="15min",
        inclusive="left",
    )
    full = hist.union(future)
    profiles = _profiles(full, rng)
    hist_mask = full.isin(hist)
    frames: list[pd.DataFrame] = []

    dispatch = _dispatch(profiles, rng)
    for metric, values in dispatch.items():
        frames.append(_frame(hist, values[hist_mask], metric))
    for code, share in BORDER_SHARES.items():
        frames.append(
            _frame(
                hist,
                dispatch[MetricId.FLOW_NET_IMPORT][hist_mask] * share + 900 * np.sign(share),
                MetricId.FLOW_NET_IMPORT,
                area=border_area("DE", code),
            )
        )

    fc_mask = full.isin(future)
    for metric, key, noise in (
        (MetricId.LOAD_ACTUAL, "load", 0.02),
        (MetricId.GENERATION_SOLAR, "solar", 0.08),
        (MetricId.GENERATION_WIND_ONSHORE, "wind_on", 0.10),
        (MetricId.GENERATION_WIND_OFFSHORE, "wind_off", 0.10),
    ):
        err = 1 + _smooth_noise(rng, int(fc_mask.sum()), 0.98, noise / 5)
        frames.append(
            _frame(future, np.clip(profiles[key][fc_mask] * err, 0, None), metric, Kind.FORECAST)
        )
    fc_res = profiles["load"] - profiles["wind_on"] - profiles["wind_off"] - profiles["solar"]
    frames.append(_frame(future, fc_res[fc_mask], MetricId.LOAD_RESIDUAL, Kind.FORECAST))

    # Day-ahead prices are known up to the end of the next day.
    price_mask = hist_mask | fc_mask
    price_index = full[price_mask]
    frames.append(
        _frame(price_index, _price(fc_res[price_mask], rng), MetricId.PRICE_DAY_AHEAD, area="DE-LU")
    )

    freq_index = pd.date_range(end - timedelta(hours=2), end, freq="10s", inclusive="left")
    freq = 50 + _smooth_noise(rng, len(freq_index), 0.98, 0.004)
    frames.append(
        _frame(
            freq_index,
            np.round(np.clip(freq, 49.85, 50.15), 4),
            MetricId.GRID_FREQUENCY,
            resolution=timedelta(seconds=10),
        )
    )

    weather_index = pd.date_range(
        floor_to(now, timedelta(hours=1)) - timedelta(hours=24),
        floor_to(now, timedelta(hours=1)) + timedelta(hours=horizon_hours),
        freq="1h",
    )
    hours = weather_index.hour.to_numpy()
    for loc in DEFAULT_LOCATIONS:
        area = weather_area(loc.name)
        temp = 11 + 5 * np.sin((hours - 9) / 24 * 2 * np.pi) + rng.normal(0, 0.5, len(hours))
        wind = np.clip(22 + _smooth_noise(rng, len(hours), 0.95, 2.5), 0, None)
        rad = np.array(
            [
                max(0.0, 800 * np.sin(np.radians(solar_elevation_deg(t, loc.lat, loc.lon))))
                for t in weather_index.to_pydatetime()
            ]
        )
        cloud = np.clip(55 + _smooth_noise(rng, len(hours), 0.9, 8), 0, 100)
        for metric, values in (
            (MetricId.WEATHER_TEMPERATURE, temp),
            (MetricId.WEATHER_WIND_SPEED_100M, wind),
            (MetricId.WEATHER_SHORTWAVE_RADIATION, rad),
            (MetricId.WEATHER_CLOUD_COVER, cloud),
        ):
            frames.append(
                _frame(
                    weather_index,
                    values,
                    metric,
                    Kind.FORECAST,
                    area=area,
                    resolution=timedelta(hours=1),
                )
            )
    return concat_frames(frames)
