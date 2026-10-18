import { render, type RenderResult } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactElement, ReactNode } from "react";
import { vi } from "vitest";
import de from "../../messages/de.json";
import en from "../../messages/en.json";

export function renderIntl(ui: ReactElement, locale: "de" | "en" = "de"): RenderResult {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <NextIntlClientProvider
        locale={locale}
        messages={locale === "de" ? de : en}
        timeZone="Europe/Berlin"
      >
        {children}
      </NextIntlClientProvider>
    );
  }
  return render(ui, { wrapper: Wrapper });
}

/** Route fetch calls by URL substring to JSON bodies. */
export function mockFetch(routes: Record<string, unknown>, status = 200) {
  const fn = vi.fn((input: RequestInfo | URL) => {
    const url = input instanceof Request ? input.url : String(input);
    const key = Object.keys(routes).find((k) => url.includes(k));
    if (!key) return Promise.resolve(new Response("{}", { status: 404 }));
    return Promise.resolve(
      new Response(JSON.stringify(routes[key]), {
        status,
        headers: { "content-type": "application/json" },
      }),
    );
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const NOW = "2026-10-18T12:00:00Z";

export const value = (v: number | null, unit: string, extra: Record<string, unknown> = {}) => ({
  value: v,
  unit,
  ts: v === null ? null : NOW,
  source: v === null ? null : "smard",
  age_seconds: v === null ? null : 300,
  stale: false,
  ...extra,
});

export const meta = {
  source: "smard",
  license: "CC BY 4.0",
  attribution: "Bundesnetzagentur | SMARD.de",
  generated_at: NOW,
  count: null,
  total: null,
  next_offset: null,
  disclaimer: "x",
};

export const summary = {
  meta,
  as_of: NOW,
  generation: {
    "generation.wind_onshore": value(20000, "MW"),
    "generation.solar": value(10000, "MW"),
    "generation.lignite": value(8000, "MW"),
  },
  load: value(45000, "MW"),
  residual_load: value(15000, "MW", { source: "gridpulse|smard" }),
  renewable_share: value(55.5, "%", { source: "gridpulse|smard" }),
  co2_intensity: value(320, "gCO2/kWh", { source: "gridpulse|smard" }),
  price: value(-5.5, "EUR/MWh"),
  price_negative: true,
  net_import: value(-2000, "MW", { source: "energy_charts", stale: true }),
  flows: [
    { neighbour: "FR", value: 1200, ts: NOW },
    { neighbour: "AT", value: -3000, ts: NOW },
  ],
  frequency: {
    current: value(50.012, "Hz", { source: "energy_charts" }),
    deviation_mhz: 12,
    status: "green",
    sparkline: [
      { ts: "2026-10-18T11:59:00Z", value: 50.01 },
      { ts: NOW, value: 50.012 },
    ],
  },
  sources: [
    { source: "smard", license: "CC BY 4.0", attribution: "SMARD" },
    { source: "energy_charts", license: "CC BY 4.0", attribution: "EC" },
  ],
};
