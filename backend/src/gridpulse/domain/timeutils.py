"""Time handling: everything internal is UTC, display is Europe/Berlin (spec 5.4)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")


class NaiveDatetimeError(ValueError):
    """Raised when a timezone-naive datetime enters the system."""


def ensure_utc(value: datetime) -> datetime:
    """Return ``value`` converted to UTC; naive datetimes are rejected."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise NaiveDatetimeError(f"naive datetime not allowed: {value!r}")
    return value.astimezone(UTC)


def from_unix_seconds(seconds: float) -> datetime:
    return datetime.fromtimestamp(seconds, tz=UTC)


def from_unix_millis(millis: float) -> datetime:
    return datetime.fromtimestamp(millis / 1000, tz=UTC)


def to_unix_millis(value: datetime) -> int:
    return int(ensure_utc(value).timestamp() * 1000)


def local_day_bounds(day: date) -> tuple[datetime, datetime]:
    """UTC start (inclusive) and end (exclusive) of a calendar day in Europe/Berlin.

    The span is 23 h on the spring-forward day and 25 h on the fall-back day.
    """
    start_local = datetime(day.year, day.month, day.day, tzinfo=BERLIN)
    nxt = day + timedelta(days=1)
    end_local = datetime(nxt.year, nxt.month, nxt.day, tzinfo=BERLIN)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def local_day_length(day: date) -> timedelta:
    start, end = local_day_bounds(day)
    return end - start


def floor_to(value: datetime, step: timedelta) -> datetime:
    """Floor an aware datetime to a multiple of ``step`` since the Unix epoch (UTC)."""
    utc = ensure_utc(value)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    steps = (utc - epoch) // step
    return epoch + steps * step


def to_berlin(value: datetime) -> datetime:
    return ensure_utc(value).astimezone(BERLIN)
