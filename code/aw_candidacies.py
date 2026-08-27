#!/usr/bin/env python3
"""Match 2026 election candidacies from abgeordnetenwatch.de to our rosters.

Currently published: Sachsen-Anhalt Wahl 2026 (parliament_period 168).
Writes data/aw_candidacies_2026.csv and attaches ``aw_url`` onto forecast JSON.

Usage
-----
  python code/aw_candidacies.py                 # fetch + match + write data/
  python code/aw_candidacies.py --offline       # reuse tmp/aw_candidacies cache
  python code/aw_candidacies.py --attach-json   # also patch output/*.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "code"))

from incumbents import (  # noqa: E402
    canon_party,
    load_2026_candidates,
    match_mps_to_candidates,
    person_flags_from_matches,
    write_csv,
)
from listen_candidates import (  # noqa: E402
    clean_person_name,
    first_last_key,
    name_tokens,
    normalize_name,
)

OUT_CSV = REPO / "data" / "aw_candidacies_2026.csv"
TMP = REPO / "tmp" / "aw_candidacies"
AW_CACHE = TMP / "aw_cache"

# Election (type=election) periods on abgeordnetenwatch — not legislatures.
AW_ELECTIONS = {
    "ST": 168,  # Sachsen-Anhalt Wahl 2026
}

FIELDNAMES = [
    "state",
    "party",
    "name",
    "norm_name",
    "match_how",
    "aw_name",
    "aw_party",
    "aw_politician_id",
    "aw_url",
    "aw_wkr",
    "aw_list_pos",
    "source",
]


def _http_get_json(url: str, retries: int = 6) -> dict:
    import urllib.error
    import urllib.request

    for i in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "website-pipeline/aw-candidacies (research; fair-use)"
                },
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 429 and i < retries - 1:
                time.sleep(65)
                continue
            raise
    raise RuntimeError(f"failed GET {url}")


def fetch_aw_candidacies(
    state: str, *, offline: bool = False, refresh: bool = False
) -> list[dict]:
    AW_CACHE.mkdir(parents=True, exist_ok=True)
    pid = AW_ELECTIONS[state]
    cache = AW_CACHE / f"{state.lower()}_candidacies_{pid}.json"
    if cache.exists() and cache.stat().st_size > 500 and not refresh:
        return json.loads(cache.read_text(encoding="utf-8"))["data"]
    if offline:
        raise FileNotFoundError(f"--offline but missing {cache}")

    rows: list[dict] = []
    page = 0
    while True:
        url = (
            "https://www.abgeordnetenwatch.de/api/v2/candidacies-mandates"
            f"?parliament_period={pid}&type=candidacy&page={page}&pager_limit=100"
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


def _wkr_from_constituency(label: str) -> str:
    m = re.match(r"^\s*(\d+)\b", label or "")
    return m.group(1) if m else ""


def parse_candidacies(state: str, raw: list[dict]) -> list[dict]:
    out: list[dict] = []
    for c in raw:
        pol = c.get("politician") or {}
        name = clean_person_name(pol.get("label") or "")
        if not name:
            continue
        ed = c.get("electoral_data") or {}
        const = (ed.get("constituency") or {}).get("label") or ""
        elist = (ed.get("electoral_list") or {}).get("label") or ""
        party = canon_party((c.get("party") or {}).get("label") or "")
        out.append(
            {
                "state": state,
                "name": name,
                "party": party,
                "politician_id": pol.get("id") or "",
                "aw_url": pol.get("abgeordnetenwatch_url") or "",
                "constituency": const,
                "electoral_list": elist,
                "aw_wkr": _wkr_from_constituency(const),
                "aw_list_pos": ed.get("list_position") or "",
                "source": "abgeordnetenwatch",
            }
        )
    return out


def _last_token(name: str) -> str:
    toks = name_tokens(name)
    return toks[-1] if toks else ""


def _match_row(mp: dict, hit: dict, how: str) -> dict:
    return {
        "state": mp["state"],
        "party": hit["party"],
        "name": hit["name"],
        "norm_name": normalize_name(hit["name"]),
        "cand_type": hit["cand_type"],
        "wkr": hit["wkr"],
        "list_pos": hit["list_pos"],
        "person_id": hit.get("person_id") or "",
        "match_how": how,
        "aw_name": mp["name"],
        "aw_party": mp.get("party") or "",
        "aw_politician_id": mp.get("politician_id") or "",
        "aw_url": mp.get("aw_url") or "",
        "mandate_won": "",
        "seat_label": mp.get("constituency") or mp.get("electoral_list") or "",
        "chamber": "",
        "source": "abgeordnetenwatch",
        "aw_wkr": mp.get("aw_wkr") or "",
        "aw_list_pos": mp.get("aw_list_pos") or "",
    }


def match_by_wkr_lastname(
    leftover: list[dict], cands: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Accept remaining AW rows when party + WK + last name uniquely match Direkt."""
    by_pw: dict[tuple[str, str], list[dict]] = {}
    for c in cands:
        if c.get("cand_type") != "direkt" or not c.get("wkr"):
            continue
        by_pw.setdefault((c["party"], str(c["wkr"])), []).append(c)

    extra: list[dict] = []
    still: list[dict] = []
    for mp in leftover:
        party = mp.get("party") or ""
        wkr = str(mp.get("aw_wkr") or "")
        last = _last_token(mp.get("name") or "")
        hits = [
            h
            for h in by_pw.get((party, wkr), [])
            if last and _last_token(h["name"]) == last
        ]
        norms = {normalize_name(h["name"]) for h in hits}
        if not hits or (len(hits) > 1 and len(norms) > 1):
            still.append(mp)
            continue
        fls = {first_last_key(h["name"]) for h in hits}
        more = [
            c
            for c in cands
            if c["party"] == party
            and (
                first_last_key(c["name"]) in fls
                or normalize_name(c["name"]) in norms
            )
        ]
        seen: set[tuple] = set()
        for h in more or hits:
            key = (h["cand_type"], h["party"], h["name"], h["wkr"], h["list_pos"])
            if key in seen:
                continue
            seen.add(key)
            extra.append(_match_row(mp, h, "wkr_lastname"))
    return extra, still


