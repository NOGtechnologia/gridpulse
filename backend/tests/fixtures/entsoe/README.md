# ENTSO-E fixtures

No ENTSO-E security token was available when the fixtures were recorded
(2026-10-18), so the live response could not be captured (spec section 3 allows this,
see `docs/data-sources.md`).

The XML files in this folder are **constructed** to follow the structure documented in
the *ENTSO-E Transparency Platform RESTful API – Implementation Guide* and the
IEC 62325-451-6 schemas (`GL_MarketDocument` for load, `Publication_MarketDocument`
for prices, `Acknowledgement_MarketDocument` for errors). The values are invented.

Replace them with real responses as soon as a token exists:

```bash
GRIDPULSE_ENTSOE_TOKEN=... uv run --project backend python scripts/verify_sources.py --save-fixtures
```

Tracked in `docs/progress.md` under "open points".
