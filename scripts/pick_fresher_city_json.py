#!/usr/bin/env python3
"""Keep the fresher of two city-WBZ scrape JSONs (more counted units wins).

Usage: pick_fresher_city_json.py <target> <candidate>
Replaces <target> with <candidate> when the target is missing/unreadable or
the candidate has counted more units. Used by the nowcast workflow to fall
back to the st-live-data branch when the runner cannot reach a city portal.
"""

import json
import shutil
import sys
from pathlib import Path


def counted(path: Path) -> int:
    try:
        return int(json.loads(path.read_text(encoding="utf-8")).get("n_counted") or 0)
    except Exception:  # noqa: BLE001
        return -1


def main() -> None:
    target, cand = Path(sys.argv[1]), Path(sys.argv[2])
    if not cand.exists():
        return
    t, c = counted(target), counted(cand)
    if c > t:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cand, target)
        print(f"using branch copy for {target.name} ({c} > {t} counted)")
    else:
        print(f"keeping runner copy of {target.name} ({t} >= {c})")


if __name__ == "__main__":
    main()
