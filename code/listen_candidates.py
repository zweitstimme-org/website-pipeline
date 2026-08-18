#!/usr/bin/env python3
"""Build / load Landes- and Bezirkslisten with placeholders for missing names.

CSV schema (per state): {state}/candidates/listenkandidaten_2026.csv
  party,list_type,bezirk,list_pos,name,person_id,wkr_direct,source,is_placeholder

Direktkandidaten stay in direktkandidaten_2026.csv; dual candidacy is linked by
normalized name → shared person_id when both are known. Placeholders never share
an identity across Direkt/Liste (assumed different people).
"""

from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

BEZ_NAMES = {
    "01": "Mitte",
    "02": "Friedrichshain-Kreuzberg",
    "03": "Pankow",
    "04": "Charlottenburg-Wilmersdorf",
    "05": "Spandau",
    "06": "Steglitz-Zehlendorf",
    "07": "Tempelhof-Schöneberg",
    "08": "Neukölln",
    "09": "Treptow-Köpenick",
    "10": "Marzahn-Hellersdorf",
    "11": "Lichtenberg",
    "12": "Reinickendorf",
}

# Berlin 2026: parties choose either Landesliste OR Bezirkslisten (rbb/tagesschau).
BE_LIST_TYPE = {
    "spd": "bezirk",
    "cdu": "bezirk",
    "linke": "bezirk",
    "gruene": "landes",
    "afd": "landes",
    "fdp": "landes",
    "bsw": "landes",
}

PARTIES_MAIN = ("spd", "afd", "cdu", "linke", "gruene", "fdp", "bsw")

LIST_LEN = {
    ("BE", "landes"): 60,
    ("BE", "bezirk"): 25,
    ("MV", "landes"): 65,
    ("ST", "landes"): 65,
}

STATE_DIRS = {
    "BE": REPO / "berlin" / "candidates",
    "MV": REPO / "mecklenburg-vorpommern" / "candidates",
    "ST": REPO / "sachsen-anhalt" / "candidates",
}

LIST_FIELDS = [
    "party",
    "list_type",
    "bezirk",
    "list_pos",
    "name",
    "person_id",
    "wkr_direct",
    "source",
    "is_placeholder",
]


def _flip_comma_name(name: str) -> str:
    name = (name or "").strip()
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            return f"{parts[1]} {parts[0]}"
    return name


# Party-congress vote shares scraped into names, e.g. "Bettina Meißner (98%)".
_VOTE_PCT_RE = re.compile(r"\s*\(\s*\d{1,3}\s*%\s*\)\s*$")

# Academic titles that may appear leading *or* mid-name (e.g. "Marela Dr. Bone-Winkel").
_TITLE_TOKEN_KEYS = frozenset({"dr", "prof", "med", "dipl", "mag", "ing"})
_TITLE_ORDER = ("prof", "dr", "med", "dipl", "mag", "ing")
_TITLE_DISPLAY = {
    "prof": "Prof.",
    "dr": "Dr.",
    "med": "med.",
    "dipl": "Dipl.",
    "mag": "Mag.",
    "ing": "Ing.",
}


def _canonicalize_academic_titles(name: str) -> str:
    """Move mid-name Dr./Prof./… tokens to the front in standard order.

    ``Marela Dr. Bone-Winkel`` → ``Dr. Marela Bone-Winkel``
    ``Prof. Dr. Martin Pätzold`` unchanged.
    """
    parts = (name or "").split()
    if not parts:
        return name
    titles: list[str] = []
    rest: list[str] = []
    for p in parts:
        key = p.lower().rstrip(".")
        if key in _TITLE_TOKEN_KEYS:
            titles.append(key)
        else:
            rest.append(p)
    if not titles:
        return name
    seen: set[str] = set()
    ordered: list[str] = []
    for key in _TITLE_ORDER:
        if key in titles and key not in seen:
            ordered.append(_TITLE_DISPLAY[key])
            seen.add(key)
    for key in titles:
        if key not in seen:
            ordered.append(_TITLE_DISPLAY.get(key, f"{key.title()}."))
            seen.add(key)
    return " ".join(ordered + rest)


