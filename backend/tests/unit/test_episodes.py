from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from gridpulse.domain.metrics import Kind, MetricId
from gridpulse.domain.observations import concat_frames, make_frame
from gridpulse.domain.rules import Event, EventCategory, RuleConfig, Severity, merge_episodes
from gridpulse.services.summary import build_summary
from gridpulse.storage.memory import MemoryRepository

T0 = datetime(2026, 10, 18, 6, tzinfo=UTC)
Q = timedelta(minutes=15)


def _e(
    minute: int, value: float | None, severity: Severity = Severity.WARNING, rule: str = "FCST-001"
) -> Event:
    return Event(
        ts=T0 + timedelta(minutes=minute),
        rule_id=rule,
        severity=severity,
        category=EventCategory.FORECAST,
        metric="generation.solar",
        area="DE",
        value=value,
        threshold=100.0,
        source="smard",
        message="err",
    )


def test_merge_episodes_collapses_consecutive_points() -> None:
    events = [
        _e(0, 150.0),
        _e(15, 400.0),
        _e(30, -300.0),
        _e(120, 200.0),
        _e(15, 900.0, Severity.CRITICAL),
    ]
    merged = merge_episodes(events, timedelta(minutes=30))
    assert len(merged) == 3
    first = next(e for e in merged if e.severity is Severity.WARNING and e.ts == T0)
    assert first.value == 400.0  # worst point of the episode
    assert "episode 06:00-06:30Z, 3 points" in first.message
    assert first.id == _e(0, 1.0).id  # id anchored at the episode start
    lone = next(e for e in merged if e.ts == T0 + timedelta(minutes=120))
    assert lone.message == "err"
    assert merge_episodes([], Q) == []


def test_merge_episodes_handles_missing_values() -> None:
    merged = merge_episodes([_e(0, None), _e(1, None)], timedelta(minutes=5))
    assert len(merged) == 1 and merged[0].value is None


async def test_summary_uses_newest_complete_timestamp() -> None:
    """SMARD publishes load one interval after wind; the mix must use a common timestamp."""
    repo = MemoryRepository()

    def frame(metric: MetricId, n: int, source: str) -> pd.DataFrame:
        return make_frame(
            timestamps=[T0 + i * Q for i in range(n)],
            values=[1000.0 + i for i in range(n)],
            metric=metric,
            area="DE",
            kind=Kind.ACTUAL,
            source=source,
            resolution=Q,
        )

    await repo.upsert_observations(
        concat_frames(
            [
                frame(MetricId.GENERATION_WIND_ONSHORE, 5, "smard"),
                frame(MetricId.LOAD_ACTUAL, 4, "smard"),
                frame(MetricId.GENERATION_WIND_ONSHORE, 3, "energy_charts"),
                frame(MetricId.LOAD_ACTUAL, 3, "energy_charts"),
            ]
        )
    )
    summary = await build_summary(repo, T0 + timedelta(hours=2), RuleConfig())
    assert summary.as_of == T0 + 3 * Q
    assert summary.load.value == 1003.0 and summary.load.source == "smard"
    assert summary.residual_load.value == 0.0
