#!/usr/bin/env python3
"""Build multi-election district panels for calibrated Landtag/AGH Erst models.

Sources
-------
MV : LTWMeckPom/ltw11-21_meckpom_abs.csv (2011, 2016, 2021 absolutes)
ST : LTW 2021 absolutes + comparable 2016 Erst/Zweit % from StaLA WK pages
BE : SB_B07-02-03_2023.xlsx sheets 3.1–3.78 (2023 + 2016 Erst/Zweit on 2023 WKs)

Writes
------
data/district_train_panel.csv
  one row per state × election × wkr × party (outcome election)
"""

from __future__ import annotations

import argparse
import csv
import re
import urllib.request
from html import unescape
from pathlib import Path

import openpyxl

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "data" / "district_train_panel.csv"

MAIN_PARTIES = ("spd", "afd", "cdu", "linke", "gruene", "fdp")

ST_PARTY_MAP = {
    "CDU": "cdu",
    "AfD": "afd",
    "DIE LINKE": "linke",
    "SPD": "spd",
    "GRÜNE": "gruene",
    "GRUENE": "gruene",
    "FDP": "fdp",
    "Andere": "others",
}

BE_PARTY_MAP = {
    "SPD": "spd",
    "CDU": "cdu",
    "GRÜNE": "gruene",
    "DIE LINKE": "linke",
    "AfD": "afd",
    "FDP": "fdp",
}


