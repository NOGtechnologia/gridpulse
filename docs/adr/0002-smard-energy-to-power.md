# 0002 – SMARD values are energy per interval

* Status: accepted · Date: 2026-10-18

## Context

The spec models generation and load in MW. Live verification showed that SMARD
chart data for generation/load is **MWh per interval** (e.g. 5003.62 MWh per quarter
hour = 20 GW wind onshore; cross-checked against Energy-Charts' MW values).

## Decision

`SmardAdapter.parse()` converts energy to mean power: `MW = MWh / interval_hours`
for all metrics whose canonical unit is MW. Prices are passed through. The contract
test asserts the factor 4 for quarter-hour data and 1 for hourly data.

## Consequences

SMARD and Energy-Charts become directly comparable (cross-check XCHK-001).
