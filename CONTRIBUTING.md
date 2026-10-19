# Contributing to GridPulse

Thanks for helping! GridPulse aims to be boringly reliable – every change goes
through the same automated quality gate.

## Setup

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/), [pnpm](https://pnpm.io) (Node 22).

```bash
make install        # backend + frontend dependencies, pre-commit hooks
docker compose -f deploy/docker-compose.dev.yml up -d   # TimescaleDB for development
make check          # everything CI runs
```

Windows without `make`: `uv run --project backend python scripts/tasks.py check`.

## Rules

- **Conventional Commits** (`feat(api): …`, `fix(adapter): …`, `test(domain): …`), small and atomic.
- `make check` must be green before you push; CI enforces the same thresholds:
  coverage ≥ 90 % overall and 100 % for `domain/` and `validation/`, `mypy --strict`,
  ESLint strict, Vitest coverage ≥ 80 %, Schemathesis, axe, Lighthouse.
- Tests first for `domain/` and `validation/`. New data source? Record real responses
  first (`scripts/verify_sources.py --save-fixtures`), write the contract test, then `parse()`.
- No `# type: ignore`, `# noqa`, `eslint-disable`, `any`, `skip`/`xfail` without a comment
  explaining why (and an issue reference).
- Never commit secrets – gitleaks runs in pre-commit and CI.
- All timestamps are timezone-aware UTC; units are always explicit.
- UI texts go through `next-intl` (`frontend/messages/{de,en}.json`), no hard-coded strings.
- Significant decisions are recorded as ADRs (`docs/adr/`, MADR format).

## Lighthouse locally

CI runs `pnpm run lhci` against the compose stack (`frontend/lighthouserc.json`).
Locally, start the production build (`pnpm build && pnpm start`) with an API behind
it, then run `pnpm --dir frontend lhci` (needs Chrome, or set `CHROME_PATH`).

If Chrome cannot be launched (e.g. Windows Server: `spawn UNKNOWN`), start
Playwright's headless shell yourself and let Lighthouse attach to it:

```bash
chrome-headless-shell --remote-debugging-port=9222 about:blank
pnpm --dir frontend exec lhci collect --settings.port=9222
pnpm --dir frontend exec lhci assert
```

Tiles reserve their final height while loading (`Tile skeletonHeight`) – keep
it in sync when a chart height changes, otherwise CLS breaks the performance score.

## API changes

The OpenAPI file is generated: change the code, then run `make openapi` and
`pnpm --dir frontend generate:api`. `make build` fails if either is outdated.

## Branch protection (maintainers)

`main` accepts changes only via pull request, all status checks (`ci`, `e2e`,
`codeql`, `docker`) are required, linear history is enforced and force pushes are disabled.
