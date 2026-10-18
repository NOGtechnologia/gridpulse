# UI guidelines

* Calm, factual, control-room suitable. **Dark theme by default**, light theme via
  the header toggle (stored per browser). Kiosk (`/de/kiosk`) forces a black,
  high-contrast theme and refreshes every 30 s.
* Every number shows **unit, data timestamp ("Datenstand: vor X min") and source**
  in the tile footer; stale data is greyed out and marked "Veraltet" (with text).
* Status is never conveyed by colour alone: badges carry text and a shape
  (● ▲ ■), flow directions use arrows and words, charts use ECharts decal
  patterns plus legends/labels and an accessible data table where useful.
* Numbers use the locale (`1.234,5 MW` in German), times are shown in Europe/Berlin.
* Every tile has loading (skeleton), error (with retry) and empty states.
* Full keyboard support: skip link, visible focus ring, native controls.

## Energy carrier colours

Okabe-Ito based, colour-blind safe; identical in `backend/src/gridpulse/domain/colors.py`
and `frontend/src/lib/carriers.ts`.

| Carrier | Colour |
|---|---|
| Wind onshore | `#0072B2` blue |
| Wind offshore | `#56B4E9` sky blue |
| Solar PV | `#F0E442` yellow |
| Biomass | `#009E73` green |
| Hydro | `#2CB5A8` teal |
| Other renewables | `#9AD17A` light green |
| Nuclear | `#CC79A7` reddish purple |
| Lignite | `#8B5A2B` brown |
| Hard coal | `#6E6E6E` grey |
| Natural gas | `#E69F00` orange |
| Oil | `#D55E00` vermilion |
| Pumped storage | `#7B68EE` slate blue |
| Other conventional | `#A9A9A9` light grey |
