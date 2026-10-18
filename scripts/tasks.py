"""Cross-platform task runner. ``make <target>`` delegates here so that local runs,
Windows (no make) and CI execute exactly the same commands (spec 7.1).

    uv run --project backend python scripts/tasks.py check
    uv run --project backend python scripts/tasks.py lint typecheck
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
OPENAPI = ROOT / "docs" / "openapi.json"
CHECK = ["lint", "typecheck", "test-unit", "test-integration", "test-frontend", "build", "security"]
# Licences compatible with distributing an Apache-2.0 project (spec 7.5).
ALLOWED_LICENSES = (
    "MIT",
    "BSD",
    "Apache",
    "ISC",
    "PSF",
    "Python Software Foundation",
    "MPL-2.0",
    "Mozilla Public License 2.0",
    "Unlicense",
    "CC0",
    "0BSD",
    "Zlib",
    "HPND",
    "LGPL",
    "GNU Lesser General Public License",
)


def run(*cmd: str, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    print(f"\n$ {' '.join(cmd)}  (in {cwd.relative_to(ROOT) if cwd != ROOT else '.'})", flush=True)
    exe = shutil.which(cmd[0]) or cmd[0]
    result = subprocess.run(
        [exe, *cmd[1:]], cwd=cwd, env={**os.environ, **(env or {})}, check=False
    )
    if result.returncode != 0:
        sys.exit(f"FAILED ({result.returncode}): {' '.join(cmd)}")


def uv(*args: str) -> None:
    run("uv", "run", "--frozen", *args, cwd=BACKEND)


def pnpm(*args: str) -> None:
    run("pnpm", *args, cwd=FRONTEND)


def lint_backend() -> None:
    uv("ruff", "format", "--check", "src", "tests", "../scripts")
    uv("ruff", "check", "src", "tests", "../scripts")


def lint_frontend() -> None:
    pnpm("run", "lint")
    pnpm("run", "format:check")


def lint() -> None:
    lint_backend()
    lint_frontend()


def typecheck() -> None:
    uv("mypy")
    pnpm("run", "typecheck")


def ci_backend() -> None:
    """CI job 'backend': the backend half of `make check`."""
    lint_backend()
    uv("mypy")
    test_unit()
    test_integration()
    openapi()
    run("uv", "build", "--wheel", "--out-dir", "dist", cwd=BACKEND)


def ci_frontend() -> None:
    """CI job 'frontend': the frontend half of `make check`."""
    lint_frontend()
    pnpm("run", "typecheck")
    test_frontend()
    pnpm("run", "generate:api:check")
    pnpm("run", "build")


def test_unit() -> None:
    uv("pytest", "tests/unit", "tests/property", "tests/contract", "--cov", "--cov-report=", "-q")


def test_integration() -> None:
    """Integration tests (real TimescaleDB), then the combined coverage gates."""
    uv(
        "pytest",
        "tests/integration",
        "-m",
        "integration",
        "--cov",
        "--cov-append",
        "--cov-report=",
        "-q",
    )
    uv("coverage", "report", "--fail-under=90")
    uv(
        "coverage",
        "report",
        "--include=*/gridpulse/domain/*,*/gridpulse/validation/*",
        "--fail-under=100",
    )


def test_frontend() -> None:
    pnpm("run", "test:coverage")


def openapi(write: bool = False) -> None:
    """Generate the OpenAPI document; fail if it differs from the committed one."""
    exe = shutil.which("uv") or "uv"
    out = subprocess.run(
        [exe, "run", "--frozen", "python", "-m", "gridpulse.api.openapi_export"],
        cwd=BACKEND,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if write or not OPENAPI.exists():
        OPENAPI.write_text(out, encoding="utf-8", newline="\n")
        print(f"wrote {OPENAPI.relative_to(ROOT)}")
        return
    if json.loads(OPENAPI.read_text(encoding="utf-8")) != json.loads(out):
        sys.exit("docs/openapi.json is outdated - run: make openapi")
    print("docs/openapi.json is up to date")


def build() -> None:
    openapi()
    pnpm("run", "generate:api:check")
    run("uv", "build", "--wheel", "--out-dir", "dist", cwd=BACKEND)
    pnpm("run", "build")


def licenses() -> None:
    exe = shutil.which("uv") or "uv"
    out = subprocess.run(
        [exe, "run", "--frozen", "pip-licenses", "--format=json", "--with-system"],
        cwd=BACKEND,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    bad = [
        p
        for p in json.loads(out)
        if p["Name"] != "gridpulse"
        and not any(a.lower() in p["License"].lower() for a in ALLOWED_LICENSES)
    ]
    for p in bad:
        print(f"  disallowed or unknown licence: {p['Name']} {p['Version']}: {p['License']}")
    if bad:
        sys.exit("licence check failed (see docs/operations.md#licences for the allow-list)")
    pnpm("run", "licenses")


def security() -> None:
    # Audit exactly the locked versions (the local gridpulse package itself is not on PyPI).
    exe = shutil.which("uv") or "uv"
    locked = subprocess.run(
        [exe, "export", "--frozen", "--no-emit-project", "--format", "requirements-txt"],
        cwd=BACKEND,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    with tempfile.TemporaryDirectory() as tmp:
        req = Path(tmp) / "requirements.txt"
        req.write_text(locked, encoding="utf-8")
        uv(
            "pip-audit",
            "--strict",
            "--disable-pip",
            "--require-hashes",
            "-r",
            str(req),
            "--progress-spinner=off",
        )
    pnpm("audit", "--prod", "--audit-level=high")
    licenses()
    if shutil.which("gitleaks"):
        run("gitleaks", "detect", "--no-banner", "--redact", "--source", str(ROOT))
    else:
        print("gitleaks not installed locally - enforced in CI and pre-commit")


def e2e() -> None:
    pnpm("run", "e2e")


def verify_sources() -> None:
    run("uv", "run", "--frozen", "python", "../scripts/verify_sources.py", cwd=BACKEND)


def check() -> None:
    for name in CHECK:
        TASKS[name]()
    print("\nmake check: all green")


TASKS: dict[str, Callable[[], None]] = {
    "lint": lint,
    "typecheck": typecheck,
    "test-unit": test_unit,
    "test-integration": test_integration,
    "test-frontend": test_frontend,
    "build": build,
    "security": security,
    "licenses": licenses,
    "openapi": lambda: openapi(write=True),
    "openapi-check": openapi,
    "e2e": e2e,
    "verify-sources": verify_sources,
    "ci-backend": ci_backend,
    "ci-frontend": ci_frontend,
    "check": check,
}


def main(argv: list[str]) -> None:
    unknown = [a for a in argv if a not in TASKS]
    if not argv or unknown:
        sys.exit(f"usage: tasks.py <{'|'.join(TASKS)}> ...  (unknown: {unknown})")
    for name in argv:
        TASKS[name]()


if __name__ == "__main__":
    main(sys.argv[1:])
