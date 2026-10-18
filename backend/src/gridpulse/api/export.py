"""CSV / Parquet export carrying source and licence information (spec 2.4)."""

from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from gridpulse.adapters.registry import license_for

DISCLAIMER = "Advisory data only; GridPulse is no substitute for certified control systems."


def _sources(frame: pd.DataFrame) -> str:
    return "|".join(sorted({str(s) for s in frame["source"]})) if not frame.empty else "none"


def export_metadata(frame: pd.DataFrame, generated_at: datetime) -> dict[str, str]:
    sources = _sources(frame)
    lic, attr = license_for(sources)
    return {
        "gridpulse.source": sources,
        "gridpulse.license": lic,
        "gridpulse.attribution": attr,
        "gridpulse.generated_at": generated_at.isoformat(),
        "gridpulse.time_basis": "UTC, interval start",
        "gridpulse.disclaimer": DISCLAIMER,
    }


def to_csv(frame: pd.DataFrame, generated_at: datetime) -> bytes:
    meta = export_metadata(frame, generated_at)
    header = "".join(f"# {k.removeprefix('gridpulse.')}: {v}\n" for k, v in meta.items())
    out = frame.copy()
    out["ts"] = pd.DatetimeIndex(out["ts"]).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (header + out.to_csv(index=False, lineterminator="\n")).encode("utf-8")


def to_parquet(frame: pd.DataFrame, generated_at: datetime) -> bytes:
    table = pa.Table.from_pandas(frame, preserve_index=False)
    existing = table.schema.metadata or {}
    meta = {k.encode(): v.encode() for k, v in export_metadata(frame, generated_at).items()}
    table = table.replace_schema_metadata({**existing, **meta})
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    return buffer.getvalue()
