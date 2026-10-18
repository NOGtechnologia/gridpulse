"""Load realistic synthetic demo data into the configured database.

    GRIDPULSE_DATABASE_URL=... uv run --project backend python scripts/seed_demo_data.py

The worker does the same automatically on start when ``GRIDPULSE_DEMO=1``.
All rows are labelled ``source=demo`` (CC0) and can never be mistaken for real data.
"""

from __future__ import annotations

import asyncio
import sys

from gridpulse.settings import get_settings
from gridpulse.storage import create_repository, migrate
from gridpulse.worker.main import seed_demo


async def main() -> int:
    settings = get_settings()
    if not settings.database_url.startswith("memory://"):
        await asyncio.to_thread(migrate.upgrade, settings.database_url)
    repo = create_repository(settings.database_url)
    try:
        rows = await seed_demo(repo)
    finally:
        await repo.close()
    print(f"seeded {rows} demo rows")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
