#!/usr/bin/env python3
"""Stable public entrypoint for the repository AGENTS policy gate."""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_agents_policy import main


if __name__ == "__main__":
    raise SystemExit(main())
