#!/usr/bin/env python3
"""Prefer the external JSON that has more Prognose/Hochrechnung rows."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def nsrc(path: Path) -> int:
    if not path.exists():
        return -1
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return -1
    return sum(len((doc.get(k) or {}).get("sources") or []) for k in ("be", "mv"))


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("usage: pick_wahlabend_external.py CANDIDATE DEST")
    cand = Path(sys.argv[1])
    dest = Path(sys.argv[2])
    if nsrc(cand) >= nsrc(dest) and cand.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(cand.read_bytes())
        print(f"external: using {cand}")
    else:
        print(f"external: keeping {dest}")


if __name__ == "__main__":
    main()
