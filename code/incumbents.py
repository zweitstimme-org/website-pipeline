#!/usr/bin/env python3
"""Sitting-MP incumbency for 2026 candidates (abgeordnetenwatch.de).

Fetches current-legislature mandates via the public API (CC0), matches them to
our Direkt/Listen rosters, and writes:

  data/incumbents_2026.csv          — durable lookup for the forecast pipeline
  tmp/incumbents/aw_*               — cache + audit CSVs

Matching (conservative):
  1. exact (party, normalize_name)
  2. unique first+last within party
  3. exact name, unique party among 2026 hits (party switch / fraktionslos)
  Manual overrides: data/incumbent_overrides.csv

Does **not** use unique-lastname-only matching (too many false friends).

Usage
-----
  python code/incumbents.py                 # fetch + match + write data/
  python code/incumbents.py --offline       # reuse tmp/incumbents/aw_cache/
  python code/incumbents.py --attach-json   # also patch output/*.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "code"))

from listen_candidates import (  # noqa: E402
    STATE_DIRS,
    clean_person_name,
    first_last_key,
    normalize_name,
)

OUT_CSV = REPO / "data" / "incumbents_2026.csv"
OVERRIDES = REPO / "data" / "incumbent_overrides.csv"
TMP = REPO / "tmp" / "incumbents"
AW_CACHE = TMP / "aw_cache"

# Current Wahlperiode legislatures on abgeordnetenwatch
AW_LEGISLATURES = {
    "BE": 133,  # Berlin 2021–2026 (incl. post-Wiederholungswahl composition)
    "ST": 131,  # Sachsen-Anhalt 2021–2026
    "MV": 134,  # Mecklenburg-Vorpommern 2021–2026
}

CHAMBER = {"BE": "MdA", "MV": "MdL", "ST": "MdL"}

PARTY_ALIASES = {
    "buendnis 90/die gruenen": "gruene",
    "buendnis90/die gruenen": "gruene",
    "die gruenen": "gruene",
    "gruenen": "gruene",
    "gruene": "gruene",
    "grune": "gruene",
    "die linke": "linke",
    "linke": "linke",
    "spd": "spd",
    "cdu": "cdu",
    "afd": "afd",
    "fdp": "fdp",
    "gruppe fdp": "fdp",
    "bsw": "bsw",
    "buendnis sahra wagenknecht": "bsw",
    "freie waehler": "fw",
    "fw": "fw",
}

ACCEPT_HOW = frozenset(
    {"exact", "first_last", "exact_cross_party", "override"}
)


def _strip_invisible(s: str) -> str:
    return (
        (s or "")
        .replace("\xad", "")
        .replace("\u00ad", "")
        .replace("\u200b", "")
        .replace("\ufeff", "")
    )


def canon_party(label: str) -> str:
    s = _strip_invisible(label).strip()
    if not s:
        return ""
    s = re.sub(r"\s*\(.*\)\s*$", "", s).strip()
    low = s.lower()
    if low.startswith("fraktionslos"):
        m = re.search(r"\(([^)]+)\)", s)
        return canon_party(m.group(1)) if m else ""
    key = (
        low.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    key = re.sub(r"[\s\-]+", " ", key).strip()
    key = key.replace(" / ", "/").replace(" /", "/").replace("/ ", "/")
    if key in PARTY_ALIASES:
        return PARTY_ALIASES[key]
    compact = key.replace(" ", "")
    if compact in PARTY_ALIASES:
        return PARTY_ALIASES[compact]
    return key.replace(" ", "_")


def _http_get_json(url: str, retries: int = 6) -> dict:
    for i in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "website-pipeline/incumbents (research; fair-use)"},
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 429 and i < retries - 1:
                time.sleep(65)
                continue
            raise
    raise RuntimeError(f"failed GET {url}")


def fetch_aw_mandates(
    state: str, *, offline: bool = False, refresh: bool = False
) -> list[dict]:
    AW_CACHE.mkdir(parents=True, exist_ok=True)
    cache = AW_CACHE / f"{state.lower()}_mandates.json"
    if cache.exists() and cache.stat().st_size > 500 and not refresh:
        return json.loads(cache.read_text(encoding="utf-8"))["data"]
    if offline:
        raise FileNotFoundError(f"--offline but missing {cache}")

    pid = AW_LEGISLATURES[state]
    rows: list[dict] = []
    page = 0
    while True:
        url = (
            "https://www.abgeordnetenwatch.de/api/v2/candidacies-mandates"
            f"?parliament_period={pid}&type=mandate&page={page}&pager_limit=100"
        )
        payload = _http_get_json(url)
        rows.extend(payload["data"])
        total = payload["meta"]["result"]["total"]
        if len(rows) >= total:
            break
        page += 1
        time.sleep(2.2)
    cache.write_text(
        json.dumps({"parliament_period": pid, "data": rows}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    time.sleep(2.2)
    return rows


def _party_from_mandate(m: dict) -> str:
    fracs = m.get("fraction_membership") or []
    cur = None
    for f in fracs:
        if f.get("valid_until") in (None, ""):
            cur = f
            break
    if cur is None and fracs:
        cur = fracs[-1]
    if cur:
        p = canon_party((cur.get("fraction") or {}).get("label") or "")
        if p:
            return p
    if m.get("party"):
        return canon_party((m["party"] or {}).get("label") or "")
    return ""


def parse_sitting_mps(state: str, raw: list[dict]) -> list[dict]:
    """Current (non-ended) mandates → flat rows."""
    out: list[dict] = []
    for m in raw:
        if m.get("end_date"):
            continue
        pol = m.get("politician") or {}
        name = clean_person_name(pol.get("label") or "")
        if not name:
            continue
        ed = m.get("electoral_data") or {}
        const = (ed.get("constituency") or {}).get("label") or ""
        elist = (ed.get("electoral_list") or {}).get("label") or ""
        out.append(
            {
                "state": state,
                "name": name,
                "party": _party_from_mandate(m),
                "politician_id": pol.get("id") or "",
                "aw_url": pol.get("abgeordnetenwatch_url") or "",
                "mandate_won": ed.get("mandate_won") or "",
                "constituency": const,
                "electoral_list": elist,
                "start_date": m.get("start_date") or "",
                "info": m.get("info") or "",
                "source": "abgeordnetenwatch",
            }
        )
    return out


def load_2026_candidates(state: str) -> list[dict]:
    ddir = STATE_DIRS[state]
    rows: list[dict] = []
    direkt = ddir / "direktkandidaten_2026.csv"
    if direkt.exists():
        with direkt.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if not (r.get("name") or "").strip():
                    continue
                rows.append(
                    {
                        "cand_type": "direkt",
                        "party": r["party"],
                        "name": clean_person_name(r["name"]),
                        "wkr": r.get("wkr") or "",
                        "list_pos": "",
                        "person_id": "",
                    }
                )
    listen = ddir / "listenkandidaten_2026.csv"
    if listen.exists():
        with listen.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("is_placeholder") in ("1", "true", "True"):
                    continue
                if not (r.get("name") or "").strip():
                    continue
                rows.append(
                    {
                        "cand_type": "liste",
                        "party": r["party"],
                        "name": clean_person_name(r["name"]),
                        "wkr": r.get("wkr_direct") or "",
                        "list_pos": r.get("list_pos") or "",
                        "person_id": r.get("person_id") or "",
                    }
                )
    return rows


def load_overrides(path: Path = OVERRIDES) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _index_cands(
    cands: list[dict],
) -> tuple[
    dict[tuple[str, str], list[dict]],
    dict[tuple[str, tuple[str, str]], list[dict]],
]:
    by_norm: dict[tuple[str, str], list[dict]] = defaultdict(list)
    by_fl: dict[tuple[str, tuple[str, str]], list[dict]] = defaultdict(list)
    for c in cands:
        by_norm[(c["party"], normalize_name(c["name"]))].append(c)
        fl = first_last_key(c["name"])
        if fl:
            by_fl[(c["party"], fl)].append(c)
    return by_norm, by_fl


def match_mps_to_candidates(
    mps: list[dict], cands: list[dict]
) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (accepted_match_rows, unmatched_mps, rejected_ambiguous)."""
    by_norm, by_fl = _index_cands(cands)
    accepted: list[dict] = []
    unmatched: list[dict] = []
    rejected: list[dict] = []

    for mp in mps:
        party = mp.get("party") or ""
        n = normalize_name(mp["name"])
        fl = first_last_key(mp["name"])
        hits: list[dict] = []
        how = "none"

        if party:
            hits = by_norm.get((party, n), [])
            how = "exact"
            if not hits and fl:
                cand_hits = by_fl.get((party, fl), [])
                # Accept only if a single normalized identity
                norms = {normalize_name(h["name"]) for h in cand_hits}
                if len(norms) == 1:
                    hits = cand_hits
                    how = "first_last"
                elif cand_hits:
                    rejected.append({**mp, "reject_how": "first_last_ambiguous", "cand_names": "|".join(sorted({h["name"] for h in cand_hits}))})
                    continue

        if not hits:
            any_hits = [c for c in cands if normalize_name(c["name"]) == n]
            parties = {c["party"] for c in any_hits}
            if any_hits and len(parties) == 1:
                hits = any_hits
                how = "exact_cross_party"
            elif any_hits:
                rejected.append(
                    {
                        **mp,
                        "reject_how": "exact_cross_party_multi",
                        "cand_names": "|".join(
                            sorted({f"{h['party']}:{h['name']}" for h in any_hits})
                        ),
                    }
                )
                continue

        if not hits or how not in ACCEPT_HOW:
            unmatched.append(mp)
            continue

        seen: set[tuple] = set()
        for h in hits:
            key = (h["cand_type"], h["party"], h["name"], h["wkr"], h["list_pos"])
            if key in seen:
                continue
            seen.add(key)
            accepted.append(
                {
                    "state": mp["state"],
                    "party": h["party"],  # candidate party (roster)
                    "name": h["name"],
                    "norm_name": normalize_name(h["name"]),
                    "cand_type": h["cand_type"],
                    "wkr": h["wkr"],
                    "list_pos": h["list_pos"],
                    "person_id": h.get("person_id") or "",
                    "match_how": how,
                    "aw_name": mp["name"],
                    "aw_party": mp.get("party") or "",
                    "aw_politician_id": mp.get("politician_id") or "",
                    "aw_url": mp.get("aw_url") or "",
                    "mandate_won": mp.get("mandate_won") or "",
                    "seat_label": mp.get("constituency") or mp.get("electoral_list") or "",
                    "chamber": CHAMBER.get(mp["state"], "MdL"),
                    "source": "abgeordnetenwatch",
                }
            )
    return accepted, unmatched, rejected


