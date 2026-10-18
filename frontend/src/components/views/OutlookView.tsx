"use client";

import { useLocale, useTranslations } from "next-intl";
import { useMemo } from "react";
import { EChart } from "@/components/charts/EChart";
import { linesOption } from "@/components/charts/options";
import { Tile } from "@/components/Tile";
import { Badge } from "@/components/ui/badge";
import { api, unwrap, type ForecastResponse } from "@/lib/api/client";
import { carrierColor } from "@/lib/carriers";
import { formatDateTime, formatNumber } from "@/lib/format";
import { useChartTheme } from "@/lib/theme";
import { usePolling } from "@/lib/usePolling";

const HOURS = 48;

export function OutlookView() {
  const t = useTranslations("outlook");
  const locale = useLocale();
  const theme = useChartTheme();
  const state = usePolling<ForecastResponse>(
    async (signal) =>
      unwrap(
        await api.GET("/api/v1/forecast/residual-load", {
          signal,
          params: { query: { hours: HOURS } },
        }),
      ),
    5 * 60_000,
  );
  const option = useMemo(() => {
    const points = state.data?.points ?? [];
    const series = [
      {
        id: "load",
        name: t("load"),
        color: "#a0aab6",
        points: points.map((p) => ({ ts: p.ts, value: p.load })),
      },
      {
        id: "wind",
        name: t("wind"),
        color: carrierColor("generation.wind_onshore"),
        points: points.map((p) => ({ ts: p.ts, value: p.wind })),
      },
      {
        id: "solar",
        name: t("solar"),
        color: carrierColor("generation.solar"),
        points: points.map((p) => ({ ts: p.ts, value: p.solar })),
      },
      {
        id: "residual",
        name: t("residual"),
        color: "#ff6b6b",
        points: points.map((p) => ({ ts: p.ts, value: p.residual_load })),
      },
      {
        id: "official",
        name: t("official"),
        color: "#CC79A7",
        points: points
          .filter((p) => p.official_residual_load != null)
          .map((p) => ({ ts: p.ts, value: p.official_residual_load ?? 0 })),
      },
    ];
    return linesOption(series, "MW", locale, theme, { dashed: ["official", "load"] });
  }, [state.data, t, locale, theme]);
  const meta = state.data?.meta;
  const provenance = meta
    ? {
        source: meta.source,
        license: meta.license,
        ts: state.data?.points[0]?.ts ?? null,
        ageSeconds: null,
      }
    : undefined;
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-bold">{t("title")}</h1>
      <Tile
        title={`${t("chart")} · ${t("horizon", { hours: HOURS })}`}
        loading={state.loading}
        error={state.error}
        onRetry={state.reload}
        empty={state.data !== undefined && state.data.points.length === 0}
        provenance={provenance}
      >
        {state.data && state.data.points.length > 0 ? (
          <EChart option={option} height={380} label={t("chart")} />
        ) : null}
        <p className="mt-2 text-xs text-muted">{t("basis")}</p>
      </Tile>
      <Tile title={t("windows")} loading={state.loading && !state.data} provenance={provenance}>
        {state.data && state.data.windows.length === 0 ? (
          <p className="text-sm">{t("noWindows")}</p>
        ) : null}
        <ul className="flex flex-col gap-2">
          {state.data?.windows.map((w) => (
            <li key={`${w.kind}-${w.start}`} className="flex flex-wrap items-center gap-2 text-sm">
              <Badge tone={w.kind === "dunkelflaute" ? "crit" : "warn"}>{t(w.kind)}</Badge>
              <span>
                {t("windowText", {
                  start: formatDateTime(w.start, locale),
                  end: formatDateTime(w.end, locale),
                  hours: formatNumber(w.hours, locale, 2),
                  detail: w.detail,
                })}
              </span>
            </li>
          ))}
        </ul>
      </Tile>
    </div>
  );
}
