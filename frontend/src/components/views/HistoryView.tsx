"use client";

import { useLocale, useTranslations } from "next-intl";
import { useMemo, useState, type FormEvent } from "react";
import { EChart } from "@/components/charts/EChart";
import { linesOption, mean, relativeHours, type Point } from "@/components/charts/options";
import { Tile } from "@/components/Tile";
import { Button } from "@/components/ui/button";
import {
  api,
  exportUrl,
  unwrap,
  type MetricId,
  type ObservationsResponse,
  type QueryResolution,
} from "@/lib/api/client";
import { berlinLocalToUtcIso, formatValue, utcIsoToBerlinLocal } from "@/lib/format";
import { useChartTheme } from "@/lib/theme";
import { usePolling } from "@/lib/usePolling";

export const HISTORY_METRICS: MetricId[] = [
  "load.actual",
  "load.residual",
  "generation.wind_onshore",
  "generation.wind_offshore",
  "generation.solar",
  "generation.lignite",
  "generation.hard_coal",
  "generation.gas",
  "generation.biomass",
  "price.day_ahead",
  "flow.net_import",
  "indicator.renewable_share",
  "indicator.co2_intensity",
];
const RESOLUTIONS: QueryResolution[] = ["15min", "1h", "1d"];

export interface HistoryQuery {
  metric: MetricId;
  from: string; // Europe/Berlin local "YYYY-MM-DDTHH:mm"
  to: string;
  resolution: QueryResolution;
  compareFrom: string;
  compareTo: string;
}

export function defaultQuery(now: Date): HistoryQuery {
  const to = utcIsoToBerlinLocal(now.toISOString());
  const from = utcIsoToBerlinLocal(new Date(now.getTime() - 7 * 86400_000).toISOString());
  return { metric: "load.actual", from, to, resolution: "1h", compareFrom: "", compareTo: "" };
}

function area(metric: MetricId): string {
  return metric === "price.day_ahead" ? "DE-LU" : "DE";
}

async function load(
  metric: MetricId,
  from: string,
  to: string,
  resolution: QueryResolution,
  signal: AbortSignal,
) {
  return unwrap(
    await api.GET("/api/v1/observations", {
      signal,
      params: {
        query: {
          metric: [metric],
          start: berlinLocalToUtcIso(from),
          end: berlinLocalToUtcIso(to),
          area: [area(metric)],
          kind: "actual",
          resolution,
          limit: 10000,
        },
      },
    }),
  );
}

/** One series per source (several sources may provide the same metric). */
function bySource(resp: ObservationsResponse | undefined): Map<string, Point[]> {
  const out = new Map<string, Point[]>();
  for (const row of resp?.data ?? []) {
    const list = out.get(row.source) ?? [];
    list.push({ ts: row.ts, value: row.value });
    out.set(row.source, list);
  }
  return out;
}