def apply_overrides(
    flags: dict[tuple[str, str, str], dict], overrides: list[dict]
) -> None:
    """Force include/exclude. Columns: state,party,name,action(include|exclude),aw_url?"""
    for o in overrides:
        state = (o.get("state") or "").upper().strip()
        party = (o.get("party") or "").strip().lower()
        name = clean_person_name(o.get("name") or "")
        action = (o.get("action") or "include").strip().lower()
        if not state or not party or not name:
            continue
        key = (state, party, normalize_name(name))
        if action == "exclude":
            flags.pop(key, None)
            continue
        flags[key] = {
            "state": state,
            "party": party,
            "name": name,
            "norm_name": key[2],
            "match_how": "override",
            "aw_name": o.get("aw_name") or name,
            "aw_party": o.get("aw_party") or party,
            "aw_politician_id": o.get("aw_politician_id") or "",
            "aw_url": o.get("aw_url") or "",
            "mandate_won": o.get("mandate_won") or "",
            "seat_label": o.get("seat_label") or "",
            "chamber": CHAMBER.get(state, "MdL"),
            "source": "override",
        }


def person_flags_from_matches(matches: list[dict]) -> dict[tuple[str, str, str], dict]:
    """Deduplicate to one row per (state, party, norm_name)."""
    flags: dict[tuple[str, str, str], dict] = {}
    for r in matches:
        key = (r["state"], r["party"], r["norm_name"])
        prev = flags.get(key)
        if prev:
            # Prefer row that has aw_url / richer mandate info
            if not prev.get("aw_url") and r.get("aw_url"):
                flags[key] = {**r}
            continue
        flags[key] = {
            "state": r["state"],
            "party": r["party"],
            "name": r["name"],
            "norm_name": r["norm_name"],
            "match_how": r["match_how"],
            "aw_name": r["aw_name"],
            "aw_party": r["aw_party"],
            "aw_politician_id": r["aw_politician_id"],
            "aw_url": r["aw_url"],
            "mandate_won": r["mandate_won"],
            "seat_label": r["seat_label"],
            "chamber": r["chamber"],
            "source": r["source"],
        }
    return flags


