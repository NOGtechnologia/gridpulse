"use client";

import dynamic from "next/dynamic";
import { useLocale, useTranslations } from "next-intl";
import { useMemo } from "react";
import { EChart } from "@/components/charts/EChart";
import { groupByMetric, mixAreaOption } from "@/components/charts/options";
import { Tile } from "@/components/Tile";
import { api, unwrap, type MetricId, type SummaryNow } from "@/lib/api/client";
import { CARRIERS, GENERATION_METRICS } from "@/lib/carriers";
import { formatDateTime } from "@/lib/format";
import { useChartTheme } from "@/lib/theme";
import { usePolling } from "@/lib/usePolling";
import { FlowsTable } from "./FlowsMap";
import {
  FrequencyTile,
  licenseFor,
  MixDonutTile,
  PriceTile,
  provenanceOf,
  ValueTile,
} from "./tiles";

const FlowsMap = dynamic(() => import("./FlowsMap").then((m) => m.FlowsMap), { ssr: false });

export const SUMMARY_INTERVAL_MS = 60_000;

export function useSummary(intervalMs = SUMMARY_INTERVAL_MS) {
  return usePolling<SummaryNow>(
    async (signal) => unwrap(await api.GET("/api/v1/summary/now", { signal })),
    intervalMs,
  );
}

function MixAreaTile({ summary }: { summary: SummaryNow | undefined }) {
  const t = useTranslations();
  const locale = useLocale();
  const theme = useChartTheme();
  const mixSource = summary ? (Object.values(summary.generation)[0]?.source ?? null) : null;
  const end = summary?.as_of ?? null;
  const state = usePolling(
    async (signal) => {
      if (!end || !mixSource) return null;
      const start = new Date(new Date(end).getTime() - 24 * 3600_000).toISOString();
      return unwrap(
        await api.GET("/api/v1/observations", {
          signal,
          params: {
            query: {
              metric: GENERATION_METRICS as MetricId[],
              start,
              end: new Date(new Date(end).getTime() + 1).toISOString(),
              area: ["DE"],
              kind: "actual",
              source: [mixSource],
              resolution: "15min",
              limit: 10000,
            },
          },
        }),
      );
    },
    0,
    `${end ?? ""}|${mixSource ?? ""}`,
  );
  const option = useMemo(() => {
    const series = groupByMetric(state.data?.data ?? [], (m) => t(`metrics.${m}`));
    const order = CARRIERS.map((c) => c.metric);
    series.sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id));
    return mixAreaOption(series, locale, theme);
  }, [state.data, t, locale, theme]);
  const first = summary ? Object.values(summary.generation)[0] : undefined;
  return (
    <Tile
      title={t("situation.mix")}
      className="lg:col-span-2"
      // The 24 h query starts only once the summary names the source and time.
      loading={state.loading || !summary}
      error={state.error}
      onRetry={state.reload}
      empty={!state.loading && summary !== undefined && (state.data?.data.length ?? 0) === 0}
      skeletonHeight={320}
      provenance={first ? provenanceOf(first, licenseFor(summary, first.source)) : undefined}
    >
      {state.data && state.data.data.length > 0 ? (
        <EChart option={option} height={320} label={t("situation.mix")} />
      ) : null}
    </Tile>
  );
}

export function SituationView() {
  const t = useTranslations();
  const locale = useLocale();
  const { data: summary, loading, error, reload, updatedAt } = useSummary();
  const common = { summary, loading, error, onRetry: reload };
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-2xl font-bold">{t("situation.title")}</h1>
        {summary?.as_of ? (
          <p className="text-sm text-muted" aria-live="polite">
            {t("common.asOf", { time: formatDateTime(summary.as_of, locale) })}
            {updatedAt
              ? ` · ${t("common.lastUpdate", { time: formatDateTime(updatedAt, locale, true) })}`
              : ""}
          </p>
        ) : null}
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <FrequencyTile {...common} />
        <ValueTile title={t("situation.load")} value={summary?.load} {...common} />
        <ValueTile
          title={t("situation.residual")}
          value={summary?.residual_load}
          hint={t("situation.residualHint")}
          {...common}
        />
        <PriceTile {...common} />
        <ValueTile title={t("situation.share")} value={summary?.renewable_share} {...common} />
        <ValueTile title={t("situation.co2")} value={summary?.co2_intensity} {...common} />
        <ValueTile
          title={t("situation.netImport")}
          value={summary?.net_import}
          hint={t("situation.flowsHint")}
          {...common}
        />
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <MixAreaTile summary={summary} />
        <MixDonutTile summary={summary} loading={loading} />
      </div>
      <Tile
        title={t("situation.flows")}
        loading={loading && !summary}
        error={summary ? undefined : error}
        onRetry={reload}
        empty={summary !== undefined && summary.flows.length === 0}
        provenance={
          summary
            ? provenanceOf(summary.net_import, licenseFor(summary, summary.net_import.source))
            : undefined
        }
      >
        {summary && summary.flows.length > 0 ? (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <div className="md:col-span-2">
              <FlowsMap flows={summary.flows} />
            </div>
            <div>
              <p className="mb-2 text-xs text-muted">{t("situation.flowsHint")}</p>
              <FlowsTable flows={summary.flows} />
            </div>
          </div>
        ) : null}
      </Tile>
    </div>
  );
}
