#!/usr/bin/env python3
"""Reconcile display_mode.json with forecast files on disk.

Stimmung jobs rebuild display_mode without forecast_*.json in output/, which
would flip forecast_available to false. Keep post-election forecasts in the
live Vorhersagen block for ``forecast_archive_days`` (default 7), then archive.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

STATE_ARCH = re.compile(r"^forecast_state_([a-z]{2})_(\d{4}-\d{2}-\d{2})\.json$")
FED_ARCH = re.compile(r"^forecast_federal_(\d{4}-\d{2}-\d{2})\.json$")
STATE_LIVE = re.compile(r"^forecast_state_([a-z]{2})\.json$")


def days_to(election_date: str, today: date) -> int | None:
    try:
        return (date.fromisoformat(str(election_date)[:10]) - today).days
    except (TypeError, ValueError):
        return None


def in_live_window(days: int, window: int, archive_days: int) -> bool:
    return -archive_days <= days <= window


def in_archive_window(days: int, archive_days: int) -> bool:
    return days < -archive_days


def catalog_entry(
    *,
    key: str,
    scope: str,
    state_code: str | None,
    election_date: str,
    election_name,
    date_is_estimated: bool,
    forecast_file: str,
) -> dict:
    return {
        "key": key,
        "scope": scope,
        "state_code": state_code,
        "election_date": election_date,
        "election_name": election_name,
        "date_is_estimated": bool(date_is_estimated),
        "forecast_file": forecast_file,
    }


def load_calendar_elections(data_dir: Path) -> list[dict]:
    path = data_dir / "election_calendar.json"
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
    rows = payload.get("elections") if isinstance(payload, dict) else None
    return [e for e in rows or [] if isinstance(e, dict)]


def election_meta(calendar: list[dict], state_code: str | None) -> dict:
    want = None if state_code is None else str(state_code).upper()
    for row in calendar:
        code = row.get("state_code")
        scope = str(row.get("scope") or "").lower()
        if want is None:
            if scope in ("bund", "federal") or code in (None, ""):
                return row
        elif str(code or "").upper() == want:
            return row
    return {}


def reconcile(data_dir: Path, today: date | None = None) -> dict:
    today = today or date.today()
    dm_path = data_dir / "display_mode.json"
    dm = json.loads(dm_path.read_text())
    window = int(dm.get("forecast_window_days") or 90)
    archive_days = int(dm.get("forecast_archive_days") or 7)
    dm["forecast_archive_days"] = archive_days
    calendar = load_calendar_elections(data_dir)

    def refresh_days(info: dict) -> int | None:
        ed = info.get("election_date")
        if not ed:
            return None
        days = days_to(str(ed), today)
        if days is None:
            return None
        info["days_to_election"] = days
        return days

    federal = dm.get("federal") or {}
    if federal:
        days = refresh_days(federal)
        has = (data_dir / "forecast_federal.json").exists()
        if has and days is not None and in_live_window(days, window, archive_days):
            federal["mode"] = "forecast"
            federal["forecast_available"] = True
        elif not has or (days is not None and not in_live_window(days, window, archive_days)):
            federal["forecast_available"] = False
            if federal.get("mode") == "forecast":
                federal["mode"] = "stimmung"
        dm["federal"] = federal

    states = dm.get("states") or {}
    for code, info in list(states.items()):
        if not isinstance(info, dict):
            continue
        days = refresh_days(info)
        has = (data_dir / f"forecast_state_{code.lower()}.json").exists()
        if has and days is not None and in_live_window(days, window, archive_days):
            info["mode"] = "forecast"
            info["forecast_available"] = True
        elif not has or (days is not None and not in_live_window(days, window, archive_days)):
            info["forecast_available"] = False
            if info.get("mode") == "forecast":
                info["mode"] = "stimmung"
        states[code] = info
    dm["states"] = states

    catalog: dict[str, dict] = {}
    for entry in list((dm.get("archive") or {}).get("forecasts") or []):
        if isinstance(entry, dict) and entry.get("key"):
            catalog[str(entry["key"])] = entry

    archive_dir = data_dir / "archive"
    if archive_dir.is_dir():
        for path in sorted(archive_dir.glob("*.json")):
            m = STATE_ARCH.match(path.name)
            if m:
                code, ed = m.group(1), m.group(2)
                days = days_to(ed, today)
                if days is None or not in_archive_window(days, archive_days):
                    continue
                meta = election_meta(calendar, code.upper())
                cal_ed = str(meta.get("election_date") or "")
                if cal_ed and cal_ed != ed:
                    continue
                info = states.get(code.upper()) or {}
                key = f"{code}_{ed}"
                catalog[key] = catalog_entry(
                    key=key,
                    scope="state",
                    state_code=code.upper(),
                    election_date=ed,
                    election_name=info.get("election_name")
                    or meta.get("election_name")
                    or (catalog.get(key) or {}).get("election_name"),
                    date_is_estimated=bool(
                        info.get("date_is_estimated", meta.get("date_is_estimated"))
                    ),
                    forecast_file=f"archive/{path.name}",
                )
                continue
            m = FED_ARCH.match(path.name)
            if not m:
                continue
            ed = m.group(1)
            days = days_to(ed, today)
            if days is None or not in_archive_window(days, archive_days):
                continue
            meta = election_meta(calendar, None)
            cal_ed = str(meta.get("election_date") or "")
            if cal_ed and cal_ed != ed:
                continue
            key = f"federal_{ed}"
            catalog[key] = catalog_entry(
                key=key,
                scope="federal",
                state_code=None,
                election_date=ed,
                election_name=federal.get("election_name")
                or meta.get("election_name")
                or (catalog.get(key) or {}).get("election_name"),
                date_is_estimated=bool(
                    federal.get("date_is_estimated", meta.get("date_is_estimated"))
                ),
                forecast_file=f"archive/{path.name}",
            )

    # Live forecast files still on disk stay in Vorhersagen through the grace period.
    for path in sorted(data_dir.glob("forecast_state_??.json")):
        m = STATE_LIVE.match(path.name)
        if not m:
            continue
        code = m.group(1).upper()
        info = states.get(code) if isinstance(states.get(code), dict) else {}
        meta = election_meta(calendar, code)
        ed = info.get("election_date") or meta.get("election_date")
        if not ed:
            continue
        days = days_to(str(ed), today)
        if days is None or not in_live_window(days, window, archive_days):
            continue
        merged = dict(info)
        merged["mode"] = "forecast"
        merged["forecast_available"] = True
        merged["election_date"] = str(ed)
        merged["days_to_election"] = days
        if meta.get("election_name") and not merged.get("election_name"):
            merged["election_name"] = meta.get("election_name")
        if "date_is_estimated" not in merged and "date_is_estimated" in meta:
            merged["date_is_estimated"] = bool(meta.get("date_is_estimated"))
        states[code] = merged
    dm["states"] = states

    live_fed = data_dir / "forecast_federal.json"
    if live_fed.is_file() and isinstance(federal, dict):
        meta = election_meta(calendar, None)
        ed = federal.get("election_date") or meta.get("election_date")
        if ed:
            days = days_to(str(ed), today)
            if days is not None and in_live_window(days, window, archive_days):
                federal["mode"] = "forecast"
                federal["forecast_available"] = True
                federal["election_date"] = str(ed)
                federal["days_to_election"] = days
                dm["federal"] = federal

    filtered = []
    for entry in catalog.values():
        ed = str(entry.get("election_date") or "")
        days = days_to(ed, today)
        if days is None or not in_archive_window(days, archive_days):
            continue
        scope = str(entry.get("scope") or "")
        if scope == "state":
            meta = election_meta(calendar, entry.get("state_code"))
            cal_ed = str(meta.get("election_date") or "")
            if cal_ed and cal_ed != ed:
                continue
        elif scope == "federal":
            meta = election_meta(calendar, None)
            cal_ed = str(meta.get("election_date") or "")
            if cal_ed and cal_ed != ed:
                continue
        rel = str(entry.get("forecast_file") or "")
        if not rel or not (data_dir / rel).is_file():
            continue
        filtered.append(entry)
    filtered.sort(key=lambda e: str(e.get("election_date") or ""), reverse=True)
    dm["archive"] = {"forecasts": filtered}

    dm_path.write_text(json.dumps(dm, indent=2, ensure_ascii=False) + "\n")
    return dm


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: reconcile_display_mode.py DATA_DIR", file=sys.stderr)
        sys.exit(2)
    reconcile(Path(sys.argv[1]))
    print("Reconciled display_mode forecast_available with static/data/*.json")


if __name__ == "__main__":
    main()