def write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        if fieldnames:
            with path.open("w", encoding="utf-8", newline="") as f:
                csv.DictWriter(f, fieldnames=fieldnames).writeheader()
        else:
            path.write_text("", encoding="utf-8")
        return
    fields = fieldnames or list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def load_incumbent_index(
    path: Path = OUT_CSV,
) -> dict[tuple[str, str, str], dict]:
    """(state, party, norm_name) → flag row."""
    if not path.exists():
        return {}
    out: dict[tuple[str, str, str], dict] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            key = (
                (r.get("state") or "").upper(),
                (r.get("party") or "").lower(),
                r.get("norm_name") or normalize_name(r.get("name") or ""),
            )
            if key[0] and key[1] and key[2]:
                out[key] = r
    return out


def lookup_incumbent(
    index: dict[tuple[str, str, str], dict],
    state: str,
    party: str,
    name: str,
) -> dict | None:
    if not name or not index:
        return None
    key = (state.upper(), (party or "").lower(), normalize_name(name))
    return index.get(key)


def attach_incumbent_fields(entry: dict, flag: dict | None) -> None:
    if not flag:
        return
    entry["is_incumbent"] = True
    entry["incumbent_chamber"] = flag.get("chamber") or ""
    if flag.get("aw_url"):
        entry["incumbent_url"] = flag["aw_url"]
    if flag.get("mandate_won"):
        entry["incumbent_mandate"] = flag["mandate_won"]
    if flag.get("match_how"):
        entry["incumbent_match"] = flag["match_how"]