def _f(x) -> float | None:
    if x is None or x == "" or x == "x":
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().replace("\xa0", " ").replace(" ", "").replace(",", ".")
    if s.upper() in {"", "X", ".", "NA", "NAN", "NULL"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _f0(x) -> float:
    v = _f(x)
    return 0.0 if v is None else v


def _share_row(counts: dict[str, float], valid: float) -> dict[str, float]:
    if valid <= 0:
        return {p: 0.0 for p in (*MAIN_PARTIES, "others")}
    out = {p: max(0.0, counts.get(p, 0.0)) / valid for p in MAIN_PARTIES}
    out["others"] = max(0.0, 1.0 - sum(out.values()))
    return out


def _emit(
    rows: list[dict],
    *,
    state: str,
    election: int,
    election_l1: int,
    wkr: int,
    wkr_name: str,
    resp_e: dict[str, float],
    resp_z: dict[str, float],
    l1_e: dict[str, float],
    l1_z: dict[str, float],
    source: str,
) -> None:
    for p in (*MAIN_PARTIES, "others"):
        rows.append(
            {
                "state": state,
                "election": election,
                "election_l1": election_l1,
                "wkr": wkr,
                "wkr_name": wkr_name,
                "party": p,
                "resp_E": round(resp_e.get(p, 0.0), 6),
                "resp_Z": round(resp_z.get(p, 0.0), 6),
                "res_l1_E": round(l1_e.get(p, 0.0), 6),
                "res_l1_Z": round(l1_z.get(p, 0.0), 6),
                "no_cand_l1": int(l1_e.get(p, 0.0) <= 1e-12),
                "source": source,
            }
        )


def build_mv() -> list[dict]:
    path = REPO / "mecklenburg-vorpommern" / "LTWMeckPom" / "ltw11-21_meckpom_abs.csv"
    by_year: dict[int, dict[int, dict]] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            year = int(r["year"])
            wkr = int(r["wahlkreis"])
            ge = _f0(r["gültige_erststimmen"])
            gz = _f0(r["gültige_zweitstimmen"])
            e_counts = {
                "spd": _f0(r["spd_erst"]),
                "cdu": _f0(r["cdu_erst"]),
                "linke": _f0(r["linke_erst"]),
                "gruene": _f0(r["gruene_erst"]),
                "fdp": _f0(r["fdp_erst"]),
                "afd": _f0(r["afd_erst"]),
            }
            z_counts = {
                "spd": _f0(r["spd_zweit"]),
                "cdu": _f0(r["cdu_zweit"]),
                "linke": _f0(r["linke_zweit"]),
                "gruene": _f0(r["gruene_zweit"]),
                "fdp": _f0(r["fdp_zweit"]),
                "afd": _f0(r["afd_zweit"]),
            }
            by_year.setdefault(year, {})[wkr] = {
                "name": r["wahlkreisname"],
                "e": _share_row(e_counts, ge),
                "z": _share_row(z_counts, gz),
            }

    out: list[dict] = []
    for election, lag in ((2016, 2011), (2021, 2016)):
        for wkr, cur in by_year[election].items():
            prev = by_year[lag][wkr]
            _emit(
                out,
                state="MV",
                election=election,
                election_l1=lag,
                wkr=wkr,
                wkr_name=cur["name"],
                resp_e=cur["e"],
                resp_z=cur["z"],
                l1_e=prev["e"],
                l1_z=prev["z"],
                source="ltw11-21_meckpom_abs.csv",
            )
    return out


def _parse_st_wk(html: str) -> tuple[dict[str, float], dict[str, float]]:
    """Return (erst_2016_shares, zweit_2016_shares) for main parties + others."""
    erst: dict[str, float] = {}
    zweit: dict[str, float] = {}
    for label, code in ST_PARTY_MAP.items():
        # two data rows (Erst then Zweit) with trailing 2016 %
        pattern = rf"&nbsp;{re.escape(label)}\s*</td>\s*<td[^>]*>[^<]*</td>\s*<td[^>]*>[^<]*</td>\s*<td[^>]*>[^<]*</td>\s*<td[^>]*>([^<]*)</td>"
        matches = re.findall(pattern, html)
        if len(matches) < 2:
            # Andere / edge labels
            pattern2 = rf">{re.escape(label)}\s*</td>\s*<td[^>]*>[^<]*</td>\s*<td[^>]*>[^<]*</td>\s*<td[^>]*>[^<]*</td>\s*<td[^>]*>([^<]*)</td>"
            matches = re.findall(pattern2, html)
        vals = [_f(m) for m in matches]
        vals = [v / 100.0 for v in vals if v is not None]
        if len(vals) >= 2:
            erst[code] = vals[0]
            zweit[code] = vals[1]
        elif len(vals) == 1:
            # fall back: treat as Zweit-only page style
            zweit[code] = vals[0]
    # normalize residual into others if missing
    for d in (erst, zweit):
        known = sum(d.get(p, 0.0) for p in MAIN_PARTIES)
        d["others"] = max(0.0, 1.0 - known) if "others" not in d else d["others"]
        for p in MAIN_PARTIES:
            d.setdefault(p, 0.0)
    return erst, zweit


def build_st() -> list[dict]:
    panel_2021 = REPO / "sachsen-anhalt" / "ltw21_st_abs.csv"
    names: dict[int, str] = {}
    cur_e: dict[int, dict[str, float]] = {}
    cur_z: dict[int, dict[str, float]] = {}
    with panel_2021.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            wkr = int(r["wahlkreis"])
            names[wkr] = r["wahlkreisname"]
            ge = float(r["gültige_stimmen_erst"])
            gz = float(r["gültige_stimmen_zweit"])
            e_counts = {p: float(r[f"{p}_erst"]) for p in MAIN_PARTIES}
            z_counts = {p: float(r[f"{p}_zweit"]) for p in MAIN_PARTIES}
            cur_e[wkr] = _share_row(e_counts, ge)
            cur_z[wkr] = _share_row(z_counts, gz)

    out: list[dict] = []
    for wkr in sorted(names):
        url = (
            f"https://wahlergebnisse.sachsen-anhalt.de/wahlen/lt21/erg/wkr/"
            f"lt.{wkr:02d}.ergtab.php"
        )
        html = urllib.request.urlopen(url, timeout=60).read().decode("utf-8")
        l1_e, l1_z = _parse_st_wk(html)
        if sum(l1_z.values()) <= 0:
            raise RuntimeError(f"ST WK {wkr}: failed to parse 2016 shares from {url}")
        _emit(
            out,
            state="ST",
            election=2021,
            election_l1=2016,
            wkr=wkr,
            wkr_name=names[wkr],
            resp_e=cur_e[wkr],
            resp_z=cur_z[wkr],
            l1_e=l1_e,
            l1_z=l1_z,
            source="stala lt21 ergtab vergleich 2016 %",
        )
        print(f"  ST WK {wkr:02d} {names[wkr]}: CDU_E16={l1_e['cdu']:.3f} CDU_Z16={l1_z['cdu']:.3f}")
    return out


def build_be() -> list[dict]:
    path = REPO / "berlin" / "raw" / "SB_B07-02-03_2023.xlsx"
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out: list[dict] = []
    for i in range(1, 79):
        ws = wb[f"3.{i}"]
        rows = list(ws.iter_rows(values_only=True))
        title = str(rows[1][0] or "")
        m = re.search(r"Wahlkreis\s+(.+)$", title)
        wkr_name = m.group(1).strip() if m else f"WK {i}"
        # columns: 2023 Erst Anz/%, 2023 Zweit Anz/%, 2016 Erst Anz/%, 2016 Zweit Anz/%
        e23: dict[str, float] = {}
        z23: dict[str, float] = {}
        e16: dict[str, float] = {}
        z16: dict[str, float] = {}
        ge23 = gz23 = ge16 = gz16 = 0.0
        for r in rows:
            label = r[0]
            if label == "Gültige Stimmen":
                ge23 = _f(r[1]) or 0.0
                gz23 = _f(r[3]) or 0.0
                ge16 = _f(r[5]) or 0.0
                gz16 = _f(r[7]) or 0.0
                continue
            if not isinstance(label, str):
                continue
            code = BE_PARTY_MAP.get(label.strip())
            if not code:
                continue
            e23[code] = _f(r[1]) or 0.0
            z23[code] = _f(r[3]) or 0.0
            e16[code] = _f(r[5]) or 0.0
            z16[code] = _f(r[7]) or 0.0
        if ge23 <= 0 or ge16 <= 0:
            raise RuntimeError(f"BE sheet 3.{i}: missing gültige Stimmen")
        _emit(
            out,
            state="BE",
            election=2023,
            election_l1=2016,
            wkr=i,
            wkr_name=wkr_name,
            resp_e=_share_row(e23, ge23),
            resp_z=_share_row(z23, gz23),
            l1_e=_share_row(e16, ge16),
            l1_z=_share_row(z16, gz16),
            source="SB_B07-02-03_2023.xlsx tab 3.*",
        )
    wb.close()
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--states", nargs="+", default=["MV", "ST", "BE"])
    args = ap.parse_args()

    fields = [
        "state",
        "election",
        "election_l1",
        "wkr",
        "wkr_name",
        "party",
        "resp_E",
        "resp_Z",
        "res_l1_E",
        "res_l1_Z",
        "no_cand_l1",
        "source",
    ]
    # Keep other states if rebuilding a subset.
    keep: list[dict] = []
    wanted = {s.upper() for s in args.states}
    if OUT.exists() and wanted != {"MV", "ST", "BE"}:
        with OUT.open(newline="", encoding="utf-8") as f:
            keep = [r for r in csv.DictReader(f) if r["state"] not in wanted]

    rows: list[dict] = list(keep)
    if "MV" in wanted:
        print("Building MV …")
        rows.extend(build_mv())
    if "ST" in wanted:
        print("Building ST (scraping StaLA) …")
        rows.extend(build_st())
    if "BE" in wanted:
        print("Building BE …")
        rows.extend(build_be())

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    n_elec = len({(r["state"], r["election"]) for r in rows})
    print(f"Wrote {OUT} ({len(rows)} party-rows, {n_elec} state-elections)")


if __name__ == "__main__":
    main()
