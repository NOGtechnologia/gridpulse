"""Reproducible training and backtest of the own residual-load model (phase 7, ADR 0010).

Runs exactly the code of the worker's daily job against a database:

    # optional: load ~2 months of history (SMARD + Open-Meteo) first, then train
    uv run --project backend python scripts/train_forecast.py --backfill-days 92 \
        --report docs/forecasting-backtest.json

The result only depends on the stored data and ``--as-of`` (fixed seed, no random
validation split). Without ``--store`` nothing is written except the backfilled
observations.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from gridpulse.adapters.base import HttpFetcher
from gridpulse.adapters.open_meteo import OpenMeteoAdapter
from gridpulse.adapters.smard import SmardAdapter
from gridpulse.domain.metrics import Kind, MetricId
from gridpulse.domain.timeutils import floor_to
from gridpulse.forecasting.config import ModelConfig
from gridpulse.forecasting.features import WEATHER_METRICS
from gridpulse.services.model_forecast import run_model
from gridpulse.settings import Settings
from gridpulse.storage import create_repository, migrate
from gridpulse.storage.repository import ModelRun, Repository
from gridpulse.worker.pipeline import IngestJob, Ingestor

HORIZON = timedelta(hours=48)


async def backfill(repo: Repository, settings: Settings, days: int, now: datetime) -> None:
    """Fetch the model inputs for the last ``days`` days through the regular pipeline."""
    lookback = timedelta(days=days)
    async with httpx.AsyncClient(
        timeout=settings.http_timeout_seconds, follow_redirects=True
    ) as client:
        fetcher = HttpFetcher(client)
        jobs = [
            IngestJob(SmardAdapter(fetcher), MetricId.LOAD_RESIDUAL, Kind.ACTUAL, lookback),
            IngestJob(
                SmardAdapter(fetcher, kind=Kind.FORECAST),
                MetricId.LOAD_RESIDUAL,
                Kind.FORECAST,
                lookback,
                HORIZON,
            ),
            *(
                IngestJob(OpenMeteoAdapter(fetcher), m, Kind.FORECAST, lookback, HORIZON)
                for m in WEATHER_METRICS
            ),
        ]
        ingestor = Ingestor(repo, settings.plausibility_config(), clock=lambda: now)
        for job in jobs:
            result = await ingestor.run_job(job)
            status = f"error: {result.error}" if result.error else f"{result.rows} rows"
            print(f"backfill {job.name}: {status}", flush=True)


def _report(run: ModelRun | None, as_of: datetime, config: ModelConfig) -> dict[str, object]:
    out: dict[str, object] = {
        "as_of": as_of.isoformat(),
        "config": {
            "history_days": config.history.days,
            "test_days": config.test_days,
            "min_train_days": config.min_train_days,
        },
    }
    if run is None:
        out["result"] = "not enough history (weather, actuals and official forecast)"
        return out
    data = asdict(run)
    data.pop("id")
    out["run"] = {k: v.isoformat() if isinstance(v, datetime) else v for k, v in data.items()}
    return out


def _table(run: ModelRun) -> str:
    def pct(v: float | None) -> str:
        return "n/a" if v is None else f"{v:.2f} %"

    rows = [
        ("Own model", run.mae_model, run.mape_model),
        ("Official forecast (SMARD)", run.mae_official, run.mape_official),
    ]
    lines = ["| | MAE | MAPE |", "|---|---|---|"]
    lines += [f"| {name} | {mae:,.0f} MW | {pct(mape)} |" for name, mae, mape in rows]
    return "\n".join(lines)


async def main() -> int:
    settings = Settings()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--database-url", default=settings.database_url)
    parser.add_argument("--as-of", type=datetime.fromisoformat, default=None)
    parser.add_argument("--backfill-days", type=int, default=0)
    parser.add_argument("--history-days", type=int, default=settings.forecast_model_history_days)
    parser.add_argument("--test-days", type=int, default=settings.forecast_model_test_days)
    parser.add_argument(
        "--min-train-days", type=int, default=settings.forecast_model_min_train_days
    )
    parser.add_argument("--store", action="store_true", help="persist run and predictions")
    parser.add_argument("--report", type=Path, help="write the backtest report as JSON")
    args = parser.parse_args()

    as_of = floor_to(args.as_of or datetime.now(UTC), timedelta(hours=1))
    config = ModelConfig(
        history=timedelta(days=args.history_days),
        test_days=args.test_days,
        min_train_days=args.min_train_days,
        horizon=HORIZON,
    )
    if not args.database_url.startswith("memory://"):
        await asyncio.to_thread(migrate.upgrade, args.database_url)
    repo = create_repository(args.database_url)
    try:
        if args.backfill_days:
            await backfill(repo, settings, args.backfill_days, as_of)
        run, prediction = await run_model(repo, as_of, config, store=args.store)
    finally:
        await repo.close()

    report = _report(run, as_of, config)
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if run is None:
        return 1
    print()
    print(_table(run))
    print(f"\nactive (shown in the outlook): {run.active}; forecast hours: {len(prediction)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
