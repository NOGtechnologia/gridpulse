import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

// jsdom lacks ResizeObserver (used by the chart wrapper).
class ResizeObserverStub {
  observe(): void {}
  disconnect(): void {}
  unobserve(): void {}
}
// Assigned directly (not vi.stubGlobal) so that unstubAllGlobals() keeps it.
globalThis.ResizeObserver = ResizeObserverStub;

// Charts and maps need canvas/WebGL; they are replaced with light stubs in unit tests.
vi.mock("echarts/core", () => {
  const instance = { setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() };
  return { use: vi.fn(), init: vi.fn(() => instance) };
});
vi.mock("echarts/charts", () => ({ LineChart: {}, PieChart: {}, BarChart: {} }));
vi.mock("echarts/components", () => ({
  GridComponent: {},
  TooltipComponent: {},
  LegendComponent: {},
  AriaComponent: {},
  MarkAreaComponent: {},
  MarkLineComponent: {},
  DataZoomComponent: {},
}));
vi.mock("echarts/renderers", () => ({ SVGRenderer: {} }));
vi.mock("maplibre-gl/dist/maplibre-gl.css", () => ({}));
vi.mock("maplibre-gl", () => {
  class Marker {
    setLngLat() {
      return this;
    }
    addTo() {
      return this;
    }
    remove() {}
  }
  class Map {
    getCanvas() {
      return document.createElement("canvas");
    }
    remove() {}
  }
  return { Map, Marker, setWorkerUrl: vi.fn() };
});

vi.mock("@/i18n/navigation", async () => {
  const React = await import("react");
  return {
    Link: ({ href, children, ...rest }: Record<string, unknown>) => {
      delete rest.locale; // not a valid <a> attribute
      return React.createElement("a", { href: String(href), ...rest }, children as React.ReactNode);
    },
    usePathname: () => "/",
    useRouter: () => ({ push: vi.fn() }),
  };
});
