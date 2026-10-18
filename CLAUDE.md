# CLAUDE.md – Arbeitsregeln für Claude Code

Verbindliche Spezifikation: `GRIDPULSE_SPEC.md` (bzw. die Abschnitte, auf die `docs/` verweist).
Diese Regeln stammen aus Abschnitt 11 der Spezifikation.

1. **Erst prüfen, dann bauen**: Vor jeder Implementierung einer Datenquelle echte Antwort abrufen
   (`scripts/verify_sources.py --save-fixtures`) und als Fixture unter `backend/tests/fixtures/<quelle>/` speichern.
2. **Test zuerst** für `domain/` und `validation/` (TDD). Für Adapter: erst Contract-Test mit Fixture, dann `parse()`.
3. Nach **jeder** abgeschlossenen Teilaufgabe: `make check` ausführen (Windows ohne make:
   `uv run --project backend python scripts/tasks.py check`). Ist es rot, wird zuerst repariert, nichts Neues angefangen.
4. **Keine** `# type: ignore`, `# noqa`, `eslint-disable`, `any`, `.skip`/`xfail` ohne Kommentar mit Begründung
   (und Issue-Referenz, sobald ein Issue-Tracker existiert).
5. Kleine, atomare Commits im Format **Conventional Commits** (`feat(adapter): …`, `fix(api): …`, `test(domain): …`).
6. Keine Secrets, Tokens oder echten Zugangsdaten in Code, Tests oder Logs.
7. Zeitstempel immer timezone-aware (UTC). Naive `datetime` ist ein Fehler (Ruff-Regel `DTZ` erzwingt das).
8. Am Ende jeder Phase: kurzer Bericht in `docs/progress.md` – was gebaut wurde, Testergebnisse, Coverage, offene Punkte.
9. Unklare oder widersprüchliche Anforderung: als ADR in `docs/adr/` dokumentieren, sinnvoll entscheiden, weitermachen.
10. Abschließende Selbstprüfung pro Phase: Spezifikation erneut lesen und jeden DoD-Punkt einzeln abhaken.

## Projektlandkarte

- `backend/src/gridpulse/` – `adapters/` (Quellen), `domain/` (reine Logik, 100 % Coverage),
  `validation/` (Pandera + Plausibilität, 100 %), `storage/` (TimescaleDB + Alembic), `services/`, `api/`,
  `worker/`, `alerts/`.
- `frontend/` – Next.js 15 App Router, `src/lib/api/schema.ts` wird aus `docs/openapi.json` generiert
  (`pnpm generate:api`); API-Änderung ⇒ `make openapi` + `pnpm generate:api`.
- `scripts/tasks.py` – einzige Wahrheit für alle Prüfbefehle (Makefile und CI rufen es auf).
- Integrationstests brauchen TimescaleDB: `GRIDPULSE_TEST_DATABASE_URL` oder Docker (Testcontainers).