def person_flags(matches: list[dict]) -> dict[tuple[str, str, str], dict]:
    flags = person_flags_from_matches(matches)
    extras: dict[tuple[str, str, str], dict] = {}
    for r in matches:
        key = (r["state"], r["party"], r["norm_name"])
        if key not in extras:
            extras[key] = {
                "aw_wkr": r.get("aw_wkr") or "",
                "aw_list_pos": r.get("aw_list_pos") or "",
            }
    by_key: dict[tuple[str, str, str], dict] = {}
    for key, flag in flags.items():
        by_key[key] = {
            **flag,
            **extras.get(key, {"aw_wkr": "", "aw_list_pos": ""}),
        }
    return by_key


def load_aw_index(
    path: Path = OUT_CSV,
) -> dict[tuple[str, str, str], dict]:
    """(state, party, norm_name) → row with aw_url."""
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
            if key[0] and key[1] and key[2] and r.get("aw_url"):
                out[key] = r
    return out


def lookup_aw(
    index: dict[tuple[str, str, str], dict],
    state: str,
    party: str,
    name: str,
) -> dict | None:
    if not name or not index:
        return None
    st = state.upper()
    p = (party or "").lower()
    key = (st, p, normalize_name(name))
    hit = index.get(key)
    if hit:
        return hit
    fl = first_last_key(name)
    if not fl:
        return None
    cands = [
        v
        for (kst, kp, _), v in index.items()
        if kst == st and kp == p and first_last_key(v.get("name") or "") == fl
    ]
    urls = {v.get("aw_url") for v in cands if v.get("aw_url")}
    if len(urls) == 1:
        return cands[0]
    return None


def attach_aw_fields(entry: dict, flag: dict | None) -> None:
    if not flag:
        return
    url = (flag.get("aw_url") or "").strip()
    if url:
        entry["aw_url"] = url


def attach_to_district_json(path: Path, index: dict[tuple[str, str, str], dict]) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    state = (data.get("metadata") or {}).get("state_code") or ""
    n = 0
    for item in data.get("items") or []:
        item.pop("aw_url", None)
        flag = lookup_aw(index, state, item.get("party") or "", item.get("name") or "")
        if flag:
            attach_aw_fields(item, flag)
            n += 1
    meta = data.setdefault("metadata", {})
    meta["aw_candidacies"] = "abgeordnetenwatch 2026 election profiles matched by name"
    meta["aw_candidacies_file"] = str(OUT_CSV.relative_to(REPO))
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return n


