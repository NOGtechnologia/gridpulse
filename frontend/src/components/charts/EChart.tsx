"use client";

import { useEffect, useRef } from "react";
import type { EChartsCoreOption } from "echarts/core";

type ECharts = import("echarts/core").EChartsType;

/** Lazily loads a tree-shaken ECharts build so the initial bundle stays small. */
async function loadEcharts(): Promise<typeof import("echarts/core")> {
  const [core, charts, components, renderers] = await Promise.all([
    import("echarts/core"),
    import("echarts/charts"),
    import("echarts/components"),
    import("echarts/renderers"),
  ]);
  core.use([
    charts.LineChart,
    charts.PieChart,
    charts.BarChart,
    components.GridComponent,
    components.TooltipComponent,
    components.LegendComponent,
    components.AriaComponent,
    components.MarkAreaComponent,
    components.MarkLineComponent,
    components.DataZoomComponent,
    renderers.SVGRenderer,
  ]);
  return core;
}

export function EChart({
  option,
  height = 260,
  label,
  className,
}: {
  option: EChartsCoreOption;
  height?: number;
  /** Accessible description of the chart. */
  label: string;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<ECharts | null>(null);
  const latest = useRef(option);
  latest.current = option;

  // The chart instance is created once; option updates are applied by the next effect.
  useEffect(() => {
    let disposed = false;
    let observer: ResizeObserver | undefined;
    void loadEcharts().then((echarts) => {
      if (disposed || !ref.current) return;
      const instance = echarts.init(ref.current, undefined, { renderer: "svg" });
      instance.setOption(latest.current, { notMerge: true });
      chart.current = instance;
      observer = new ResizeObserver(() => {
        instance.resize();
      });
      observer.observe(ref.current);
    });
    return () => {
      disposed = true;
      observer?.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption(option, { notMerge: true });
  }, [option]);

  return (
    <div
      ref={ref}
      role="img"
      aria-label={label}
      className={className}
      style={{ height, width: "100%" }}
    />
  );
}
