"""Fail if the mutmut mutation score is below a threshold (nightly CI, spec 7.2).

Run inside backend/ after ``mutmut run``. The score counts killed (and timed-out)
mutants among all mutants that were tested.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min", type=float, default=80.0)
    args = parser.parse_args()
    exe = shutil.which("mutmut") or "mutmut"
    out = subprocess.run(
        [exe, "results", "--all", "true"], capture_output=True, text=True, check=False
    ).stdout
    statuses = re.findall(
        r":\s*(killed|survived|timeout|suspicious|no tests|skipped)\s*$", out, re.MULTILINE
    )
    tested = [s for s in statuses if s in {"killed", "survived", "timeout", "suspicious"}]
    if not tested:
        print("no mutation results found")
        return 1
    killed = sum(1 for s in tested if s in {"killed", "timeout"})
    score = 100.0 * killed / len(tested)
    print(f"mutation score: {score:.1f} % ({killed}/{len(tested)})")
    return 0 if score >= args.min else 1


if __name__ == "__main__":
    sys.exit(main())
