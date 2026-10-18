# 0006 – Same-origin API proxy in the web app

* Status: accepted · Date: 2026-10-18

## Context

Next.js rewrites are fixed at build time; the API URL differs per deployment.
Calling the API directly from the browser would need CORS and a public API URL.

## Decision

`frontend/src/app/api/v1/[...path]/route.ts` proxies GET requests to
`GRIDPULSE_API_URL`, read at runtime. The browser only talks to the web origin; the
CSP can stay `connect-src 'self'`. The admin token for the alert test button is
added server-side by `/api/alerts-test` and never reaches the browser.

## Consequences

One web image for all environments, strict CSP, no CORS configuration needed for
the dashboard (CORS remains configurable for third-party API consumers).
