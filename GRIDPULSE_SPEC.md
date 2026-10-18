# GridPulse – Open-Source Netz-Lagebild für Stromnetzbetreiber

> Verbindliche Projektspezifikation (Stand 2026-10-18). Abweichungen der Realität
> (z. B. Datenquellen) sind in `docs/data-sources.md` und `docs/adr/` dokumentiert;
> der Umsetzungsstand steht in `docs/progress.md`.

---

## 1. Vision

**GridPulse** ist ein selbst hostbares, quelloffenes Dashboard, das Netzbetreibern (Stadtwerke, Verteilnetzbetreiber, Energiegenossenschaften, kommunale Energieagenturen) sowie Leitwarten-Analysten ein **echtzeitnahes Lagebild des deutschen und europäischen Stromsystems** liefert – ausschließlich aus öffentlichen, offiziellen Datenquellen.

Kernfrage: *„Wie ist die Lage im Netz gerade, was kommt in den nächsten 24–48 Stunden auf uns zu, und gibt es Auffälligkeiten?"*

### Zielgruppen
| Rolle | Nutzen |
|---|---|
| Netzleitstelle / Schichtleitung | Netzfrequenz, Residuallast, Erzeugungsmix, Warnungen auf einen Blick |
| Energiehandel / Beschaffung | Day-Ahead-Preise, negative Preisphasen, Prognosen |
| Netzplanung | Historische Analysen, Lastgänge, EE-Einspeisung, Exporte |
| Kommunikation / Öffentlichkeit | CO₂-Intensität, EE-Anteil, öffentliches Kiosk-Dashboard |

### Nicht-Ziele
- **Keine** Anbindung an SCADA/Leittechnik, **keine** Steuerbefehle ins Netz. GridPulse ist rein lesend und beratend.
- Keine personenbezogenen Daten, keine Smart-Meter-Einzeldaten.
- Kein Ersatz für zertifizierte Leitsysteme – das muss in UI und README klar stehen.

## 2. Funktionsumfang

### 2.1 Live-Lagebild („Lage")
- Netzfrequenz (50-Hz-Abweichung) mit Ampel: grün ±50 mHz, gelb ±100 mHz, rot darüber; Sparkline der letzten 60 min.
- Aktueller Erzeugungsmix (Wind on/offshore, PV, Biomasse, Wasser, Kernkraft historisch, Braunkohle, Steinkohle, Gas, Pumpspeicher, Sonstige) als gestapelte Fläche + Donut.
- Netzlast & Residuallast (Last minus Wind minus PV).
- EE-Anteil in % und CO₂-Intensität in g/kWh (dokumentierte Emissionsfaktoren, Quelle im Code).
- Day-Ahead-Preis (Gebotszone DE-LU) mit Kennzeichnung negativer Preise.
- Grenzüberschreitende Flüsse (Import/Export je Nachbarland) als Karte.

### 2.2 Prognose („Ausblick")
- Residuallast-Prognose 48 h aus offiziellen Prognosen (Last, Wind, PV).
- Optional eigenes Modell (Phase 7) mit Backtest-Kennzahlen (MAE, MAPE) gegen die offizielle Prognose.
- Hinweis-Fenster: erwartete Stunden mit negativen Preisen, Dunkelflaute-Risiko (Wind+PV < X % der Last über ≥ N Stunden, konfigurierbar).

### 2.3 Anomalie- und Ereigniserkennung („Ereignisse")
- Regelbasiert: Frequenzausreißer, Prognosefehler > Schwellwert, extreme Preisspitzen, fehlende/verspätete Daten.
- Statistisch: rollierender Z-Score / MAD auf Residuallast und Frequenz.
- Jedes Ereignis: Zeitstempel (UTC), Schweregrad, Regel-ID, Messwert, Schwelle, Datenquelle.
- Benachrichtigungen per Webhook (JSON), E-Mail (SMTP), optional Teams/Slack-kompatibler Webhook.

