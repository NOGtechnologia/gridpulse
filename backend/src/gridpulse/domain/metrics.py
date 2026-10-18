"""Canonical metric catalogue.

Every series stored by GridPulse is identified by a :class:`MetricId`. The catalogue
fixes the unit of each metric so that units are never implicit (spec 5.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Unit(StrEnum):
    MW = "MW"
    EUR_PER_MWH = "EUR/MWh"
    HZ = "Hz"
    G_CO2_PER_KWH = "gCO2/kWh"
    PERCENT = "%"
    CELSIUS = "degC"
    KMH = "km/h"
    W_PER_M2 = "W/m2"


class Kind(StrEnum):
    ACTUAL = "actual"
    FORECAST = "forecast"


class Category(StrEnum):
    GENERATION = "generation"
    LOAD = "load"
    PRICE = "price"
    GRID = "grid"
    FLOW = "flow"
    INDICATOR = "indicator"
    WEATHER = "weather"


class MetricId(StrEnum):
    GENERATION_WIND_ONSHORE = "generation.wind_onshore"
    GENERATION_WIND_OFFSHORE = "generation.wind_offshore"
    GENERATION_SOLAR = "generation.solar"
    GENERATION_BIOMASS = "generation.biomass"
    GENERATION_HYDRO = "generation.hydro"
    GENERATION_OTHER_RENEWABLE = "generation.other_renewable"
    GENERATION_NUCLEAR = "generation.nuclear"
    GENERATION_LIGNITE = "generation.lignite"
    GENERATION_HARD_COAL = "generation.hard_coal"
    GENERATION_GAS = "generation.gas"
    GENERATION_OIL = "generation.oil"
    GENERATION_PUMPED_STORAGE = "generation.pumped_storage"
    GENERATION_OTHER_CONVENTIONAL = "generation.other_conventional"
    CONSUMPTION_PUMPED_STORAGE = "consumption.pumped_storage"
    LOAD_ACTUAL = "load.actual"
    LOAD_RESIDUAL = "load.residual"
    PRICE_DAY_AHEAD = "price.day_ahead"
    GRID_FREQUENCY = "grid.frequency"
    FLOW_NET_IMPORT = "flow.net_import"
    INDICATOR_RENEWABLE_SHARE = "indicator.renewable_share"
    INDICATOR_CO2_INTENSITY = "indicator.co2_intensity"
    WEATHER_TEMPERATURE = "weather.temperature_2m"
    WEATHER_WIND_SPEED_100M = "weather.wind_speed_100m"
    WEATHER_SHORTWAVE_RADIATION = "weather.shortwave_radiation"
    WEATHER_CLOUD_COVER = "weather.cloud_cover"


@dataclass(frozen=True, slots=True)
class MetricInfo:
    unit: Unit
    category: Category
    renewable: bool = False
    may_be_negative: bool = False


_G = Category.GENERATION
CATALOG: dict[MetricId, MetricInfo] = {
    MetricId.GENERATION_WIND_ONSHORE: MetricInfo(Unit.MW, _G, renewable=True),
    MetricId.GENERATION_WIND_OFFSHORE: MetricInfo(Unit.MW, _G, renewable=True),
    MetricId.GENERATION_SOLAR: MetricInfo(Unit.MW, _G, renewable=True),
    MetricId.GENERATION_BIOMASS: MetricInfo(Unit.MW, _G, renewable=True),
    MetricId.GENERATION_HYDRO: MetricInfo(Unit.MW, _G, renewable=True),
    MetricId.GENERATION_OTHER_RENEWABLE: MetricInfo(Unit.MW, _G, renewable=True),
    MetricId.GENERATION_NUCLEAR: MetricInfo(Unit.MW, _G),
    MetricId.GENERATION_LIGNITE: MetricInfo(Unit.MW, _G),
    MetricId.GENERATION_HARD_COAL: MetricInfo(Unit.MW, _G),
    MetricId.GENERATION_GAS: MetricInfo(Unit.MW, _G),
    MetricId.GENERATION_OIL: MetricInfo(Unit.MW, _G),
    MetricId.GENERATION_PUMPED_STORAGE: MetricInfo(Unit.MW, _G),
    MetricId.GENERATION_OTHER_CONVENTIONAL: MetricInfo(Unit.MW, _G),
    # Pumped-storage consumption is modelled explicitly as a separate, non-negative
    # metric (spec 7.4); it is never mixed into the generation sum.
    MetricId.CONSUMPTION_PUMPED_STORAGE: MetricInfo(Unit.MW, Category.LOAD),
    MetricId.LOAD_ACTUAL: MetricInfo(Unit.MW, Category.LOAD),
    MetricId.LOAD_RESIDUAL: MetricInfo(Unit.MW, Category.LOAD, may_be_negative=True),
    MetricId.PRICE_DAY_AHEAD: MetricInfo(Unit.EUR_PER_MWH, Category.PRICE, may_be_negative=True),
    MetricId.GRID_FREQUENCY: MetricInfo(Unit.HZ, Category.GRID),
    # Positive = import into the area, negative = export.
    MetricId.FLOW_NET_IMPORT: MetricInfo(Unit.MW, Category.FLOW, may_be_negative=True),
    MetricId.INDICATOR_RENEWABLE_SHARE: MetricInfo(Unit.PERCENT, Category.INDICATOR),
    MetricId.INDICATOR_CO2_INTENSITY: MetricInfo(Unit.G_CO2_PER_KWH, Category.INDICATOR),
    MetricId.WEATHER_TEMPERATURE: MetricInfo(Unit.CELSIUS, Category.WEATHER, may_be_negative=True),
    MetricId.WEATHER_WIND_SPEED_100M: MetricInfo(Unit.KMH, Category.WEATHER),
    MetricId.WEATHER_SHORTWAVE_RADIATION: MetricInfo(Unit.W_PER_M2, Category.WEATHER),
    MetricId.WEATHER_CLOUD_COVER: MetricInfo(Unit.PERCENT, Category.WEATHER),
}

GENERATION_METRICS: tuple[MetricId, ...] = tuple(
    m for m, info in CATALOG.items() if info.category is Category.GENERATION
)
RENEWABLE_METRICS: frozenset[MetricId] = frozenset(m for m, i in CATALOG.items() if i.renewable)
WIND_METRICS: frozenset[MetricId] = frozenset(
    {MetricId.GENERATION_WIND_ONSHORE, MetricId.GENERATION_WIND_OFFSHORE}
)
VARIABLE_RENEWABLE_METRICS: frozenset[MetricId] = WIND_METRICS | {MetricId.GENERATION_SOLAR}


def unit_of(metric: MetricId) -> Unit:
    """Return the canonical unit of ``metric``."""
    return CATALOG[metric].unit


def may_be_negative(metric: MetricId) -> bool:
    """Whether negative values are physically meaningful for ``metric``."""
    return CATALOG[metric].may_be_negative
