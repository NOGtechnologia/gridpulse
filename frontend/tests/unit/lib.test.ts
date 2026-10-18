import { describe, expect, it } from "vitest";
import {
  donutOption,
  groupByMetric,
  linesOption,
  mean,
  mixAreaOption,
  relativeHours,
  sparklineOption,
} from "@/components/charts/options";
import { ApiError, exportUrl, unwrap } from "@/lib/api/client";
import { CARRIERS, carrierColor, GENERATION_METRICS } from "@/lib/carriers";
import { cn } from "@/lib/cn";
import {
  berlinLocalToUtcIso,
  formatAge,
  formatDateTime,
  formatNumber,
  formatTime,
  formatValue,
  unitLabel,
  utcIsoToBerlinLocal,
} from "@/lib/format";

describe("format", () => {
  it("formats numbers per locale with units (spec 8: 1.234,5 MW)", () => {
    expect(formatValue(1234.5, "MW", "de", 1)).toBe("1.234,5 MW");
    expect(formatValue(1234.5, "MW", "en", 1)).toBe("1,234.5 MW");
    expect(formatValue(184.53, "EUR/MWh", "de")).toBe("184,53 €/MWh");
    expect(formatValue(null, "MW", "de")).toBe("–");
    expect(formatValue(Number.NaN, "MW", "de")).toBe("–");
    expect(formatValue(3.21, "unknown", "en")).toBe("3.2 unknown");
    expect(formatNumber(1.5, "de", 2)).toBe("1,50");
    expect(unitLabel("gCO2/kWh")).toBe("g CO₂/kWh");
  });

  it("displays times in Europe/Berlin incl. DST", () => {
    expect(formatDateTime("2026-07-01T10:00:00Z", "de")).toBe("01.07.2026, 12:00");
    expect(formatDateTime("2026-01-01T10:00:00Z", "de")).toBe("01.01.2026, 11:00");
    expect(formatDateTime(new Date("2026-01-01T10:00:05Z"), "en", true)).toContain("11:00:05");
    expect(formatTime("2026-01-01T10:00:00Z", "de")).toBe("11:00");
    expect(formatTime(new Date("2026-07-01T10:00:00Z"), "de")).toBe("12:00");
  });

  it("formats relative ages", () => {
    expect(formatAge(null, "de")).toBe("–");
    expect(formatAge(30, "en")).toContain("30");
    expect(formatAge(600, "en")).toContain("10 min");
    expect(formatAge(7200, "en")).toContain("2 hr");
    expect(formatAge(3 * 86400, "en")).toContain("3 days");
  });

  it("converts Berlin wall clock <-> UTC across DST changes", () => {
    expect(berlinLocalToUtcIso("2026-07-01T12:00")).toBe("2026-07-01T10:00:00Z");
    expect(berlinLocalToUtcIso("2026-01-01T12:00")).toBe("2026-01-01T11:00:00Z");
    expect(berlinLocalToUtcIso("2026-03-29T03:30")).toBe("2026-03-29T01:30:00Z");
    expect(berlinLocalToUtcIso("2026-10-25")).toBe("2026-10-24T22:00:00Z");
    expect(utcIsoToBerlinLocal("2026-07-01T10:00:00Z")).toBe("2026-07-01T12:00");
    expect(utcIsoToBerlinLocal("2026-12-01T10:00:00Z")).toBe("2026-12-01T11:00");
  });
});

describe("carriers", () => {
  it("has one documented colour per generation metric", () => {
    expect(new Set(GENERATION_METRICS).size).toBe(13);
    expect(carrierColor("generation.wind_onshore")).toBe("#0072B2");
    expect(carrierColor("nope")).toBe("#888888");
    expect(CARRIERS.filter((c) => c.renewable)).toHaveLength(6);
  });
});

describe("api helpers", () => {
  it("unwraps or throws", () => {
    expect(unwrap({ data: 1, response: new Response() })).toBe(1);
    expect(() => unwrap({ error: {}, response: new Response(null, { status: 503 }) })).toThrow(
      ApiError,
    );
    expect(exportUrl({ metric: ["a", "b"], format: "csv" })).toBe(
      "/api/v1/export?metric=a&metric=b&format=csv",
    );
  });

  it("merges classes", () => {
    expect(cn("px-2", "px-4", undefined, { hidden: false })).toBe("px-4");
  });
});

describe("chart options", () => {
  const points = [
    { ts: "2026-10-18T00:00:00Z", value: 1 },
    { ts: "2026-10-18T01:00:00Z", value: 3 },
  ];

  it("builds accessible charts with decals", () => {
    const mix = mixAreaOption([{ id: "generation.solar", name: "PV", points }], "de") as Record<
      string,
      never
    >;
    expect(mix.aria).toEqual({ enabled: true, decal: { show: true } });
    const series = (mix.series as unknown as { stack: string; color: string }[])[0];
    expect(series?.stack).toBe("mix");
    expect(series?.color).toBe("#F0E442");
    const donut = donutOption(
      [
        { id: "generation.gas", name: "Gas", value: 5 },
        { id: "generation.oil", name: "Oil", value: 0 },
      ],
      "en",
    ) as { series: { data: unknown[] }[] };
    expect(donut.series[0]?.data).toHaveLength(1);
    const spark = sparklineOption(points, "de") as { yAxis: { min: number } };
    expect(spark.yAxis.min).toBe(49.85);
    const lines = linesOption(
      [{ id: "a", name: "A", points, color: "#fff" }],
      "MW",
      "de",
      undefined,
      {
        dashed: ["a"],
        zoom: true,
        categoryX: true,
      },
    ) as { series: { lineStyle: { type: string }; data: unknown[][] }[]; dataZoom: unknown[] };
    expect(lines.series[0]?.lineStyle.type).toBe("dashed");
    expect(lines.dataZoom).toHaveLength(2);
    expect(linesOption([], "MW", "de")).toMatchObject({ dataZoom: [] });
  });

  it("formats axis labels and tooltips", () => {
    const opt = linesOption([{ id: "a", name: "A", points }], "MW", "de") as {
      xAxis: { axisLabel: { formatter: (v: number) => string } };
      yAxis: { axisLabel: { formatter: (v: number) => string } };
      tooltip: { valueFormatter: (v: unknown) => string };
    };
    expect(opt.xAxis.axisLabel.formatter(Date.parse("2026-01-01T10:00:00Z"))).toContain("11:00");
    expect(opt.yAxis.axisLabel.formatter(1234.5)).toBe("1.234,5");
    expect(opt.tooltip.valueFormatter(2.5)).toBe("2,5 MW");
    expect(opt.tooltip.valueFormatter("x")).toBe("–");
    const donut = donutOption([{ id: "generation.gas", name: "Gas", value: 5 }], "de") as {
      tooltip: { valueFormatter: (v: unknown) => string };
    };
    expect(donut.tooltip.valueFormatter(1500)).toBe("1.500 MW");
  });

  it("groups, aligns and averages", () => {
    const groups = groupByMetric(
      [
        { ts: "t1", metric: "a", value: 1 },
        { ts: "t1", metric: "b", value: 2 },
        { ts: "t2", metric: "a", value: 3 },
      ],
      (m) => m.toUpperCase(),
    );
    expect(groups.map((g) => [g.name, g.points.length])).toEqual([
      ["A", 2],
      ["B", 1],
    ]);
    expect(relativeHours(points).map((p) => p.ts)).toEqual(["0", "1"]);
    expect(relativeHours([])).toEqual([]);
    expect(mean(points)).toBe(2);
    expect(mean([])).toBeNull();
  });
});
