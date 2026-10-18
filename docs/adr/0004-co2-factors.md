# 0004 – CO₂ emission factors

* Status: accepted · Date: 2026-10-18

## Context

The spec asks for a CO₂ intensity with documented factors.

## Decision

Life-cycle medians of **IPCC AR5 WG III, Annex III, Table A.III.2** (2014) for
hard coal 820, gas CC 490, biomass 230, hydro 24, nuclear 12, wind onshore 11,
offshore 12, PV utility 48, geothermal 38 g/kWh. Lignite is not separated in AR5;
GridPulse uses **1100 g/kWh** based on Umweltbundesamt publications for German
lignite plants (≈ 1000–1200 g/kWh). Oil 650 and "other conventional" 700 follow the
open electricityMaps defaults. Pumped storage counts 0 (no double counting). The
intensity is production-based; imports are not attributed.

## Consequences

Values are comparable with common public dashboards but not identical to
consumption-based figures. Factors live in one place (`domain/co2.py`) with sources.
