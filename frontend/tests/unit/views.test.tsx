import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Footer } from "@/components/Footer";
import { Header, LocaleSwitch, ThemeToggle } from "@/components/Header";
import { EChart } from "@/components/charts/EChart";
import { FlowsMap, FlowsTable, flowLabel } from "@/components/situation/FlowsMap";
import { SituationView } from "@/components/situation/SituationView";
import { licenseFor, provenanceOf } from "@/components/situation/tiles";
import { Tile } from "@/components/Tile";
import { CountriesView } from "@/components/views/CountriesView";
import { EventsView, TestAlertButton } from "@/components/views/EventsView";
import { defaultQuery, HistoryView } from "@/components/views/HistoryView";
import { KioskView } from "@/components/views/KioskView";
import { OutlookView } from "@/components/views/OutlookView";
import { StatusView } from "@/components/views/StatusView";
import { applyTheme, currentTheme, readChartTheme } from "@/lib/theme";
import { meta, mockFetch, renderIntl, summary } from "./utils";

const observations = {
  meta: { ...meta, count: 2, total: 2 },
  data: [
    {
      ts: "2026-10-18T11:00:00Z",
      metric: "generation.solar",
      area: "DE",
      kind: "actual",
      source: "smard",
      unit: "MW",
      value: 9000,
    },
    {
      ts: "2026-10-18T11:00:00Z",
      metric: "generation.lignite",
      area: "DE",
      kind: "actual",
      source: "smard",
      unit: "MW",
      value: 8000,
    },
  ],
};

describe("Tile", () => {
  it("renders loading, error with retry, empty and stale states", () => {
    const retry = vi.fn();
    const { rerender } = renderIntl(<Tile title="T" loading />);
    expect(screen.getByRole("status")).toHaveTextContent("Lädt");
    rerender(<Tile title="T" error={new Error("x")} onRetry={retry} />);
    fireEvent.click(screen.getByRole("button", { name: "Erneut versuchen" }));
    expect(retry).toHaveBeenCalled();
    rerender(<Tile title="T" empty />);
    expect(screen.getByText("Keine Daten verfügbar.")).toBeInTheDocument();
  });

  it("shows source, licence, age and stale marker", () => {
    renderIntl(
      <Tile
        title="T"
        provenance={{
          source: "smard",
          license: "CC BY 4.0",
          ts: "2026-10-18T12:00:00Z",
          ageSeconds: 120,
          stale: true,
        }}
      >
        x
      </Tile>,
    );
    expect(screen.getByText(/Quelle: smard/)).toBeInTheDocument();
    expect(screen.getByText(/Lizenz: CC BY 4.0/)).toBeInTheDocument();
    expect(screen.getByText(/Veraltet/)).toBeInTheDocument();
  });

  it("helpers derive provenance and licences", () => {
    expect(provenanceOf(undefined)).toMatchObject({ source: null, stale: false });
    expect(licenseFor(undefined, "smard")).toBeNull();
    expect(licenseFor(summary as never, "gridpulse|smard")).toBe("CC BY 4.0");
    expect(licenseFor(summary as never, "unknown")).toBe("CC BY 4.0");
  });
});

describe("SituationView", () => {
  it("renders all tiles with units and sources", async () => {
    mockFetch({ "/api/v1/summary/now": summary, "/api/v1/observations": observations });
    renderIntl(<SituationView />);
    expect(await screen.findByText("45.000 MW")).toBeInTheDocument();
    expect(screen.getByText("50,012 Hz")).toBeInTheDocument();
    expect(screen.getByText(/Normal/)).toBeInTheDocument();
    expect(screen.getByText("Negativer Preis")).toBeInTheDocument();
    expect(screen.getByText("55,5 %")).toBeInTheDocument();
    expect(screen.getAllByText(/Quelle:/).length).toBeGreaterThan(5);
    await waitFor(() => {
      expect(screen.getAllByRole("img").length).toBeGreaterThan(1);
    });
    expect(screen.getByRole("table", { name: "Grenzüberschreitende Flüsse" })).toBeInTheDocument();
  });

  it("shows an error with retry when the API fails", async () => {
    mockFetch({ "/api/v1/summary/now": {} }, 500);
    renderIntl(<SituationView />);
    expect((await screen.findAllByRole("alert")).length).toBeGreaterThan(0);
  });
});