def attach_to_district_json(path: Path, index: dict[tuple[str, str, str], dict]) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    state = (data.get("metadata") or {}).get("state_code") or ""
    n = 0
    for item in data.get("items") or []:
        name = item.get("name")
        party = item.get("party")
        flag = lookup_incumbent(index, state, party or "", name or "")
        # Clear previous flags so re-runs stay consistent
        for k in (
            "is_incumbent",
            "incumbent_chamber",
            "incumbent_url",
            "incumbent_mandate",
            "incumbent_match",
        ):
            item.pop(k, None)
        if flag:
            attach_incumbent_fields(item, flag)
            n += 1
    meta = data.setdefault("metadata", {})
    meta["incumbents"] = "abgeordnetenwatch sitting MPs matched to 2026 names"
    meta["incumbents_file"] = str(OUT_CSV.relative_to(REPO))
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return n


def attach_to_entry_json(path: Path, index: dict[tuple[str, str, str], dict]) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    n = 0
    states = data.get("states") or {}
    # Support dict keyed by state code (current) or list of state objects.
    state_iter = (
        states.items()
        if isinstance(states, dict)
        else [
            ((s.get("state") or s.get("state_code") or "").upper(), s) for s in states
        ]
    )
    for state_key, st in state_iter:
        state = (state_key or st.get("state_code") or st.get("state") or "").upper()
        for party in st.get("parties") or []:
            code = (party.get("party") or party.get("code") or "").lower()
            for c in party.get("candidates") or []:
                for k in (
                    "is_incumbent",
                    "incumbent_chamber",
                    "incumbent_url",
                    "incumbent_mandate",
                    "incumbent_match",
                ):
                    c.pop(k, None)
                if c.get("is_placeholder"):
                    continue
                flag = lookup_incumbent(index, state, code, c.get("name") or "")
                if flag:
                    attach_incumbent_fields(c, flag)
                    n += 1
    meta = data.setdefault("metadata", {})
    meta["incumbents"] = "abgeordnetenwatch sitting MPs matched to 2026 names"
    meta["incumbents_file"] = str(OUT_CSV.relative_to(REPO))
    path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
    return n