def clean_person_name(name: str) -> str:
    """Display-ready name: flip Last, First; drop nomination %; fix mid-name titles."""
    return _canonicalize_academic_titles(
        _VOTE_PCT_RE.sub("", _flip_comma_name(name or "")).strip()
    )


_SOURCE_URL_CACHE: dict[str, str] = {}
_CANONICAL_RE = re.compile(
    r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']'
    r'|<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)["\']'
    r'|<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']',
    re.I,
)


def public_source_url(source: str) -> str:
    """Turn local scrape paths into public http(s) URLs when possible.

    Many Berlin list seeds store ``berlin/candidates/raw/...html`` instead of the
    live page; the UI only links http(s) sources.
    """
    s = (source or "").strip()
    if not s:
        return ""
    if re.match(r"^https?://", s, re.I):
        return s
    if s in _SOURCE_URL_CACHE:
        return _SOURCE_URL_CACHE[s]

    path = Path(s)
    if not path.is_absolute():
        path = REPO / s
    url = ""
    if path.is_file():
        try:
            head = path.read_text(encoding="utf-8", errors="ignore")[:100_000]
        except OSError:
            head = ""
        m = _CANONICAL_RE.search(head) if head else None
        if m:
            url = next((g for g in m.groups() if g), "") or ""
        if not url.startswith("http"):
            # Filename heuristic: www.example.de_wahlen_foo.html → https://www.example.de/wahlen/foo
            stem = path.name[: -len(path.suffix)] if path.suffix else path.name
            m2 = re.match(
                r"((?:www\.)?[A-Za-z0-9.-]+\.[A-Za-z]{2,})_(.+)$", stem
            )
            if m2:
                url = f"https://{m2.group(1)}/{m2.group(2).replace('_', '/')}"
            elif re.match(r"((?:www\.)?[A-Za-z0-9.-]+\.[A-Za-z]{2,})$", stem):
                url = f"https://{stem}/"
    _SOURCE_URL_CACHE[s] = url if url.startswith("http") else s
    return _SOURCE_URL_CACHE[s]


