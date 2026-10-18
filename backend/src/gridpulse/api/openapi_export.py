"""Print the OpenAPI document (used by ``make openapi`` / the drift check in ``make build``)."""

from __future__ import annotations

import json

from gridpulse.api.main import create_app
from gridpulse.settings import Settings


def render() -> str:
    spec = create_app(Settings(database_url="memory://")).openapi()
    return json.dumps(spec, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    print(render(), end="")
