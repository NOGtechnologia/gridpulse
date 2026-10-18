"use client";

import { useLocale, useTranslations } from "next-intl";
import { useEffect, useRef } from "react";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Schemas } from "@/lib/api/client";
import { formatValue } from "@/lib/format";

type Flow = Schemas["FlowOut"];

const LABEL_POSITIONS: Record<string, [number, number]> = {
  AT: [14.5, 47.6],
  BE: [4.6, 50.6],
  CH: [8.2, 46.8],
  CZ: [15.3, 49.8],
  DK: [9.3, 56.0],
  FR: [4.5, 48.4],
  LU: [6.1, 49.8],
  NL: [5.6, 52.2],
  NO: [9.0, 59.2],
  PL: [18.0, 52.3],
  SE: [14.2, 57.2],
};
export const IMPORT_COLOR = "#56B4E9";
export const EXPORT_COLOR = "#E69F00";

/** "↓ Import" / "↑ Export" text so that direction never depends on colour alone. */
export function flowLabel(value: number, t: (key: "import" | "export") => string): string {
  return value >= 0 ? `↓ ${t("import")}` : `↑ ${t("export")}`;
}

/**
 * Border flows on a MapLibre map with a fully local style (Natural Earth polygons,
 * no tile server, no API key, works offline). Labels are HTML markers, so no glyph
 * server is needed either.
 */
export function FlowsMap({ flows }: { flows: Flow[] }) {
  const t = useTranslations("situation");
  const locale = useLocale();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    let cleanup: (() => void) | undefined;
    void import("maplibre-gl").then((maplibregl) => {
      if (cancelled || !ref.current) return;
      // Worker module copied to public/ by scripts/copy-maplibre-worker.mjs (same origin, CSP-safe).
      maplibregl.setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");
      const byCode = Object.fromEntries(flows.map((f) => [f.neighbour, f.value]));
      const fill: unknown[] = ["match", ["get", "code"], "DE", "#30363d"];
      for (const [code, value] of Object.entries(byCode)) {
        fill.push(code, value >= 0 ? IMPORT_COLOR : EXPORT_COLOR);
      }
      fill.push("#1f242c");
      const map = new maplibregl.Map({
        container: ref.current,
        style: {
          version: 8,
          sources: { countries: { type: "geojson", data: "/geo/neighbours.json" } },
          layers: [
            { id: "bg", type: "background", paint: { "background-color": "#0d1117" } },
            {
              id: "fill",
              type: "fill",
              source: "countries",
              filter: ["==", ["geometry-type"], "Polygon"],
              paint: { "fill-color": fill as never, "fill-opacity": 0.55 },
            },
            {
              id: "line",
              type: "line",
              source: "countries",
              filter: ["==", ["geometry-type"], "Polygon"],
              paint: { "line-color": "#a0aab6", "line-width": 0.8 },
            },
          ],
        },
        center: [10.4, 51.8],
        zoom: 3.6,
        interactive: false,
        attributionControl: { compact: true, customAttribution: "Natural Earth" },
      });
      const markers = flows
        .filter((f) => LABEL_POSITIONS[f.neighbour])
        .map((f) => {
          const el = document.createElement("div");
          el.className = "rounded bg-black/70 px-1 text-[10px] leading-tight text-white";
          el.textContent = `${f.neighbour} ${flowLabel(f.value, t)} ${formatValue(Math.abs(f.value), "MW", locale)}`;
          const marker = new maplibregl.Marker({ element: el })
            .setLngLat(LABEL_POSITIONS[f.neighbour] as [number, number])
            .addTo(map);
          // MapLibre labels markers "Map marker"; the accessible name must match the text.
          el.setAttribute("aria-label", el.textContent);
          return marker;
        });
      // The map is a non-interactive illustration; the table carries the data for
      // keyboard and screen-reader users, so the canvas is taken out of the tab order.
      map.getCanvas().tabIndex = -1;
      cleanup = () => {
        markers.forEach((m) => m.remove());
        map.remove();
      };
    });
    return () => {
      cancelled = true;
      cleanup?.();
    };
  }, [flows, locale, t]);

  return (
    <div
      ref={ref}
      role="figure"
      aria-label={t("flows")}
      className="h-72 w-full overflow-hidden rounded"
    />
  );
}

export function FlowsTable({ flows }: { flows: Flow[] }) {
  const t = useTranslations("situation");
  const locale = useLocale();
  return (
    <table className="w-full text-sm">
      <caption className="sr-only">{t("flows")}</caption>
      <thead>
        <tr className="text-left text-xs text-muted">
          <th scope="col">{t("neighbour")}</th>
          <th scope="col" className="text-right">
            MW
          </th>
          <th scope="col" className="text-right">
            &nbsp;
          </th>
        </tr>
      </thead>
      <tbody>
        {[...flows]
          .sort((a, b) => b.value - a.value)
          .map((f) => (
            <tr key={f.neighbour} className="border-t border-border">
              <th scope="row" className="py-0.5 text-left font-normal">
                {f.neighbour}
              </th>
              <td className="tabular text-right">{formatValue(f.value, "MW", locale)}</td>
              {/* Theme tokens keep WCAG AA contrast in both dark and light mode. */}
              <td
                className={`pl-2 text-right text-xs ${f.value >= 0 ? "text-accent" : "text-warn"}`}
              >
                {flowLabel(f.value, t)}
              </td>
            </tr>
          ))}
      </tbody>
    </table>
  );
}
