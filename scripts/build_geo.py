"""Builds frontend/public/geo/neighbours.json from Natural Earth (public domain).

Input: ne_50m_admin_0_countries.geojson from
https://github.com/nvkelso/natural-earth-vector (Natural Earth, public domain).
Keeps Germany and its electrical neighbours, rounds coordinates to 0.01 degrees
and adds a label point per country. Run once; the output is committed.

    uv run --project backend python scripts/build_geo.py <path-to-geojson>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

KEEP = {"DE", "AT", "BE", "CH", "CZ", "DK", "FR", "LU", "NL", "NO", "PL", "SE"}
# Label positions (lon, lat) chosen near the German border for readability.
LABELS = {
    "DE": (10.4, 51.1),
    "AT": (14.5, 47.6),
    "BE": (4.6, 50.6),
    "CH": (8.2, 46.8),
    "CZ": (15.3, 49.8),
    "DK": (9.3, 56.0),
    "FR": (4.5, 48.4),
    "LU": (6.1, 49.8),
    "NL": (5.6, 52.2),
    "NO": (9.0, 59.2),
    "PL": (18.0, 52.3),
    "SE": (14.2, 57.2),
}
BBOX = (-1.0, 43.0, 25.0, 61.5)


def _round(coords: Any) -> Any:
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], 2), round(coords[1], 2)]
    return [_round(c) for c in coords]


def _in_bbox(ring: list[list[float]]) -> bool:
    return any(BBOX[0] <= x <= BBOX[2] and BBOX[1] <= y <= BBOX[3] for x, y in ring)


def _clip(geometry: dict[str, Any]) -> dict[str, Any] | None:
    polygons = (
        geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    )
    kept = [p for p in polygons if _in_bbox(p[0])]
    if not kept:
        return None
    return {"type": "MultiPolygon", "coordinates": _round(kept)}


def main(src: str) -> None:
    data = json.loads(Path(src).read_text(encoding="utf-8"))
    features = []
    for feature in data["features"]:
        code = feature["properties"].get("ISO_A2_EH") or feature["properties"].get("ISO_A2")
        if code not in KEEP:
            continue
        geometry = _clip(feature["geometry"])
        if geometry:
            features.append({"type": "Feature", "properties": {"code": code}, "geometry": geometry})
    labels = [
        {
            "type": "Feature",
            "properties": {"code": c},
            "geometry": {"type": "Point", "coordinates": list(p)},
        }
        for c, p in LABELS.items()
    ]
    out = {
        "type": "FeatureCollection",
        "attribution": "Made with Natural Earth (public domain)",
        "features": features + labels,
    }
    target = (
        Path(__file__).resolve().parent.parent / "frontend" / "public" / "geo" / "neighbours.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"{target}: {len(features)} countries, {target.stat().st_size} bytes")


if __name__ == "__main__":
    main(sys.argv[1])
