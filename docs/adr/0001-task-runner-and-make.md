# 0001 – One task runner behind `make`

* Status: accepted · Date: 2026-10-18

## Context and problem

The spec requires `make check` to run exactly what CI runs. Contributors (and the
initial build machine, a Windows Server without `make` and Docker) need the same
gate without GNU make.

## Decision

All checks live in `scripts/tasks.py` (stdlib only). The `Makefile` and every CI
job call it (`make check` ≙ `uv run --project backend python scripts/tasks.py check`).
CI splits the same functions into `ci-backend` and `ci-frontend` jobs.

## Consequences

* + Identical commands locally, on Windows and in CI; no drift between Makefile and workflows.
* − One extra indirection when reading the Makefile.
