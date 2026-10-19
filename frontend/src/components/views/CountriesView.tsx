"use client";

import { useLocale, useTranslations } from "next-intl";
import { EChart } from "@/components/charts/EChart";
import { linesOption, type NamedSeries } from "@/components/charts/options";
import { Tile, type Provenance } from "@/components/Tile";
import { Badge } from "@/components/ui/badge";
import { api, unwrap, type ObservationsResponse } from "@/lib/api/client";
import { ageSeconds, summarize, ZONES, type ZoneSummary } from "@/lib/countries";
import { formatValue } from "@/lib/format";
import { useChartTheme } from "@/lib/theme";
import { usePolling } from "@/lib/usePolling";

const HOUR = 3_600_000;
// ENTSO-E publishes actual load with roughly one hour delay; older data is marked stale.
const STALE_AFTER_SECONDS = 3 * 3600;
// Okabe-Ito based palette: distinguishable with colour-vision deficiencies (spec 8).
const ZONE_COLORS = [
  "#E69F00",
  "#56B4E9",
  "#009E73",
  "#F0E442",
  "#0072B2",
  "#D55E00",
  "#CC79A7",
  "#a0aab6",
  "#9b7fd9",
];

export function CountriesView({ now }: { now?: Date }) {
  const t = useTranslations("countries");
  const locale = useLocale();
  const theme = useChartTheme();
  const state = usePolling<ObservationsResponse>(async (signal) => {
    const at = now ?? new Date();
    return unwrap(
      await api.GET("/api/v1/observations", {
        signal,
        params: {
          query: {
            metric: ["load.actual", "price.day_ahead"],
            area: [...ZONES],
            source: ["entsoe"],
            kind: "actual",
            resolution: "1h",
            start: new Date(at.getTime() - 24 * HOUR).toISOString(),
            end: new Date(at.getTime() + 24 * HOUR).toISOString(),
            limit: 10000,
          },
        },
      }),
    );
  }, 15 * 60_000);
  // Ages refer to the moment of the last successful fetch (at most a few hundred rows).
  const at = now ?? state.updatedAt ?? new Date();
  const zones = summarize(state.data?.data ?? [], at);
  const empty = state.data !== undefined && state.data.data.length === 0;
  const meta = state.data?.meta;

  const chart = (pick: (z: ZoneSummary) => NamedSeries["points"], unit: string) =>
    linesOption(
      zones
        .map((z, i) => ({
          id: z.zone,
          name: t(`zones.${z.zone}`),
          color: ZONE_COLORS[i],
          points: pick(z),
        }))
        .filter((s) => s.points.length > 0),
      unit,
      locale,
      theme,
    );
  const priceOption = chart((z) => z.pricePoints, "EUR/MWh");
  const loadOption = chart((z) => z.loadPoints, "MW");
  const chartProvenance: Provenance | undefined = meta
    ? { source: meta.source, license: meta.license, ts: meta.generated_at, ageSeconds: null }
    : undefined;

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-bold">{t("title")}</h1>
      <p className="text-sm text-muted">{t("intro")}</p>
      {empty ? (
        <Tile title={t("emptyTitle")} provenance={chartProvenance}>
          <p className="text-sm">{t("emptyToken")}</p>
          <p className="mt-2 text-xs text-muted">{t("emptyHint")}</p>
        </Tile>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {zones.map((z) => (
              <ZoneTile
                key={z.zone}
                zone={z}
                now={at}
                license={meta?.license ?? null}
                loading={state.loading && !state.data}
                error={state.error}
                onRetry={state.reload}
              />
            ))}
          </div>
          <Tile
            title={t("priceChart")}
            loading={state.loading && !state.data}
            error={state.error}
            onRetry={state.reload}
            provenance={chartProvenance}
          >
            {state.data ? (
              <EChart option={priceOption} height={320} label={t("priceChart")} />
            ) : null}
          </Tile>
          <Tile
            title={t("loadChart")}
            loading={state.loading && !state.data}
            error={state.error}
            onRetry={state.reload}
            provenance={chartProvenance}
          >
            {state.data ? <EChart option={loadOption} height={320} label={t("loadChart")} /> : null}
          </Tile>
        </>
      )}
    </div>
  );
}

function ZoneTile({
  zone,
  now,
  license,
  loading,
  error,
  onRetry,
}: {
  zone: ZoneSummary;
  now: Date;
  license: string | null;
  loading: boolean;
  error: Error | undefined;
  onRetry: () => void;
}) {
  const t = useTranslations();
  const locale = useLocale();
  // The footer shows the older of both timestamps so that the age is never understated.
  const oldest = [zone.load, zone.price]
    .filter((v) => v !== null)
    .sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime())[0];
  const age = oldest ? ageSeconds(oldest.ts, now) : null;
  const provenance: Provenance = {
    source: oldest?.source ?? null,
    license,
    ts: oldest?.ts ?? null,
    ageSeconds: age,
    stale: age !== null && age > STALE_AFTER_SECONDS,
  };
  const hasData = zone.load !== null || zone.price !== null;
  return (
    <Tile
      title={`${t(`countries.zones.${zone.zone}`)} (${zone.zone})`}
      loading={loading}
      error={error}
      onRetry={onRetry}
      empty={!loading && !hasData}
      provenance={provenance}
    >
      {hasData ? (
        <dl className="grid grid-cols-2 gap-2 text-sm">
          <div>
            <dt className="text-xs text-muted">{t("metrics.load.actual")}</dt>
            <dd className="tabular text-xl font-semibold" data-testid="big-number">
              {formatValue(zone.load?.value, zone.load?.unit ?? "MW", locale)}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted">{t("metrics.price.day_ahead")}</dt>
            <dd className="tabular text-xl font-semibold" data-testid="big-number">
              {formatValue(zone.price?.value, zone.price?.unit ?? "EUR/MWh", locale)}
            </dd>
            {zone.price && zone.price.value < 0 ? (
              <Badge tone="warn">{t("situation.negativePrice")}</Badge>
            ) : null}
          </div>
          <div className="col-span-2 text-xs text-muted">
            {t("countries.priceMean", {
              value: formatValue(zone.priceMean, "EUR/MWh", locale),
            })}
          </div>
        </dl>
      ) : null}
    </Tile>
  );
}