def normalize_name(name: str) -> str:
    s = clean_person_name(name)
    # Expand umlauts before NFKD (otherwise ä → a + combining mark → "a").
    s = (
        s.replace("Ä", "Ae")
        .replace("Ö", "Oe")
        .replace("Ü", "Ue")
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        # Capital ẞ must be handled before .lower(); otherwise ẞ→ß after the
        # ß→ss replace and gets stripped by the ASCII filter (Hauẞ vs Hauß).
        .replace("ẞ", "ss")
        .replace("ß", "ss")
        # Turkish dotted/dotless I (NFKD does not map these to ASCII)
        .replace("İ", "I")
        .replace("ı", "i")
    )
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"\b(dr|prof|med|dipl|mag|ing)\.?\b", " ", s)
    s = re.sub(r"[^a-z0-9\s\-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def name_tokens(name: str) -> list[str]:
    # Treat hyphens as spaces so "Eric-Helge Giesel" ↔ "Eric Giesel".
    return [t for t in normalize_name(name).replace("-", " ").split() if t]


def first_last_key(name: str) -> tuple[str, str] | None:
    """First + last token — bridges 'Clemens Brandt' ↔ 'Clemens Wilhelm Brandt'."""
    toks = name_tokens(name)
    if len(toks) < 2:
        return None
    return toks[0], toks[-1]


def lookup_shared_pid(
    name_pid: dict[tuple[str, str], str], party: str, name: str
) -> str | None:
    """Exact normalized name, else unique first+last match within the party."""
    key = (party, normalize_name(name))
    if key in name_pid:
        return name_pid[key]
    fl = first_last_key(name)
    if not fl:
        return None
    hits: list[str] = []
    for (p, other), pid in name_pid.items():
        if p != party:
            continue
        if first_last_key(other) == fl:
            hits.append(pid)
    uniq = list(dict.fromkeys(hits))
    return uniq[0] if len(uniq) == 1 else None


def prefer_display_name(current: str, candidate: str) -> str:
    """Keep the more complete spelling (middle names, etc.)."""
    cur = (current or "").strip()
    cand = (candidate or "").strip()
    if not cur:
        return cand
    if not cand:
        return cur
    if len(name_tokens(cand)) > len(name_tokens(cur)):
        return cand
    if len(name_tokens(cand)) == len(name_tokens(cur)) and len(cand) > len(cur):
        return cand
    return cur


def load_wkr_to_bezirk() -> dict[int, str]:
    import json

    m = json.loads((REPO / "berlin" / "awk_wkr_map.json").read_text(encoding="utf-8"))
    out: dict[int, str] = {}
    for awk, wkr in m["awk_to_wkr"].items():
        out[int(wkr)] = f"{int(awk[:2]):02d}"
    return out


def load_direkt(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                wkr = int(r["wkr"])
            except (KeyError, TypeError, ValueError):
                continue
            party = (r.get("party") or "").strip().lower()
            name = (r.get("name") or "").strip()
            if not party:
                continue
            rows.append(
                {
                    "wkr": wkr,
                    "party": party,
                    "name": name,
                    "source": (r.get("source") or "").strip(),
                }
            )
    return rows


def _pid(state: str, party: str, kind: str, *parts: str | int) -> str:
    tail = ":".join(str(p) for p in parts)
    return f"{state.lower()}:{party}:{kind}:{tail}"


def _placeholder_list_name(list_type: str, pos: int, bezirk: str | None) -> str:
    if list_type == "bezirk" and bezirk:
        bname = BEZ_NAMES.get(bezirk, bezirk)
        return f"Listenplatz {pos} ({bname}) · unbekannt"
    return f"Listenplatz {pos} · unbekannt"


def _placeholder_direkt_name(wkr: int) -> str:
    return f"WK {wkr} · unbekannt"


# ---------------------------------------------------------------------------
# Optional parsers for already-scraped raw pages (best-effort)
# ---------------------------------------------------------------------------

def _parse_berlin_cdu_sz_ol(raw: Path) -> list[tuple[int, str]]:
    if not raw.exists():
        return []
    text = raw.read_text(encoding="utf-8", errors="ignore")
    idx = text.lower().find("bezirksliste")
    if idx < 0:
        return []
    chunk = text[idx : idx + 12000]
    m = re.search(r"<ol>(.*?)</ol>", chunk, re.S | re.I)
    if not m:
        return []
    items = re.findall(r"<li>(.*?)</li>", m.group(1), re.S | re.I)
    out = []
    for i, item in enumerate(items, 1):
        name = re.sub(r"<[^>]+>", "", item).strip()
        name = _flip_comma_name(name)
        if name:
            out.append((i, name))
    return out


def _parse_mv_cdu_md(raw: Path, direkts: list[dict] | None = None) -> dict[int, dict]:
    """Listenplatz → {name, wkr_direct} via WK↔Listenplatz in raw_cdu.md + Direkt CSV."""
    if not raw.exists():
        return {}
    text = raw.read_text(encoding="utf-8", errors="ignore")
    by_wkr = {
        d["wkr"]: d["name"]
        for d in (direkts or [])
        if d.get("party") == "cdu" and d.get("name")
    }
    out: dict[int, dict] = {}
    for m in re.finditer(
        r"Wahlkreis[e]?\s*(?P<wkr>\d+)\s*\|\s*Listenplatz\s*(?P<lp>\d+)",
        text,
        re.I,
    ):
        wkr = int(m.group("wkr"))
        lp = int(m.group("lp"))
        name = by_wkr.get(wkr)
        if not name:
            continue
        out[lp] = {"name": name, "wkr_direct": wkr}
    return out


def _parse_mv_spd_html(raw: Path, direkts: list[dict] | None = None) -> dict[int, dict]:
    """Landesliste from spd-mv.de kandidaten page (<ol> after 'Landesliste')."""
    if not raw.exists():
        return {}
    text = raw.read_text(encoding="utf-8", errors="ignore")
    idx = text.lower().find("landesliste")
    if idx < 0:
        return {}
    chunk = text[idx : idx + 40000]
    m = re.search(r"<ol[^>]*>(.*?)</ol>", chunk, re.S | re.I)
    if not m:
        return {}
    by_name_wkr: dict[str, int] = {}
    for d in direkts or []:
        if d.get("party") == "spd" and d.get("name"):
            by_name_wkr[normalize_name(d["name"])] = int(d["wkr"])
    out: dict[int, dict] = {}
    for i, li in enumerate(re.findall(r"<li[^>]*>(.*?)</li>", m.group(1), re.S | re.I), 1):
        plain = re.sub(r"<[^>]+>", " ", li)
        plain = re.sub(r"\s+", " ", plain).strip()
        # "Manuela Schwesig, Schwerin"
        name = plain.split(",")[0].strip()
        name = re.sub(r"^\d+\.?\s*", "", name)
        if not name or len(name) < 3:
            continue
        info: dict = {"name": name}
        wkr = by_name_wkr.get(normalize_name(name))
        if wkr is not None:
            info["wkr_direct"] = wkr
        out[i] = info
    return out


def _parse_st_linke_html(raw: Path) -> dict[int, dict]:
    if not raw.exists():
        return {}
    text = raw.read_text(encoding="utf-8", errors="ignore")
    out: dict[int, dict] = {}
    for m in re.finditer(
        r"<tr>\s*<td>(?P<wkr>\d+)\s*[-–][^<]*</td>\s*"
        r"<td[^>]*>(?P<name>[^<]+)</td>\s*<td>(?P<lp>\d+|-)</td>",
        text,
        re.I | re.S,
    ):
        lp = m.group("lp")
        if lp == "-":
            continue
        name = re.sub(r"\s+", " ", m.group("name")).strip()
        out[int(lp)] = {"name": name, "wkr_direct": int(m.group("wkr"))}
    return out


def _load_seed_csv(path: Path, *, bezirk: str | None = None) -> dict[int, dict]:
    """Load curated lists/{party}.csv or lists/{party}_{bez}.csv rows."""
    if not path.exists():
        return {}
    out: dict[int, dict] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                pos = int(r["list_pos"])
            except (KeyError, TypeError, ValueError):
                continue
            row_bez = (r.get("bezirk") or "").strip()
            if bezirk is not None and row_bez and row_bez != bezirk:
                continue
            name = clean_person_name(r.get("name") or "")
            if not name:
                continue
            wkr = (r.get("wkr_direct") or "").strip()
            info: dict = {
                "name": name,
                "source": public_source_url(r.get("source") or ""),
            }
            if wkr.isdigit():
                info["wkr_direct"] = int(wkr)
            out[pos] = info
    return out


def _known_list_slots(
    state: str,
    party: str,
    list_type: str,
    bezirk: str | None,
    direkts: list[dict] | None = None,
) -> dict[int, dict]:
    """Best-effort known names keyed by list_pos (seed CSVs first, then parsers)."""
    known: dict[int, dict] = {}
    lists_dir = STATE_DIRS[state] / "lists"

    if list_type == "landes":
        known.update(_load_seed_csv(lists_dir / f"{party}.csv"))
    elif list_type == "bezirk" and bezirk:
        # Prefer combined harvest, then per-bezirk file
        known.update(
            _load_seed_csv(lists_dir / f"{party}_bezirk.csv", bezirk=bezirk)
        )
        if not known:
            known.update(_load_seed_csv(lists_dir / f"{party}_{bezirk}.csv"))

    # HTML / ad-hoc fallbacks fill gaps only
    def _fill(extra: dict[int, dict]) -> None:
        for pos, info in extra.items():
            if pos not in known:
                known[pos] = info

    if state == "BE" and party == "cdu" and list_type == "bezirk" and bezirk == "06":
        _fill(
            {
                pos: {"name": name, "source": "https://www.cdusz.de/"}
                for pos, name in _parse_berlin_cdu_sz_ol(
                    REPO
                    / "berlin"
                    / "candidates"
                    / "raw"
                    / "bezirk2"
                    / "cdu-sz-k2.html"
                )
            }
        )
    if state == "BE" and party == "afd" and list_type == "landes":
        _fill(
            {
                pos: {
                    "name": name,
                    "source": "https://www.rbb24.de/politik/beitrag/2025/10/berlin-afd-parteitag-kandidaten-wahl-abgeordnetenhaus.html",
                }
                for pos, name in enumerate(
                    [
                        "Kristin Brinker",
                        "Thorsten Bertram",
                        "Robert Wiedenhaupt",
                        "Felix Streeck",
                        "Alexander Kohler",
                    ],
                    1,
                )
            }
        )
    if state == "MV" and party == "cdu" and list_type == "landes":
        _fill(
            {
                pos: {
                    "name": info["name"],
                    "wkr_direct": info.get("wkr_direct"),
                    "source": "https://www.cdu-mv.de/",
                }
                for pos, info in _parse_mv_cdu_md(
                    REPO / "mecklenburg-vorpommern" / "candidates" / "raw_cdu.md",
                    direkts,
                ).items()
            }
        )
    if state == "MV" and party == "spd" and list_type == "landes":
        _fill(
            {
                pos: {
                    "name": info["name"],
                    "wkr_direct": info.get("wkr_direct"),
                    "source": "https://spd-mv.de/wahlen/landtagswahl-2026/kandidaten-landtagswahl-2026",
                }
                for pos, info in _parse_mv_spd_html(
                    REPO / "mecklenburg-vorpommern" / "candidates" / "raw_spd.html",
                    direkts,
                ).items()
            }
        )
    if state == "ST" and party == "linke" and list_type == "landes":
        _fill(
            {
                pos: {
                    "name": info["name"],
                    "wkr_direct": info.get("wkr_direct"),
                    "source": "https://www.die-linke-sachsen-anhalt.de/",
                }
                for pos, info in _parse_st_linke_html(
                    REPO / "sachsen-anhalt" / "candidates" / "raw" / "linke.html"
                ).items()
            }
        )
    return known


def build_state_listen(state: str) -> list[dict]:
    state = state.upper()
    cdir = STATE_DIRS[state]
    direkt_path = cdir / "direktkandidaten_2026.csv"
    direkts = load_direkt(direkt_path)
    wkr_to_bez = load_wkr_to_bezirk() if state == "BE" else {}

    # person_id by (party, normalized name) for dual-candidacy linking
    name_pid: dict[tuple[str, str], str] = {}
    direkt_by_party_wkr: dict[tuple[str, int], dict] = {}

    for d in direkts:
        party = d["party"]
        wkr = d["wkr"]
        if d["name"]:
            pid = _pid(state, party, "person", normalize_name(d["name"]) or f"d{wkr}")
            name_pid[(party, normalize_name(d["name"]))] = pid
            direkt_by_party_wkr[(party, wkr)] = {**d, "person_id": pid}
        else:
            pid = _pid(state, party, "direkt", wkr)
            direkt_by_party_wkr[(party, wkr)] = {
                **d,
                "name": _placeholder_direkt_name(wkr),
                "person_id": pid,
                "is_placeholder": True,
            }

    rows: list[dict] = []

    def add_list_row(
        party: str,
        list_type: str,
        bezirk: str,
        pos: int,
        *,
        name: str | None = None,
        source: str = "",
        wkr_direct: int | None = None,
    ) -> None:
        if name:
            name = clean_person_name(name) or None
        source = public_source_url(source)
        is_ph = not bool(name)
        if is_ph:
            name = _placeholder_list_name(list_type, pos, bezirk or None)
            pid = _pid(
                state,
                party,
                "list",
                list_type,
                bezirk or "land",
                pos,
            )
        else:
            key = (party, normalize_name(name))
            pid = lookup_shared_pid(name_pid, party, name)
            if pid is None:
                pid = _pid(state, party, "person", key[1] or f"list-{pos}")
            name_pid[key] = pid
            # attach wkr_direct from direkt match if missing
            if wkr_direct is None:
                fl = first_last_key(name)
                exact: list[tuple[int, str]] = []
                fuzzy: list[tuple[int, str]] = []
                for (p, wkr), info in direkt_by_party_wkr.items():
                    if p != party:
                        continue
                    dname = info.get("name", "")
                    if normalize_name(dname) == key[1]:
                        exact.append((wkr, dname))
                    elif fl is not None and first_last_key(dname) == fl:
                        fuzzy.append((wkr, dname))
                picks = exact if exact else (fuzzy if len(fuzzy) == 1 else [])
                if len(picks) == 1:
                    wkr_direct, dname = picks[0]
                    name = prefer_display_name(name, dname)
        rows.append(
            {
                "party": party,
                "list_type": list_type,
                "bezirk": bezirk,
                "list_pos": str(pos),
                "name": name,
                "person_id": pid,
                "wkr_direct": "" if wkr_direct is None else str(wkr_direct),
                "source": source,
                "is_placeholder": "1" if is_ph else "0",
            }
        )

    if state == "BE":
        for party in PARTIES_MAIN:
            lt = BE_LIST_TYPE[party]
            if lt == "landes":
                n = LIST_LEN[("BE", "landes")]
                known = _known_list_slots("BE", party, "landes", None, direkts)
                for pos in range(1, n + 1):
                    info = known.get(pos, {})
                    add_list_row(
                        party,
                        "landes",
                        "",
                        pos,
                        name=info.get("name"),
                        source=info.get("source", ""),
                        wkr_direct=info.get("wkr_direct"),
                    )
            else:
                for bez in BEZ_NAMES:
                    known = _known_list_slots("BE", party, "bezirk", bez, direkts)
                    # Only fill through the last known name; trim trailing unknowns.
                    # Gaps before that last known place stay as placeholders.
                    if not known:
                        continue
                    max_pos = max(known)
                    for pos in range(1, max_pos + 1):
                        info = known.get(pos, {})
                        add_list_row(
                            party,
                            "bezirk",
                            bez,
                            pos,
                            name=info.get("name"),
                            source=info.get("source", ""),
                            wkr_direct=info.get("wkr_direct"),
                        )
    else:
        for party in PARTIES_MAIN:
            n = LIST_LEN[(state, "landes")]
            known = _known_list_slots(state, party, "landes", None, direkts)
            for pos in range(1, n + 1):
                info = known.get(pos, {})
                add_list_row(
                    party,
                    "landes",
                    "",
                    pos,
                    name=info.get("name"),
                    source=info.get("source", ""),
                    wkr_direct=info.get("wkr_direct"),
                )

    return rows


def write_listen_csv(state: str, rows: list[dict] | None = None) -> Path:
    state = state.upper()
    path = STATE_DIRS[state] / "listenkandidaten_2026.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    if rows is None:
        rows = build_state_listen(state)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LIST_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in LIST_FIELDS})
    n_ph = sum(1 for r in rows if r.get("is_placeholder") in ("1", True, "true"))
    print(f"Wrote {path} ({len(rows)} rows, {n_ph} placeholders)")
    return path