### 2.4 Analyse („Historie")
- Frei wählbarer Zeitraum, Auflösung 15 min / 1 h / 1 Tag; Vergleich zweier Zeiträume.
- Export als CSV und Parquet mit Quellenangabe und Lizenzhinweis.

### 2.5 Datenqualität („Status")
- Pro Quelle: letzter erfolgreicher Abruf, Latenz, Lückenquote, Plausibilitätsverstöße.
- Öffentliche Statusseite + Prometheus-Metriken.

### 2.6 Öffentliche API
- REST-API (OpenAPI 3.1, generiert) unter `/api/v1`, read-only, Rate-Limit, optionale API-Keys.

### 2.7 Kiosk-Modus
- Vollbild für Leitwarten-Wandbildschirme, Auto-Refresh, Dark Mode, hoher Kontrast, keine Interaktion nötig.

## 3. Datenquellen

| Quelle | Inhalt | Zugang | Lizenz |
|---|---|---|---|
| SMARD (Bundesnetzagentur) | Erzeugung, Last, Prognosen, Großhandelspreise (DE) | JSON-Chart-Daten, kein Key | CC BY 4.0 |
| Energy-Charts API (Fraunhofer ISE) | Erzeugung, Preise, Flüsse, Netzfrequenz, EE-Anteil | REST, kein Key | CC BY 4.0 |
| ENTSO-E Transparency Platform | Europaweite Last, Erzeugung, Flüsse, Preise | REST, Security Token | ENTSO-E T&C |
| Open-Meteo | Wetter-/Strahlungsprognosen | REST, kein Key | CC BY 4.0 |

Jede Quelle ist ein Adapter hinter einem gemeinsamen Interface; ENTSO-E ist optional. Quellenangabe und Lizenz in UI, API (`meta.source`, `meta.license`) und Exporten. Höfliches Abrufverhalten (Caching, Backoff mit Jitter, Intervalle, User-Agent).

## 4. Tech-Stack

Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async), uv · PostgreSQL 16 + TimescaleDB, Alembic · APScheduler (Worker) · Pydantic + Pandera · Next.js 15 (App Router), React, TypeScript strict, Tailwind + shadcn/ui, ECharts, MapLibre GL, pnpm · Docker/Compose · Prometheus, JSON-Logs, OpenTelemetry (optional).

## 5. Architektur

Worker (Adapter → Validierung → Normalisierung → Speicherung → Regeln/Alerts) → PostgreSQL/TimescaleDB → API (FastAPI) → Web (Next.js).

- Adapter-Interface: `source_id`, `license`, `attribution`, `async fetch(metric, start, end) -> RawPayload`, `parse(payload) -> DataFrame` (rein, ohne I/O, gegen Fixtures getestet).
- Kanonische Tabelle `observations` (Hypertable): `ts` (UTC, Intervallbeginn), `resolution`, `metric`, `area`, `value`, `unit`, `kind` (actual|forecast), `source`, `ingested_at`; PK (`ts`, `metric`, `area`, `kind`, `source`); idempotenter Upsert; Continuous Aggregates 1 h und 1 Tag. Weitere Tabellen: `events`, `source_status`, `alert_channels`, `api_keys` (nur Hash).
- Intern UTC, Anzeige Europe/Berlin; 23-h- und 25-h-Tage explizit testen. Einheiten nie implizit.

## 6. Repository-Struktur

Siehe Repository (`backend/`, `frontend/`, `deploy/`, `docs/`, `scripts/`, `.github/`, Lizenz- und Community-Dateien).

## 7. Qualitätssicherung

`make check = make lint typecheck test-unit test-integration test-frontend build security`, zusätzlich `make e2e` und `make verify-sources`.

