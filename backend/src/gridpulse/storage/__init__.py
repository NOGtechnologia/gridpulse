"""Persistence: repository interface, TimescaleDB and in-memory implementations."""

from __future__ import annotations

from gridpulse.storage.memory import MemoryRepository
from gridpulse.storage.repository import Repository


def create_repository(database_url: str) -> Repository:
    """``memory://`` selects the in-memory repository (tests / offline demo)."""
    if database_url.startswith("memory://"):
        return MemoryRepository()
    from gridpulse.storage.sql import SqlRepository  # noqa: PLC0415 - avoid DB driver import for memory mode

    return SqlRepository(database_url)
