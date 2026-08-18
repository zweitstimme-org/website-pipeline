"""Official candidate bio metadata (birth year/place, residence, profession).

Currently populated for Sachsen-Anhalt from the StaLa / Landeswahlleiterin Excel.
Keyed by (party, normalized name) for joins onto Direkt/Listen rows.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Lazy import to avoid circular deps when used from listen_candidates.
def _normalize_name(name: str) -> str:
    from listen_candidates import normalize_name

    return normalize_name(name)


BIO_PATHS = {
    "ST": REPO / "sachsen-anhalt" / "candidates" / "official_bio.csv",
}

BIO_FIELDS = ("birth_year", "birth_place", "residence", "profession")


def load_official_bio(state: str) -> dict[tuple[str, str], dict]:
    """Return {(party, normalized_name): {birth_year, birth_place, residence, profession, source}}."""
    path = BIO_PATHS.get(state.upper())
    if not path or not path.exists():
        return {}
    out: dict[tuple[str, str], dict] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            party = (r.get("party") or "").strip().lower()
            name = (r.get("name") or "").strip()
            if not party or not name:
                continue
            entry: dict = {}
            by = (r.get("birth_year") or "").strip()
            if by.isdigit():
                entry["birth_year"] = int(by)
            bp = (r.get("birth_place") or "").strip()
            if bp:
                entry["birth_place"] = bp
            res = (r.get("residence") or "").strip()
            if res:
                entry["residence"] = res
            prof = (r.get("profession") or "").strip()
            if prof:
                entry["profession"] = prof
            src = (r.get("source") or "").strip()
            if src:
                entry["source"] = src
            if not any(k in entry for k in BIO_FIELDS):
                continue
            out[(party, _normalize_name(name))] = entry
            # Also index first+last for middle-name mismatches
            toks = [t for t in _normalize_name(name).replace("-", " ").split() if t]
            if len(toks) >= 2:
                fl_key = (party, f"{toks[0]} {toks[-1]}")
                out.setdefault(fl_key, entry)
    return out


def lookup_bio(
    bio_index: dict[tuple[str, str], dict], party: str, name: str
) -> dict | None:
    if not bio_index or not party or not name:
        return None
    party = party.lower()
    key = (party, _normalize_name(name))
    if key in bio_index:
        return bio_index[key]
    toks = [t for t in _normalize_name(name).replace("-", " ").split() if t]
    if len(toks) >= 2:
        return bio_index.get((party, f"{toks[0]} {toks[-1]}"))
    return None


def attach_bio_fields(target: dict, bio: dict | None) -> None:
    """Copy bio fields onto a candidate/item dict (in-place)."""
    if not bio:
        return
    for k in BIO_FIELDS:
        if k in bio and bio[k] not in (None, ""):
            target[k] = bio[k]


def parse_birth_cell(raw) -> tuple[str, str]:
    """Split Excel 'Geburtsjahr\\nGeburtsort' cell → (year, place)."""
    if raw is None:
        return "", ""
    text = str(raw).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return "", ""
    parts = [p.strip() for p in text.split("\n") if p.strip()]
    year = ""
    place = ""
    if parts and re.fullmatch(r"\d{4}", parts[0]):
        year = parts[0]
        place = parts[1] if len(parts) > 1 else ""
    elif parts:
        m = re.match(r"^(\d{4})\s*(.*)$", parts[0])
        if m:
            year, place = m.group(1), m.group(2).strip()
            if not place and len(parts) > 1:
                place = parts[1]
        else:
            place = parts[0]
    return year, place
