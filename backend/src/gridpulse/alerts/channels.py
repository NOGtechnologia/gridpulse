"""Notification channels: generic JSON webhook, Slack/Teams-compatible webhook, SMTP."""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any, Protocol

import httpx

from gridpulse.adapters.base import USER_AGENT
from gridpulse.domain.rules.model import Event, Severity


def event_payload(event: Event) -> dict[str, Any]:
    return {
        "id": event.id,
        "ts": event.ts.isoformat(),
        "rule_id": event.rule_id,
        "severity": event.severity.value,
        "category": event.category.value,
        "metric": event.metric,
        "area": event.area,
        "value": event.value,
        "threshold": event.threshold,
        "unit": event.unit,
        "source": event.source,
        "message": event.message,
    }


def summary_text(events: list[Event]) -> str:
    lines = [f"GridPulse: {len(events)} event(s)"]
    lines += [
        f"[{e.severity.value.upper()}] {e.rule_id} {e.ts:%Y-%m-%d %H:%M}Z - {e.message}"
        for e in events
    ]
    return "\n".join(lines)


class Channel(Protocol):
    name: str
    min_severity: Severity

    async def send(self, events: list[Event]) -> None: ...


@dataclass
class WebhookChannel:
    """POSTs ``{"source": "gridpulse", "events": [...]}`` as JSON."""

    name: str
    url: str
    client: httpx.AsyncClient
    min_severity: Severity = Severity.WARNING

    async def send(self, events: list[Event]) -> None:
        body = {"source": "gridpulse", "events": [event_payload(e) for e in events]}
        response = await self.client.post(self.url, json=body, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()


@dataclass
class ChatWebhookChannel:
    """Slack incoming webhooks and Microsoft Teams webhooks both accept ``{"text": ...}``."""

    name: str
    url: str
    client: httpx.AsyncClient
    min_severity: Severity = Severity.WARNING

    async def send(self, events: list[Event]) -> None:
        response = await self.client.post(
            self.url, json={"text": summary_text(events)}, headers={"User-Agent": USER_AGENT}
        )
        response.raise_for_status()


@dataclass
class SmtpChannel:
    name: str
    host: str
    port: int
    sender: str
    recipients: list[str]
    user: str | None = None
    password: str | None = None
    starttls: bool = True
    min_severity: Severity = Severity.WARNING
    timeout: float = 30.0

    def build_message(self, events: list[Event]) -> EmailMessage:
        worst = max(events, key=lambda e: e.severity.rank)
        msg = EmailMessage()
        msg["Subject"] = f"[GridPulse] {worst.severity.value.upper()}: {len(events)} event(s)"
        msg["From"] = self.sender
        msg["To"] = ", ".join(self.recipients)
        msg.set_content(summary_text(events))
        return msg

    def _send_sync(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as smtp:
            if self.starttls:
                smtp.starttls(context=ssl.create_default_context())
            if self.user and self.password:
                smtp.login(self.user, self.password)
            smtp.send_message(message)

    async def send(self, events: list[Event]) -> None:
        await asyncio.to_thread(self._send_sync, self.build_message(events))