describe("flows", () => {
  it("labels direction with text, not colour only", () => {
    const t = (k: "import" | "export") => k;
    expect(flowLabel(5, t)).toBe("↓ import");
    expect(flowLabel(-5, t)).toBe("↑ export");
    renderIntl(<FlowsTable flows={summary.flows} />, "en");
    expect(screen.getByText("↑ Export")).toBeInTheDocument();
    expect(screen.getByText("↓ Import")).toBeInTheDocument();
  });

  it("creates and disposes the map", async () => {
    const { unmount } = renderIntl(<FlowsMap flows={summary.flows} />);
    await act(async () => {
      await Promise.resolve();
    });
    unmount();
  });
});

describe("EChart", () => {
  it("initialises lazily, updates and disposes", async () => {
    const core = await import("echarts/core");
    const { rerender, unmount } = renderIntl(<EChart option={{ a: 1 }} label="chart" />);
    await waitFor(() => {
      expect(core.init).toHaveBeenCalled();
    });
    rerender(<EChart option={{ a: 2 }} label="chart" />);
    unmount();
    expect(screen.queryByRole("img")).toBeNull();
  });
});

describe("other views", () => {
  it("OutlookView shows chart and windows", async () => {
    mockFetch({
      "/api/v1/forecast/residual-load": {
        meta,
        unit: "MW",
        points: [
          {
            ts: "2026-10-18T12:00:00Z",
            load: 50000,
            wind: 20000,
            solar: 10000,
            residual_load: 20000,
            official_residual_load: 21000,
          },
        ],
        windows: [
          {
            kind: "negative_price",
            start: "2026-10-19T10:00:00Z",
            end: "2026-10-19T12:00:00Z",
            hours: 2,
            detail: "min -5 EUR/MWh",
          },
        ],
      },
    });
    renderIntl(<OutlookView />);
    expect(await screen.findByText("Negative Preise")).toBeInTheDocument();
    expect(screen.getByText(/min -5 EUR\/MWh/)).toBeInTheDocument();
    expect(screen.getByText(/Noch kein Backtest/)).toBeInTheDocument();
  });

  it("OutlookView without windows", async () => {
    mockFetch({ "/api/v1/forecast/residual-load": { meta, unit: "MW", points: [], windows: [] } });
    renderIntl(<OutlookView />, "en");
    expect(await screen.findByText(/No negative prices/)).toBeInTheDocument();
  });

  const backtest = (active: boolean) => ({
    trained_at: "2026-10-18T10:00:00Z",
    algorithm: "scikit-learn HistGradientBoostingRegressor",
    seed: 42,
    target: "load.residual",
    features: ["hour", "weekday", "holiday"],
    train_start: "2026-08-18T00:00:00Z",
    train_end: "2026-10-11T00:00:00Z",
    test_start: "2026-10-11T00:00:00Z",
    test_end: "2026-10-18T00:00:00Z",
    test_points: 168,
    unit: "MW",
    mae_model: active ? 900 : 2500,
    mape_model: active ? 4.2 : null,
    mae_official: 1200,
    mape_official: 5.5,
    active,
  });
  const point = {
    ts: "2026-10-18T12:00:00Z",
    load: 50000,
    wind: 20000,
    solar: 10000,
    residual_load: 20000,
    official_residual_load: 21000,
    model_residual_load: 20500,
  };

  it("OutlookView shows the model and its backtest when it beats the official forecast", async () => {
    mockFetch({
      "/api/v1/forecast/residual-load": {
        meta,
        unit: "MW",
        points: [point],
        windows: [],
        model: backtest(true),
      },
    });
    renderIntl(<OutlookView />);
    expect(await screen.findByText(/✓ Eingeblendet/)).toBeInTheDocument();
    expect(screen.getByText("900 MW")).toBeInTheDocument();
    expect(screen.getByText("4,2 %")).toBeInTheDocument();
    expect(screen.getByText(/Zusätzlich eingeblendet/)).toBeInTheDocument();
    expect(screen.getByText(/Seed 42, 3 Merkmale/)).toBeInTheDocument();
    expect(screen.getByText(/Quelle: gridpulse_model/)).toBeInTheDocument();
  });

  it("OutlookView keeps metrics visible but hides a worse model", async () => {
    mockFetch({
      "/api/v1/forecast/residual-load": {
        meta,
        unit: "MW",
        points: [point],
        windows: [],
        model: backtest(false),
      },
    });
    renderIntl(<OutlookView />, "en");
    expect(await screen.findByText(/Not shown – the official forecast/)).toBeInTheDocument();
    expect(screen.getByText("2,500 MW")).toBeInTheDocument();
    expect(screen.getByText("–")).toBeInTheDocument();
    expect(screen.getByText(/Own model not shown/)).toBeInTheDocument();
  });

  it("EventsView lists events and filters by severity", async () => {
    const fetchMock = mockFetch({
      "/api/v1/events": {
        meta,
        data: [
          {
            id: "1",
            ts: "2026-10-18T12:00:00Z",
            rule_id: "FREQ-001",
            severity: "critical",
            category: "grid",
            metric: "grid.frequency",
            area: "DE",
            value: 49.7,
            threshold: 200,
            unit: "Hz",
            source: "energy_charts",
            message: "Frequency deviation",
          },
        ],
      },
    });
    renderIntl(<EventsView />);
    expect(await screen.findByText("FREQ-001")).toBeInTheDocument();
    expect(screen.getByText("Kritisch", { selector: "span" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Mindest-Schweregrad"), {
      target: { value: "critical" },
    });
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some((c) =>
          String(c[0] instanceof Request ? c[0].url : c[0]).includes("min_severity=critical"),
        ),
      ).toBe(true);
    });
  });

  it("EventsView empty state", async () => {
    mockFetch({ "/api/v1/events": { meta, data: [] } });
    renderIntl(<EventsView />);
    expect(await screen.findByText(/Keine Ereignisse/)).toBeInTheDocument();
  });

  it("TestAlertButton reports success and failure", async () => {
    mockFetch({ "/api/alerts-test": { results: { hook: "ok" } } });
    renderIntl(<TestAlertButton />);
    fireEvent.click(screen.getByRole("button"));
    expect(await screen.findByText(/Test gesendet/)).toBeInTheDocument();
    mockFetch({ "/api/alerts-test": { detail: "disabled" } }, 403);
    fireEvent.click(screen.getByRole("button"));
    expect(await screen.findByText(/fehlgeschlagen: disabled/)).toBeInTheDocument();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new Error("offline"))),
    );
    fireEvent.click(screen.getByRole("button"));
    expect(await screen.findByText(/offline/)).toBeInTheDocument();
  });

  it("HistoryView loads, compares and offers exports", async () => {
    const fetchMock = mockFetch({ "/api/v1/observations": observations });
    renderIntl(<HistoryView now={new Date("2026-10-18T12:00:00Z")} />);
    expect(await screen.findByText(/Mittelwert – Zeitraum A/)).toBeInTheDocument();
    expect(screen.getByText("CSV exportieren").getAttribute("href")).toContain("format=csv");
    fireEvent.change(screen.getByLabelText("Vergleich von"), {
      target: { value: "2025-10-11T12:00" },
    });
    fireEvent.change(screen.getByLabelText("Vergleich bis"), {
      target: { value: "2025-10-18T12:00" },
    });
    fireEvent.change(screen.getByLabelText("Kennzahl"), { target: { value: "price.day_ahead" } });
    fireEvent.change(screen.getByLabelText("Auflösung"), { target: { value: "1d" } });
    fireEvent.change(screen.getByLabelText("Von"), { target: { value: "2026-10-10T00:00" } });
    fireEvent.change(screen.getByLabelText("Bis"), { target: { value: "2026-10-18T00:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Anzeigen" }));
    expect(await screen.findByText(/Mittelwert – Zeitraum B/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(3);
    expect(defaultQuery(new Date("2026-10-18T12:00:00Z")).to).toBe("2026-10-18T14:00");
  });

  it("StatusView shows health per source", async () => {
    mockFetch({
      "/api/v1/sources/status": {
        meta,
        data: [
          {
            source: "smard",
            license: "CC BY 4.0",
            attribution: "SMARD",
            last_attempt: null,
            last_success: "2026-10-18T12:00:00Z",
            last_error: null,
            latency_ms: 120,
            rows_last_run: 10,
            gap_ratio: 0.01,
            plausibility_violations: 0,
            consecutive_failures: 0,
            newest_data: null,
            data_age_seconds: 600,
            healthy: true,
          },
          {
            source: "entsoe",
            license: "x",
            attribution: "y",
            last_attempt: null,
            last_success: null,
            last_error: "boom",
            latency_ms: null,
            rows_last_run: 0,
            gap_ratio: 0,
            plausibility_violations: 2,
            consecutive_failures: 3,
            newest_data: null,
            data_age_seconds: null,
            healthy: false,
          },
        ],
      },
    });
    renderIntl(<StatusView />);
    expect(await screen.findByText("✓ OK")).toBeInTheDocument();
    expect(screen.getByText("✕ Gestört")).toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();
  });

  it("KioskView forces the high-contrast theme", async () => {
    mockFetch({ "/api/v1/summary/now": summary });
    const { unmount } = renderIntl(<KioskView />);
    expect(await screen.findByText("45.000 MW")).toBeInTheDocument();
    expect(document.documentElement.classList.contains("kiosk")).toBe(true);
    unmount();
    expect(document.documentElement.classList.contains("kiosk")).toBe(false);
  });
});

