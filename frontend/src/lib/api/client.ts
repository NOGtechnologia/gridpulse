import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type SummaryNow = Schemas["SummaryNow"];
export type Value = Schemas["Value"];
export type ForecastResponse = Schemas["ForecastResponse"];
export type EventsResponse = Schemas["EventsResponse"];
export type EventOut = Schemas["EventOut"];
export type SourcesResponse = Schemas["SourcesResponse"];
export type ObservationsResponse = Schemas["ObservationsResponse"];
export type ObservationOut = Schemas["ObservationOut"];
export type MetricId = Schemas["MetricId"];
export type QueryResolution = Schemas["QueryResolution"];
export type Severity = Schemas["Severity"];

/** Browser and server share one origin: /api/v1 is proxied by src/app/api/v1/[...path]. */
export const api = createClient<paths>({
  baseUrl: typeof window === "undefined" ? "" : window.location.origin,
  // Resolve fetch at call time (allows instrumentation and test doubles).
  fetch: (request: Request) => globalThis.fetch(request),
});

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Unwrap an openapi-fetch result or throw an ApiError. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.data === undefined) {
    throw new ApiError(`HTTP ${result.response.status}`, result.response.status);
  }
  return result.data;
}

export function exportUrl(params: Record<string, string | string[]>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    for (const v of Array.isArray(value) ? value : [value]) search.append(key, v);
  }
  return `/api/v1/export?${search.toString()}`;
}
