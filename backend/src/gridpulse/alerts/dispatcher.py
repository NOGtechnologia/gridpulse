"""Routes new events to channels with debouncing (no alert spam, spec Phase 5)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import httpx

from gridpulse.alerts.channels import Channel, ChatWebhookChannel, SmtpChannel, WebhookChannel
from gridpulse.domain.rules.model import Event, EventCategory, Severity
from gridpulse.observability import ALERTS_SENT, get_logger
from gridpulse.settings import Settings
from gridpulse.storage.repository import AlertChannel, Repository

log = get_logger(__name__)


def channel_from_config(
    config: AlertChannel, client: httpx.AsyncClient, settings: Settings
) -> Channel:
    if config.kind == "webhook":
        return WebhookChannel(config.name, config.target, client, config.min_severity)
    if config.kind in {"slack", "teams"}:
        return ChatWebhookChannel(config.name, config.target, client, config.min_severity)
    if config.kind == "smtp":
        if not settings.smtp_host:
            raise ValueError("smtp channel requires GRIDPULSE_SMTP_HOST")
        return SmtpChannel(
            name=config.name,
            host=settings.smtp_host,
            port=settings.smtp_port,
            sender=settings.smtp_from,
            recipients=[config.target],
            user=settings.smtp_user,
            password=settings.smtp_password.get_secret_value() if settings.smtp_password else None,
            starttls=settings.smtp_starttls,
            min_severity=config.min_severity,
        )
    raise ValueError(f"unknown channel kind {config.kind!r}")


async def channels_from_settings(
    repo: Repository, client: httpx.AsyncClient, settings: Settings
) -> list[Channel]:
    """Channels from ENV (webhook URLs, SMTP) plus the ones stored in ``alert_channels``."""
    min_sev = Severity(settings.alert_min_severity)
    configs = [
        AlertChannel(f"env-webhook-{i}", "webhook", url, min_sev)
        for i, url in enumerate(settings.alert_webhook_urls)
    ]
    configs += [
        AlertChannel(f"env-smtp-{i}", "smtp", to, min_sev) for i, to in enumerate(settings.smtp_to)
    ]
    configs += [c for c in await repo.list_alert_channels() if c.enabled]
    return [channel_from_config(c, client, settings) for c in configs]


class AlertDispatcher:
    def __init__(self, repo: Repository, channels: Sequence[Channel], debounce: timedelta) -> None:
        self.repo = repo
        self.channels = list(channels)
        self.debounce = debounce

    async def _debounced(self, events: Sequence[Event], now: datetime) -> list[Event]:
        """One notification per (rule, area, metric) and debounce window."""
        selected: list[Event] = []
        seen: set[tuple[str, str, str]] = set()
        for event in sorted(events, key=lambda e: (-e.severity.rank, e.ts)):
            key = (event.rule_id, event.area, event.metric)
            if key in seen:
                continue
            last = await self.repo.last_notified(*key)
            if last is not None and now - last < self.debounce:
                continue
            seen.add(key)
            selected.append(event)
        return selected

    async def dispatch(self, events: Sequence[Event], now: datetime | None = None) -> list[Event]:
        """Send new events; returns the events that were actually notified."""
        now = now or datetime.now(UTC)
        if not events or not self.channels:
            return []
        selected = await self._debounced(events, now)
        notified: set[str] = set()
        for channel in self.channels:
            batch = [e for e in selected if e.severity.rank >= channel.min_severity.rank]
            if not batch:
                continue
            try:
                await channel.send(batch)
                ALERTS_SENT.labels(channel.name, "ok").inc()
                notified.update(e.id for e in batch)
            except Exception as exc:
                ALERTS_SENT.labels(channel.name, "error").inc()
                # The channel target (URL/address) may contain a secret and is never logged.
                log.warning("alert_send_failed", channel=channel.name, error=type(exc).__name__)
        await self.repo.mark_notified(sorted(notified), now)
        return [e for e in selected if e.id in notified]

    async def send_test(self, now: datetime | None = None) -> dict[str, str]:
        """Send a test notification to every channel (UI test button); not debounced."""
        now = now or datetime.now(UTC)
        event = Event(
            ts=now,
            rule_id="TEST-000",
            severity=Severity.CRITICAL,
            category=EventCategory.GRID,
            metric="test",
            area="TEST",
            value=None,
            threshold=None,
            source="gridpulse",
            message="GridPulse test notification - no action required",
        )
        results: dict[str, str] = {}
        for channel in self.channels:
            try:
                await channel.send([event])
                results[channel.name] = "ok"
            except Exception as exc:
                results[channel.name] = f"error: {type(exc).__name__}"
        return results
