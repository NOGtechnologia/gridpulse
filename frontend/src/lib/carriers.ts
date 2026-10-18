/**
 * Energy carrier colours (spec 8). Same values as backend/src/gridpulse/domain/colors.py,
 * based on the colour-blind-safe Okabe-Ito palette; documented in docs/ui.md. Charts
 * also use decal patterns and text labels so that colour is never the only cue.
 */
export interface Carrier {
  metric: string;
  color: string;
  renewable: boolean;
}

/** Stacking order: base load at the bottom, variable renewables on top. */
export const CARRIERS: readonly Carrier[] = [
  { metric: "generation.nuclear", color: "#CC79A7", renewable: false },
  { metric: "generation.lignite", color: "#8B5A2B", renewable: false },
  { metric: "generation.hard_coal", color: "#6E6E6E", renewable: false },
  { metric: "generation.gas", color: "#E69F00", renewable: false },
  { metric: "generation.oil", color: "#D55E00", renewable: false },
  { metric: "generation.other_conventional", color: "#A9A9A9", renewable: false },
  { metric: "generation.pumped_storage", color: "#7B68EE", renewable: false },
  { metric: "generation.biomass", color: "#009E73", renewable: true },
  { metric: "generation.hydro", color: "#2CB5A8", renewable: true },
  { metric: "generation.other_renewable", color: "#9AD17A", renewable: true },
  { metric: "generation.wind_offshore", color: "#56B4E9", renewable: true },
  { metric: "generation.wind_onshore", color: "#0072B2", renewable: true },
  { metric: "generation.solar", color: "#F0E442", renewable: true },
];

export const GENERATION_METRICS = CARRIERS.map((c) => c.metric);

export function carrierColor(metric: string): string {
  return CARRIERS.find((c) => c.metric === metric)?.color ?? "#888888";
}
