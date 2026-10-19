/**
 * Country comparison (phase 6): load and day-ahead price per bidding zone from ENTSO-E.
 * Pure helpers, unit-tested; the zone codes mirror ``AREAS`` in backend/adapters/entsoe.py.
 */
import type { Point } from "@/components/charts/options";

export const ZONES = ["DE-LU", "FR", "NL", "BE", "AT", "PL", "CZ", "CH", "DK1"] as const;
export type Zone = (typeof ZONES)[number];

export interface Row {
  ts: string;
  metric: string;
  area: string;
  source: string;
  unit: string;
  value: number;
}

export interface Latest {
  value: number;
  ts: string;
  unit: string;
  source: string;
}

export interface ZoneSummary {
  zone: string;
  load: Latest | null;
  price: Latest | null;
  priceMean: number | null;
  loadPoints: Point[];
  pricePoints: Point[];
}

/** Newest value not after ``now`` (day-ahead prices reach into tomorrow). */
export function latestAt(rows: Row[], now: Date): Latest | null {
  let best: Row | null = null;
  const limit = now.getTime();
  for (const row of rows) {
    const t = new Date(row.ts).getTime();
    if (t <= limit && (best === null || t > new Date(best.ts).getTime())) best = row;
  }
  return best ? { value: best.value, ts: best.ts, unit: best.unit, source: best.source } : null;
}

function points(rows: Row[]): Point[] {
  return rows
    .map((r) => ({ ts: r.ts, value: r.value }))
    .sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime());
}

/** Group long-format observations per zone; zones without data are kept (empty). */
export function summarize(rows: Row[], now: Date): ZoneSummary[] {
  return ZONES.map((zone) => {
    const own = rows.filter((r) => r.area === zone);
    const load = own.filter((r) => r.metric === "load.actual");
    const price = own.filter((r) => r.metric === "price.day_ahead");
    const priceMean =
      price.length > 0 ? price.reduce((sum, r) => sum + r.value, 0) / price.length : null;
    return {
      zone,
      load: latestAt(load, now),
      price: latestAt(price, now),
      priceMean,
      loadPoints: points(load),
      pricePoints: points(price),
    };
  });
}

/** Seconds between a data timestamp and ``now`` (for "Datenstand: vor X min"). */
export function ageSeconds(ts: string, now: Date): number {
  return Math.max(0, (now.getTime() - new Date(ts).getTime()) / 1000);
}
