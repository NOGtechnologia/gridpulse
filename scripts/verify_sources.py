"""Live verification of all GridPulse data sources.

Fetches a small sample from every configured endpoint, checks reachability and the
expected response structure and (with ``--save-fixtures``) stores the raw responses
under ``backend/tests/fixtures/<source>/`` so that adapter ``parse()`` functions can
be contract-tested offline. Afterwards every adapter fetches and parses one metric
end to end.

Run from the repository root::

    uv run --project backend python scripts/verify_sources.py [--save-fixtures]

Exit code is non-zero if any mandatory source fails. ENTSO-E is only checked when
``GRIDPULSE_ENTSOE_TOKEN`` is set.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "backend" / "tests" / "fixtures"
USER_AGENT = "GridPulse/0.1 (+https://github.com/NOGtechnologia/gridpulse; verify_sources)"
SMARD = "https://www.smard.de/app/chart_data"
EC = "https://api.energy-charts.info"

# (filter id, region, resolution); see docs/data-sources.md for the meaning.
SMARD_SERIES: list[tuple[int, str, str]] = [
    (4067, "DE", "quarterhour"),  # wind onshore
    (4068, "DE", "quarterhour"),  # photovoltaics
    (4071, "DE", "quarterhour"),  # natural gas
    (410, "DE", "quarterhour"),  # grid load
    (4359, "DE", "quarterhour"),  # residual load
    (411, "DE", "quarterhour"),  # forecast: grid load
    (123, "DE", "quarterhour"),  # forecast: wind onshore
    (125, "DE", "quarterhour"),  # forecast: photovoltaics
    (4169, "DE-LU", "quarterhour"),  # day-ahead price
    (4067, "DE", "hour"),
]


@dataclass
class Check:
    source: str
    name: str
    ok: bool
    detail: str
    mandatory: bool = True


@dataclass
class Probe:
    source: str
    name: str
    url: str
    params: dict[str, Any]
    keys: list[str]
    mandatory: bool = True
    count_key: str = "unix_seconds"
    extra: dict[str, Any] = field(default_factory=dict)


def _missing_keys(payload: Any, keys: list[str]) -> list[str]:
    first = payload[0] if isinstance(payload, list) and payload else payload
    if not isinstance(first, dict):
        return keys
    return [k for k in keys if k not in first]


async def _get(client: httpx.AsyncClient, url: str, params: dict[str, Any] | None = None) -> Any:
    response = await client.get(url, params=params)
    response.raise_for_status()
    if "json" in response.headers.get("content-type", "") or url.endswith(".json"):
        return response.json()
    return response.text


def _save(source: str, name: str, payload: Any) -> None:
    target = FIXTURES / source
    target.mkdir(parents=True, exist_ok=True)
    text = (
        payload
        if isinstance(payload, str)
        else json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )
    (target / name).write_text(text, encoding="utf-8")


async def verify_smard(client: httpx.AsyncClient, save: bool) -> list[Check]:
    checks = []
    for filter_id, region, resolution in SMARD_SERIES:
        name = f"{filter_id}_{region}_{resolution}"
        try:
            index = await _get(client, f"{SMARD}/{filter_id}/{region}/index_{resolution}.json")
            if missing := _missing_keys(index, ["timestamps"]):
                raise ValueError(f"missing keys {missing}")
            ts = index["timestamps"][-1]
            url = f"{SMARD}/{filter_id}/{region}/{filter_id}_{region}_{resolution}_{ts}.json"
            series = await _get(client, url)
            if missing := _missing_keys(series, ["meta_data", "series"]):
                raise ValueError(f"missing keys {missing}")
            if save:
                _save("smard", f"index_{name}.json", index)
                _save("smard", f"series_{name}.json", series)
            checks.append(Check("smard", name, True, f"{len(series['series'])} points"))
        except Exception as exc:
            checks.append(Check("smard", name, False, repr(exc)))
    return checks


def _probes(now: datetime) -> list[Probe]:
    day = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    fmt = "%Y-%m-%dT%H:%MZ"
    probes = [
        Probe(
            "energy_charts",
            "public_power",
            f"{EC}/public_power",
            {"country": "de", "start": day, "end": day},
            ["unix_seconds", "production_types"],
        ),
        Probe(
            "energy_charts",
            "price",
            f"{EC}/price",
            {"bzn": "DE-LU", "start": day, "end": day},
            ["unix_seconds", "price"],
        ),
        Probe(
            "energy_charts",
            "cbet",
            f"{EC}/cbet",
            {"country": "de", "start": day, "end": day},
            ["unix_seconds", "countries"],
        ),
        Probe(
            "energy_charts",
            "frequency",
            f"{EC}/frequency",
            {
                "region": "DE-Freiburg",
                "start": (now - timedelta(minutes=10)).strftime(fmt),
                "end": now.strftime(fmt),
            },
            ["unix_seconds", "data"],
        ),
        Probe(
            "energy_charts",
            "ren_share_forecast",
            f"{EC}/ren_share_forecast",
            {"country": "de"},
            ["unix_seconds", "ren_share"],
            mandatory=False,
        ),
        Probe(
            "open_meteo",
            "forecast_multi",
            "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": "53.55,51.0,48.14",
                "longitude": "9.99,10.0,11.58",
                "hourly": "temperature_2m,wind_speed_100m,shortwave_radiation,cloud_cover",
                "timezone": "UTC",
                "forecast_days": 2,
            },
            ["hourly", "hourly_units"],
            count_key="hourly",
        ),
        # History for the forecasting model (phase 7): the forecast API keeps roughly two
        # months of past hours; older hours within past_days come back as null.
        Probe(
            "open_meteo",
            "forecast_past_days",
            "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": "53.55",
                "longitude": "9.99",
                "hourly": "temperature_2m,wind_speed_100m,shortwave_radiation,cloud_cover",
                "timezone": "UTC",
                "past_days": 92,
                "forecast_days": 1,
            },
            ["hourly", "hourly_units"],
            count_key="hourly",
            mandatory=False,
        ),
    ]
    token = os.environ.get("GRIDPULSE_ENTSOE_TOKEN")
    if token:
        probes.append(
            Probe(
                "entsoe",
                "actual_load_A65",
                "https://web-api.tp.entsoe.eu/api",
                {
                    "securityToken": token,
                    "documentType": "A65",
                    "processType": "A16",
                    "outBiddingZone_Domain": "10Y1001A1001A82H",
                    "periodStart": (now - timedelta(days=1)).strftime("%Y%m%d%H%M"),
                    "periodEnd": now.strftime("%Y%m%d%H%M"),
                },
                [],
                mandatory=False,
                extra={"xml_root": "GL_MarketDocument", "secret": token},
            )
        )
    return probes


async def verify_probe(client: httpx.AsyncClient, probe: Probe, save: bool) -> Check:
    try:
        payload = await _get(client, probe.url, probe.params)
        if isinstance(payload, str):
            if probe.extra.get("xml_root", "<none>") not in payload:
                raise ValueError("unexpected XML root")
            detail = f"{len(payload)} bytes"
            suffix = ".xml"
        else:
            if missing := _missing_keys(payload, probe.keys):
                raise ValueError(f"missing keys {missing}")
            first = payload[0] if isinstance(payload, list) else payload
            count = first[probe.count_key]
            detail = f"{len(count.get('time', count) if isinstance(count, dict) else count)} points"
            suffix = ".json"
        if save:
            _save(probe.source, probe.name + suffix, payload)
        return Check(probe.source, probe.name, True, detail, probe.mandatory)
    except Exception as exc:
        detail = repr(exc)
        if secret := probe.extra.get("secret"):
            detail = detail.replace(str(secret), "***")
        return Check(probe.source, probe.name, False, detail, probe.mandatory)


async def verify_adapters(client: httpx.AsyncClient) -> list[Check]:
    """End-to-end check: every adapter fetches and parses at least one metric."""
    sys.path.insert(0, str(ROOT / "backend" / "src"))
    from gridpulse.adapters.registry import build_adapters  # noqa: PLC0415 - path set above
    from gridpulse.domain.metrics import MetricId  # noqa: PLC0415 - path set above

    end = datetime.now(UTC)
    start = end - timedelta(hours=6)
    samples = {
        "smard": MetricId.GENERATION_WIND_ONSHORE,
        "energy_charts": MetricId.PRICE_DAY_AHEAD,
        "open_meteo": MetricId.WEATHER_WIND_SPEED_100M,
        "entsoe": MetricId.LOAD_ACTUAL,
    }
    checks = []
    for adapter in build_adapters(client, entsoe_token=os.environ.get("GRIDPULSE_ENTSOE_TOKEN")):
        metric = samples[adapter.source_id]
        mandatory = adapter.source_id != "entsoe"
        try:
            frame = adapter.parse(await adapter.fetch(metric, start, end))
            ok = not frame.empty
            checks.append(
                Check(
                    adapter.source_id,
                    f"adapter:{metric.value}",
                    ok,
                    f"{len(frame)} rows",
                    mandatory,
                )
            )
        except Exception as exc:
            checks.append(
                Check(adapter.source_id, f"adapter:{metric.value}", False, repr(exc), mandatory)
            )
    return checks


async def main() -> int:
    parser = argparse.ArgumentParser(description="Verify GridPulse data sources live.")
    parser.add_argument("--save-fixtures", action="store_true")
    parser.add_argument("--raw-only", action="store_true", help="skip adapter end-to-end checks")
    args = parser.parse_args()

    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True
    ) as client:
        checks = await verify_smard(client, args.save_fixtures)
        checks += [await verify_probe(client, p, args.save_fixtures) for p in _probes(now)]
        if not os.environ.get("GRIDPULSE_ENTSOE_TOKEN"):
            checks.append(
                Check(
                    "entsoe",
                    "actual_load_A65",
                    True,
                    "skipped: GRIDPULSE_ENTSOE_TOKEN not set",
                    mandatory=False,
                )
            )
        if not args.raw_only:
            checks += await verify_adapters(client)

    failed = False
    for c in checks:
        mark = "OK  " if c.ok else ("FAIL" if c.mandatory else "WARN")
        print(f"[{mark}] {c.source:14} {c.name:40} {c.detail}")
        failed |= c.mandatory and not c.ok
    print(f"\nverified at {datetime.now(UTC).isoformat(timespec='seconds')}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
