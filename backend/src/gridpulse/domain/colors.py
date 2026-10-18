"""Energy carrier colours (spec 8), documented in docs/ui.md.

Based on the Okabe-Ito colour-blind-safe palette, mapped to common conventions
(wind blue, PV yellow, lignite brown, gas orange). The frontend uses the same
values (frontend/src/lib/carriers.ts); charts additionally use decal patterns and
labels so that information is never conveyed by colour alone.
"""

from __future__ import annotations

from gridpulse.domain.metrics import MetricId

CARRIER_COLORS: dict[MetricId, str] = {
    MetricId.GENERATION_WIND_ONSHORE: "#0072B2",
    MetricId.GENERATION_WIND_OFFSHORE: "#56B4E9",
    MetricId.GENERATION_SOLAR: "#F0E442",
    MetricId.GENERATION_BIOMASS: "#009E73",
    MetricId.GENERATION_HYDRO: "#2CB5A8",
    MetricId.GENERATION_OTHER_RENEWABLE: "#9AD17A",
    MetricId.GENERATION_NUCLEAR: "#CC79A7",
    MetricId.GENERATION_LIGNITE: "#8B5A2B",
    MetricId.GENERATION_HARD_COAL: "#6E6E6E",
    MetricId.GENERATION_GAS: "#E69F00",
    MetricId.GENERATION_OIL: "#D55E00",
    MetricId.GENERATION_PUMPED_STORAGE: "#7B68EE",
    MetricId.GENERATION_OTHER_CONVENTIONAL: "#A9A9A9",
}


def color_of(metric: MetricId) -> str | None:
    return CARRIER_COLORS.get(metric)