def load_listen_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                pos = int(r["list_pos"])
            except (KeyError, TypeError, ValueError):
                continue
            wkr = (r.get("wkr_direct") or "").strip()
            out.append(
                {
                    "party": (r.get("party") or "").strip().lower(),
                    "list_type": (r.get("list_type") or "").strip().lower(),
                    "bezirk": (r.get("bezirk") or "").strip(),
                    "list_pos": pos,
                    "name": (r.get("name") or "").strip(),
                    "person_id": (r.get("person_id") or "").strip(),
                    "wkr_direct": int(wkr) if wkr.isdigit() else None,
                    "source": (r.get("source") or "").strip(),
                    "is_placeholder": (r.get("is_placeholder") or "0").strip()
                    in ("1", "true", "True", "yes"),
                }
            )
    return out


def build_roster(state: str) -> dict:
    """Full person roster: list slots + Direkt-only people."""
    state = state.upper()
    cdir = STATE_DIRS[state]
    listen_path = cdir / "listenkandidaten_2026.csv"
    if not listen_path.exists():
        write_listen_csv(state)
    listen = load_listen_csv(listen_path)
    direkts = load_direkt(cdir / "direktkandidaten_2026.csv")
    wkr_to_bez = load_wkr_to_bezirk() if state == "BE" else {}

    # Index list person_ids
    by_pid: dict[str, dict] = {}
    list_slots: list[dict] = []
    for r in listen:
        list_slots.append(r)
        pid = r["person_id"]
        if pid not in by_pid:
            by_pid[pid] = {
                "person_id": pid,
                "party": r["party"],
                "name": r["name"],
                "is_placeholder": r["is_placeholder"],
                "source": r["source"],
                "list_type": r["list_type"],
                "bezirk": r["bezirk"],
                "list_pos": r["list_pos"],
                "wkr_direct": r["wkr_direct"],
            }

    # Direkt coverage: n_wk from max wkr in direkt file or state defaults
    n_wk = {"BE": 78, "MV": 36, "ST": 41}[state]
    parties = list(PARTIES_MAIN)
    direkt_index: dict[tuple[str, int], str] = {}  # (party, wkr) → person_id

    name_to_pid = {
        (r["party"], normalize_name(r["name"])): r["person_id"]
        for r in listen
        if not r["is_placeholder"] and r["name"]
    }

    try:
        from candidate_bio import attach_bio_fields, load_official_bio, lookup_bio

        bio_index = load_official_bio(state)
    except Exception:
        bio_index = {}
        attach_bio_fields = None  # type: ignore
        lookup_bio = None  # type: ignore

    for party in parties:
        for wkr in range(1, n_wk + 1):
            match = next((d for d in direkts if d["party"] == party and d["wkr"] == wkr), None)
            if match and match["name"]:
                key = (party, normalize_name(match["name"]))
                pid = lookup_shared_pid(name_to_pid, party, match["name"])
                if pid is None:
                    pid = _pid(state, party, "person", key[1] or f"d{wkr}")
                    if pid not in by_pid:
                        by_pid[pid] = {
                            "person_id": pid,
                            "party": party,
                            "name": match["name"],
                            "is_placeholder": False,
                            "source": match.get("source", ""),
                            "list_type": None,
                            "bezirk": wkr_to_bez.get(wkr, ""),
                            "list_pos": None,
                            "wkr_direct": wkr,
                        }
                    name_to_pid[key] = pid
                else:
                    name_to_pid[key] = pid
                    by_pid[pid]["name"] = prefer_display_name(
                        by_pid[pid].get("name", ""), match["name"]
                    )
                # ensure wkr_direct set
                by_pid[pid]["wkr_direct"] = wkr
                if match.get("source") and not by_pid[pid].get("source"):
                    by_pid[pid]["source"] = match["source"]
            else:
                pid = _pid(state, party, "direkt", wkr)
                if pid not in by_pid:
                    by_pid[pid] = {
                        "person_id": pid,
                        "party": party,
                        "name": _placeholder_direkt_name(wkr),
                        "is_placeholder": True,
                        "source": "",
                        "list_type": None,
                        "bezirk": wkr_to_bez.get(wkr, ""),
                        "list_pos": None,
                        "wkr_direct": wkr,
                    }
                else:
                    by_pid[pid]["wkr_direct"] = wkr
            direkt_index[(party, wkr)] = pid

    # Attach official bio (ST StaLa etc.) onto named people
    if bio_index and lookup_bio and attach_bio_fields:
        for person in by_pid.values():
            if person.get("is_placeholder") or not person.get("name"):
                continue
            attach_bio_fields(
                person, lookup_bio(bio_index, person["party"], person["name"])
            )

    list_type = (
        {p: BE_LIST_TYPE[p] for p in PARTIES_MAIN}
        if state == "BE"
        else {p: "landes" for p in PARTIES_MAIN}
    )

    return {
        "state": state,
        "people": by_pid,
        "list_slots": list_slots,
        "direkt_index": direkt_index,
        "list_type": list_type,
        "wkr_to_bez": wkr_to_bez,
        "n_wk": n_wk,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--states", nargs="+", default=["BE", "MV", "ST"])
    args = ap.parse_args()
    for st in args.states:
        write_listen_csv(st.upper())


if __name__ == "__main__":
    main()
