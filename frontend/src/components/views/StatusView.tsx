"use client";

import { useLocale, useTranslations } from "next-intl";
import { Tile } from "@/components/Tile";
import { Badge } from "@/components/ui/badge";
import { api, unwrap, type SourcesResponse } from "@/lib/api/client";
import { formatAge, formatDateTime, formatNumber } from "@/lib/format";
import { usePolling } from "@/lib/usePolling";

export function StatusView() {
  const t = useTranslations("status");
  const locale = useLocale();
  const state = usePolling<SourcesResponse>(
    async (signal) => unwrap(await api.GET("/api/v1/sources/status", { signal })),
    60_000,
  );
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-bold">{t("title")}</h1>
      <Tile
        title={t("title")}
        loading={state.loading}
        error={state.error}
        onRetry={state.reload}
        empty={state.data !== undefined && state.data.data.length === 0}
        provenance={
          state.data
            ? {
                source: "gridpulse",
                license: state.data.meta.license,
                ts: state.data.meta.generated_at,
                ageSeconds: 0,
              }
            : undefined
        }
      >
        {state.data && state.data.data.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">{t("title")}</caption>
              <thead>
                <tr className="text-left text-xs text-muted">
                  <th scope="col" className="py-1 pr-3">
                    {t("source")}
                  </th>
                  <th scope="col" className="pr-3">
                    Status
                  </th>
                  <th scope="col" className="pr-3">
                    {t("lastSuccess")}
                  </th>
                  <th scope="col" className="pr-3 text-right">
                    {t("age")}
                  </th>
                  <th scope="col" className="pr-3 text-right">
                    {t("latency")}
                  </th>
                  <th scope="col" className="pr-3 text-right">
                    {t("gaps")}
                  </th>
                  <th scope="col" className="pr-3 text-right">
                    {t("violations")}
                  </th>
                  <th scope="col" className="pr-3 text-right">
                    {t("failures")}
                  </th>
                  <th scope="col">{t("error")}</th>
                </tr>
              </thead>
              <tbody>
                {state.data.data.map((s) => (
                  <tr key={s.source} className="border-t border-border align-top">
                    <th scope="row" className="py-1 pr-3 text-left font-medium">
                      {s.source}
                      <span className="block text-xs font-normal text-muted">
                        {s.attribution} · {s.license}
                      </span>
                    </th>
                    <td className="pr-3">
                      {s.healthy ? (
                        <Badge tone="ok">✓ {t("healthy")}</Badge>
                      ) : (
                        <Badge tone="crit">✕ {t("unhealthy")}</Badge>
                      )}
                    </td>
                    <td className="tabular whitespace-nowrap pr-3">
                      {s.last_success ? formatDateTime(s.last_success, locale) : "–"}
                    </td>
                    <td className="tabular pr-3 text-right">
                      {formatAge(s.data_age_seconds, locale)}
                    </td>
                    <td className="tabular pr-3 text-right">
                      {s.latency_ms != null ? `${formatNumber(s.latency_ms, locale, 0)} ms` : "–"}
                    </td>
                    <td className="tabular pr-3 text-right">
                      {formatNumber(100 * s.gap_ratio, locale, 1)} %
                    </td>
                    <td className="tabular pr-3 text-right">{s.plausibility_violations}</td>
                    <td className="tabular pr-3 text-right">{s.consecutive_failures}</td>
                    <td className="max-w-xs truncate text-xs text-muted" title={s.last_error ?? ""}>
                      {s.last_error ?? "–"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Tile>
    </div>
  );
}
