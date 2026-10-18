"use client";

import { useLocale, useTranslations } from "next-intl";
import { useEffect } from "react";
import { FrequencyTile, PriceTile, ValueTile } from "@/components/situation/tiles";
import { useSummary } from "@/components/situation/SituationView";
import { formatDateTime } from "@/lib/format";

export const KIOSK_REFRESH_SECONDS = 30;

/** Full-screen wall display: dark, high contrast, auto refresh, no interaction needed. */
export function KioskView() {
  const t = useTranslations();
  const locale = useLocale();
  const { data: summary, loading, error } = useSummary(KIOSK_REFRESH_SECONDS * 1000);
  useEffect(() => {
    const root = document.documentElement;
    root.classList.add("kiosk", "dark");
    root.classList.remove("light");
    return () => {
      root.classList.remove("kiosk");
    };
  }, []);
  const common = { summary, loading, error, size: "text-5xl" };
  return (
    <main id="main" className="flex min-h-screen flex-col gap-4 p-6">
      <header className="flex items-baseline justify-between">
        <h1 className="text-3xl font-bold">
          {t("app.name")} · {t("situation.title")}
        </h1>
        <p className="text-lg text-muted" aria-live="polite">
          {summary?.as_of ? t("common.asOf", { time: formatDateTime(summary.as_of, locale) }) : ""}{" "}
          · {t("kiosk.refresh", { seconds: KIOSK_REFRESH_SECONDS })}
        </p>
      </header>
      <div className="grid flex-1 grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        <FrequencyTile {...common} />
        <ValueTile title={t("situation.load")} value={summary?.load} {...common} />
        <ValueTile title={t("situation.residual")} value={summary?.residual_load} {...common} />
        <ValueTile title={t("situation.share")} value={summary?.renewable_share} {...common} />
        <ValueTile title={t("situation.co2")} value={summary?.co2_intensity} {...common} />
        <PriceTile {...common} />
      </div>
      <footer className="text-sm text-muted">{t("footer.disclaimer")}</footer>
    </main>
  );
}
