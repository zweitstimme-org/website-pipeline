#!/usr/bin/env python3
"""Backward-compatible wrapper — prefer code/district_forecast.py --state MV."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from district_forecast import main  # noqa: E402

if __name__ == "__main__":
    if "--state" not in sys.argv:
        sys.argv.extend(["--state", "MV"])
    main()
