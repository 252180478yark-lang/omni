#!/usr/bin/env python3
"""Stable repository-root entrypoint for the Omni PRD validator."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


TARGET = (
    Path(__file__).resolve().parents[1]
    / ".agents"
    / "skills"
    / "omni-fde-prd"
    / "scripts"
    / "validate_prd.py"
)


def main() -> int:
    if not TARGET.is_file():
        print(f"ERROR: canonical PRD validator does not exist: {TARGET}", file=sys.stderr)
        return 2
    sys.argv = [str(TARGET), *sys.argv[1:]]
    runpy.run_path(str(TARGET), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
