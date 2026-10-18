# 0009 – Locale resolution via `next/root-params`

* Status: accepted · Date: 2026-10-18

## Context

next-intl 4.14 deprecates `setRequestLocale` / `requestLocale` in favour of
`next/root-params`; the strict ESLint config (no deprecated APIs) rejects the old API.
In Next.js 15.5 root params are experimental.

## Decision

Enable `experimental.rootParams` and read the `[locale]` root segment in
`src/i18n/request.ts`. The untyped placeholder module is narrowed with a single
documented type assertion.

## Consequences

Static generation of all locale pages keeps working; when upgrading to Next.js 16
the experimental flag can be removed.
