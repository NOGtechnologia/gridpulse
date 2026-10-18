/**
 * UI test button (spec Phase 5). The admin token stays on the server
 * (GRIDPULSE_ADMIN_TOKEN) and is never sent to the browser.
 */
export const dynamic = "force-dynamic";

export async function POST(): Promise<Response> {
  const token = process.env.GRIDPULSE_ADMIN_TOKEN;
  if (!token) {
    return Response.json({ detail: "test notifications disabled" }, { status: 403 });
  }
  const base = process.env.GRIDPULSE_API_URL ?? "http://localhost:8000";
  try {
    const upstream = await fetch(new URL("/api/v1/alerts/test", base), {
      method: "POST",
      headers: { "X-Admin-Token": token },
      cache: "no-store",
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
    });
  } catch {
    return Response.json({ detail: "API unreachable" }, { status: 502 });
  }
}
