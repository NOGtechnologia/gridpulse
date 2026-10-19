"""Services, demo data, memory repository, pipeline and alerts (no network, no DB)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import pandas as pd
import pytest
import respx

from gridpulse.adapters.base import HttpFetcher, RawPayload
from gridpulse.adapters.energy_charts import EnergyChartsAdapter
from gridpulse.adapters.smard import SmardAdapter
from gridpulse.alerts.channels import ChatWebhookChannel, SmtpChannel, WebhookChannel, event_payload
from gridpulse.alerts.dispatcher import AlertDispatcher, channel_from_config, channels_from_settings
from gridpulse.demo import generate
from gridpulse.domain.metrics import Kind, MetricId
from gridpulse.domain.observations import make_frame
from gridpulse.domain.rules import Event, EventCategory, RuleConfig, Severity
from gridpulse.services.analysis import cross_check_sources, derive_indicators, evaluate_rules
from gridpulse.services.forecast import build_forecast
from gridpulse.services.series import best_source, pick_series
from gridpulse.services.summary import build_summary
from gridpulse.settings import Settings
from gridpulse.storage import create_repository
from gridpulse.storage.memory import MemoryRepository, bucket
from gridpulse.storage.repository import (
    AlertChannel,
    EventQuery,
    ObservationQuery,
    QueryResolution,
    SourceStatus,
)
from gridpulse.worker.pipeline import (
    IngestJob,
    Ingestor,
    energy_charts_jobs,
    entsoe_jobs,
    expected_points,
    frequency_jobs,
    smard_jobs,
    weather_jobs,
)

NOW = datetime(2026, 10, 18, 12, 7, tzinfo=UTC)
Q = timedelta(minutes=15)
CFG = RuleConfig()


@pytest.fixture
async def demo_repo() -> MemoryRepository:
    repo = MemoryRepository()
    await repo.upsert_observations(generate(NOW, days=4))
    await repo.save_source_status(SourceStatus("demo", last_success=NOW, newest_data=NOW))
    return repo


# --- demo -----------------------------------------------------------------------


def test_demo_is_deterministic_and_plausible() -> None:
    a, b = generate(NOW, days=2), generate(NOW, days=2)
    pd.testing.assert_frame_equal(a, b)
    assert set(a["source"]) == {"demo"}
    gen = a[a["metric"].str.startswith("generation.")]
    assert (gen["value"] >= 0).all()
    freq = a[a["metric"] == "grid.frequency"]["value"]
    assert freq.between(49.85, 50.15).all()
    assert {"forecast", "actual"} == set(a["kind"])


# --- memory repository -------------------------------------------------------------


async def test_memory_repository_semantics() -> None:
    repo = create_repository("memory://")
    assert isinstance(repo, MemoryRepository)
    frame = make_frame(
        timestamps=[NOW, NOW + Q],
        values=[1.0, 3.0],
        metric=MetricId.LOAD_ACTUAL,
        area="DE",
        kind=Kind.ACTUAL,
        source="x",
        resolution=Q,
    )
    assert await repo.upsert_observations(frame) == 2
    assert await repo.upsert_observations(frame.iloc[:0]) == 0
    await repo.upsert_observations(frame.assign(value=[5.0, 3.0]))
    query = ObservationQuery(
        metrics=["load.actual"],
        start=NOW - Q,
        end=NOW + 2 * Q,
        areas=["DE"],
        kind="actual",
        sources=["x"],
        resolution=QueryResolution.HOUR,
    )
    hourly = await repo.query_observations(query)
    assert hourly["value"].tolist() == [4.0]
    assert await repo.count_observations(query) == 1
    assert await repo.latest_timestamp("load.actual", "DE", "actual", "x") == NOW + Q
    assert await repo.latest_timestamp("load.actual", "DE", "actual", "y") is None
    assert await repo.ping()
    await repo.close()
    with pytest.raises(ValueError, match="exists"):
        await repo.add_alert_channel(AlertChannel("a", "webhook", "u"))
        await repo.add_alert_channel(AlertChannel("a", "webhook", "u"))
    await repo.add_api_key("n", "k")
    assert await repo.is_valid_api_key("k")
    assert not await repo.is_valid_api_key("z")


def test_bucket_day_and_raw() -> None:
    frame = generate(NOW, days=2)
    sel = frame[(frame["metric"] == "load.actual") & (frame["kind"] == "actual")]
    daily = bucket(sel, QueryResolution.DAY)
    assert len(daily) == 3  # 48 h ending 12:00 UTC touch three Berlin calendar days
    assert len(bucket(sel, QueryResolution.RAW)) == len(sel)
    assert bucket(sel.iloc[:0], QueryResolution.HOUR).empty


async def test_memory_events_filters() -> None:
    repo = MemoryRepository()
    events = [
        Event(
            ts=NOW + timedelta(minutes=i),
            rule_id=r,
            severity=s,
            category=EventCategory.GRID,
            metric="m",
            area="DE",
            value=None,
            threshold=None,
            source="s",
            message="x",
        )
        for i, (r, s) in enumerate([("A", Severity.INFO), ("B", Severity.CRITICAL)])
    ]
    assert len(await repo.upsert_events(events)) == 2
    assert await repo.upsert_events(events) == []
    q = EventQuery(
        start=NOW,
        end=NOW + timedelta(hours=1),
        min_severity=Severity.WARNING,
        rule_ids=["B"],
        categories=["grid"],
    )
    assert [e.rule_id for e in await repo.list_events(q)] == ["B"]
    await repo.mark_notified([events[1].id], NOW)
    assert await repo.last_notified("B", "DE", "m") == NOW
    assert await repo.last_notified("A", "DE", "m") is None


# --- services -----------------------------------------------------------------


async def test_summary_from_demo(demo_repo: MemoryRepository) -> None:
    summary = await build_summary(demo_repo, NOW, CFG)
    assert summary.as_of is not None
    assert summary.load.value and summary.load.value > 30_000
    assert summary.load.unit == "MW"
    assert summary.renewable_share.value is not None and 0 <= summary.renewable_share.value <= 100
    assert summary.co2_intensity.unit == "gCO2/kWh"
    assert summary.price.value is not None and summary.price_negative is not None
    assert summary.frequency.status in {"green", "yellow", "red"}
    assert len(summary.frequency.sparkline) > 10
    assert {f.neighbour for f in summary.flows} >= {"FR", "AT"}
    assert summary.meta.license == "CC0 1.0"
    assert [a.source for a in summary.sources] == ["demo"]


async def test_summary_empty_repository() -> None:
    summary = await build_summary(MemoryRepository(), NOW, CFG)
    assert summary.as_of is None
    assert summary.load.value is None and summary.load.stale
    assert summary.frequency.status is None
    assert summary.flows == []
    assert summary.meta.source == "none"


async def test_forecast_from_demo(demo_repo: MemoryRepository) -> None:
    forecast = await build_forecast(demo_repo, NOW, 48, CFG)
    assert len(forecast.points) > 150
    p = forecast.points[0]
    assert p.residual_load == pytest.approx(p.load - p.wind - p.solar)
    assert p.official_residual_load is not None
    lenient = RuleConfig(dunkelflaute_share=0.9, dunkelflaute_min_duration=timedelta(hours=1))
    windows = (await build_forecast(demo_repo, NOW, 48, lenient)).windows
    assert any(w.kind == "dunkelflaute" for w in windows)


async def test_forecast_negative_prices_and_empty() -> None:
    repo = MemoryRepository()
    stamps = [NOW + i * Q for i in range(8)]
    await repo.upsert_observations(
        make_frame(
            timestamps=stamps,
            values=[5, -1, -2, 3, 4, 5, -9, 1],
            metric=MetricId.PRICE_DAY_AHEAD,
            area="DE-LU",
            kind=Kind.ACTUAL,
            source="smard",
            resolution=Q,
        )
    )
    forecast = await build_forecast(repo, NOW, 48, CFG)
    assert [w.kind for w in forecast.windows] == ["negative_price", "negative_price"]
    assert forecast.points == []
    assert forecast.windows[0].hours == 0.5


async def test_derive_and_evaluate(demo_repo: MemoryRepository) -> None:
    assert await derive_indicators(demo_repo, NOW) > 0
    assert await derive_indicators(MemoryRepository(), NOW) == 0
    strict = RuleConfig(
        frequency_yellow_mhz=5,
        frequency_critical_mhz=10,
        price_spike_warning=50,
        forecast_error_relative=0.01,
        stale_after=timedelta(minutes=1),
    )
    events = await evaluate_rules(demo_repo, NOW, strict, sources=("demo", "smard"))
    rules = {e.rule_id for e in events}
    assert {"FREQ-001", "PRICE-001", "FCST-001"} <= rules


async def test_evaluate_stale_and_crosscheck() -> None:
    repo = MemoryRepository()
    stamps = [NOW - timedelta(hours=10) + i * Q for i in range(4)]
    for source, values in (
        ("smard", [100.0, 100.0, 100.0, 100.0]),
        ("energy_charts", [100.0, 150.0, 100.0, 100.0]),
    ):
        await repo.upsert_observations(
            make_frame(
                timestamps=stamps,
                values=values,
                metric=MetricId.LOAD_ACTUAL,
                area="DE",
                kind=Kind.ACTUAL,
                source=source,
                resolution=Q,
            )
        )
        await repo.save_source_status(SourceStatus(source))
    events = await evaluate_rules(repo, NOW, CFG)
    assert [e.rule_id for e in events if e.rule_id == "DATA-001"] == ["DATA-001", "DATA-001"]
    xchk = await cross_check_sources(repo, NOW, CFG)
    assert len(xchk) == 1 and xchk[0].source == "smard|energy_charts"


def test_best_source_prefers_newest_then_priority() -> None:
    def f(source: str, start: datetime) -> pd.DataFrame:
        return make_frame(
            timestamps=[start],
            values=[1.0],
            metric=MetricId.LOAD_ACTUAL,
            area="DE",
            kind=Kind.ACTUAL,
            source=source,
            resolution=Q,
        )

    frame = pd.concat([f("smard", NOW), f("energy_charts", NOW), f("demo", NOW + Q)])
    assert best_source(frame, MetricId.LOAD_ACTUAL) == "demo"
    assert best_source(frame[frame["source"] != "demo"], MetricId.LOAD_ACTUAL) == "energy_charts"
    assert best_source(frame, MetricId.GENERATION_GAS) is None
    assert pick_series(frame, MetricId.LOAD_ACTUAL, "smard").tolist() == [1.0]


# --- pipeline -------------------------------------------------------------------


@dataclass
class FakeAdapter:
    frame: pd.DataFrame
    source_id: str = "fake"
    license: str = "CC0"
    attribution: str = "fake"
    fail: bool = False
    calls: list[tuple[datetime, datetime]] = field(default_factory=list)

    def supported_metrics(self) -> frozenset[MetricId]:
        return frozenset({MetricId.LOAD_ACTUAL})

    async def fetch(self, metric: MetricId, start: datetime, end: datetime) -> RawPayload:
        self.calls.append((start, end))
        if self.fail:
            raise RuntimeError("boom")
        return RawPayload(self.source_id, metric, start, end, [])

    def parse(self, payload: RawPayload) -> pd.DataFrame:
        return self.frame


def _load(values: list[float], start: datetime = NOW - timedelta(hours=1)) -> pd.DataFrame:
    return make_frame(
        timestamps=[start + i * Q for i in range(len(values))],
        values=values,
        metric=MetricId.LOAD_ACTUAL,
        area="DE",
        kind=Kind.ACTUAL,
        source="fake",
        resolution=Q,
    )


async def test_ingestor_success_records_status_and_events() -> None:
    repo = MemoryRepository()
    frame = pd.concat(
        [_load([1.0, 2.0]), _load([3.0], start=NOW + timedelta(hours=1))], ignore_index=True
    )
    frame.loc[0, "value"] = -5.0  # plausibility violation (negative load)
    adapter = FakeAdapter(frame)
    ingestor = Ingestor(repo, Settings().plausibility_config(), clock=lambda: NOW)
    job = IngestJob(
        adapter, MetricId.LOAD_ACTUAL, lookback=timedelta(hours=2), lookahead=timedelta(hours=1)
    )
    status, events = await ingestor.run_source("fake", [job])
    assert adapter.calls == [(NOW - timedelta(hours=2), NOW + timedelta(hours=1))]
    assert status.rows_last_run == 3
    assert status.expected_points == 9 and status.received_points == 3  # 2 h span = 9 slots
    assert status.last_success == NOW
    assert {e.rule_id for e in events} == {"PLAUS-002", "PLAUS-005"}
    assert status.plausibility_violations == 2
    # The point at NOW+1h lies in the future and must not count as "newest data".
    assert (await repo.list_source_status())[0].newest_data == NOW - timedelta(minutes=45)


async def test_ingestor_failures_and_schema_errors() -> None:
    repo = MemoryRepository()
    ingestor = Ingestor(repo, Settings().plausibility_config(), clock=lambda: NOW)
    failing = IngestJob(FakeAdapter(_load([1.0]), fail=True), MetricId.LOAD_ACTUAL)
    status, _ = await ingestor.run_source("fake", [failing])
    status, _ = await ingestor.run_source("fake", [failing])
    assert status.consecutive_failures == 2
    assert status.last_success is None
    assert "boom" in (status.last_error or "")
    bad = _load([1.0]).assign(unit="GW")
    _, events = await ingestor.run_source(
        "fake", [IngestJob(FakeAdapter(bad), MetricId.LOAD_ACTUAL)]
    )
    assert [e.rule_id for e in events] == ["DATA-002"]
    empty = await ingestor.run_job(IngestJob(FakeAdapter(_load([])), MetricId.LOAD_ACTUAL))
    assert empty.rows == 0 and empty.error is None


def test_expected_points() -> None:
    assert expected_points(_load([1.0, 2.0, 3.0])) == 3


def test_default_job_catalogue() -> None:
    fetcher = cast("HttpFetcher", None)
    jobs = smard_jobs(
        SmardAdapter(fetcher),
        SmardAdapter(fetcher, kind=Kind.FORECAST),
        timedelta(hours=48),
        timedelta(hours=48),
    )
    names = {j.name for j in jobs}
    assert "smard:price.day_ahead:actual" in names
    assert "smard:load.actual:forecast" in names
    assert not any("nuclear" in n for n in names)
    ec = EnergyChartsAdapter(fetcher)
    ec_names = {j.name for j in energy_charts_jobs(ec, timedelta(hours=1), timedelta(hours=1))}
    assert "energy_charts:flow.net_import:actual:borders" in ec_names
    assert frequency_jobs(ec)[0].lookback == timedelta(minutes=15)
    from gridpulse.adapters.entsoe import EntsoeAdapter  # noqa: PLC0415
    from gridpulse.adapters.open_meteo import OpenMeteoAdapter  # noqa: PLC0415

    assert len(weather_jobs(OpenMeteoAdapter(fetcher), timedelta(hours=1))) == 4
    zones = [EntsoeAdapter(fetcher, "t", area=a) for a in ("DE-LU", "FR")]
    entsoe = entsoe_jobs(zones, timedelta(hours=1), timedelta(hours=1))
    assert [j.name for j in entsoe] == [
        "entsoe:load.actual:actual@DE-LU",
        "entsoe:price.day_ahead:actual@DE-LU",
        "entsoe:load.actual:actual@FR",
        "entsoe:price.day_ahead:actual@FR",
    ]
    assert entsoe[1].lookahead == timedelta(hours=1)


@respx.mock
async def test_ingest_energy_charts_border_flows(load_fixture: Callable[[str, str], Any]) -> None:
    respx.get("https://api.energy-charts.info/cbet").mock(
        return_value=httpx.Response(200, json=load_fixture("energy_charts", "cbet.json"))
    )
    first = datetime.fromtimestamp(
        load_fixture("energy_charts", "cbet.json")["unix_seconds"][0], tz=UTC
    )
    async with httpx.AsyncClient() as client:
        adapter = EnergyChartsAdapter(HttpFetcher(client))
        repo = MemoryRepository()
        ingestor = Ingestor(
            repo, Settings().plausibility_config(), clock=lambda: first + timedelta(hours=23)
        )
        job = IngestJob(
            adapter, MetricId.FLOW_NET_IMPORT, lookback=timedelta(hours=24), border_flows=True
        )
        result = await ingestor.run_job(job)
    assert result.rows > 0 and result.newest is not None


# --- alerts ---------------------------------------------------------------------


def _event(rule: str = "FREQ-001", sev: Severity = Severity.WARNING, minute: int = 0) -> Event:
    return Event(
        ts=NOW + timedelta(minutes=minute),
        rule_id=rule,
        severity=sev,
        category=EventCategory.GRID,
        metric="grid.frequency",
        area="DE",
        value=49.8,
        threshold=100.0,
        source="ec",
        message="deviation",
        unit="Hz",
    )


@dataclass
class RecordingChannel:
    name: str = "rec"
    min_severity: Severity = Severity.WARNING
    fail: bool = False
    sent: list[list[Event]] = field(default_factory=list)

    async def send(self, events: list[Event]) -> None:
        if self.fail:
            raise RuntimeError("down")
        self.sent.append(events)


async def test_dispatcher_debounces_and_filters_severity() -> None:
    repo = MemoryRepository()
    events = [_event(minute=0), _event(minute=1), _event("OUT-001", Severity.INFO, 2)]
    await repo.upsert_events(events)
    channel = RecordingChannel()
    dispatcher = AlertDispatcher(repo, [channel], timedelta(minutes=60))
    sent = await dispatcher.dispatch(events, NOW)
    assert [e.ts for e in sent] == [NOW]  # one per (rule, area, metric); info filtered out
    later = _event(minute=10)
    await repo.upsert_events([later])
    assert await dispatcher.dispatch([later], NOW + timedelta(minutes=10)) == []  # debounced
    assert await dispatcher.dispatch([later], NOW + timedelta(minutes=90)) == [later]
    assert len(channel.sent) == 2
    assert await dispatcher.dispatch([], NOW) == []


async def test_dispatcher_survives_failing_channel() -> None:
    repo = MemoryRepository()
    good, bad = RecordingChannel("good"), RecordingChannel("bad", fail=True)
    dispatcher = AlertDispatcher(repo, [bad, good], timedelta(0))
    event = _event(sev=Severity.CRITICAL)
    await repo.upsert_events([event])
    assert await dispatcher.dispatch([event], NOW) == [event]
    results = await dispatcher.send_test(NOW)
    assert results == {"bad": "error: RuntimeError", "good": "ok"}


@respx.mock
async def test_webhook_channels() -> None:
    generic = respx.post("https://hooks.test/generic").mock(return_value=httpx.Response(204))
    chat = respx.post("https://hooks.test/chat").mock(return_value=httpx.Response(200))
    async with httpx.AsyncClient() as client:
        await WebhookChannel("w", "https://hooks.test/generic", client).send([_event()])
        await ChatWebhookChannel("c", "https://hooks.test/chat", client).send([_event()])
    body = generic.calls[0].request.read().decode()
    assert '"rule_id":"FREQ-001"' in body.replace(" ", "")
    assert "deviation" in chat.calls[0].request.read().decode()
    assert event_payload(_event())["severity"] == "warning"


def test_smtp_channel_message_and_send(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[Any] = []

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            sent.append((host, port))

        def __enter__(self) -> FakeSMTP:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def starttls(self, context: object) -> None:
            sent.append("tls")

        def login(self, user: str, password: str) -> None:
            sent.append(("login", user))

        def send_message(self, message: object) -> None:
            sent.append(message)

    monkeypatch.setattr("gridpulse.alerts.channels.smtplib.SMTP", FakeSMTP)
    channel = SmtpChannel("m", "smtp.test", 587, "a@test", ["b@test"], user="u", password="p")
    msg = channel.build_message([_event(), _event(sev=Severity.CRITICAL)])
    assert msg["Subject"] == "[GridPulse] CRITICAL: 2 event(s)"
    channel._send_sync(msg)
    assert sent[:3] == [("smtp.test", 587), "tls", ("login", "u")]


async def test_channel_factory() -> None:
    settings = Settings(
        smtp_host="smtp.test",
        smtp_to=["ops@test"],
        alert_webhook_urls=["https://h.test/1"],
        smtp_password="pw",
    )
    repo = MemoryRepository()
    await repo.add_alert_channel(AlertChannel("teams", "teams", "https://h.test/teams"))
    await repo.add_alert_channel(AlertChannel("off", "slack", "https://h.test/off", enabled=False))
    async with httpx.AsyncClient() as client:
        channels = await channels_from_settings(repo, client, settings)
        assert [type(c).__name__ for c in channels] == [
            "WebhookChannel",
            "SmtpChannel",
            "ChatWebhookChannel",
        ]
        with pytest.raises(ValueError, match="unknown channel"):
            channel_from_config(AlertChannel("x", "pigeon", "t"), client, settings)
        with pytest.raises(ValueError, match="SMTP_HOST"):
            channel_from_config(AlertChannel("x", "smtp", "t"), client, Settings())


def test_settings_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRIDPULSE_CORS_ORIGINS", "https://a.test, https://b.test")
    monkeypatch.setenv("GRIDPULSE_FREQ_YELLOW_MHZ", "80")
    settings = Settings()
    assert settings.cors_origins == ["https://a.test", "https://b.test"]
    assert settings.rule_config().frequency_yellow_mhz == 80
    assert settings.plausibility_config().price_max_eur_mwh == 4000
