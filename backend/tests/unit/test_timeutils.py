from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from gridpulse.domain.timeutils import (
    BERLIN,
    NaiveDatetimeError,
    ensure_utc,
    floor_to,
    from_unix_millis,
    from_unix_seconds,
    local_day_bounds,
    local_day_length,
    to_berlin,
    to_unix_millis,
)


def test_ensure_utc_rejects_naive() -> None:
    with pytest.raises(NaiveDatetimeError):
        ensure_utc(datetime(2026, 1, 1))  # noqa: DTZ001 - deliberately naive input


def test_ensure_utc_converts_offset() -> None:
    value = datetime(2026, 1, 1, 12, tzinfo=timezone(timedelta(hours=2)))
    assert ensure_utc(value) == datetime(2026, 1, 1, 10, tzinfo=UTC)
    assert ensure_utc(value).tzinfo is UTC


def test_unix_roundtrip() -> None:
    value = datetime(2026, 3, 29, 1, 15, tzinfo=UTC)
    assert from_unix_millis(to_unix_millis(value)) == value
    assert from_unix_seconds(value.timestamp()) == value


@pytest.mark.parametrize(
    ("day", "hours"),
    [
        (date(2026, 3, 29), 23),  # spring forward
        (date(2026, 10, 25), 25),  # fall back
        (date(2026, 6, 1), 24),
        (date(2025, 3, 30), 23),
        (date(2025, 10, 26), 25),
    ],
)
def test_local_day_length_dst(day: date, hours: int) -> None:
    assert local_day_length(day) == timedelta(hours=hours)


def test_local_day_bounds_are_utc_midnights_in_berlin() -> None:
    start, end = local_day_bounds(date(2026, 10, 25))
    assert start == datetime(2026, 10, 24, 22, tzinfo=UTC)
    assert end == datetime(2026, 10, 25, 23, tzinfo=UTC)
    assert to_berlin(start).hour == 0
    assert to_berlin(end).hour == 0


def test_floor_to() -> None:
    value = datetime(2026, 1, 1, 10, 7, 33, tzinfo=UTC)
    assert floor_to(value, timedelta(minutes=15)) == datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    assert floor_to(value, timedelta(seconds=10)) == datetime(2026, 1, 1, 10, 7, 30, tzinfo=UTC)


def test_to_berlin_summer_offset() -> None:
    assert to_berlin(datetime(2026, 7, 1, 12, tzinfo=UTC)).utcoffset() == timedelta(hours=2)
    assert to_berlin(datetime(2026, 1, 1, 12, tzinfo=UTC)).tzinfo == BERLIN
