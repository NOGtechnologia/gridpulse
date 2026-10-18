## What and why

<!-- Short description, link the issue. Title in Conventional Commits format. -->

## Checklist

- [ ] `make check` is green locally
- [ ] Tests added/updated (TDD for `domain/` and `validation/`)
- [ ] New data source? Real fixture recorded + contract test
- [ ] API changed? `make openapi` and `pnpm --dir frontend generate:api` run
- [ ] UI texts in `messages/de.json` and `messages/en.json`
- [ ] Every new number shows unit, data timestamp and source
- [ ] Docs / ADR updated where relevant
- [ ] No secrets, no `# noqa` / `type: ignore` / `eslint-disable` without justification
