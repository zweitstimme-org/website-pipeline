#!/usr/bin/env python3
"""Parse Berlin AGH Musterstimmzettel PDFs into Direkt + list-top CSVs.

Official public names are the Landeswahlleiter sample ballots (born-digital PDFs).
Ballots print every Direktkandidat and the first five names of each Landes-/
Bezirksliste. Positions 6+ are not on the ballot.

Left column = Erststimme; right column = Zweitstimme. Linear text mixes columns,
so we clip by x-coordinate.

Usage:
  python3 code/parse_be_musterstimmzettel.py --download
  python3 code/parse_be_musterstimmzettel.py --apply
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

import fitz

from listen_candidates import (
    BEZ_NAMES,
    clean_person_name,
    load_awk_to_wkr,
    prefer_display_name,
    statewide_wkr_direct,
)

REPO = Path(__file__).resolve().parents[1]
OFFICIAL = REPO / "berlin" / "candidates" / "official"
LISTS = REPO / "berlin" / "candidates" / "lists"
DIREKT_PATH = REPO / "berlin" / "candidates" / "direktkandidaten_2026.csv"
PDF_DIR = Path("/tmp/be-agh-wk")
WLS_JSON = Path("/tmp/wls.json")
WLS_URL = (
    "https://www.wahlen-berlin.de/wahlen/BE2026/wahllokalsuche/wahllokalsuchdaten.json"
)

TRACKED = ("spd", "afd", "cdu", "linke", "gruene", "fdp", "bsw")
PARTY_LABEL = {
    "spd": "SPD",
    "afd": "AfD",
    "cdu": "CDU/CSU",
    "linke": "LINKE",
    "gruene": "GRÜNE",
    "fdp": "FDP",
    "bsw": "BSW",
}
PARTY_TOKEN = {
    "CDU": "cdu",
    "SPD": "spd",
    "GRÜNE": "gruene",
    "Die Linke": "linke",
    "AfD": "afd",
    "FDP": "fdp",
    "BSW": "bsw",
    "Volt": "volt",
    "Einzelbewerber": "einzel",
    "Einzelbewerberin": "einzel",
}

# Occupations / ballot chrome that can look like "Last, First".
_JUNK = re.compile(
    r"(?i)\b("
    r"rentner(?:in)?|angestellte[rs]?|referent(?:in)?|mitarbeiter(?:in)?|"
    r"student(?:in)?|rechtsanwalt|rechtsanwältin|journalist(?:in)?|"
    r"autor(?:in)?|psychotherapeut(?:in)?|leiter(?:in)?|beamte[rsn]?|"
    r"selbstst[aä]ndig|b[uü]roleiter(?:in)?|sachbearbeiter(?:in)?|"
    r"fachwirt(?:in)?|mitglied|abgeordnetenhaus|forschung|stadtentw|"
    r"wahlkreisb[uü]ro|wissenschaftlich|projektleiter(?:in)?|"
    r"grundschul|lehrer(?:in)?|erzieher(?:in)?|"
    r"ingenieur(?:in)?|arzt|ärztin|soziolog|"
    r"elitenf[oö]rderung|tierschutz|partei"
    r")\b"
)

# Unicode letters so Ş/Ș/Ç/Ğ last names parse; spaces for "Caballero Alvarez".
_NAME_RE = re.compile(
    r"^(?:(?:Prof\.\s*)?(?:Dr\.\s*)+)?"
    r"[^\s,][\w.'’\-]*(?:\s+[^\s,][\w.'’\-]*)*"
    r",\s+"
    r"(?:(?:Dr\.\s*)+)?[^\s,][\w.'’\-].*$",
    re.UNICODE,
)


def _looks_like_name(line: str) -> bool:
    s = re.sub(r"\s+", " ", (line or "").strip())
    if not s or "," not in s:
        return False
    if not _NAME_RE.match(s):
        return False
    left, right = [p.strip() for p in s.split(",", 1)]
    if len(left.split()) > 5 or len(right.split()) > 5:
        return False
    # Occupations sit *under* the name, not in the given-name slot.
    if _JUNK.search(right):
        return False
    return True


_PARTY_CHROME = re.compile(
    r"(?i)^(die\s+linke|christlich|sozialdemokrat|bündnis|alternative\s+f[uü]r|"
    r"freie\s+demokrat|volt(\s+deutschland)?|einzelbewerber|"
    r"vernunft\s+und|deutschlands$)"
)


def _is_party_chrome(line: str) -> bool:
    s = re.sub(r"\s+", " ", (line or "").strip())
    if not s:
        return True
    if s in PARTY_TOKEN:
        return True
    return bool(_PARTY_CHROME.search(s))


def _looks_like_unflipped_name(line: str) -> bool:
    """Ballot sometimes prints 'Nguyen Thuy Dung' without a comma."""
    s = re.sub(r"\s+", " ", (line or "").strip())
    if not s or "," in s:
        return False
    if _is_party_chrome(s) or _JUNK.search(s):
        return False
    parts = s.split()
    if not 2 <= len(parts) <= 4:
        return False
    blob = s.lower()
    if any(
        k in blob
        for k in (
            "union",
            "partei",
            "bündnis",
            "alternative",
            "deutschland",
            "grüne",
            "linke",
            "volt",
        )
    ):
        return False
    for p in parts:
        if p.endswith("."):
            continue
        if not p[0].isupper():
            return False
    return True


def _find_party(window: list[str]) -> str | None:
    for w in window:
        if w in PARTY_TOKEN:
            return PARTY_TOKEN[w]
    return None


def _header(page: fitz.Page) -> tuple[str, int] | None:
    full = page.get_text()
    if "Abgeordnetenhaus" not in full:
        return None
    if full.find("Bezirksverordnetenversammlung") != -1 and full.find(
        "Abgeordnetenhaus"
    ) > full.find("Bezirksverordnetenversammlung"):
        return None
    m_bez = re.search(r"Wahlkreisverband:\s*.+?\s*\((\d{2})\)", full)
    m_wk = re.search(r"Wahlkreis Nr\.:\s*(\d+)", full)
    if not m_bez or not m_wk:
        return None
    return m_bez.group(1), int(m_wk.group(1))


def parse_pdf(path: Path) -> tuple[list[dict], list[dict]]:
    """Return (direkt rows, list-top rows) for one AGH ballot PDF."""
    doc = fitz.open(path)
    direkts: list[dict] = []
    lists: list[dict] = []
    seen_d: set[tuple] = set()
    seen_l: set[tuple] = set()
    for page in doc:
        hdr = _header(page)
        if not hdr:
            continue
        bez, wk_local = hdr
        r = page.rect
        left = page.get_text("text", clip=fitz.Rect(r.x0, r.y0, r.x0 + r.width * 0.46, r.y1))
        right = page.get_text(
            "text", clip=fitz.Rect(r.x0 + r.width * 0.50, r.y0, r.x1, r.y1)
        )
        lines = [ln.strip() for ln in left.splitlines() if ln.strip()]
        seen_party: set[str] = set()
        i = 0
        while i < len(lines):
            line = lines[i]
            if _is_party_chrome(line):
                i += 1
                continue
            if _looks_like_name(line) or _looks_like_unflipped_name(line):
                party = _find_party(lines[i + 1 : i + 8])
                if party and party in TRACKED and party not in seen_party:
                    name = clean_person_name(line) if "," in line else re.sub(r"\s+", " ", line).strip()
                    if name and not _JUNK.search(name) and not _is_party_chrome(name):
                        key = (bez, wk_local, party)
                        if key not in seen_d:
                            seen_d.add(key)
                            direkts.append(
                                {
                                    "bezirk": bez,
                                    "wk_local": wk_local,
                                    "party": party,
                                    "name": name,
                                    "source": str(path),
                                }
                            )
                        seen_party.add(party)
            i += 1
        for party, names in _parse_list_tops(right).items():
            if party not in TRACKED or not names:
                continue
            for pos, name in enumerate(names[:5], 1):
                key = (party, bez, pos, name)
                if key in seen_l:
                    continue
                seen_l.add(key)
                lists.append(
                    {
                        "party": party,
                        "bezirk": bez,
                        "list_pos": pos,
                        "name": name,
                    }
                )
    return direkts, lists


def _parse_list_tops(right_text: str) -> dict[str, list[str]]:
    """First ≤5 names after each party header in the Zweitstimme column."""
    lines = [ln.strip() for ln in right_text.splitlines() if ln.strip()]
    out: dict[str, list[str]] = {}
    i = 0
    while i < len(lines):
        party = PARTY_TOKEN.get(lines[i])
        if not party or party in out:
            i += 1
            continue
        # Skip long party name lines, then collect until a lone integer (row no.)
        chunk: list[str] = []
        j = i + 1
        while j < len(lines) and not re.fullmatch(r"\d{1,2}", lines[j]):
            tok = lines[j]
            if tok in PARTY_TOKEN and chunk:
                break
            if tok in PARTY_TOKEN:
                j += 1
                continue
            # skip official long names
            if tok.lower().startswith("christlich") or tok.lower().startswith(
                "sozialdemokrat"
            ):
                j += 1
                continue
            if tok.lower() in {
                "deutschlands",
                "bündnis 90/die grünen",
                "die linke",
                "alternative für deutschland",
                "freie demokratische partei",
                "volt deutschland",
                "bündnis sahra wagenknecht -",
                "vernunft und gerechtigkeit",
            }:
                j += 1
                continue
            chunk.append(tok)
            j += 1
        blob = " ".join(chunk)
        blob = blob.replace(" ,", ",").replace(",,", ",")
        names = []
        for part in blob.split(","):
            n = clean_person_name(part.replace("\n", " "))
            n = re.sub(r"\s+", " ", n).strip(" -")
            if n and not _JUNK.search(n) and 2 <= len(n.split()) <= 6:
                names.append(n)
        if names:
            out[party] = names[:5]
        i = j
    return out


def unique_pdf_urls() -> list[str]:
    if not WLS_JSON.exists():
        urllib.request.urlretrieve(WLS_URL, WLS_JSON)
    data = json.loads(WLS_JSON.read_text(encoding="utf-8"))
    urls = sorted(
        {
            v["kv"]["stimmzettel1_url"]
            for v in data["wahllokale"].values()
            if v.get("kv", {}).get("stimmzettel1_url")
        }
    )
    return urls


def download_pdfs(delay_s: float = 0.25) -> list[Path]:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    opener = urllib.request.build_opener()
    opener.addheaders = [("User-Agent", "zweitstimme.org candidate ingest")]
    urllib.request.install_opener(opener)
    for i, url in enumerate(unique_pdf_urls(), 1):
        dest = PDF_DIR / Path(url).name
        if dest.exists() and dest.stat().st_size > 10_000:
            paths.append(dest)
            continue
        quoted = urllib.parse.quote(url, safe=":/")
        try:
            urllib.request.urlretrieve(quoted, dest)
            print(f"  [{i}] {dest.name}")
        except Exception as e:
            print(f"  FAIL {url}: {e}")
            continue
        paths.append(dest)
        time.sleep(delay_s)
    return paths


def parse_all(pdfs: list[Path]) -> tuple[list[dict], list[dict]]:
    awk = load_awk_to_wkr()
    direkt_by: dict[tuple[str, int], dict] = {}
    list_votes: dict[tuple[str, str, int, str], int] = defaultdict(int)
    for p in pdfs:
        drows, lrows = parse_pdf(p)
        for r in drows:
            awk_key = f"{r['bezirk']}{r['wk_local']:02d}"
            wkr = awk.get(awk_key)
            if wkr is None:
                continue
            r = {**r, "wkr": wkr, "source": f"https://www.wahlen-berlin.de/wahlen/BE2026/wahllokalsuche/Stimmzettel/{p.name}"}
            direkt_by[(r["party"], wkr)] = r
        for r in lrows:
            list_votes[(r["party"], r["bezirk"], r["list_pos"], r["name"])] += 1
    # Majority vote per (party, bezirk, pos) — Landeslisten repeat in every WK
    best: dict[tuple[str, str, int], tuple[int, str]] = {}
    for (party, bez, pos, name), n in list_votes.items():
        key = (party, bez, pos)
        if key not in best or n > best[key][0]:
            best[key] = (n, name)
    # Landes vs Bezirk: if the same 5 names appear in every bezirk, it's Landesliste
    by_party_pos: dict[tuple[str, int], dict[str, str]] = defaultdict(dict)
    for (party, bez, pos), (_, name) in best.items():
        by_party_pos[(party, pos)][bez] = name
    list_rows: list[dict] = []
    landes_parties: set[str] = set()
    for (party, pos), bez_names in by_party_pos.items():
        uniq = set(bez_names.values())
        if len(bez_names) >= 8 and len(uniq) == 1:
            landes_parties.add(party)
    for (party, bez, pos), (_, name) in sorted(best.items()):
        list_type = "landes" if party in landes_parties else "bezirk"
        if list_type == "landes" and bez != min(BEZ_NAMES):
            continue
        list_rows.append(
            {
                "party": party,
                "list_type": list_type,
                "bezirk": "" if list_type == "landes" else bez,
                "list_pos": pos,
                "name": name,
                "source": "https://www.berlin.de/wahlen/wahlen/berliner-wahlen-2026/wahllokalsuche/artikel.1701445.php",
            }
        )
    direkts = [direkt_by[k] for k in sorted(direkt_by, key=lambda x: (x[1], x[0]))]
    return direkts, list_rows


def write_official(direkts: list[dict], lists: list[dict]) -> None:
    OFFICIAL.mkdir(parents=True, exist_ok=True)
    dpath = OFFICIAL / "direkt_from_musterstimmzettel.csv"
    with dpath.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["wkr", "party", "partei", "name", "bezirk", "wk_local", "source"]
        )
        w.writeheader()
        for r in direkts:
            w.writerow(
                {
                    "wkr": r["wkr"],
                    "party": r["party"],
                    "partei": PARTY_LABEL[r["party"]],
                    "name": r["name"],
                    "bezirk": r["bezirk"],
                    "wk_local": r["wk_local"],
                    "source": r["source"],
                }
            )
    lpath = OFFICIAL / "list_tops.csv"
    with lpath.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["party", "list_type", "bezirk", "list_pos", "name", "source"]
        )
        w.writeheader()
        for r in lists:
            w.writerow(r)
    urls = {
        "wahllokalsuche": "https://www.berlin.de/wahlen/wahlen/berliner-wahlen-2026/wahllokalsuche/artikel.1701445.php",
        "per_wk_pattern": "https://www.wahlen-berlin.de/wahlen/BE2026/wahllokalsuche/Stimmzettel/Muster_AGH_{bez}_{name}_{bez}-{wk}.pdf",
        "note": "AGH Musterstimmzettel: all Direkt names + first 5 of each list. Not a full Bewerberverzeichnis.",
    }
    (OFFICIAL / "source_urls.json").write_text(
        json.dumps(urls, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote {dpath} ({len(direkts)} Direkt)")
    print(f"Wrote {lpath} ({len(lists)} list-top rows)")


def apply_direkt(official: list[dict]) -> None:
    existing: dict[tuple[str, int], dict] = {}
    with DIREKT_PATH.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys()) if rows else ["wkr", "party", "partei", "name", "source"]
        for r in rows:
            existing[(r["party"].strip().lower(), int(r["wkr"]))] = r
    added = updated = kept = 0
    for o in official:
        key = (o["party"], int(o["wkr"]))
        cur = existing.get(key)
        if cur is None:
            existing[key] = {
                "wkr": str(o["wkr"]),
                "party": o["party"],
                "partei": PARTY_LABEL[o["party"]],
                "name": o["name"],
                "source": o["source"],
            }
            added += 1
            continue
        old = (cur.get("name") or "").strip()
        new = o["name"]
        if old == new:
            kept += 1
            continue
        # Same (party, WK) slot: the ballot is authoritative.
        cur["name"] = new
        cur["source"] = o["source"]
        updated += 1
        existing[key] = cur
    official_keys = {(o["party"], int(o["wkr"])) for o in official}
    dropped = 0
    for key in list(existing):
        party, _wkr = key
        if party in TRACKED and key not in official_keys:
            del existing[key]
            dropped += 1
    out = sorted(existing.values(), key=lambda r: (int(r["wkr"]), r["party"]))
    with DIREKT_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out)
    print(
        f"direktkandidaten_2026.csv: +{added} filled, {updated} respellt, "
        f"{kept} unchanged, {dropped} dropped (not on ballot)"
    )


def _same_tokens(a: str, b: str) -> bool:
    from listen_candidates import first_last_key, normalize_name

    if normalize_name(a) == normalize_name(b):
        return True
    fa, fb = first_last_key(a), first_last_key(b)
    return bool(fa and fa == fb)


def apply_list_seeds(official: list[dict]) -> None:
    """Patch positions 1–5 in seed CSVs; add missing CDU Bezirkslisten tops."""
    by_key: dict[tuple, dict] = {}
    for r in official:
        by_key[(r["party"], r["list_type"], r.get("bezirk") or "", int(r["list_pos"]))] = r

    def patch_file(path: Path, party: str, list_type: str, bezirk: str) -> None:
        if not path.exists():
            return
        with path.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
            fields = list(rows[0].keys()) if rows else [
                "list_pos",
                "name",
                "wkr_direct",
                "bezirk",
                "source",
            ]
        changed = 0
        for row in rows:
            try:
                pos = int(row["list_pos"])
            except (KeyError, ValueError):
                continue
            if pos > 5:
                continue
            row_bez = (row.get("bezirk") or bezirk or "").strip()
            if list_type == "bezirk" and bezirk and row_bez and row_bez != bezirk:
                continue
            info = by_key.get((party, list_type, row_bez if list_type == "bezirk" else "", pos))
            if not info:
                continue
            if (row.get("name") or "").strip() != info["name"]:
                row["name"] = info["name"]
                changed += 1
        if changed:
            with path.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                w.writerows(rows)
            print(f"  {path.name}: {changed} list-top names from ballot")

    for party in TRACKED:
        patch_file(LISTS / f"{party}.csv", party, "landes", "")
        patch_file(LISTS / f"{party}_bezirk.csv", party, "bezirk", "")
        for bez in BEZ_NAMES:
            patch_file(LISTS / f"{party}_{bez}.csv", party, "bezirk", bez)

    # Missing CDU Bezirkslisten: write first 5 from ballots into cdu_bezirk.csv
    with (LISTS / "cdu_bezirk.csv").open(newline="", encoding="utf-8") as f:
        cdu_rows = list(csv.DictReader(f))
        cdu_fields = list(cdu_rows[0].keys())
    have = {r.get("bezirk") for r in cdu_rows}
    added = 0
    src = "https://www.berlin.de/wahlen/wahlen/berliner-wahlen-2026/wahllokalsuche/artikel.1701445.php"
    for bez in BEZ_NAMES:
        if bez in have:
            continue
        tops = [
            by_key[(p, lt, b, pos)]
            for (p, lt, b, pos) in sorted(by_key)
            if p == "cdu" and lt == "bezirk" and b == bez
        ]
        if not tops:
            continue
        for info in tops:
            cdu_rows.append(
                {
                    "list_pos": str(info["list_pos"]),
                    "name": info["name"],
                    "wkr_direct": "",
                    "bezirk": bez,
                    "source": src,
                }
            )
            added += 1
            have.add(bez)
    if added:
        with (LISTS / "cdu_bezirk.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cdu_fields)
            w.writeheader()
            w.writerows(cdu_rows)
        print(f"  cdu_bezirk.csv: +{added} official list-top rows for missing Bezirke")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--apply", action="store_true", help="Patch direkt + list seed CSVs")
    ap.add_argument("--pdf-dir", type=Path, default=PDF_DIR)
    args = ap.parse_args()
    pdfs: list[Path] = []
    if args.download:
        print("Downloading per-WK AGH Musterstimmzettel …")
        pdfs = download_pdfs()
    pdfs = sorted(args.pdf_dir.glob("Muster_AGH_*.pdf")) or sorted(
        Path("/tmp/be-muster").glob("musterstimmzettel---*.pdf")
    )
    if not pdfs:
        raise SystemExit("No PDFs found. Run with --download.")
    print(f"Parsing {len(pdfs)} PDFs …")
    direkts, lists = parse_all(pdfs)
    write_official(direkts, lists)
    from collections import Counter

    print("Direkt by party:", dict(Counter(r["party"] for r in direkts)))
    if args.apply:
        apply_direkt(direkts)
        apply_list_seeds(lists)


if __name__ == "__main__":
    main()
