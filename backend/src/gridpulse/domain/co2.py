"""CO2 intensity of electricity generation.

Emission factors are life-cycle values in gCO2-eq/kWh. Sources:

* IPCC AR5 WG III (2014), Annex III, Table A.III.2, median life-cycle values
  (Schlömer et al.): hard coal 820, gas (combined cycle) 490, biomass (dedicated) 230,
  hydro 24, nuclear 12, wind onshore 11, wind offshore 12, solar PV (utility) 48,
  geothermal 38. https://www.ipcc.ch/report/ar5/wg3/
* Lignite is not listed separately in AR5. GridPulse uses 1100 g/kWh as an
  approximation of German lignite plants (Umweltbundesamt, "Entwicklung der
  spezifischen Treibhausgas-Emissionen des deutschen Strommix", reports direct
  emissions of roughly 1000-1200 g/kWh for lignite). See docs/adr/0004-co2-factors.md.
* Oil (650) and "other conventional" (700) follow the defaults used by the open
  electricityMaps methodology for oil and unknown sources.
* Pumped storage is set to 0: the energy was already accounted for when it was
  generated; counting it again would double-count emissions.

Intensity is generation-based (production mix), not consumption-based: imports
are not attributed.
"""

from __future__ import annotations

from collections.abc import Mapping

from gridpulse.domain.metrics import GENERATION_METRICS, MetricId

EMISSION_FACTORS_G_PER_KWH: Mapping[MetricId, float] = {
    MetricId.GENERATION_WIND_ONSHORE: 11.0,
    MetricId.GENERATION_WIND_OFFSHORE: 12.0,
    MetricId.GENERATION_SOLAR: 48.0,
    MetricId.GENERATION_BIOMASS: 230.0,
    MetricId.GENERATION_HYDRO: 24.0,
    MetricId.GENERATION_OTHER_RENEWABLE: 38.0,
    MetricId.GENERATION_NUCLEAR: 12.0,
    MetricId.GENERATION_LIGNITE: 1100.0,
    MetricId.GENERATION_HARD_COAL: 820.0,
    MetricId.GENERATION_GAS: 490.0,
    MetricId.GENERATION_OIL: 650.0,
    MetricId.GENERATION_PUMPED_STORAGE: 0.0,
    MetricId.GENERATION_OTHER_CONVENTIONAL: 700.0,
}

if set(EMISSION_FACTORS_G_PER_KWH) != set(GENERATION_METRICS):  # pragma: no cover - invariant
    raise RuntimeError("every generation metric needs an emission factor")


def co2_intensity(mix_mw: Mapping[MetricId, float]) -> float | None:
    """Weighted CO2 intensity in gCO2/kWh for a generation mix in MW.

    Unknown or non-generation metrics are ignored; negative values are clipped to 0.
    Returns ``None`` if total generation is zero (intensity undefined).
    """
    total = 0.0
    weighted = 0.0
    for metric, value in mix_mw.items():
        factor = EMISSION_FACTORS_G_PER_KWH.get(metric)
        if factor is None:
            continue
        mw = max(value, 0.0)
        total += mw
        weighted += mw * factor
    if total <= 0.0:
        return None
    return weighted / total
