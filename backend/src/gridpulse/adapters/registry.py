"""Builds the configured set of adapters. ENTSO-E is only included with a token."""

from __future__ import annotations

import httpx

from gridpulse.adapters.base import HttpFetcher, SourceAdapter
from gridpulse.adapters.energy_charts import EnergyChartsAdapter
from gridpulse.adapters.entsoe import EntsoeAdapter
from gridpulse.adapters.open_meteo import OpenMeteoAdapter
from gridpulse.adapters.smard import SmardAdapter

LICENSES: dict[str, tuple[str, str]] = {
    "smard": (SmardAdapter.license, SmardAdapter.attribution),
    "energy_charts": (EnergyChartsAdapter.license, EnergyChartsAdapter.attribution),
    "open_meteo": (OpenMeteoAdapter.license, OpenMeteoAdapter.attribution),
    "entsoe": (EntsoeAdapter.license, EntsoeAdapter.attribution),
    "gridpulse": ("CC BY 4.0 (derived)", "GridPulse calculation from the cited sources"),
    "gridpulse_model": (
        "CC BY 4.0 (derived)",
        "GridPulse forecasting model trained on Open-Meteo weather and SMARD data",
    ),
    "demo": ("CC0 1.0", "GridPulse synthetic demo data"),
}


def license_for(source: str) -> tuple[str, str]:
    """(license, attribution) for a source id; compound ids like 'a|b' are joined."""
    parts = source.split("|")
    found = [LICENSES.get(p, ("unknown", p)) for p in parts]
    return "; ".join(dict.fromkeys(f[0] for f in found)), "; ".join(f[1] for f in found)


def build_adapters(
    client: httpx.AsyncClient, *, entsoe_token: str | None = None
) -> list[SourceAdapter]:
    fetcher = HttpFetcher(client)
    adapters: list[SourceAdapter] = [
        SmardAdapter(fetcher),
        EnergyChartsAdapter(fetcher),
        OpenMeteoAdapter(fetcher),
    ]
    if entsoe_token:
        adapters.append(EntsoeAdapter(fetcher, entsoe_token))
    return adapters
