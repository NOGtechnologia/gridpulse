# 0007 – Offline border-flow map without tile server

* Status: accepted · Date: 2026-10-18

## Context

The spec requires MapLibre GL "without key, free tiles". Demo mode and E2E tests
must work without internet; external tile/glyph servers would also need CSP
exceptions and a privacy review.

## Decision

MapLibre renders a fully local style: Germany and its neighbours from Natural Earth
(public domain, trimmed to 63 kB by `scripts/build_geo.py`). Labels are HTML
markers (no glyph server). The map is decorative for assistive technology; the
adjacent table carries the data.

## Consequences

Works offline, no third-party requests, no API key. No street-level detail – not
needed for border flows.
