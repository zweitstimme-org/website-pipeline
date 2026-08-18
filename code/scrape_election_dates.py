#!/usr/bin/env python3
"""Scrape upcoming election dates from wahlrecht.de."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import ELECTION_DATES_FILE, WAHLRECHT_ELECTION_DATES_URL

STATE_NAME_TO_CODE = {
    "Baden-Württemberg": "BW",
    "Bayern": "BY",
    "Berlin": "BE",
    "Brandenburg": "BB",
    "Bremen": "HB",
    "Hamburg": "HH",
    "Hessen": "HE",
    "Mecklenburg-Vorpommern": "MV",
    "Niedersachsen": "NI",
    "Nordrhein-Westfalen": "NW",
    "Rheinland-Pfalz": "RP",
    "Saarland": "SL",
    "Sachsen": "SN",
    "Sachsen-Anhalt": "ST",
    "Schleswig-Holstein": "SH",
    "Thüringen": "TH",
}

MONTH_MAP = {
    "januar": 1,
    "jan": 1,
    "februar": 2,
    "feb": 2,
    "märz": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "mai": 5,
    "may": 5,
    "juni": 6,
    "jun": 6,
    "juli": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "oktober": 10,
    "okt": 10,
    "november": 11,
    "nov": 11,
    "dezember": 12,
    "dez": 12,
    "dec": 12,
}


def estimate_date_from_season(season_text: str, year: int) -> datetime:
    season_text = season_text.lower().strip()
    if "frühjahr" in season_text:
        return datetime(year, 4, 15)
    if "herbst" in season_text:
        return datetime(year, 10, 15)
    if "winter" in season_text:
        return datetime(year, 1, 15)
    if "sommer" in season_text:
        return datetime(year, 7, 15)
    return datetime(year, 6, 15)


def find_next_sunday(date: datetime) -> datetime:
    """Snap to the same day if already Sunday, otherwise the following Sunday."""
    days_ahead = (6 - date.weekday()) % 7
    return date + timedelta(days=days_ahead)


def format_display_date(date_text: str) -> str:
    if not date_text:
        return ""
    formatted = re.sub(r"(\D)(\d{4})", r"\1 \2", date_text.strip())
    return re.sub(r"\s+", " ", formatted)


def parse_date_text(date_text: str) -> tuple[datetime | None, bool]:
    if not date_text:
        return None, False

    text = date_text.strip()

    # Exact calendar dates from wahlrecht.de are authoritative — keep them.
    # (Older code wrongly snapped Sundays forward by one week.)
    specific_match = re.search(r"(\d+)\.\s*(\w+)\s*(\d{4})", text)
    if specific_match:
        day = int(specific_match.group(1))
        month_name = specific_match.group(2).lower()
        year = int(specific_match.group(3))
        month = MONTH_MAP.get(month_name)
        if month:
            return datetime(year, month, day), False

    season_match = re.search(r"(\w+)\s*(\d{4})", text)
    if season_match:
        season = season_match.group(1)
        year = int(season_match.group(2))
        return find_next_sunday(estimate_date_from_season(season, year)), True

    return None, False


def scrape_election_dates(url: str = WAHLRECHT_ELECTION_DATES_URL) -> list[dict[str, str | bool]]:
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.content, "html.parser")
    table = soup.find("table", class_="wilko")
    if not table:
        raise RuntimeError("Could not find election date table on wahlrecht.de")

    tbody = table.find("tbody") or table
    rows = tbody.find_all("tr")

    elections: list[dict[str, str | bool]] = []
    for row in rows:
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue

        state_link = cells[0].find("a")
        if not state_link:
            continue

        state_name = " ".join(state_link.get_text(strip=True).split())
        date_text = " ".join(cells[1].get_text(strip=True).split())
        estimated_date, is_estimated = parse_date_text(date_text)
        if not estimated_date:
            continue

        state_code = STATE_NAME_TO_CODE.get(state_name)
        if not state_code:
            continue

        elections.append(
            {
                "state_code": state_code,
                "state_name": state_name,
                "display_date": format_display_date(date_text),
                "estimated_date": estimated_date.strftime("%Y-%m-%d"),
                "year": estimated_date.year,
                "date_is_estimated": is_estimated,
            }
        )

    elections.sort(key=lambda item: item["estimated_date"])
    return elections


def write_election_dates(output_file: Path, elections: list[dict[str, str | bool]]) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata": {
            "last_updated": datetime.now().isoformat(),
            "source": WAHLRECHT_ELECTION_DATES_URL,
            "total_states": len(elections),
        },
        "elections": elections,
    }
    output_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=ELECTION_DATES_FILE,
        help=f"Output JSON file (default: {ELECTION_DATES_FILE})",
    )
    args = parser.parse_args()

    output_file = Path(args.output)
    elections = scrape_election_dates()
    write_election_dates(output_file, elections)

    print(f"Wrote {len(elections)} election dates to {output_file}")
    for election in elections:
        suffix = " (estimated)" if election["date_is_estimated"] else ""
        print(f"  {election['state_code']}: {election['display_date']} -> {election['estimated_date']}{suffix}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
