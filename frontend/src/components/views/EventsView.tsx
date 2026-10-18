"use client";

import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { Tile } from "@/components/Tile";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, unwrap, type EventsResponse, type Severity } from "@/lib/api/client";
import { formatDateTime, formatNumber, unitLabel } from "@/lib/format";
import { usePolling } from "@/lib/usePolling";

const TONE: Record<string, BadgeTone> = { info: "neutral", warning: "warn", critical: "crit" };
const SYMBOL: Record<string, string> = { info: "ℹ", warning: "▲", critical: "■" };
const SEVERITIES = ["info", "warning", "critical"] as const;

export function SeverityBadge({ severity, label }: { severity: string; label: string }) {
  return (
    <Badge tone={TONE[severity] ?? "neutral"}>
      <span aria-hidden="true">{SYMBOL[severity] ?? "•"}</span> {label}
    </Badge>
  );
}

export function TestAlertButton() {
  const t = useTranslations("events");
  const [result, setResult] = useState<string>();
  const [busy, setBusy] = useState(false);
  return (
    <div className="flex items-center gap-2">
      <Button
        disabled={busy}
        onClick={() => {
          setBusy(true);
          void fetch("/api/alerts-test", { method: "POST" })
            .then(async (r) => {
              const body = (await r.json()) as {
                results?: Record<string, string>;
                detail?: string;
              };
              setResult(
                r.ok
                  ? t("testSent", { result: JSON.stringify(body.results ?? {}) })
                  : t("testFailed", { error: body.detail ?? String(r.status) }),
              );
            })
            .catch((e: unknown) => {
              setResult(t("testFailed", { error: String(e) }));
            })
            .finally(() => {
              setBusy(false);
            });
        }}
      >
        {t("testAlert")}
      </Button>
      {result ? (
        <span role="status" className="text-xs text-muted">
          {result}
        </span>
      ) : null}
    </div>
  );
}

export function EventsView() {
  const t = useTranslations("events");
  const locale = useLocale();
  const [minSeverity, setMinSeverity] = useState<Severity | "">("");
  const state = usePolling<EventsResponse>(
    async (signal) =>
      unwrap(
        await api.GET("/api/v1/events", {
          signal,
          params: { query: { limit: 200, ...(minSeverity ? { min_severity: minSeverity } : {}) } },
        }),
      ),
    60_000,
    minSeverity,
  );
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <h1 className="text-2xl font-bold">{t("title")}</h1>
        <div className="flex flex-wrap items-end gap-4">
          <label className="flex flex-col text-sm">
            {t("minSeverity")}
            <select
              className="mt-1 rounded border border-border bg-panel px-2 py-1"
              value={minSeverity}
              onChange={(e) => {
                setMinSeverity(e.target.value as Severity | "");
              }}
            >
              <option value="">{t("all")}</option>
              {SEVERITIES.map((s) => (
                <option key={s} value={s}>
                  {t(s)}
                </option>
              ))}
            </select>
          </label>
          <TestAlertButton />
        </div>
      </div>
      <Tile
        title={t("title")}
        loading={state.loading}
        error={state.error}
        onRetry={state.reload}
        provenance={
          state.data
            ? {
                source: state.data.meta.source,
                license: state.data.meta.license,
                ts: state.data.meta.generated_at,
                ageSeconds: 0,
              }
            : undefined
        }
      >
        {state.data && state.data.data.length === 0 ? <p className="text-sm">{t("none")}</p> : null}
        {state.data && state.data.data.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">{t("title")}</caption>
              <thead>
                <tr className="text-left text-xs text-muted">
                  <th scope="col" className="py-1 pr-3">
                    {t("time")}
                  </th>
                  <th scope="col" className="pr-3">
                    {t("severity")}
                  </th>
                  <th scope="col" className="pr-3">
                    {t("rule")}
                  </th>
                  <th scope="col" className="pr-3">
                    {t("message")}
                  </th>
                  <th scope="col" className="pr-3 text-right">
                    {t("value")}
                  </th>
                  <th scope="col" className="text-right">
                    {t("threshold")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {state.data.data.map((e) => (
                  <tr key={e.id} className="border-t border-border align-top">
                    <td className="tabular whitespace-nowrap py-1 pr-3">
                      <time dateTime={e.ts}>{formatDateTime(e.ts, locale)}</time>
                    </td>
                    <td className="pr-3">
                      <SeverityBadge
                        severity={e.severity}
                        label={t(e.severity as (typeof SEVERITIES)[number])}
                      />
                    </td>
                    <td className="font-mono pr-3 text-xs">{e.rule_id}</td>
                    <td className="pr-3">
                      {e.message}
                      <span className="block text-xs text-muted">
                        {e.metric} · {e.area} · {e.source}
                      </span>
                    </td>
                    <td className="tabular pr-3 text-right">
                      {e.value != null
                        ? `${formatNumber(e.value, locale, 2)} ${unitLabel(e.unit ?? "")}`
                        : "–"}
                    </td>
                    <td className="tabular text-right">
                      {e.threshold != null ? formatNumber(e.threshold, locale, 2) : "–"}
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
