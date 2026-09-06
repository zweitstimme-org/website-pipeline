#!/usr/bin/env python3
"""Live Sachsen-Anhalt 2026 Wahlabend nowcast from StaLA WKR CSV.

Units are the 41 Wahlkreise (StaLA has not published a WBZ CSV yet).
Prior = district Zweit forecast (fallback: 2021 WKR swung to statewide π₀).
Reported WKs (Ist.Wahlbezirke / votes) are locked; the rest gets shrunk surprise.

Writes output/wahlabend_nowcast_st_live.json (same shape as the replay UI).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "output"

PARTIES = ("cdu", "afd", "spd", "linke", "gruene", "bsw", "fdp", "others")
MAIN = ("cdu", "afd", "spd", "linke", "gruene", "bsw", "fdp")
EPS = 1e-12
HALF_LIFE = 0.05

PARTY_LABELS = {
    "cdu": "CDU",
    "afd": "AfD",
    "spd": "SPD",
    "linke": "Linke",
    "gruene": "GRÜNE",
    "bsw": "BSW",
    "fdp": "FDP",
    "others": "Sonstige",
}

FORECAST_PARTY = {
    "cdu": "cdu",
    "spd": "spd",
    "afd": "afd",
    "fdp": "fdp",
    "bsw": "bsw",
    "gru": "gruene",
    "gruene": "gruene",
    "lin": "linke",
    "linke": "linke",
    "oth": "others",
    "others": "others",
}

DIREKT_PARTY = {
    "cdu": "cdu",
    "afd": "afd",
    "spd": "spd",
    "fdp": "fdp",
    "bsw": "bsw",
    "die linke": "linke",
    "linke": "linke",
    "grüne": "gruene",
    "gruene": "gruene",
    "gru": "gruene",
}

ZWEIT_COL = {
    "cdu": "F01.CDU",
    "afd": "F02.AfD",
    "linke": "F03.Die Linke",
    "spd": "F04.SPD",
    "fdp": "F05.FDP",
    "gruene": "F06.GRÜNE",
    "bsw": "F15.BSW",
}
ERST_COL = {
    "cdu": "D01.CDU",
    "afd": "D02.AfD",
    "linke": "D03.Die Linke",
    "spd": "D04.SPD",
    "fdp": "D05.FDP",
    "gruene": "D06.GRÜNE",
    "bsw": "D15.BSW",
}

STALA_WKR_CSV = (
    "https://wahlergebnisse.sachsen-anhalt.de/wahlen/lt26/downloads/"
    "Ergebnisse_Land_RKR_WKR_LT_2026.csv"
)
FORECAST_STATE_URL = "https://zweitstimme.org/data/forecast_state_st.json"
FORECAST_DISTRICT_URL = "https://zweitstimme.org/data/forecast_districts_st.json"

KIND_LABEL = {
    "L": "Leerdatei (noch keine Auszählung)",
    "Z": "Zwischenergebnis",
    "V": "Vorläufiges Ergebnis",
    "E": "Endgültiges Ergebnis",
}

SCENARIO_CFG = REPO / "data" / "state_forecast_scenarios.json"
_SCENARIO_ALIAS = {
    "gru": "gruene",
    "gruene": "gruene",
    "lin": "linke",
    "linke": "linke",
}


def _scenario_party(p: str) -> str:
    return _SCENARIO_ALIAS.get((p or "").strip().lower(), (p or "").strip().lower())


def _coalition_majority(shares: dict[str, float], parties: list[str], hurdle: float = 0.05) -> bool:
    parl = {p: v for p, v in shares.items() if p != "others"}
    if any(parl.get(p, 0.0) < hurdle for p in parties):
        return False
    above = sum(v for v in parl.values() if v >= hurdle)
    if above <= EPS:
        return False
    return sum(parl.get(p, 0.0) for p in parties) / above > 0.5


def _majority_excluding(shares: dict[str, float], exclude: list[str], hurdle: float = 0.05) -> bool:
    parl = {p: v for p, v in shares.items() if p != "others"}
    above = {p: v for p, v in parl.items() if v >= hurdle}
    if not above:
        return False
    excl = set(exclude)
    bloc = {p: v for p, v in above.items() if p not in excl}
    if not bloc:
        return False
    return sum(bloc.values()) / sum(above.values()) > 0.5


def _eval_scenario(shares: dict[str, float], defn: dict) -> bool:
    cat = defn["category"]
    if cat == "largest_party":
        p = defn["party"]
        parl = {k: v for k, v in shares.items() if k != "others"}
        return p in parl and parl[p] >= max(parl.values()) - EPS
    if cat == "above_hurdle":
        return shares.get(defn["party"], 0.0) >= float(defn.get("hurdle", 0.05))
    if cat == "coalition":
        parties = defn["parties"]
        if not _coalition_majority(shares, parties, float(defn.get("hurdle", 0.05))):
            return False
        lead = defn.get("lead")
        if not lead:
            return True
        return shares.get(lead, 0.0) >= max(shares.get(p, 0.0) for p in parties) - EPS
    if cat == "majority_excluding":
        return _majority_excluding(
            shares, list(defn.get("exclude") or []), float(defn.get("hurdle", 0.05))
        )
    return False


def load_st_scenario_defs(*, hurdle: float = 0.05) -> list[dict]:
    cfg = json.loads(SCENARIO_CFG.read_text(encoding="utf-8")) if SCENARIO_CFG.exists() else {}
    known = set(MAIN)
    defs: list[dict] = []
    for p in MAIN:
        defs.append(
            {
                "id": f"largest_party_{'gru' if p == 'gruene' else ('lin' if p == 'linke' else p)}",
                "category": "largest_party",
                "label_de": f"{PARTY_LABELS[p]} stärkste Kraft",
                "party": p,
                "hurdle": hurdle,
            }
        )
    for raw in cfg.get("above_hurdle_parties_by_state", {}).get("ST", ["fdp", "gru", "spd", "bsw"]):
        p = _scenario_party(raw)
        if p not in known:
            continue
        defs.append(
            {
                "id": f"above_hurdle_{raw}",
                "category": "above_hurdle",
                "label_de": f"{PARTY_LABELS[p]} über 5%-Hürde",
                "party": p,
                "hurdle": hurdle,
            }
        )
    coalitions = list(cfg.get("coalitions") or [])
    coalitions.extend(cfg.get("coalitions_by_state", {}).get("ST") or [])
    excluded = set(cfg.get("exclude_scenario_ids_by_state", {}).get("ST") or [])
    seen: set[str] = set()
    for coal in coalitions:
        cid = coal.get("id") or ""
        if not cid or cid in excluded or cid in seen:
            continue
        parties = [_scenario_party(x) for x in (coal.get("parties") or [])]
        if any(p not in known for p in parties):
            continue
        seen.add(cid)
        lead_raw = coal.get("lead")
        lead = _scenario_party(lead_raw) if lead_raw else None
        label = (coal.get("label_de") or cid).replace("CDU/CSU", "CDU")
        defs.append(
            {
                "id": cid,
                "category": "coalition",
                "label_de": label,
                "parties": parties,
                "lead": lead,
                "hurdle": hurdle,
            }
        )
    for row in cfg.get("majority_excluding_by_state", {}).get("ST") or []:
        excl = [_scenario_party(x) for x in (row.get("exclude") or [])]
        defs.append(
            {
                "id": row.get("id") or "maj_ohne",
                "category": "majority_excluding",
                "label_de": row.get("label_de") or "Parlamentsmehrheit ohne …",
                "exclude": excl,
                "hurdle": hurdle,
            }
        )
    return defs


def night_scenario_probs(
    nc_land_pct: dict[str, float],
    unc_pp: dict[str, float],
    rng: np.random.Generator,
    *,
    n_draws: int = 64,
    p_start_by_id: dict[str, float] | None = None,
) -> dict:
    defs = load_st_scenario_defs()
    hits = {d["id"]: 0 for d in defs}
    for _ in range(n_draws):
        draw = {
            p: max(
                0.0,
                float(nc_land_pct.get(p, 0.0))
                + rng.normal(0.0, float(unc_pp.get(p, 0.0)) / 1.28),
            )
            for p in PARTIES
        }
        tot = sum(draw.values()) or 1.0
        frac = {p: draw[p] / tot for p in PARTIES}
        for d in defs:
            if _eval_scenario(frac, d):
                hits[d["id"]] += 1
    items = []
    for d in defs:
        p_hat = hits[d["id"]] / float(n_draws)
        call = p_hat >= 0.5
        p_now = round(p_hat * 100.0, 1)
        p_start = (
            round(float(p_start_by_id[d["id"]]), 1)
            if p_start_by_id and d["id"] in p_start_by_id
            else p_now
        )
        items.append(
            {
                "id": d["id"],
                "category": d["category"],
                "label_de": d["label_de"],
                "p": p_now,
                "p_start": p_start,
                "truth": None,
                "call": call,
                "correct": None,
            }
        )
    items.sort(key=lambda x: (-x["p"], x["label_de"]))
    return {
        "n_draws": n_draws,
        "call_threshold": 0.5,
        "items": items,
        "n_ok": None,
        "n_total": len(items),
    }


def _num(x) -> float:
    if x is None or x == "" or x in ("-", "x", "X", "."):
        return 0.0
    if isinstance(x, (int, float)):
        return float(x) if math.isfinite(float(x)) else 0.0
    s = str(x).strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _shares(counts: dict[str, float]) -> dict[str, float]:
    tot = sum(counts.values()) + EPS
    return {p: counts[p] / tot for p in PARTIES}


def _pct(sh: dict[str, float]) -> dict[str, float]:
    return {p: round(sh[p] * 100.0, 2) for p in PARTIES}


def _wkr_id(raw) -> str:
    s = str(raw or "").strip()
    try:
        return str(int(float(s)))
    except ValueError:
        return s.lstrip("0") or "0"


def _load_json(path: Path | None, url: str) -> dict:
    if path and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def statewide_prior(forecast: dict) -> dict[str, float]:
    raw = {p: 0.0 for p in PARTIES}
    for row in forecast.get("parties") or []:
        code = FORECAST_PARTY.get(str(row.get("party_code") or "").lower())
        if not code:
            continue
        raw[code] += float(row.get("fit") or 0.0)
    return _shares(raw)


def prior_uncertainty_pp(forecast: dict) -> dict[str, float]:
    """Half-width in pp from statewide forecast_state low/high (≈83 % interval)."""
    fallback = 2.3
    from_fcst: dict[str, float] = {}
    for row in forecast.get("parties") or []:
        code = FORECAST_PARTY.get(str(row.get("party_code") or "").lower())
        if not code:
            continue
        try:
            lo = float(row["low"])
            hi = float(row["high"])
        except (KeyError, TypeError, ValueError):
            continue
        from_fcst[code] = max(from_fcst.get(code, 0.0), abs(hi - lo) / 2.0)
    return {p: round(max(0.4, float(from_fcst.get(p, fallback))), 2) for p in PARTIES}


def district_wk_unc_pp(districts: dict) -> dict[str, dict[str, float]]:
    """Per-WK Erst half-width from the Wahlkreis regression (low/high, z=1.96).

    These are not the statewide forecast bands. Missing party → omitted.
    """
    out: dict[str, dict[str, float]] = {}
    for item in districts.get("items") or []:
        wid = _wkr_id(item.get("wkr"))
        p = str(item.get("party") or "").lower()
        if p not in PARTIES:
            continue
        try:
            lo = float(item["low"])
            hi = float(item["high"])
        except (KeyError, TypeError, ValueError):
            continue
        half = abs(hi - lo) / 2.0
        out.setdefault(wid, {})[p] = round(max(0.0, half), 2)
    return out


def unc_phase(frac: float) -> str:
    if frac <= 1e-6:
        return "forecast"
    if frac >= 0.999:
        return "counted"
    return "mixed"


def load_wkr_panel() -> dict[str, dict]:
    path = REPO / "sachsen-anhalt" / "ltw21_st_abs.csv"
    out: dict[str, dict] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            wid = _wkr_id(row.get("wahlkreis"))
            g = _num(row.get("gültige_stimmen_zweit"))
            counts = {
                "cdu": _num(row.get("cdu_zweit")),
                "afd": _num(row.get("afd_zweit")),
                "spd": _num(row.get("spd_zweit")),
                "linke": _num(row.get("linke_zweit")),
                "gruene": _num(row.get("gruene_zweit")),
                "bsw": _num(row.get("bsw_zweit")),
                "fdp": _num(row.get("fdp_zweit")),
                "others": _num(row.get("others_zweit")),
            }
            if g <= 0:
                g = sum(counts.values())
            out[wid] = {
                "id": wid,
                "name": str(row.get("wahlkreisname") or f"WK {wid}").strip(),
                "gueltig_l1": g,
                "shares_l1": _shares(counts),
                "erst_l1": {
                    "cdu": _num(row.get("cdu_erst")),
                    "afd": _num(row.get("afd_erst")),
                    "spd": _num(row.get("spd_erst")),
                    "linke": _num(row.get("linke_erst")),
                    "gruene": _num(row.get("gruene_erst")),
                    "bsw": _num(row.get("bsw_erst")),
                    "fdp": _num(row.get("fdp_erst")),
                    "others": _num(row.get("others_erst")),
                },
                "gueltig_erst_l1": _num(row.get("gültige_stimmen_erst")),
            }
    wber_path = REPO / "sachsen-anhalt" / "raw" / "lt21dat1.csv"
    if wber_path.exists():
        raw = wber_path.read_bytes()
        text = raw.decode("utf-8-sig") if raw[:3] == b"\xef\xbb\xbf" else None
        if text is None:
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("latin-1")
        for row in csv.DictReader(io.StringIO(text), delimiter=";"):
            if (row.get("Satzart") or "").strip() != "WKR":
                continue
            wid = _wkr_id(row.get("Schlüsselnummer"))
            if wid in out:
                out[wid]["wber_l1"] = _num(row.get("A - Wahlberechtigte"))
                out[wid]["waehler_l1"] = _num(row.get("B - Wähler"))
    return out


def squeeze_in(shares: dict[str, float], party: str, target: float) -> dict[str, float]:
    """Give a new party `target` by scaling everyone else. Stays on the simplex.

    BSW has no 2016/2021 geography. Dummy = land π₀, taken proportionally from
    all other parties (not a correlation with Linke/AfD/etc.).
    """
    target = float(max(0.0, min(1.0, target)))
    rest = {p: float(v) for p, v in shares.items() if p != party}
    pool = sum(rest.values())
    out = {p: float(v) for p, v in shares.items()}
    out[party] = target
    if pool <= EPS:
        return _shares(out)
    scale = (1.0 - target) / pool
    for p in rest:
        out[p] = rest[p] * scale
    return _shares(out)


def district_priors(
    districts: dict, panel: dict[str, dict], land: dict[str, float]
) -> tuple[dict[str, dict], dict[str, dict], set[str]]:
    by_z: dict[str, dict[str, float]] = {}
    by_e: dict[str, dict[str, float]] = {}
    bsw_direkt: set[str] = set()
    for item in districts.get("items") or []:
        wid = _wkr_id(item.get("wkr"))
        p = str(item.get("party") or "").lower()
        if p not in PARTIES:
            continue
        zs = item.get("zs_value")
        es = item.get("value")
        by_z.setdefault(wid, {q: 0.0 for q in PARTIES})
        by_e.setdefault(wid, {q: 0.0 for q in PARTIES})
        if zs is not None:
            by_z[wid][p] += float(zs or 0.0)
        if es is not None:
            by_e[wid][p] += float(es or 0.0)
        if p == "bsw" and str(item.get("name") or "").strip():
            bsw_direkt.add(wid)
    l1_land = _shares(
        {p: sum(panel[w]["gueltig_l1"] * panel[w]["shares_l1"][p] for w in panel) for p in PARTIES}
    )
    bsw_land = float(land.get("bsw") or 0.0)
    priors: dict[str, dict] = {}
    for wid, row in panel.items():
        if wid in by_z and sum(by_z[wid].values()) > 0:
            sh = _shares(by_z[wid])
        else:
            base = row["shares_l1"]
            swung = {}
            for p in PARTIES:
                if l1_land[p] > EPS:
                    swung[p] = base[p] * (land[p] / l1_land[p])
                else:
                    swung[p] = 0.0
            sh = _shares(swung)
        if sh.get("bsw", 0.0) <= EPS and bsw_land > EPS:
            sh = squeeze_in(sh, "bsw", bsw_land)
        priors[wid] = sh
    total_g = sum(panel[w]["gueltig_l1"] for w in panel) + EPS
    agg = {p: sum(panel[w]["gueltig_l1"] * priors[w][p] for w in panel) / total_g for p in PARTIES}
    out: dict[str, dict] = {}
    for wid, sh in priors.items():
        swung = {}
        for p in PARTIES:
            if agg[p] > EPS:
                swung[p] = sh[p] * (land[p] / agg[p])
            else:
                swung[p] = land[p]
        out[wid] = _shares(swung)

    erst: dict[str, dict] = {}
    for wid, row in panel.items():
        if wid in by_e and sum(by_e[wid].values()) > 0:
            sh_e = _shares(by_e[wid])
        else:
            # 2021 Erst−Zweit gap on top of the Zweit prior
            l1e = row["erst_l1"]
            e_tot = sum(l1e.values()) + EPS
            e_sh = {p: l1e[p] / e_tot for p in PARTIES}
            raw_e = {p: max(0.0, out[wid][p] + (e_sh[p] - row["shares_l1"][p])) for p in PARTIES}
            sh_e = _shares(raw_e)
        if bsw_land > EPS and wid not in bsw_direkt:
            sh_e["bsw"] = 0.0
            sh_e = _shares(sh_e)
        erst[wid] = sh_e
    return out, erst, bsw_direkt


def parse_stala_csv(path: Path) -> dict:
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    land = None
    wkrs: dict[str, dict] = {}
    for row in rows:
        satz = (row.get("Satzart") or "").strip()
        art = (row.get("Wahllokal") or "").strip()
        if art not in ("",):
            continue
        if satz == "LAN":
            land = row
        elif satz == "WKR":
            wkrs[_wkr_id(row.get("Schlüsselnummer"))] = row
    return {"land": land or {}, "wkr": wkrs, "n_rows": len(rows)}


def row_counts(row: dict, cols: dict[str, str]) -> tuple[dict[str, float], float]:
    named = {p: _num(row.get(col)) for p, col in cols.items()}
    if cols is ZWEIT_COL:
        gueltig = _num(row.get("F.Gültige.Zweitstimmen"))
    else:
        gueltig = _num(row.get("D.Gültige.Erststimmen"))
    named_sum = sum(named.values())
    if gueltig <= 0 and named_sum > 0:
        gueltig = named_sum
    counts = {p: named.get(p, 0.0) for p in PARTIES}
    counts["others"] = max(0.0, gueltig - named_sum)
    return counts, gueltig


def hare_niemeyer(votes: dict[str, float], seats: int) -> dict[str, int]:
    parties = list(votes.keys())
    v = np.array([votes[p] for p in parties], dtype=float)
    total = float(v.sum())
    if total <= 0 or seats <= 0:
        return {p: 0 for p in parties}
    quotas = v * seats / total
    base = np.floor(quotas).astype(int)
    rem = seats - int(base.sum())
    order = np.argsort(-(quotas - base))
    for i in range(rem):
        base[order[i % len(order)]] += 1
    return {p: int(base[i]) for i, p in enumerate(parties)}


def allocate_st(votes: dict[str, float], directs: dict[str, int], base: int = 83) -> dict:
    above = {
        p: s
        for p, s in votes.items()
        if p not in ("others", "Sonstige") and s >= 0.05
    }
    if not above:
        return {"size": base, "seats": {}, "total_oh": 0}
    below_d = sum(d for p, d in directs.items() if p not in above)
    dir_a = {p: int(directs.get(p, 0)) for p in above}
    s = base - below_d
    prop0 = hare_niemeyer(above, s)
    oh0 = sum(max(0, dir_a[p] - prop0[p]) for p in above)
    if oh0 == 0:
        seats = {p: max(prop0[p], dir_a[p]) for p in above}
        return {"size": sum(seats.values()) + below_d, "seats": seats, "total_oh": 0}
    round_i = 0
    while True:
        alloc = hare_niemeyer(above, s)
        rem_oh = {p: max(0, dir_a[p] - alloc[p]) for p in above}
        rem = sum(rem_oh.values())
        if rem == 0:
            seats = alloc
            break
        round_i += 1
        if round_i >= 3 and rem <= 2:
            seats = {p: max(alloc[p], dir_a[p]) for p in above}
            return {
                "size": sum(seats.values()) + below_d,
                "seats": seats,
                "total_oh": oh0,
            }
        s = s + 2 * rem
        if s > 400:
            seats = {p: max(alloc[p], dir_a[p]) for p in above}
            return {
                "size": sum(seats.values()) + below_d,
                "seats": seats,
                "total_oh": oh0,
            }
    return {"size": sum(seats.values()) + below_d, "seats": seats, "total_oh": oh0}


def night_entry_mc(
    nc_land_pct: dict[str, float],
    unc_pp: dict[str, float],
    wkr_leaders: dict[str, str],
    rng: np.random.Generator,
    n_draws: int = 64,
) -> dict:
    directs = {p: 0 for p in MAIN}
    for lead in wkr_leaders.values():
        if lead in directs:
            directs[lead] += 1
    sizes: list[int] = []
    seats_acc: dict[str, list[int]] = {p: [] for p in MAIN}
    list_acc: dict[str, list[int]] = {p: [] for p in MAIN}
    for _ in range(n_draws):
        draw = {p: 0.0 for p in PARTIES}
        for p in PARTIES:
            sd = float(unc_pp.get(p, 0.0)) / 1.28
            draw[p] = max(0.0, float(nc_land_pct.get(p, 0.0)) + rng.normal(0.0, sd))
        tot = sum(draw.values()) or 1.0
        frac = {p: draw[p] / tot for p in PARTIES}
        alloc = allocate_st(frac, directs)
        sizes.append(int(alloc["size"]))
        for p in MAIN:
            s_p = int(alloc["seats"].get(p, 0))
            seats_acc[p].append(s_p)
            list_acc[p].append(max(0, s_p - directs.get(p, 0)))

    def q(vals: list[int]) -> list[int]:
        arr = np.asarray(vals)
        return [int(np.percentile(arr, 10)), int(np.percentile(arr, 50)), int(np.percentile(arr, 90))]

    return {
        "n_draws": n_draws,
        "size": q(sizes),
        "seats": {p: q(seats_acc[p]) for p in MAIN},
        "directs": directs,
        "list_seats": {p: q(list_acc[p]) for p in MAIN},
    }


def load_listen_roster() -> dict[str, dict]:
    path = REPO / "sachsen-anhalt" / "candidates" / "listenkandidaten_2026.csv"
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            party = (r.get("party") or "").strip().lower()
            if party not in MAIN:
                continue
            try:
                pos = int(r.get("list_pos") or 0)
            except (TypeError, ValueError):
                continue
            if pos <= 0:
                continue
            ph = str(r.get("is_placeholder") or "").strip() in ("1", "true", "True")
            entry: dict = {
                "pos": pos,
                "name": (r.get("name") or f"{PARTY_LABELS[party]} · Listenplatz {pos}").strip(),
                "ph": ph,
            }
            wkd = (r.get("wkr_direct") or "").strip()
            if wkd:
                try:
                    entry["wkr"] = int(float(wkd))
                except ValueError:
                    pass
            slot = out.setdefault(party, {"list_type": "landes", "landes": [], "bezirk": {}})
            slot["landes"].append(entry)
    for slot in out.values():
        slot["landes"].sort(key=lambda e: e["pos"])
    return out


def _direkt_party_code(raw: str) -> str | None:
    s = (raw or "").strip().lower()
    if s in DIREKT_PARTY:
        return DIREKT_PARTY[s]
    if "linke" in s:
        return "linke"
    if "grün" in s or "gruene" in s:
        return "gruene"
    return None


def load_direkt_roster() -> dict[str, dict]:
    """Official 2026 Direktkandidaten, keyed by WK then party.

    Smaller parties / Einzelbewerber live under `_extra`.
    """
    path = REPO / "sachsen-anhalt" / "candidates" / "direktkandidaten_2026_official.csv"
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            wid = _wkr_id(r.get("wkr"))
            name = (r.get("name") or "").strip()
            if not wid or not name:
                continue
            cell = {
                "name": name,
                "is_placeholder": False,
                "source": (r.get("source") or "").strip(),
                "party_raw": (r.get("party_raw") or "").strip(),
            }
            slot = out.setdefault(wid, {})
            code = _direkt_party_code(r.get("party_raw") or "")
            if code:
                slot[code] = cell
            else:
                extra = slot.setdefault("_extra", [])
                extra.append(cell)
    return out


def nowcast_wkrs(
    panel: dict[str, dict],
    prior: dict[str, dict],
    live_wkr: dict[str, dict],
    bsw_direkt: set[str] | None = None,
    erst_prior: dict[str, dict] | None = None,
    prior_unc_pp: dict[str, float] | None = None,
) -> tuple[dict[str, dict], dict]:
    reported: dict[str, dict] = {}
    for wid, row in live_wkr.items():
        soll = _num(row.get("Soll.Wahlbezirke"))
        ist = _num(row.get("Ist.Wahlbezirke"))
        counts, gueltig = row_counts(row, ZWEIT_COL)
        erst_c, erst_g = row_counts(row, ERST_COL)
        frac = (ist / soll) if soll > 0 else (1.0 if gueltig > 0 else 0.0)
        if frac <= 0 and gueltig <= 0:
            continue
        reported[wid] = {
            "frac": min(1.0, frac if frac > 0 else 1.0),
            "ist": ist,
            "soll": soll,
            "counts": counts,
            "gueltig": gueltig,
            "shares": _shares(counts) if gueltig > 0 else dict(prior[wid]),
            "erst_counts": erst_c,
            "erst_gueltig": erst_g,
            "erst_shares": _shares(erst_c) if erst_g > 0 else None,
            "wber": _num(row.get("A.Wahlberechtigte")),
            "waehler": _num(row.get("B.Wähler")),
            "winner": (row.get("Gewählt im Wahlkreis") or "").strip(),
        }

    rep_ids = [w for w in reported if reported[w]["gueltig"] > 0]
    if not rep_ids:
        surprise = {p: 0.0 for p in PARTIES}
        w = 0.0
        frac_votes = 0.0
        obs = {p: 0.0 for p in PARTIES}
        pri_r = dict(list(prior.values())[0]) if prior else {p: 0.0 for p in PARTIES}
    else:
        tw = sum(reported[w]["gueltig"] for w in rep_ids) + EPS
        obs = {p: sum(reported[w]["gueltig"] * reported[w]["shares"][p] for w in rep_ids) / tw for p in PARTIES}
        pri_r = {p: sum(reported[w]["gueltig"] * prior[w][p] for w in rep_ids) / tw for p in PARTIES}
        surprise = {p: obs[p] - pri_r[p] for p in PARTIES}
        total_g = sum(panel[w]["gueltig_l1"] for w in panel) + EPS
        frac_votes = sum(panel[w]["gueltig_l1"] * reported.get(w, {}).get("frac", 0.0) for w in panel) / total_g
        w = frac_votes / (frac_votes + HALF_LIFE)

    nc: dict[str, dict] = {}
    for wid, row in panel.items():
        pri = prior[wid]
        if wid in reported and reported[wid]["frac"] >= 0.999 and reported[wid]["gueltig"] > 0:
            sh = dict(reported[wid]["shares"])
            mix = 1.0
        elif wid in reported and reported[wid]["gueltig"] > 0:
            mix = reported[wid]["frac"]
            raw_open = {p: max(0.0, pri[p] + w * surprise[p]) for p in PARTIES}
            open_sh = _shares(raw_open)
            sh = {p: mix * reported[wid]["shares"][p] + (1.0 - mix) * open_sh[p] for p in PARTIES}
            sh = _shares(sh)
        else:
            mix = 0.0
            raw = {p: max(0.0, pri[p] + w * surprise[p]) for p in PARTIES}
            sh = _shares(raw)
        erst_sh = None
        if wid in reported and reported[wid]["erst_shares"] and reported[wid]["frac"] >= 0.5:
            erst_sh = reported[wid]["erst_shares"]
        elif erst_prior and wid in erst_prior:
            raw_e = {p: max(0.0, erst_prior[wid][p] + w * surprise[p]) for p in PARTIES}
            erst_sh = _shares(raw_e)
            if bsw_direkt is not None and wid not in bsw_direkt:
                erst_sh["bsw"] = 0.0
                erst_sh = _shares(erst_sh)
        else:
            # Erst ≈ Zweit nowcast + 2021 Erst−Zweit gap
            gap = {}
            l1e = row["erst_l1"]
            l1z = row["shares_l1"]
            e_tot = sum(l1e.values()) + EPS
            e_sh = {p: l1e[p] / e_tot for p in PARTIES}
            for p in PARTIES:
                gap[p] = e_sh[p] - l1z[p]
            raw_e = {p: max(0.0, sh[p] + gap[p]) for p in PARTIES}
            erst_sh = _shares(raw_e)
            if bsw_direkt is not None and wid not in bsw_direkt:
                erst_sh["bsw"] = 0.0
                erst_sh = _shares(erst_sh)
        nc[wid] = {
            "nowcast": sh,
            "erst": erst_sh,
            "frac": reported.get(wid, {}).get("frac", 0.0),
            "n_reported": int(reported.get(wid, {}).get("ist", 0)),
            "n_total": int(reported.get(wid, {}).get("soll", 0)),
            "reported": wid in reported,
            "winner": reported.get(wid, {}).get("winner", ""),
        }

    open_frac = 1.0 - frac_votes
    base_unc = prior_unc_pp or {p: 4.0 for p in PARTIES}
    unc = {p: round(max(0.0, float(base_unc.get(p, 2.3)) * open_frac), 2) for p in PARTIES}
    if open_frac <= 1e-9:
        unc = {p: 0.0 for p in PARTIES}
    live_mix = frac_votes + (1.0 - frac_votes) * w
    diag = {
        "learn_weight": round(w, 4),
        "frac_votes": round(frac_votes, 4),
        "mix_live": round(live_mix, 4),
        "mix_prior": round(1.0 - live_mix, 4),
        "surprise": {p: round(surprise[p] * 100, 3) for p in PARTIES},
        "uncertainty": unc,
        "naive": _pct(obs) if rep_ids else _pct(pri_r),
        "n_wkr_touch": len(reported),
    }
    return nc, diag


def turnout_nowcast(panel, live_land, live_wkr, reported_frac: float) -> dict:
    prior = 60.3
    wber = _num(live_land.get("A.Wahlberechtigte"))
    waehler = _num(live_land.get("B.Wähler"))
    if wber > 0 and waehler > 0:
        naive = 100.0 * waehler / wber
        w = reported_frac / (reported_frac + 0.08) if reported_frac > 0 else 0.0
        nc = prior + (naive - prior) * w
        unc = 0.0 if reported_frac >= 0.999 else round(5.0 * (1.0 - reported_frac), 2)
        return {
            "nowcast": round(float(np.clip(nc, 0, 100)), 2),
            "naive": round(naive, 2),
            "prior": prior,
            "truth": None,
            "uncertainty": unc,
            "frac_wber_reported": round(reported_frac, 4),
            "abs_err": None,
        }
    return {
        "nowcast": prior,
        "naive": prior,
        "prior": prior,
        "truth": None,
        "uncertainty": 5.0,
        "frac_wber_reported": round(reported_frac, 4),
        "abs_err": None,
    }


def _leader(sh: dict[str, float]) -> str:
    return max(MAIN, key=lambda p: sh.get(p, 0.0))


def clock_from_row(row: dict) -> str | None:
    d = (row.get("Datum") or "").strip()
    t = (row.get("Uhrzeit") or "").strip()
    if not d and not t:
        return None
    if d and t:
        # StaLA: dd.mm.yyyy + hh:mm:ss or hh:mm
        parts = d.replace("/", ".")
        try:
            if len(t) == 5:
                t = t + ":00"
            dt = datetime.strptime(f"{parts} {t}", "%d.%m.%Y %H:%M:%S")
            return dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return f"{d} {t}".strip()
    return d or t


def build_step(
    panel,
    prior,
    live,
    land_prior,
    rng,
    bsw_direkt: set[str] | None = None,
    erst_prior: dict[str, dict] | None = None,
    prior_unc_pp: dict[str, float] | None = None,
    wk_unc_pp: dict[str, dict[str, float]] | None = None,
) -> dict:
    land_row = live["land"]
    nc, diag = nowcast_wkrs(
        panel,
        prior,
        live["wkr"],
        bsw_direkt=bsw_direkt,
        erst_prior=erst_prior,
        prior_unc_pp=prior_unc_pp,
    )
    total_g = sum(panel[w]["gueltig_l1"] for w in panel) + EPS
    nc_land = {
        p: sum(panel[w]["gueltig_l1"] * nc[w]["nowcast"][p] for w in panel) / total_g
        for p in PARTIES
    }
    unc = diag["uncertainty"]
    wkr_out = {}
    for wid in sorted(panel, key=lambda x: int(x) if x.isdigit() else 99):
        now = nc[wid]["nowcast"]
        erst = nc[wid]["erst"]
        frac_w = nc[wid]["frac"]
        complete = frac_w >= 0.999
        open_w = max(0.0, 1.0 - frac_w)
        wk_base = (wk_unc_pp or {}).get(wid) or {}
        u_w = {}
        for p in PARTIES:
            if p in wk_base:
                u_w[p] = round(float(wk_base[p]) * open_w, 2)
        top2 = sorted(MAIN, key=lambda p: (erst or now)[p], reverse=True)[:2]
        margin = ((erst or now)[top2[0]] - (erst or now)[top2[1]]) * 100
        u0 = u_w.get(top2[0])
        u1 = u_w.get(top2[1])
        if u0 is None:
            u0 = float(unc.get(top2[0], 1))
        if u1 is None:
            u1 = float(unc.get(top2[1], 1))
        m_u = math.sqrt(float(u0) ** 2 + float(u1) ** 2)
        z = margin / (m_u + 0.5)
        p_lead = float(0.5 * (1 + math.erf(z / math.sqrt(2))))
        likely = p_lead >= 0.90
        called = p_lead >= 0.999 and frac_w > 0 and (complete or margin >= (1 - frac_w) * 40)
        lp = _leader(erst if erst else now)
        wkr_out[wid] = {
            "frac_reported": round(frac_w, 4),
            "n_reported": nc[wid]["n_reported"],
            "n_total": nc[wid]["n_total"] or None,
            "nowcast": _pct(now),
            "erst": _pct(erst) if erst else _pct(now),
            "truth": None,
            "leader_pred": lp,
            "leader_truth": None,
            "leader_ok": None,
            "direct_pred": lp,
            "runner_up": top2[1] if len(top2) > 1 else None,
            "margin": round(margin, 2),
            "p_lead": round(p_lead, 4),
            "likely": likely,
            "called": called,
            "complete": complete,
            "uncertainty": u_w,
            "ballot": "erst" if nc[wid]["reported"] and live["wkr"].get(wid) and _num(live["wkr"][wid].get("D.Gültige.Erststimmen")) > 0 else "erst_proxy",
            "official_winner": nc[wid]["winner"] or None,
        }

    soll = _num(land_row.get("Soll.Wahlbezirke"))
    ist = _num(land_row.get("Ist.Wahlbezirke"))
    frac_wb = (ist / soll) if soll > 0 else diag["frac_votes"]
    turnout = turnout_nowcast(panel, land_row, live["wkr"], frac_wb)
    entry_mc = night_entry_mc(
        _pct(nc_land),
        unc,
        {wid: r["direct_pred"] for wid, r in wkr_out.items()},
        rng,
    )
    kind = (land_row.get("Ergebnisart") or "L").strip() or "L"
    clock = clock_from_row(land_row)
    scen = night_scenario_probs(_pct(nc_land), unc, rng)
    return {
        "frac_reported": round(frac_wb if soll > 0 else diag["frac_votes"], 4),
        "n_reported": int(ist),
        "n_total": int(soll) if soll > 0 else 0,
        "clock": clock,
        "clock_source": "stala",
        "nowcast": _pct(nc_land),
        "naive": diag["naive"],
        "prior": _pct(land_prior),
        "truth": None,
        "mae_nowcast": None,
        "mae_naive": None,
        "learn_weight": diag["learn_weight"],
        "mix_live": diag.get("mix_live"),
        "mix_prior": diag.get("mix_prior"),
        "representativeness": None,
        "surprise": diag["surprise"],
        "uncertainty": unc,
        "turnout": turnout,
        "by_wkr": wkr_out,
        "by_bezirk": {},
        "entry_mc": entry_mc,
        "scenario_probs": scen,
        "eval": None,
        "result_kind": kind,
        "n_wkr_touch": diag["n_wkr_touch"],
        "uncertainty_note": {
            "phase": unc_phase(frac_wb if soll > 0 else diag["frac_votes"]),
            "land": (
                "Landes-± = Band der zweitstimme.org-Landesprognose (ca. 83 %). "
                "Vor der Auszählung die volle Prognose; danach offener Stimmenanteil × dieses Band. "
                "Ausgezählte Wahlbezirke ohne Fehler."
            ),
            "wkr": (
                "Wahlkreis-± = Band der Wahlkreis-Regression (zweitstimme.org, ca. 95 %), "
                "nicht das Landesband. Schrumpft mit dem offenen Anteil in diesem Kreis."
            ),
        },
    }


def _stamp_p_start(steps: list[dict]) -> list[dict]:
    if not steps:
        return steps
    start_items = (steps[0].get("scenario_probs") or {}).get("items") or []
    start_p = {it["id"]: it["p"] for it in start_items if "id" in it and "p" in it}
    for s in steps:
        sp = s.get("scenario_probs") or {}
        for it in sp.get("items") or []:
            sid = it.get("id")
            if sid in start_p:
                it["p_start"] = start_p[sid]
    return steps[-60:]


def merge_history(prev: dict | None, step: dict) -> list[dict]:
    steps = []
    if prev:
        sc = (prev.get("scenarios") or {}).get("live") or (prev.get("scenarios") or {}).get("random")
        if sc:
            steps = list(sc.get("steps") or [])
    key = (step.get("clock"), step.get("frac_reported"), step.get("n_reported"), json.dumps(step.get("nowcast"), sort_keys=True))
    if steps:
        last = steps[-1]
        last_key = (
            last.get("clock"),
            last.get("frac_reported"),
            last.get("n_reported"),
            json.dumps(last.get("nowcast"), sort_keys=True),
        )
        if last_key == key:
            steps[-1] = step
            return _stamp_p_start(steps)
    steps.append(step)
    return _stamp_p_start(steps)


def run(csv_path: Path, prev_path: Path | None) -> dict:
    panel = load_wkr_panel()
    state_fc = _load_json(REPO / "output" / "forecast_state_st.json", FORECAST_STATE_URL)
    dist_fc = _load_json(REPO / "output" / "forecast_districts_st.json", FORECAST_DISTRICT_URL)
    land_prior = statewide_prior(state_fc)
    prior_unc = prior_uncertainty_pp(state_fc)
    prior, erst_prior, bsw_direkt = district_priors(dist_fc, panel, land_prior)
    wk_unc = district_wk_unc_pp(dist_fc)
    live = parse_stala_csv(csv_path)
    rng = np.random.default_rng(20260906)
    step = build_step(
        panel,
        prior,
        live,
        land_prior,
        rng,
        bsw_direkt=bsw_direkt,
        erst_prior=erst_prior,
        prior_unc_pp=prior_unc,
        wk_unc_pp=wk_unc,
    )
    prev = None
    if prev_path and prev_path.exists():
        try:
            prev = json.loads(prev_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prev = None
    steps = merge_history(prev, step)
    kind = step.get("result_kind") or "L"
    land_row = live["land"]
    payload = {
        "election": "LTW2026",
        "state": "st",
        "state_label": "Sachsen-Anhalt",
        "last_election": {
            "year": 2021,
            "label": "LTW 2021",
            "turnout": 60.3,
            "parliament_size": 97,
        },
        "baseline": "π₀ = Landesprognose + WK-Zweit; Live = StaLA WKR-CSV",
        "parties": list(PARTIES),
        "party_labels": PARTY_LABELS,
        "n_precincts": int(step["n_total"] or len(panel)),
        "n_wkr": len(panel),
        "match": {"n_truth": len(panel), "n_l1": len(panel), "n_matched": len(panel), "match_rate": 1.0},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "prior_uncertainty_pp": prior_unc,
        "model": {
            "description": (
                "Sachsen-Anhalt 2026 Live-Nowcast: StaLA Wahlkreis-CSV "
                "(Zwischenergebnisse nach 18 Uhr) + Vorwahl-Prognose. "
                "Zweit = WK-Prognose; Erst = dieselbe WK-Regression "
                "(Zweit + LTW 2021, ohne Kandidateneffekte; 0 ohne Direktkandidat). "
                "BSW ohne Historie: Landesanteil, proportional "
                "von allen anderen; Erst 0 wo kein Direktkandidat."
            )
        },
        "call_threshold": 0.90,
        "hard_call_threshold": 0.999,
        "geo_units": {
            "land": [{"id": "ST", "label": "Sachsen-Anhalt"}],
            "bezirk": [],
            "wkr": [
                {"id": wid, "label": f"{wid} {panel[wid]['name']}", "bezirk": None}
                for wid in sorted(panel, key=lambda x: int(x) if x.isdigit() else 99)
            ],
        },
        "scenarios": {
            "live": {
                "label": "StaLA Live-CSV",
                "steps": steps,
                "wkr_calls": {},
                "summary": {},
            }
        },
        "scenario": "live",
        "features": {"bezirkslisten": False, "listen_einzug": True},
        "listen_mode": "landes",
        "listen_roster_2026": load_listen_roster(),
        "listen_roster_note": (
            "Landeslisten 2026 (StaLa Bewerberverzeichnis). Einzug = Nowcast-Sitze; "
            "Wackelbereich = MC p10–p90. Keine Bezirkslisten."
        ),
        "direkt_candidates_2026": load_direkt_roster(),
        "direkt_candidates_note": (
            "Direktkandidaten LTW 2026, amtliches Bewerberverzeichnis (StaLA). "
            "Kein Eintrag = kein Direktkandidat in diesem Wahlkreis."
        ),
        "live": {
            "source_url": STALA_WKR_CSV,
            "csv_path": str(csv_path),
            "result_kind": kind,
            "result_kind_label": KIND_LABEL.get(kind, kind),
            "clock": step.get("clock"),
            "ist_wb": step["n_reported"],
            "soll_wb": step["n_total"],
            "datum": (land_row.get("Datum") or "").strip() or None,
            "uhrzeit": (land_row.get("Uhrzeit") or "").strip() or None,
            "mix_live": step.get("mix_live"),
            "mix_prior": step.get("mix_prior"),
            "run_id": os.environ.get("GITHUB_RUN_ID"),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "run_url": (
                f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
                f"{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/"
                f"{os.environ['GITHUB_RUN_ID']}"
                if os.environ.get("GITHUB_RUN_ID") and os.environ.get("GITHUB_REPOSITORY")
                else None
            ),
        },
        "precincts": [],
    }
    return payload


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--csv",
        type=Path,
        default=REPO / "sachsen-anhalt" / "wahlabend" / "live" / "Ergebnisse_Land_RKR_WKR_LT_2026.csv",
    )
    ap.add_argument("--out", type=Path, default=OUT_DIR / "wahlabend_nowcast_st_live.json")
    ap.add_argument("--prev", type=Path, default=None)
    args = ap.parse_args()
    if not args.csv.exists():
        raise SystemExit(f"StaLA CSV missing: {args.csv}")
    prev = args.prev or args.out
    payload = run(args.csv, prev)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    live = payload["live"]
    step = payload["scenarios"]["live"]["steps"][-1]
    print(
        f"wrote {args.out}  kind={live['result_kind']}  "
        f"{live['ist_wb']}/{live['soll_wb']} WB  "
        f"clock={live['clock']}  AfD={step['nowcast'].get('afd')}  "
        f"CDU={step['nowcast'].get('cdu')}  steps={len(payload['scenarios']['live']['steps'])}"
    )


if __name__ == "__main__":
    main()
