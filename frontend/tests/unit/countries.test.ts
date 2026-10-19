import { describe, expect, it } from "vitest";
import { ageSeconds, latestAt, summarize, ZONES, type Row } from "@/lib/countries";

const NOW = new Date("2026-10-18T12:30:00Z");

function row(area: string, metric: string, ts: string, value: number): Row {
  return {
    ts,
    metric,
    area,
    source: "entsoe",
    unit: metric === "load.actual" ? "MW" : "EUR/MWh",
    value,
  };
}

describe("countries", () => {
  it("covers the backend ENTSO-E bidding zones", () => {
    expect(ZONES).toEqual(["DE-LU", "FR", "NL", "BE", "AT", "PL", "CZ", "CH", "DK1"]);
  });

  it("latestAt ignores values after now (day-ahead prices for tomorrow)", () => {
    const rows = [
      row("FR", "price.day_ahead", "2026-10-18T11:00:00Z", 80),
      row("FR", "price.day_ahead", "2026-10-18T12:00:00Z", 90),
      row("FR", "price.day_ahead", "2026-10-19T12:00:00Z", 999),
    ];
    expect(latestAt(rows, NOW)).toEqual({
      value: 90,
      ts: "2026-10-18T12:00:00Z",
      unit: "EUR/MWh",
      source: "entsoe",
    });
    expect(latestAt([], NOW)).toBeNull();
    expect(latestAt([rows[2] as Row], NOW)).toBeNull();
  });

  it("summarize groups per zone, keeps empty zones and sorts points", () => {
    const rows = [
      row("FR", "load.actual", "2026-10-18T12:00:00Z", 52000),
      row("FR", "load.actual", "2026-10-18T11:00:00Z", 51000),
      row("FR", "price.day_ahead", "2026-10-18T12:00:00Z", -10),
      row("FR", "price.day_ahead", "2026-10-18T13:00:00Z", 30),
      row("XX", "load.actual", "2026-10-18T12:00:00Z", 1),
    ];
    const out = summarize(rows, NOW);
    expect(out.map((z) => z.zone)).toEqual([...ZONES]);
    const fr = out.find((z) => z.zone === "FR");
    expect(fr?.load?.value).toBe(52000);
    expect(fr?.price?.value).toBe(-10);
    expect(fr?.priceMean).toBe(10);
    expect(fr?.loadPoints.map((p) => p.value)).toEqual([51000, 52000]);
    const at = out.find((z) => z.zone === "AT");
    expect(at).toMatchObject({ load: null, price: null, priceMean: null, loadPoints: [] });
  });

  it("ageSeconds is never negative", () => {
    expect(ageSeconds("2026-10-18T12:00:00Z", NOW)).toBe(1800);
    expect(ageSeconds("2026-10-19T12:00:00Z", NOW)).toBe(0);
  });
});