def build(
    *, states: list[str], offline: bool = False, refresh: bool = False
) -> dict[tuple[str, str, str], dict]:
    TMP.mkdir(parents=True, exist_ok=True)
    all_mps: list[dict] = []
    all_matches: list[dict] = []
    all_unmatched: list[dict] = []
    all_rejected: list[dict] = []

    for state in states:
        print(f"=== {state} ===")
        raw = fetch_aw_mandates(state, offline=offline, refresh=refresh)
        mps = parse_sitting_mps(state, raw)
        cands = load_2026_candidates(state)
        matches, unmatched, rejected = match_mps_to_candidates(mps, cands)
        print(
            f"  AW sitting: {len(mps)}  2026 named: {len(cands)}  "
            f"match rows: {len(matches)}  unmatched: {len(unmatched)}  "
            f"rejected: {len(rejected)}"
        )
        print("  match_how:", Counter(m["match_how"] for m in matches))
        all_mps.extend(mps)
        all_matches.extend(matches)
        all_unmatched.extend(unmatched)
        all_rejected.extend(rejected)

    flags = person_flags_from_matches(all_matches)
    apply_overrides(flags, load_overrides())

    flag_rows = sorted(flags.values(), key=lambda r: (r["state"], r["party"], r["name"]))
    write_csv(
        OUT_CSV,
        flag_rows,
        fieldnames=[
            "state",
            "party",
            "name",
            "norm_name",
            "match_how",
            "aw_name",
            "aw_party",
            "aw_politician_id",
            "aw_url",
            "mandate_won",
            "seat_label",
            "chamber",
            "source",
        ],
    )
    write_csv(TMP / "aw_sitting_mps.csv", all_mps)
    write_csv(TMP / "aw_matches.csv", all_matches)
    write_csv(TMP / "aw_unmatched.csv", all_unmatched)
    write_csv(TMP / "aw_rejected.csv", all_rejected)

    print(f"\nWrote {OUT_CSV} ({len(flag_rows)} persons)")
    print(f"  audit under {TMP}/aw_*.csv")
    for st in states:
        n = sum(1 for r in flag_rows if r["state"] == st)
        print(f"  {st}: {n}")
    return flags


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--states", nargs="+", default=["BE", "MV", "ST"], choices=["BE", "MV", "ST"])
    ap.add_argument("--offline", action="store_true", help="Reuse AW JSON cache")
    ap.add_argument(
        "--attach-json",
        action="store_true",
        help="Patch output/forecast_districts_*.json and forecast_candidate_entry.json",
    )
    ap.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore cache and re-fetch from abgeordnetenwatch",
    )
    args = ap.parse_args()
    flags = build(states=args.states, offline=args.offline, refresh=args.refresh)

    if args.attach_json:
        out_dir = REPO / "output"
        for st in args.states:
            path = out_dir / f"forecast_districts_{st.lower()}.json"
            if path.exists():
                n = attach_to_district_json(path, flags)
                print(f"  patched {path.name}: {n} items flagged")
            prev = REPO / "pages-preview" / "data" / f"forecast_districts_{st.lower()}.json"
            if prev.exists():
                n = attach_to_district_json(prev, flags)
                print(f"  patched preview {prev.name}: {n} items flagged")
        entry = out_dir / "forecast_candidate_entry.json"
        if entry.exists():
            n = attach_to_entry_json(entry, flags)
            print(f"  patched {entry.name}: {n} candidates flagged")
        prev_e = REPO / "pages-preview" / "data" / "forecast_candidate_entry.json"
        if prev_e.exists():
            n = attach_to_entry_json(prev_e, flags)
            print(f"  patched preview entry: {n} candidates flagged")


if __name__ == "__main__":
    main()