export function HistoryView({ now = new Date() }: { now?: Date }) {
  const t = useTranslations();
  const locale = useLocale();
  const theme = useChartTheme();
  const [draft, setDraft] = useState<HistoryQuery>(() => defaultQuery(now));
  const [query, setQuery] = useState<HistoryQuery>(draft);
  const key = JSON.stringify(query);
  const state = usePolling(
    async (signal) => {
      const a = await load(query.metric, query.from, query.to, query.resolution, signal);
      const b =
        query.compareFrom && query.compareTo
          ? await load(query.metric, query.compareFrom, query.compareTo, query.resolution, signal)
          : undefined;
      return { a, b };
    },
    0,
    key,
  );
  const unit = state.data?.a.data[0]?.unit ?? "";
  const comparing = Boolean(state.data?.b);
  const option = useMemo(() => {
    const series = [];
    for (const [source, points] of bySource(state.data?.a)) {
      series.push({
        id: `a-${source}`,
        name: `${t("history.periodA")} (${source})`,
        points: comparing ? relativeHours(points) : points,
      });
    }
    for (const [source, points] of bySource(state.data?.b)) {
      series.push({
        id: `b-${source}`,
        name: `${t("history.periodB")} (${source})`,
        points: relativeHours(points),
      });
    }
    return linesOption(series, unit, locale, theme, {
      zoom: true,
      categoryX: comparing,
      dashed: series.filter((s) => s.id.startsWith("b-")).map((s) => s.id),
    });
  }, [state.data, comparing, unit, locale, theme, t]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setQuery(draft);
  };
  const exportParams = (format: string) => ({
    metric: query.metric,
    area: area(query.metric),
    kind: "actual",
    start: berlinLocalToUtcIso(query.from),
    end: berlinLocalToUtcIso(query.to),
    resolution: query.resolution,
    format,
  });
  const meta = state.data?.a.meta;
  const meanA = mean([...bySource(state.data?.a).values()][0] ?? []);
  const meanB = mean([...bySource(state.data?.b).values()][0] ?? []);
  const input = "mt-1 rounded border border-border bg-panel px-2 py-1";
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-bold">{t("history.title")}</h1>
      <form
        onSubmit={submit}
        className="grid grid-cols-1 gap-3 rounded-lg border border-border bg-panel p-4 md:grid-cols-4"
      >
        <label className="flex flex-col text-sm">
          {t("history.metric")}
          <select
            className={input}
            value={draft.metric}
            onChange={(e) => {
              setDraft({ ...draft, metric: e.target.value as MetricId });
            }}
          >
            {HISTORY_METRICS.map((m) => (
              <option key={m} value={m}>
                {t(`metrics.${m}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col text-sm">
          {t("history.from")}
          <input
            type="datetime-local"
            className={input}
            value={draft.from}
            onChange={(e) => {
              setDraft({ ...draft, from: e.target.value });
            }}
          />
        </label>
        <label className="flex flex-col text-sm">
          {t("history.to")}
          <input
            type="datetime-local"
            className={input}
            value={draft.to}
            onChange={(e) => {
              setDraft({ ...draft, to: e.target.value });
            }}
          />
        </label>
        <label className="flex flex-col text-sm">
          {t("history.resolution")}
          <select
            className={input}
            value={draft.resolution}
            onChange={(e) => {
              setDraft({ ...draft, resolution: e.target.value as QueryResolution });
            }}
          >
            {RESOLUTIONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
        <fieldset className="col-span-1 grid grid-cols-1 gap-3 md:col-span-2 md:grid-cols-2">
          <legend className="text-sm font-medium">{t("history.compare")}</legend>
          <label className="flex flex-col text-sm">
            {t("history.compareFrom")}
            <input
              type="datetime-local"
              className={input}
              value={draft.compareFrom}
              onChange={(e) => {
                setDraft({ ...draft, compareFrom: e.target.value });
              }}
            />
          </label>
          <label className="flex flex-col text-sm">
            {t("history.compareTo")}
            <input
              type="datetime-local"
              className={input}
              value={draft.compareTo}
              onChange={(e) => {
                setDraft({ ...draft, compareTo: e.target.value });
              }}
            />
          </label>
        </fieldset>
        <div className="flex flex-wrap items-end gap-2 md:col-span-2">
          <Button type="submit" className="border-accent">
            {t("history.show")}
          </Button>
          <a
            className="rounded border border-border px-3 py-1.5 text-sm hover:border-accent"
            href={exportUrl(exportParams("csv"))}
          >
            {t("history.exportCsv")}
          </a>
          <a
            className="rounded border border-border px-3 py-1.5 text-sm hover:border-accent"
            href={exportUrl(exportParams("parquet"))}
          >
            {t("history.exportParquet")}
          </a>
        </div>
      </form>
      <Tile
        title={t(`metrics.${query.metric}`)}
        loading={state.loading}
        error={state.error}
        onRetry={state.reload}
        empty={state.data !== undefined && state.data.a.data.length === 0}
        provenance={
          meta
            ? {
                source: meta.source,
                license: meta.license,
                ts: state.data?.a.data.at(-1)?.ts ?? null,
                ageSeconds: null,
              }
            : undefined
        }
      >
        {state.data && state.data.a.data.length > 0 ? (
          <>
            <EChart option={option} height={380} label={t(`metrics.${query.metric}`)} />
            <dl className="mt-2 flex flex-wrap gap-6 text-sm">
              <div>
                <dt className="text-xs text-muted">
                  {t("history.mean")} – {t("history.periodA")}
                </dt>
                <dd className="tabular">{formatValue(meanA, unit, locale)}</dd>
              </div>
              {comparing ? (
                <div>
                  <dt className="text-xs text-muted">
                    {t("history.mean")} – {t("history.periodB")}
                  </dt>
                  <dd className="tabular">{formatValue(meanB, unit, locale)}</dd>
                </div>
              ) : null}
            </dl>
          </>
        ) : null}
        <p className="mt-2 text-xs text-muted">{t("history.hint")}</p>
      </Tile>
    </div>
  );
}