def attach_to_entry_json(path: Path, index: dict[tuple[str, str, str], dict]) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    n = 0
    states = data.get("states") or {}
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
                c.pop("aw_url", None)
                if c.get("is_placeholder"):
                    continue
                flag = lookup_aw(index, state, code, c.get("name") or "")
                if flag:
                    attach_aw_fields(c, flag)
                    n += 1
    meta = data.setdefault("metadata", {})
    meta["aw_candidacies"] = "abgeordnetenwatch 2026 election profiles matched by name"
    meta["aw_candidacies_file"] = str(OUT_CSV.relative_to(REPO))
    path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
    return n


def _enrich_matches(matches: list[dict], aw_rows: list[dict]) -> list[dict]:
    """Copy WK / list_pos from the AW row onto each accepted match."""
    by_id: dict[str, dict] = {}
    by_name: dict[tuple[str, str, str], dict] = {}
    for a in aw_rows:
        pid = str(a.get("politician_id") or "")
        if pid:
            by_id[pid] = a
        by_name[(a["state"], a.get("party") or "", normalize_name(a["name"]))] = a
    out = []
    for m in matches:
        aw = by_id.get(str(m.get("aw_politician_id") or "")) or by_name.get(
            (m["state"], m.get("aw_party") or m["party"], normalize_name(m.get("aw_name") or m["name"]))
        )
        extra = {
            "aw_wkr": (aw or {}).get("aw_wkr") or "",
            "aw_list_pos": (aw or {}).get("aw_list_pos") or "",
        }
        out.append({**m, **extra})
    return out


def build(
    *, states: list[str], offline: bool = False, refresh: bool = False
) -> dict[tuple[str, str, str], dict]:
    TMP.mkdir(parents=True, exist_ok=True)
    all_aw: list[dict] = []
    all_matches: list[dict] = []
    all_unmatched: list[dict] = []
    all_rejected: list[dict] = []

    for state in states:
        if state not in AW_ELECTIONS:
            print(f"=== {state} ===  (no AW election period yet, skip)")
            continue
        print(f"=== {state} ===")
        raw = fetch_aw_candidacies(state, offline=offline, refresh=refresh)
        aw_rows = parse_candidacies(state, raw)
        cands = load_2026_candidates(state)
        matches, unmatched, rejected = match_mps_to_candidates(aw_rows, cands)
        extra, unmatched = match_by_wkr_lastname(unmatched + rejected, cands)
        if extra:
            matches.extend(extra)
            rejected = []
        matches = _enrich_matches(matches, aw_rows)
        print(
            f"  AW candidacies: {len(aw_rows)}  2026 named: {len(cands)}  "
            f"match rows: {len(matches)}  unmatched: {len(unmatched)}  "
            f"rejected: {len(rejected)}"
        )
        print("  match_how:", Counter(m["match_how"] for m in matches))
        all_aw.extend(aw_rows)
        all_matches.extend(matches)
        all_unmatched.extend(unmatched)
        all_rejected.extend(rejected)

    flags = person_flags(all_matches)
    flag_rows = sorted(flags.values(), key=lambda r: (r["state"], r["party"], r["name"]))
    write_csv(OUT_CSV, flag_rows, fieldnames=FIELDNAMES)
    write_csv(TMP / "aw_raw.csv", all_aw)
    write_csv(TMP / "aw_matches.csv", all_matches)
    write_csv(TMP / "aw_unmatched.csv", all_unmatched)
    write_csv(TMP / "aw_rejected.csv", all_rejected)

    print(f"\nWrote {OUT_CSV} ({len(flag_rows)} persons)")
    print(f"  audit under {TMP}/")
    for st in states:
        n = sum(1 for r in flag_rows if r["state"] == st)
        print(f"  {st}: {n}")
    return flags


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--states",
        nargs="+",
        default=list(AW_ELECTIONS),
        choices=["BE", "MV", "ST"],
    )
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
                print(f"  patched {path.name}: {n} items with aw_url")
        entry = out_dir / "forecast_candidate_entry.json"
        if entry.exists():
            n = attach_to_entry_json(entry, flags)
            print(f"  patched {entry.name}: {n} candidates with aw_url")


if __name__ == "__main__":
    main()