- Backend: ruff (E,F,I,B,UP,S,SIM,RUF,ASYNC,DTZ,PL), mypy --strict, pytest, Coverage ≥ 90 % gesamt und 100 % für `domain/` und `validation/`, Hypothesis-Property-Tests, Integration mit echter TimescaleDB (Migration up/down, Upsert-Idempotenz), Contract-Tests gegen Original-Fixtures, Schemathesis, nächtliche Mutationstests (≥ 80 %).
- Frontend: ESLint strict + Prettier, `tsc --noEmit` (strict, noUncheckedIndexedAccess), Vitest ≥ 80 %, Playwright (Chromium, Firefox, WebKit), axe (0 serious/critical, Ziel WCAG 2.2 AA), Lighthouse (Perf ≥ 90, A11y ≥ 95, BP ≥ 95), visuelle Regression (0,2 %).
- Datenplausibilität zur Laufzeit und in Tests (Frequenz 49–51 Hz, Erzeugung ≥ 0, PV nachts ≈ 0, Bilanz, Preisgrenzen, Zeitachse, Quellen-Kreuzprüfung); Verstöße werden als `data_quality`-Ereignis protokolliert, nicht still verworfen.
- Sicherheit: CodeQL, Bandit-Regeln, pip-audit, pnpm audit, Dependabot, gitleaks, Trivy, Hadolint, Syft-SBOM, Lizenzprüfung, Actions auf SHA gepinnt, `permissions: read-all`, OpenSSF Scorecard, gehärtete Container.
- Pre-commit: ruff, ruff-format, mypy, prettier, eslint, gitleaks, Basis-Hooks, commitlint.
- CI: `ci.yml`, `e2e.yml`, `codeql.yml`, `nightly.yml`, `release.yml` (release-please, Multi-Arch, SBOM, cosign); Branch-Schutz in README dokumentiert.

## 8. UI/UX

Ruhig, sachlich, leitwartentauglich; Dark Mode Standard, Light verfügbar. Einheitliche, farbenblindsichere Farben je Energieträger; Information nie nur über Farbe. Jede Zahl mit Einheit, Zeitstempel und Quelle; „Datenstand: vor X min", veraltete Daten markiert. Responsive, vollständig per Tastatur bedienbar. DE (Standard) und EN über `next-intl`. Leer-, Lade- und Fehlerzustände je Kachel. Zahlenformat nach Locale.

## 9. Konfiguration & Betrieb

Nur Umgebungsvariablen (`.env.example`). `docker compose up` startet den Stack; `GRIDPULSE_DEMO=1` lädt Demo-Daten. `/healthz`, `/readyz`, `/metrics`. Backups und Retention in `docs/operations.md`.

## 10. Dokumentation

README, `docs/architecture.md`, `docs/data-sources.md`, `docs/api.md` + OpenAPI-Datei, `docs/adr/` (MADR), CONTRIBUTING, SECURITY, CODE_OF_CONDUCT, CHANGELOG, NOTICE. Lizenz Apache-2.0.

## 11. Arbeitsregeln für Claude Code

Siehe `CLAUDE.md`.

## 12. Umsetzungsphasen

0. Fundament & Quellenverifikation · 1. Datenkern · 2. Domänenlogik · 3. API · 4. Frontend · 5. Alerts & Betrieb · 6. ENTSO-E & Europa · 7. Eigenes Prognosemodell (optional) · 8. Release-Reife.
Definition of Done je Phase: siehe `docs/progress.md`.

## 13. Abnahmekriterien

- Frischer Klon → `make check` grün.
- `docker compose up` → Dashboard mit Demo-Daten unter `http://localhost:3000` in < 2 min.
- Mit Internet: Live-Daten von SMARD und Energy-Charts, automatische Aktualisierung.
- Alle Schwellen aus Abschnitt 7 in der CI erzwungen.
- Jede angezeigte Zahl hat Einheit, Zeitstand und Quelle.
- Keine Secrets im Repo (gitleaks über gesamte History).
- Haftungsausschluss und Datenlizenzen in README, UI-Footer und NOTICE.
