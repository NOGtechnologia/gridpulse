# GridPulse - every target delegates to scripts/tasks.py so that local runs,
# Windows and CI execute identical commands (spec 7.1).
#
#   make check          lint typecheck test-unit test-integration test-frontend build security
#   make e2e            Playwright + axe + Lighthouse against the Docker Compose stack
#   make verify-sources live check of all external data sources (manual / nightly)

TASK := uv run --project backend --frozen python scripts/tasks.py

.PHONY: check lint typecheck test-unit test-integration test-frontend build security licenses \
        openapi e2e verify-sources install up up-demo down

check lint typecheck test-unit test-integration test-frontend build security licenses e2e verify-sources:
	$(TASK) $@

openapi:
	$(TASK) openapi

install:
	cd backend && uv sync --frozen
	cd frontend && pnpm install --frozen-lockfile
	uvx pre-commit install --hook-type pre-commit --hook-type commit-msg

up:
	docker compose -f deploy/docker-compose.yml up -d --build

up-demo:
	GRIDPULSE_DEMO=1 docker compose -f deploy/docker-compose.yml up -d --build

down:
	docker compose -f deploy/docker-compose.yml down
