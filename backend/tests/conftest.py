from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def read_fixture(source: str, name: str) -> Any:
    path = FIXTURES / source / name
    text = path.read_text(encoding="utf-8")
    return text if path.suffix == ".xml" else json.loads(text)


@pytest.fixture
def load_fixture() -> Callable[[str, str], Any]:
    return read_fixture