describe("CountriesView", () => {
  const now = new Date("2026-10-18T12:30:00Z");
  const row = (area: string, metric: string, ts: string, value: number) => ({
    ts,
    metric,
    area,
    kind: "actual",
    source: "entsoe",
    unit: metric === "load.actual" ? "MW" : "EUR/MWh",
    value,
  });

  it("shows load and price per bidding zone with unit, source and age", async () => {
    const fetchMock = mockFetch({
      "/api/v1/observations": {
        meta: { ...meta, source: "entsoe", license: "ENTSO-E T&C" },
        data: [
          row("FR", "load.actual", "2026-10-18T11:00:00Z", 52000),
          row("FR", "price.day_ahead", "2026-10-18T12:00:00Z", -12.5),
          row("FR", "price.day_ahead", "2026-10-19T12:00:00Z", 40),
          row("DE-LU", "load.actual", "2026-10-18T06:00:00Z", 60000),
        ],
      },
    });
    renderIntl(<CountriesView now={now} />);
    expect(await screen.findByText("52.000 MW")).toBeInTheDocument();
    expect(screen.getByText("-12,50 €/MWh")).toBeInTheDocument();
    expect(screen.getByText("Negativer Preis")).toBeInTheDocument();
    expect(screen.getByText("Frankreich (FR)")).toBeInTheDocument();
    expect(screen.getAllByText(/Lizenz: ENTSO-E T&C/).length).toBeGreaterThan(2);
    // DE-LU load is 6.5 h old -> marked stale; zones without data show the empty state.
    expect(screen.getAllByText(/Veraltet/).length).toBe(1);
    expect(screen.getAllByText("Keine Daten verfügbar.").length).toBe(7);
    const url = (fetchMock.mock.calls[0]?.[0] as Request).url;
    expect(url).toContain("source=entsoe");
    expect(url).toContain("area=DK1");
  });

  it("explains the missing ENTSO-E token when there is no data", async () => {
    mockFetch({ "/api/v1/observations": { meta: { ...meta, source: "none" }, data: [] } });
    renderIntl(<CountriesView now={now} />, "en");
    expect(await screen.findByText("No ENTSO-E data")).toBeInTheDocument();
    expect(screen.getByText(/GRIDPULSE_ENTSOE_TOKEN/)).toBeInTheDocument();
  });
});

describe("chrome", () => {
  it("Header has skip link, navigation, theme toggle and locale switch", () => {
    renderIntl(<Header />);
    expect(screen.getByText("Zum Inhalt springen")).toHaveAttribute("href", "#main");
    expect(screen.getByRole("link", { name: "Lage" })).toHaveAttribute("aria-current", "page");
    renderIntl(<LocaleSwitch />, "en");
  });

  it("ThemeToggle switches and persists the theme", () => {
    document.documentElement.className = "dark";
    renderIntl(<ThemeToggle />);
    fireEvent.click(screen.getByRole("button", { name: /Farbschema/ }));
    expect(currentTheme()).toBe("light");
    expect(localStorage.getItem("gridpulse-theme")).toBe("light");
    applyTheme("dark");
    expect(currentTheme()).toBe("dark");
    expect(readChartTheme().fg).toMatch(/^#|rgb/);
  });

  it("Footer shows disclaimer and licences", () => {
    renderIntl(<Footer />, "en");
    expect(screen.getByRole("note")).toHaveTextContent(
      "no substitute for certified control systems",
    );
    expect(screen.getByText(/SMARD.de/)).toBeInTheDocument();
  });
});
