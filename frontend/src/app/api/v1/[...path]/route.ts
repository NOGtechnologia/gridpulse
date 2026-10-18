/**
 * Same-origin proxy to the GridPulse API. The target is read at *runtime* from
 * GRIDPULSE_API_URL, so one image works in every deployment (no CORS needed).
 */
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

const API_URL = (): string => process.env.GRIDPULSE_API_URL ?? "http://localhost:8000";
const FORWARD_REQUEST_HEADERS = ["accept", "x-api-key"];
const FORWARD_RESPONSE_HEADERS = [
  "content-type",
  "content-disposition",
  "cache-control",
  "retry-after",
];

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await params;
  const target = new URL(`/api/v1/${path.map(encodeURIComponent).join("/")}`, API_URL());
  target.search = request.nextUrl.search;
  const headers = new Headers();
  for (const name of FORWARD_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const forwarded = request.headers.get("x-forwarded-for");
  if (forwarded) headers.set("x-forwarded-for", forwarded);
  try {
    const upstream = await fetch(target, { headers, cache: "no-store" });
    const out = new Headers();
    for (const name of FORWARD_RESPONSE_HEADERS) {
      const value = upstream.headers.get(name);
      if (value) out.set(name, value);
    }
    return new Response(upstream.body, { status: upstream.status, headers: out });
  } catch {
    return Response.json({ detail: "API unreachable" }, { status: 502 });
  }
}
