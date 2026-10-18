# 0005 – Repository protocol with TimescaleDB and in-memory implementations

* Status: accepted · Date: 2026-10-18

## Context

API, services and worker need fast, deterministic tests (including Schemathesis)
without a database, while storage semantics must be verified against a real
TimescaleDB.

## Decision

A `Repository` protocol with two implementations: `SqlRepository` (production,
integration-tested against TimescaleDB 2.30 with Testcontainers or
`GRIDPULSE_TEST_DATABASE_URL`) and `MemoryRepository` (same semantics incl. bucket
means and Berlin calendar days; used by unit/API/Schemathesis tests).
`GRIDPULSE_DATABASE_URL=memory://` selects it explicitly.

## Consequences

* + Unit tests are fast and need no Docker; storage specifics are covered by integration tests.
* − Two implementations must stay in sync (guarded by mirrored tests).
