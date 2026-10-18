"use client";

import { useLocale, useTranslations } from "next-intl";
import { useMemo } from "react";
import { EChart } from "@/components/charts/EChart";
import { donutOption, sparklineOption } from "@/components/charts/options";
import { Tile, type Provenance } from "@/components/Tile";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import type { SummaryNow, Value } from "@/lib/api/client";
import { CARRIERS } from "@/lib/carriers";
import { formatNumber, formatValue } from "@/lib/format";
import { useChartTheme } from "@/lib/theme";

export function provenanceOf(value: Value | undefined, license?: string | null): Provenance {
  return {
    source: value?.source ?? null,
    license: license ?? null,
    ts: value?.ts ?? null,
    ageSeconds: value?.age_seconds ?? null,
    stale: value?.stale ?? false,
  };
}

export function licenseFor(
  summary: SummaryNow | undefined,
  source: string | null | undefined,
): string | null {
  if (!summary || !source) return null;
  const parts = source.split("|").filter((s) => s !== "gridpulse");
  const found = summary.sources.filter((a) => parts.includes(a.source)).map((a) => a.license);
  return found.length ? [...new Set(found)].join("; ") : summary.meta.license;
}

export function BigNumber({
  value,
  digits,
  size = "text-3xl",
}: {
  value: Value | undefined;
  digits?: number;
  size?: string;
}) {
  const locale = useLocale();
  return (
    <p className={`tabular font-semibold ${size}`} data-testid="big-number">
      {formatValue(value?.value, value?.unit ?? "", locale, digits)}
    </p>
  );
}

export function ValueTile({
  title,
  value,
  summary,
  hint,
  digits,
  loading,
  error,
  onRetry,
  size,
  children,
}: {
  title: string;
  value: Value | undefined;
  summary: SummaryNow | undefined;
  hint?: string;
  digits?: number;
  loading?: boolean;
  error?: Error | undefined;
  onRetry?: () => void;
  size?: string;
  children?: React.ReactNode;
}) {
  return (
    <Tile
      title={title}
      loading={loading && !value}
      error={value ? undefined : error}
      onRetry={onRetry}
      provenance={value ? provenanceOf(value, licenseFor(summary, value.source)) : undefined}
    >
      {value ? (
        <>
          <BigNumber value={value} digits={digits} size={size} />
          {hint ? <p className="text-xs text-muted">{hint}</p> : null}
          {children}
        </>
      ) : null}
    </Tile>
  );
}

const LIGHT_TONE: Record<string, BadgeTone> = { green: "ok", yellow: "warn", red: "crit" };
const LIGHT_SYMBOL: Record<string, string> = { green: "●", yellow: "▲", red: "■" };

export function FrequencyTile({
  summary,
  loading,
  error,
  onRetry,
  size,
}: {
  summary: SummaryNow | undefined;
  loading?: boolean;
  error?: Error | undefined;
  onRetry?: () => void;
  size?: string;
}) {
  const t = useTranslations("situation");
  const locale = useLocale();
  const theme = useChartTheme();
  const freq = summary?.frequency;
  const option = useMemo(
    () =>
      sparklineOption(
        (freq?.sparkline ?? []).map((p) => ({ ts: p.ts, value: p.value })),
        locale,
        theme,
      ),
    [freq?.sparkline, locale, theme],
  );
  const status = freq?.status ?? null;
  const statusText = status
    ? t(status === "green" ? "statusGreen" : status === "yellow" ? "statusYellow" : "statusRed")
    : null;
  return (
    <Tile
      title={t("frequency")}
      loading={loading && !summary}
      error={summary ? undefined : error}
      onRetry={onRetry}
      empty={summary !== undefined && freq?.current.value == null}
      provenance={
        freq ? provenanceOf(freq.current, licenseFor(summary, freq.current.source)) : undefined
      }
      actions={
        status && statusText ? (
          <Badge tone={LIGHT_TONE[status] ?? "neutral"}>
            <span aria-hidden="true">{LIGHT_SYMBOL[status]}</span> {statusText}
          </Badge>
        ) : null
      }
    >
      {freq?.current.value != null ? (
        <div className="flex flex-col gap-1">
          <BigNumber value={freq.current} size={size} />
          <p className="text-xs text-muted">
            {t("deviation", { value: formatNumber(freq.deviation_mhz ?? 0, locale, 0) })}
          </p>
          <EChart option={option} height={110} label={t("sparkline")} />
        </div>
      ) : null}
    </Tile>
  );
}

export function PriceTile({
  summary,
  loading,
  error,
  onRetry,
  size,
}: {
  summary: SummaryNow | undefined;
  loading?: boolean;
  error?: Error | undefined;
  onRetry?: () => void;
  size?: string;
}) {
  const t = useTranslations("situation");
  return (
    <ValueTile
      title={t("price")}
      value={summary?.price}
      summary={summary}
      loading={loading}
      error={error}
      onRetry={onRetry}
      size={size}
    >
      {summary?.price_negative ? (
        <Badge tone="warn" className="mt-1">
          <span aria-hidden="true">▼</span> {t("negativePrice")}
        </Badge>
      ) : null}
    </ValueTile>
  );
}

export function MixDonutTile({
  summary,
  loading,
}: {
  summary: SummaryNow | undefined;
  loading?: boolean;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const theme = useChartTheme();
  const slices = useMemo(
    () =>
      CARRIERS.map((c) => ({
        id: c.metric,
        name: t(`metrics.${c.metric}`),
        value: summary?.generation[c.metric]?.value ?? 0,
      })),
    [summary, t],
  );
  const first = summary ? Object.values(summary.generation)[0] : undefined;
  const option = useMemo(() => donutOption(slices, locale, theme), [slices, locale, theme]);
  const total = slices.reduce((s, x) => s + x.value, 0);
  return (
    <Tile
      title={t("situation.mixNow")}
      loading={loading && !summary}
      empty={summary !== undefined && total === 0}
      provenance={first ? provenanceOf(first, licenseFor(summary, first.source)) : undefined}
    >
      {total > 0 ? (
        <>
          <EChart option={option} height={240} label={t("situation.mixNow")} />
          <table className="mt-2 w-full text-xs">
            <caption className="sr-only">{t("situation.mixNow")}</caption>
            <tbody>
              {slices
                .filter((s) => s.value > 0)
                .sort((a, b) => b.value - a.value)
                .map((s) => (
                  <tr key={s.id}>
                    <th scope="row" className="py-0.5 text-left font-normal">
                      {s.name}
                    </th>
                    <td className="tabular text-right">{formatValue(s.value, "MW", locale)}</td>
                    <td className="tabular w-14 text-right text-muted">
                      {formatValue((100 * s.value) / total, "%", locale)}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </>
      ) : null}
    </Tile>
  );
}
