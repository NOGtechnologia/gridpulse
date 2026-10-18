/**
 * Pure ECharts option builders (unit-tested). Charts enable ARIA descriptions and
 * decal patterns so that series are distinguishable without colour (spec 8).
 */
import type { EChartsCoreOption } from "echarts/core";
import { carrierColor } from "@/lib/carriers";
import { TIME_ZONE } from "@/lib/format";

export interface ChartTheme {
  fg: string;
  muted: string;
  border: string;
}

export const DEFAULT_THEME: ChartTheme = { fg: "#e6edf3", muted: "#a0aab6", border: "#30363d" };

export interface Point {
  ts: string;
  value: number;
}

export interface NamedSeries {
  id: string;
  name: string;
  points: Point[];
  color?: string;
}

function axisTime(theme: ChartTheme, locale: string): Record<string, unknown> {
  const fmt = new Intl.DateTimeFormat(locale, {
    timeZone: TIME_ZONE,
    hour: "2-digit",
    minute: "2-digit",
    day: "2-digit",
    month: "2-digit",
  });
  return {
    type: "time",
    axisLabel: {
      color: theme.muted,
      formatter: (v: number) => fmt.format(new Date(v)),
      hideOverlap: true,
    },
    axisLine: { lineStyle: { color: theme.border } },
    splitLine: { show: false },
  };
}

function axisValue(theme: ChartTheme, unit: string, locale: string): Record<string, unknown> {
  const nf = new Intl.NumberFormat(locale, { maximumFractionDigits: 3 });
  return {
    type: "value",
    name: unit,
    nameTextStyle: { color: theme.muted },
    scale: true,
    axisLabel: { color: theme.muted, formatter: (v: number) => nf.format(v) },
    splitLine: { lineStyle: { color: theme.border, opacity: 0.4 } },
  };
}

function tooltip(unit: string, locale: string): Record<string, unknown> {
  const nf = new Intl.NumberFormat(locale, { maximumFractionDigits: 2 });
  return {
    trigger: "axis",
    valueFormatter: (v: unknown) => (typeof v === "number" ? `${nf.format(v)} ${unit}` : "–"),
  };
}

const ARIA = { enabled: true, decal: { show: true } };

/** Stacked area of the generation mix in MW. */
export function mixAreaOption(
  series: NamedSeries[],
  locale: string,
  theme: ChartTheme = DEFAULT_THEME,
): EChartsCoreOption {
  return {
    aria: ARIA,
    animation: false,
    grid: { left: 56, right: 16, top: 16, bottom: 72 },
    tooltip: tooltip("MW", locale),
    legend: { bottom: 0, type: "scroll", textStyle: { color: theme.fg } },
    xAxis: axisTime(theme, locale),
    yAxis: axisValue(theme, "MW", locale),
    series: series.map((s) => ({
      id: s.id,
      name: s.name,
      type: "line",
      stack: "mix",
      areaStyle: { opacity: 0.85 },
      lineStyle: { width: 0.5 },
      showSymbol: false,
      color: s.color ?? carrierColor(s.id),
      data: s.points.map((p) => [p.ts, p.value]),
    })),
  };
}

/** Donut of the current mix with labels in the legend (not colour only). */
export function donutOption(
  slices: { id: string; name: string; value: number }[],
  locale: string,
  theme: ChartTheme = DEFAULT_THEME,
): EChartsCoreOption {
  const nf = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 });
  return {
    aria: ARIA,
    animation: false,
    tooltip: { trigger: "item", valueFormatter: (v: unknown) => `${nf.format(Number(v))} MW` },
    legend: { show: false },
    series: [
      {
        type: "pie",
        radius: ["45%", "75%"],
        label: { color: theme.fg, formatter: "{b}: {d}%", fontSize: 11 },
        data: slices
          .filter((s) => s.value > 0)
          .map((s) => ({ name: s.name, value: s.value, itemStyle: { color: carrierColor(s.id) } })),
      },
    ],
  };
}

/** Frequency sparkline with the ±50/±100 mHz bands. */
export function sparklineOption(
  points: Point[],
  locale: string,
  theme: ChartTheme = DEFAULT_THEME,
): EChartsCoreOption {
  return {
    aria: ARIA,
    animation: false,
    grid: { left: 48, right: 8, top: 8, bottom: 24 },
    tooltip: tooltip("Hz", locale),
    xAxis: axisTime(theme, locale),
    yAxis: { ...axisValue(theme, "Hz", locale), min: 49.85, max: 50.15, name: "" },
    series: [
      {
        type: "line",
        name: "Hz",
        showSymbol: false,
        lineStyle: { width: 1.5 },
        color: theme.fg,
        data: points.map((p) => [p.ts, p.value]),
        markArea: {
          silent: true,
          data: [
            [{ yAxis: 49.95, itemStyle: { color: "rgba(63,185,80,0.12)" } }, { yAxis: 50.05 }],
          ],
        },
        markLine: {
          silent: true,
          symbol: "none",
          lineStyle: { type: "dashed", color: theme.muted },
          data: [{ yAxis: 49.9 }, { yAxis: 50.1 }],
          label: { show: false },
        },
      },
    ],
  };
}

/** Generic multi-line chart (forecast, history, comparison). */
export function linesOption(
  series: NamedSeries[],
  unit: string,
  locale: string,
  theme: ChartTheme = DEFAULT_THEME,
  options: { dashed?: string[]; zoom?: boolean; categoryX?: boolean } = {},
): EChartsCoreOption {
  const dashed = new Set(options.dashed ?? []);
  return {
    aria: ARIA,
    animation: false,
    grid: { left: 64, right: 16, top: 16, bottom: options.zoom ? 96 : 56 },
    tooltip: tooltip(unit, locale),
    legend: { bottom: options.zoom ? 40 : 0, textStyle: { color: theme.fg } },
    xAxis: options.categoryX
      ? { type: "value", name: "h", axisLabel: { color: theme.muted } }
      : axisTime(theme, locale),
    yAxis: axisValue(theme, unit, locale),
    dataZoom: options.zoom ? [{ type: "inside" }, { type: "slider", bottom: 8 }] : [],
    series: series.map((s) => ({
      id: s.id,
      name: s.name,
      type: "line",
      showSymbol: false,
      lineStyle: { width: 2, type: dashed.has(s.id) ? "dashed" : "solid" },
      ...(s.color ? { color: s.color } : {}),
      data: s.points.map((p) => [options.categoryX ? Number(p.ts) : p.ts, p.value]),
    })),
  };
}

/** Group long-format observations into one series per metric. */
export function groupByMetric(
  rows: { ts: string; metric: string; value: number }[],
  label: (metric: string) => string,
): NamedSeries[] {
  const map = new Map<string, Point[]>();
  for (const row of rows) {
    const list = map.get(row.metric) ?? [];
    list.push({ ts: row.ts, value: row.value });
    map.set(row.metric, list);
  }
  return [...map.entries()].map(([id, points]) => ({ id, name: label(id), points }));
}

/** Align a comparison period on "hours since period start" so both can share an axis. */
export function relativeHours(points: Point[]): Point[] {
  const first = points[0];
  if (!first) return [];
  const t0 = new Date(first.ts).getTime();
  return points.map((p) => ({
    ts: String((new Date(p.ts).getTime() - t0) / 3_600_000),
    value: p.value,
  }));
}

export function mean(points: Point[]): number | null {
  if (points.length === 0) return null;
  return points.reduce((sum, p) => sum + p.value, 0) / points.length;
}
