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
# z for the central ~83% interval of a normal (low/high band -> sd)
Z83 = 1.37
# Monte Carlo draws for scenario probs / seat sim (was 64: +-6pp MC noise)
N_MC = 2000
# Common (across-WK) Erst deviation per party in the seat MC, pp. The Erst
# regression's own uncertainty (coefficient draws) shifts ALL Wahlkreise of a
# party together, which is what creates Überhang sweeps. Calibrated so the
# pre-count size distribution matches parliament_size_sim.py / the published
# forecast_parliament_size.json (P(oh)~0.2, size p90 89). Decays with the
# open share of each WK as results come in.
ERST_COMMON_SD = 4.5

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
FORECAST_DRAWS_URL = "https://zweitstimme.org/data/forecast_state_st_draws.json"

# forecast_state_st_draws.json party codes -> internal codes, in PARTIES order
DRAWS_KEYS = ("cdu", "afd", "spd", "lin", "gru", "bsw", "fdp", "oth")

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
    n_draws: int = N_MC,
    p_start_by_id: dict[str, float] | None = None,
    state_draws: np.ndarray | None = None,
    prior_unc_pp: dict[str, float] | None = None,
) -> dict:
    defs = load_st_scenario_defs()
    hits = {d["id"]: 0 for d in defs}
    x = sample_land_draws(nc_land_pct, unc_pp, prior_unc_pp, state_draws, rng, n_draws)
    for i in range(n_draws):
        frac = {p: float(x[i, j]) for j, p in enumerate(PARTIES)}
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


def load_state_draws(doc: dict | None) -> np.ndarray | None:
    """(n, 8) posterior vote shares in pp, columns in PARTIES order.

    Full correlation structure + skew of the zweitstimme.org posterior
    (e.g. CDU-AfD corr -0.59), unlike independent normals per party.
    """
    if not doc:
        return None
    rows = []
    for dr in doc.get("draws") or []:
        try:
            rows.append([100.0 * float(dr[k]) for k in DRAWS_KEYS])
        except (KeyError, TypeError, ValueError):
            return None
    if len(rows) < 100:
        return None
    return np.asarray(rows, dtype=float)


def sample_land_draws(
    nc_land_pct: dict[str, float],
    unc_pp: dict[str, float],
    prior_unc_pp: dict[str, float] | None,
    state_draws: np.ndarray | None,
    rng: np.random.Generator,
    n_draws: int,
) -> np.ndarray:
    """(n_draws, 8) simplex vote-share draws around the current nowcast.

    Preferred: recentre the posterior draws on the nowcast and shrink their
    spread by unc/prior_unc per party (open share, plus Brief floor).
    Fallback: independent normals with sd = unc/Z83.
    """
    nc = np.array([float(nc_land_pct.get(p, 0.0)) for p in PARTIES])
    if state_draws is not None:
        idx = rng.integers(0, len(state_draws), size=n_draws)
        base = state_draws[idx]
        mean = state_draws.mean(axis=0)
        scale = np.array(
            [
                min(
                    3.0,
                    float(unc_pp.get(p, 0.0))
                    / max(float((prior_unc_pp or {}).get(p, 0.0)), 1e-6),
                )
                for p in PARTIES
            ]
        )
        x = nc + (base - mean) * scale
    else:
        sd = np.array([float(unc_pp.get(p, 0.0)) / Z83 for p in PARTIES])
        x = nc + rng.normal(0.0, 1.0, size=(n_draws, len(PARTIES))) * sd
    x = np.clip(x, 0.0, None)
    tot = x.sum(axis=1, keepdims=True)
    tot[tot <= 0.0] = 1.0
    return x / tot


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
    wkr_ub: dict[str, dict[str, dict]] = {"U": {}, "B": {}}
    land_ub: dict[str, dict] = {}
    for row in rows:
        satz = (row.get("Satzart") or "").strip()
        art = (row.get("Wahllokal") or "").strip()
        if satz == "LAN":
            if art == "":
                land = row
            elif art in ("U", "B"):
                land_ub[art] = row
        elif satz == "WKR":
            wid = _wkr_id(row.get("Schlüsselnummer"))
            if art == "":
                wkrs[wid] = row
            elif art in ("U", "B"):
                wkr_ub[art][wid] = row
    return {
        "land": land or {},
        "wkr": wkrs,
        "wkr_ub": wkr_ub,
        "land_ub": land_ub,
        "n_rows": len(rows),
    }


GEM_CSV_NAME = "Ergebnisse_Gemeinden_LT_2026.csv"
GEM_BASELINE_2021 = REPO / "sachsen-anhalt" / "wahlabend" / "raw" / "lt21dat2.csv"

# 2021 Gemeinde CSV party columns by prefix (cp1252; order differs from 2026:
# 2021 F05=GRÜNE/F06=FDP vs 2026 F05=FDP/F06=GRÜNE).
GEM21_PREFIX = {
    "cdu": "F01",
    "afd": "F02",
    "linke": "F03",
    "spd": "F04",
    "gruene": "F05",
    "fdp": "F06",
}


def load_gem_baseline(path: Path = GEM_BASELINE_2021) -> dict[str, dict]:
    """2021 Gemeinde results (final): AGS -> gueltig + Zweit shares."""
    if not path.exists():
        return {}
    with path.open(newline="", encoding="cp1252") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    if not rows:
        return {}
    cols = list(rows[0].keys())
    key_col = next((c for c in cols if "sseln" in c), None)  # Schlüsselnummer
    g_col = next((c for c in cols if c.startswith("F - G")), None)
    party_col = {
        p: next((c for c in cols if c.startswith(pref)), None)
        for p, pref in GEM21_PREFIX.items()
    }
    out: dict[str, dict] = {}
    for r in rows:
        if (r.get("Satzart") or "").strip() != "GEM" or not key_col:
            continue
        ags = (r.get(key_col) or "").strip()
        gueltig = _num(r.get(g_col)) if g_col else 0.0
        if not ags or gueltig <= 0:
            continue
        counts = {p: (_num(r.get(c)) if c else 0.0) for p, c in party_col.items()}
        counts["bsw"] = 0.0
        counts["others"] = max(0.0, gueltig - sum(counts.values()))
        out[ags] = {
            "name": (r.get("Name") or "").strip(),
            "gueltig": gueltig,
            "shares": _shares(counts),
        }
    return out


def parse_gemeinden_csv(path: Path) -> dict[str, dict]:
    """Live 2026 Gemeinden CSV: AGS -> Summe-row counting state + Zweit counts."""
    if not path.exists():
        return {}
    try:
        with path.open(newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f, delimiter=";"))
    except (OSError, csv.Error):
        return {}
    out: dict[str, dict] = {}
    for row in rows:
        if (row.get("Satzart") or "").strip() != "GEM":
            continue
        if (row.get("Wahllokal") or "").strip() != "":
            continue  # Summe row only (U/B handled statewide by brief_stats)
        ags = (row.get("Schlüsselnummer") or "").strip()
        if not ags:
            continue
        counts, gueltig = row_counts(row, ZWEIT_COL)
        out[ags] = {
            "name": (row.get("Name") or "").strip(),
            "soll": _num(row.get("Soll.Wahlbezirke")),
            "ist": _num(row.get("Ist.Wahlbezirke")),
            "gueltig": gueltig,
            "counts": counts,
        }
    return out


_WBZ_DIR = REPO / "sachsen-anhalt" / "wahlabend"
# Cities with own Elect-iT live portals (per-Stimmbezirk pages): AGS -> files
CITY_WBZ = {
    "15002000": {
        "city": "halle",
        "live": _WBZ_DIR / "live" / "halle_wbz_2026.json",
        "base": _WBZ_DIR / "raw" / "halle_wbz_2021.json",
    },
    "15003000": {
        "city": "magdeburg",
        "live": _WBZ_DIR / "live" / "magdeburg_wbz_2026.json",
        "base": _WBZ_DIR / "raw" / "magdeburg_wbz_2021.json",
    },
}
# City presentation party labels -> internal codes (rest -> others)
CITY_PARTY = {
    "cdu": "cdu",
    "afd": "afd",
    "die linke": "linke",
    "linke": "linke",
    "spd": "spd",
    "grüne": "gruene",
    "bündnis 90/die grünen": "gruene",
    "fdp": "fdp",
    "bsw": "bsw",
    "bündnis sahra wagenknecht": "bsw",
}


def _city_counts(parties: dict) -> tuple[dict[str, float], float]:
    counts = {p: 0.0 for p in PARTIES}
    for name, v in (parties or {}).items():
        z = v.get("zweit")
        if z is None:
            continue
        counts[CITY_PARTY.get(name.strip().lower(), "others")] += float(z)
    return counts, sum(counts.values())


def apply_city_subunits(
    gem_live: dict[str, dict], gem21: dict[str, dict]
) -> tuple[dict[str, dict], dict[str, dict], dict]:
    """Split portal cities (Halle, Magdeburg) into their Stimmbezirke.

    Both cities (~22% of the state, counted late) publish per-Stimmbezirk
    results that StaLA does not. 2026 Stimmbezirk ids match 2021, so
    within-city counting composition (Neustadt vs Paulusviertel ...) is
    corrected by the same estimator that handles the 218 Gemeinden. Brief is
    only city-wide attributable -> one pseudo-unit per city with the 2021
    Brief baseline. Falls back to the StaLA Gemeinde row per city when the
    portal scrape is missing or behind.
    """
    all_diag: dict = {}
    for ags, cfg in CITY_WBZ.items():
        gem_live, gem21, diag = _apply_one_city(gem_live, gem21, ags, cfg)
        all_diag[cfg["city"]] = diag
    return gem_live, gem21, all_diag


def _apply_one_city(
    gem_live: dict[str, dict], gem21: dict[str, dict], city_ags: str, cfg: dict
) -> tuple[dict[str, dict], dict[str, dict], dict]:
    diag: dict = {"used": False}
    if city_ags not in gem_live or city_ags not in gem21:
        diag["reason"] = "no gemeinde row for city"
        return gem_live, gem21, diag
    try:
        live_doc = json.loads(cfg["live"].read_text(encoding="utf-8"))
        base_doc = json.loads(cfg["base"].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        diag["reason"] = f"files unavailable: {exc}"[:120]
        return gem_live, gem21, diag
    lu = live_doc.get("units") or {}
    bu = base_doc.get("units") or {}
    sub_live: dict[str, dict] = {}
    sub_base: dict[str, dict] = {}
    # Urne: unit-by-unit (ids stable 2021 -> 2026)
    for uid, unit in lu.items():
        if unit.get("art") != "U" or uid not in bu or bu[uid].get("art") != "U":
            continue
        b = bu[uid]
        b_counts, b_g = _city_counts(b.get("parties"))
        if b_g <= 0:
            continue
        key = f"{city_ags}:{uid}"
        sub_base[key] = {"name": b.get("name", uid), "gueltig": b_g, "shares": _shares(b_counts)}
        if unit.get("counted"):
            c, g = _city_counts(unit.get("parties"))
            sub_live[key] = {"name": unit.get("name", uid), "soll": 1, "ist": 1, "gueltig": g, "counts": c}
        else:
            sub_live[key] = {
                "name": unit.get("name", uid),
                "soll": 1,
                "ist": 0,
                "gueltig": 0.0,
                "counts": {p: 0.0 for p in PARTIES},
            }
    # Brief: city-wide pseudo-unit (Bezirk ids/counts changed since 2021)
    b_counts = {p: 0.0 for p in PARTIES}
    b_g = 0.0
    for uid, b in bu.items():
        if b.get("art") != "B":
            continue
        c, g = _city_counts(b.get("parties"))
        b_g += g
        for p in PARTIES:
            b_counts[p] += c[p]
    n_b = sum(1 for u in lu.values() if u.get("art") == "B")
    n_b_cnt = sum(1 for u in lu.values() if u.get("art") == "B" and u.get("counted"))
    l_counts = {p: 0.0 for p in PARTIES}
    l_g = 0.0
    for u in lu.values():
        if u.get("art") != "B" or not u.get("counted"):
            continue
        c, g = _city_counts(u.get("parties"))
        l_g += g
        for p in PARTIES:
            l_counts[p] += c[p]
    if b_g > 0 and n_b > 0:
        key = f"{city_ags}:brief"
        label = f"{cfg['city'].title()} Briefwahl"
        sub_base[key] = {"name": label, "gueltig": b_g, "shares": _shares(b_counts)}
        sub_live[key] = {"name": label, "soll": n_b, "ist": n_b_cnt, "gueltig": l_g, "counts": l_counts}
    if len(sub_base) < 80:
        diag["reason"] = f"only {len(sub_base)} units matched"
        return gem_live, gem21, diag
    # Authority: use the source with more counted Zweit votes for this city
    scraped_g = sum(v["gueltig"] for v in sub_live.values())
    stala_g = gem_live[city_ags]["gueltig"]
    if scraped_g < stala_g:
        diag["reason"] = f"portal behind StaLA ({int(scraped_g)} < {int(stala_g)} votes)"
        return gem_live, gem21, diag
    out_live = {k: v for k, v in gem_live.items() if k != city_ags}
    out_base = {k: v for k, v in gem21.items() if k != city_ags}
    out_live.update(sub_live)
    out_base.update(sub_base)
    diag.update(
        {
            "used": True,
            "n_units": len(sub_base),
            "n_counted": int(live_doc.get("n_counted") or 0),
            "scraped_gueltig": int(scraped_g),
            "stala_gueltig": int(stala_g),
            "generated_at": live_doc.get("generated_at"),
        }
    )
    return out_live, out_base, diag


def gem_land_nowcast(
    gem_live: dict[str, dict],
    gem21: dict[str, dict],
    land_prior: dict[str, float],
) -> tuple[dict[str, float] | None, dict]:
    """Composition-corrected statewide Zweit nowcast from the 218 Gemeinden.

    Per-Gemeinde prior = 2021 shares + uniform swing to the statewide prior.
    Surprise = counted-vote-weighted deviation of observed shares from these
    LOCAL priors, so early-reporting rural Gemeinden do not bias the state
    estimate (the WK aggregate can, when a WK's counted part is atypical).
    Open votes per Gemeinde = 2021 volume x live volume ratio, projected with
    prior + shrunk surprise. Returns (None, diag) when unusable.
    """
    diag: dict = {"used": False}
    if not gem_live or not gem21:
        diag["reason"] = "missing gemeinde live/baseline data"
        return None, diag
    matched = [a for a in gem_live if a in gem21]
    match_rate = len(matched) / max(1, len(gem_live))
    diag["n_gem"] = len(gem_live)
    diag["n_matched"] = len(matched)
    if match_rate < 0.9:
        diag["reason"] = f"AGS match rate {match_rate:.2f} < 0.9"
        return None, diag
    tot21 = sum(gem21[a]["gueltig"] for a in matched) + EPS
    land21 = {
        p: sum(gem21[a]["gueltig"] * gem21[a]["shares"][p] for a in matched) / tot21
        for p in PARTIES
    }
    swing = {p: land_prior[p] - land21[p] for p in PARTIES}
    prior_g = {
        a: _shares({p: max(0.0, gem21[a]["shares"][p] + swing[p]) for p in PARTIES})
        for a in matched
    }

    reported: list[str] = []
    frac_g: dict[str, float] = {}
    for a in matched:
        g = gem_live[a]
        f = (g["ist"] / g["soll"]) if g["soll"] > 0 else 0.0
        if f <= 0 and g["gueltig"] > 0:
            # votes but stale Ist counter: estimate from 2021 volume, never lock
            f = min(0.98, g["gueltig"] / max(1.0, gem21[a]["gueltig"]))
        frac_g[a] = min(1.0, f)
        if g["gueltig"] > 0:
            reported.append(a)
    diag["n_gem_reported"] = len(reported)
    if not reported:
        diag["reason"] = "no gemeinde has counted votes"
        return None, diag

    cnt_tot = sum(gem_live[a]["gueltig"] for a in reported) + EPS
    surprise = {}
    for p in PARTIES:
        surprise[p] = (
            sum(
                gem_live[a]["gueltig"]
                * (gem_live[a]["counts"][p] / max(EPS, gem_live[a]["gueltig"]) - prior_g[a][p])
                for a in reported
            )
            / cnt_tot
        )
    # Live volume ratio 2026/2021 from reported parts (turnout drift), guarded.
    exp_cnt = sum(frac_g[a] * gem21[a]["gueltig"] for a in reported)
    vol_ratio = (cnt_tot / exp_cnt) if exp_cnt > 50 else 1.0
    vol_ratio = float(np.clip(vol_ratio, 0.5, 2.0))
    frac_votes = sum(gem21[a]["gueltig"] * frac_g[a] for a in matched) / tot21
    w = frac_votes / (frac_votes + HALF_LIFE)

    proj = {p: 0.0 for p in PARTIES}
    for a in matched:
        g = gem_live[a]
        open_vol = max(0.0, (1.0 - frac_g[a]) * gem21[a]["gueltig"] * vol_ratio)
        open_sh = _shares({p: max(0.0, prior_g[a][p] + w * surprise[p]) for p in PARTIES})
        for p in PARTIES:
            proj[p] += g["counts"][p] + open_vol * open_sh[p]
    nc = _shares(proj)
    diag.update(
        {
            "used": True,
            "frac_votes": round(frac_votes, 4),
            "learn_weight": round(w, 4),
            "vol_ratio": round(vol_ratio, 4),
            "surprise": {p: round(surprise[p] * 100, 3) for p in PARTIES},
            "ist": int(sum(gem_live[a]["ist"] for a in gem_live)),
            "soll": int(sum(gem_live[a]["soll"] for a in gem_live)),
        }
    )
    return nc, diag


def live_precincts(panel: dict[str, dict], live: dict) -> list[dict]:
    """One UI 'precinct' per Wahlkreis so Rohstand can show StaLA counts."""
    wkrs = live.get("wkr") or {}
    out: list[dict] = []
    for wid in sorted(panel, key=lambda x: int(x) if str(x).isdigit() else 99):
        row = wkrs.get(wid) or {}
        counts, gueltig = row_counts(row, ZWEIT_COL) if row else ({p: 0.0 for p in PARTIES}, 0.0)
        erst_c, erst_g = row_counts(row, ERST_COL) if row else ({p: 0.0 for p in PARTIES}, 0.0)
        out.append(
            {
                "id": wid,
                "wkr": wid,
                "art": "S",
                "name": panel[wid]["name"],
                "bezirk": None,
                "gueltig": int(round(gueltig)),
                "gueltig_erst": int(round(erst_g)),
                "wber": int(round(_num(row.get("A.Wahlberechtigte")))),
                "waehler": int(round(_num(row.get("B.Wähler")))),
                "counts": {p: int(round(counts[p])) for p in PARTIES},
                "counts_erst": {p: int(round(erst_c[p])) for p in PARTIES},
            }
        )
    return out


def brief_stats(live: dict) -> dict[str, dict]:
    """Statewide Urne vs Brief counting state from the per-WKR U/B rows."""
    out: dict[str, dict] = {}
    ub = live.get("wkr_ub") or {}
    land_ub = live.get("land_ub") or {}
    for art in ("U", "B"):
        rows = list((ub.get(art) or {}).values())
        if not rows and land_ub.get(art):
            rows = [land_ub[art]]
        soll = ist = g = 0.0
        counts = {p: 0.0 for p in PARTIES}
        for r in rows:
            soll += _num(r.get("Soll.Wahlbezirke"))
            ist += _num(r.get("Ist.Wahlbezirke"))
            c, gg = row_counts(r, ZWEIT_COL)
            g += gg
            for p in PARTIES:
                counts[p] += c[p]
        out[art] = {
            "soll": soll,
            "ist": ist,
            "gueltig": g,
            "frac": (ist / soll) if soll > 0 else 0.0,
            "shares": _shares(counts) if g > 0 else None,
        }
    return out


def brief_unc_floor(stats: dict[str, dict]) -> tuple[dict[str, float], dict]:
    """Extra pp uncertainty for Urne/Brief composition of the open votes.

    The nowcast projects open votes from the counted mix; if Brief lags Urne
    (or vice versa) the projection is systematically off by roughly
    gap x (Brief share of open - Brief share of counted) x open share.
    The gap is estimated live from the U/B rows (no gap data before votes:
    floor 0, but then the full prior band dominates anyway).
    """
    zero = {p: 0.0 for p in PARTIES}
    u, b = stats.get("U") or {}, stats.get("B") or {}
    if not u.get("shares") or not b.get("shares"):
        return zero, {}
    frac_u = min(1.0, float(u["frac"]))
    frac_b = min(1.0, float(b["frac"]))
    if frac_u <= 0.02 or frac_b <= 0.02:
        return zero, {}
    est_u = u["gueltig"] / frac_u
    est_b = b["gueltig"] / frac_b
    b_hat = est_b / (est_u + est_b + EPS)
    open_b = b_hat * (1.0 - frac_b)
    open_u = (1.0 - b_hat) * (1.0 - frac_u)
    open_tot = open_b + open_u
    cnt_b = b_hat * frac_b
    cnt_u = (1.0 - b_hat) * frac_u
    cnt_tot = cnt_b + cnt_u
    if open_tot <= 1e-9 or cnt_tot <= 1e-9:
        return zero, {"b_hat": round(b_hat, 4), "frac_u": round(frac_u, 4), "frac_b": round(frac_b, 4)}
    mix_shift = abs(open_b / open_tot - cnt_b / cnt_tot)
    w_g = min(frac_u, frac_b)
    w_g = w_g / (w_g + HALF_LIFE)
    floor = {}
    gap_pp = {}
    for p in PARTIES:
        gap = 100.0 * (b["shares"][p] - u["shares"][p]) * w_g
        gap_pp[p] = round(gap, 2)
        floor[p] = round(abs(gap) * mix_shift * open_tot, 2)
    diag = {
        "b_hat": round(b_hat, 4),
        "frac_u": round(frac_u, 4),
        "frac_b": round(frac_b, 4),
        "mix_shift": round(mix_shift, 4),
        "gap_pp": gap_pp,
        "floor_pp": dict(floor),
    }
    return floor, diag


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
    races: dict[str, dict],
    rng: np.random.Generator,
    n_draws: int = N_MC,
    state_draws: np.ndarray | None = None,
    prior_unc_pp: dict[str, float] | None = None,
) -> dict:
    """Seat MC. `races` per WK: {a, b, margin (pp), sigma (pp), open (0..1)}.

    Direct mandates are resampled per draw: WK margin shifts with the
    statewide swing of that draw (uniform-swing coupling, scaled by the open
    share of the WK) plus local noise, so correlated flips (e.g. an AfD
    sweep with Überhang) show up in the p10-p90 seat bands. Fully counted
    WKs stay fixed at the observed leader.
    """
    directs = {p: 0 for p in MAIN}
    for r in races.values():
        if r["a"] in directs:
            directs[r["a"]] += 1
    x = sample_land_draws(nc_land_pct, unc_pp, prior_unc_pp, state_draws, rng, n_draws)
    xpct = x * 100.0
    nc = np.array([float(nc_land_pct.get(p, 0.0)) for p in PARTIES])
    delta = xpct - nc  # statewide swing per draw, pp
    # Erst-model uncertainty: common across WKs per party (see ERST_COMMON_SD)
    eta = rng.normal(0.0, ERST_COMMON_SD, size=(n_draws, len(PARTIES)))
    pidx = {p: i for i, p in enumerate(PARTIES)}
    race_list = list(races.values())
    winners = np.empty((n_draws, len(race_list)), dtype=np.int16)
    for j, r in enumerate(race_list):
        ia, ib = pidx[r["a"]], pidx[r["b"]]
        if r["open"] <= 1e-3:
            winners[:, j] = ia if r["margin"] >= 0 else ib
            continue
        swing = (delta[:, ia] - delta[:, ib] + eta[:, ia] - eta[:, ib]) * float(r["open"])
        var_sw = float(np.var(swing))
        sig_local = math.sqrt(max(float(r["sigma"]) ** 2 - var_sw, 0.25))
        m = float(r["margin"]) + swing + rng.normal(0.0, sig_local, size=n_draws)
        winners[:, j] = np.where(m > 0.0, ia, ib)
    sizes: list[int] = []
    seats_acc: dict[str, list[int]] = {p: [] for p in MAIN}
    list_acc: dict[str, list[int]] = {p: [] for p in MAIN}
    for i in range(n_draws):
        frac = {p: float(x[i, pidx[p]]) for p in PARTIES}
        dirs = {p: 0 for p in MAIN}
        for j in range(len(race_list)):
            wp = PARTIES[winners[i, j]]
            if wp in dirs:
                dirs[wp] += 1
        alloc = allocate_st(frac, dirs)
        sizes.append(int(alloc["size"]))
        for p in MAIN:
            s_p = int(alloc["seats"].get(p, 0))
            seats_acc[p].append(s_p)
            list_acc[p].append(max(0, s_p - dirs.get(p, 0)))

    def q(vals: list[int]) -> list[int]:
        arr = np.asarray(vals)
        return [int(np.percentile(arr, 10)), int(np.percentile(arr, 50)), int(np.percentile(arr, 90))]

    sz = np.asarray(sizes)
    return {
        "n_draws": n_draws,
        "size": q(sizes),
        "size_mean": round(float(sz.mean()), 1),
        "size_p95": int(np.percentile(sz, 95)),
        "p_size_gt_base": round(float((sz > 83).mean()), 3),
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
        frac = (ist / soll) if soll > 0 else 0.0
        if frac <= 0 and gueltig > 0:
            # Votes but stale/missing Ist counter: estimate the counted share
            # from 2021 volume and never lock the WK as complete.
            g_l1 = panel.get(wid, {}).get("gueltig_l1", 0.0)
            frac = min(0.98, gueltig / g_l1) if g_l1 > 0 else 0.5
        if frac <= 0 and gueltig <= 0:
            continue
        reported[wid] = {
            "frac": min(1.0, frac),
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
        # Prior-based Erst projection (used for the open part of the WK)
        if erst_prior and wid in erst_prior:
            raw_e = {p: max(0.0, erst_prior[wid][p] + w * surprise[p]) for p in PARTIES}
        else:
            # Erst ≈ Zweit nowcast + 2021 Erst−Zweit gap
            l1e = row["erst_l1"]
            l1z = row["shares_l1"]
            e_tot = sum(l1e.values()) + EPS
            e_sh = {p: l1e[p] / e_tot for p in PARTIES}
            raw_e = {p: max(0.0, sh[p] + (e_sh[p] - l1z[p])) for p in PARTIES}
        proj_e = _shares(raw_e)
        if bsw_direkt is not None and wid not in bsw_direkt:
            proj_e["bsw"] = 0.0
            proj_e = _shares(proj_e)
        # Mix observed Erst continuously by counted fraction (like Zweit),
        # instead of jumping from prior to fully-observed at frac >= 0.5.
        if wid in reported and reported[wid]["erst_shares"]:
            mix_e = reported[wid]["frac"]
            erst_sh = _shares(
                {
                    p: mix_e * reported[wid]["erst_shares"][p] + (1.0 - mix_e) * proj_e[p]
                    for p in PARTIES
                }
            )
        else:
            erst_sh = proj_e
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
        # StaLA semantics mid-count are ambiguous: A may be the full
        # electorate (~1.79M in 2021) while B covers only counted WBZ.
        # If A looks complete, scale counted voters by the reported share.
        if wber > 1_500_000 and 0.02 < reported_frac < 0.99:
            naive = min(100.0, 100.0 * (waehler / reported_frac) / wber)
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
    state_draws: np.ndarray | None = None,
    gem_live: dict[str, dict] | None = None,
    gem_baseline: dict[str, dict] | None = None,
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
    # Gemeinde-level composition-corrected Land nowcast (finer than WK: knows
    # WHICH municipalities inside each WK have reported). Used when the
    # Gemeinden CSV is fresh enough vs the WKR file; otherwise WK aggregate.
    nowcast_source = "wkr"
    gem_nc, gem_diag = gem_land_nowcast(gem_live or {}, gem_baseline or {}, land_prior)
    if gem_nc is not None:
        land_ist = _num(land_row.get("Ist.Wahlbezirke"))
        gem_ist = float(gem_diag.get("ist") or 0)
        fresh = land_ist <= 0 or gem_ist >= 0.8 * land_ist
        if fresh:
            nc_land = gem_nc
            nowcast_source = "gemeinden"
        else:
            gem_diag["used"] = False
            gem_diag["reason"] = f"stale: gem ist {int(gem_ist)} < 0.8 x land ist {int(land_ist)}"
    unc = diag["uncertainty"]
    # Urne/Brief composition risk of the still-open votes (live U/B rows);
    # added in quadrature so the band cannot collapse while Brief lags.
    b_stats = brief_stats(live)
    b_floor, b_diag = brief_unc_floor(b_stats)
    unc = {
        p: round(math.sqrt(float(unc[p]) ** 2 + float(b_floor.get(p, 0.0)) ** 2), 2)
        for p in PARTIES
    }
    wkr_out = {}
    races: dict[str, dict] = {}
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
        races[wid] = {
            "a": top2[0],
            "b": top2[1],
            "margin": margin,
            "sigma": m_u + 0.5,
            "open": open_w,
        }
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
    # City portals (Halle/Magdeburg) often run ahead of the StaLA counter;
    # show the larger precinct count so the page reflects what the model uses.
    if nowcast_source == "gemeinden":
        ist = max(ist, float(gem_diag.get("ist") or 0))
        if soll <= 0:
            soll = float(gem_diag.get("soll") or 0)
    frac_wb = (ist / soll) if soll > 0 else diag["frac_votes"]
    turnout = turnout_nowcast(panel, land_row, live["wkr"], frac_wb)
    entry_mc = night_entry_mc(
        _pct(nc_land),
        unc,
        races,
        rng,
        state_draws=state_draws,
        prior_unc_pp=prior_unc_pp,
    )
    kind = (land_row.get("Ergebnisart") or "L").strip() or "L"
    clock = clock_from_row(land_row)
    scen = night_scenario_probs(
        _pct(nc_land),
        unc,
        rng,
        state_draws=state_draws,
        prior_unc_pp=prior_unc_pp,
    )
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
        "surprise": gem_diag["surprise"] if nowcast_source == "gemeinden" else diag["surprise"],
        "nowcast_source": nowcast_source,
        "gemeinden": gem_diag or None,
        "uncertainty": unc,
        "turnout": turnout,
        "by_wkr": wkr_out,
        "by_bezirk": {},
        "entry_mc": entry_mc,
        "scenario_probs": scen,
        "eval": None,
        "result_kind": kind,
        "n_wkr_touch": diag["n_wkr_touch"],
        "brief": b_diag or None,
        "uncertainty_note": {
            "phase": unc_phase(frac_wb if soll > 0 else diag["frac_votes"]),
            "land": (
                "Landes-± = Band der zweitstimme.org-Landesprognose (ca. 83 %). "
                "Vor der Auszählung die volle Prognose; danach offener Stimmenanteil × dieses Band, "
                "plus Zuschlag für noch offene Briefwahl (Urne-Brief-Differenz live geschätzt). "
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
    if steps:
        last = steps[-1]
        last_key = (
            last.get("clock"),
            last.get("frac_reported"),
            last.get("n_reported"),
        )
        if last_key == (step.get("clock"), step.get("frac_reported"), step.get("n_reported")):
            steps[-1] = step
            return _stamp_p_start(steps)
    steps.append(step)
    return _stamp_p_start(steps)


def run(csv_path: Path, prev_path: Path | None) -> dict:
    panel = load_wkr_panel()
    state_fc = _load_json(REPO / "output" / "forecast_state_st.json", FORECAST_STATE_URL)
    dist_fc = _load_json(REPO / "output" / "forecast_districts_st.json", FORECAST_DISTRICT_URL)
    try:
        draws_doc = _load_json(
            REPO / "output" / "forecast_state_st_draws.json", FORECAST_DRAWS_URL
        )
    except Exception:
        draws_doc = None
    state_draws = load_state_draws(draws_doc)
    land_prior = statewide_prior(state_fc)
    if state_draws is not None:
        # Unrounded posterior mean (forecast_state fit/low/high are integers;
        # the 1pp grid distorts 5%-hurdle probabilities).
        m = state_draws.mean(axis=0)
        land_prior = _shares({p: float(m[i]) for i, p in enumerate(PARTIES)})
    prior_unc = prior_uncertainty_pp(state_fc)
    prior, erst_prior, bsw_direkt = district_priors(dist_fc, panel, land_prior)
    wk_unc = district_wk_unc_pp(dist_fc)
    live = parse_stala_csv(csv_path)
    gem_live = parse_gemeinden_csv(csv_path.parent / GEM_CSV_NAME)
    gem_baseline = load_gem_baseline()
    gem_live, gem_baseline, city_diag = apply_city_subunits(gem_live, gem_baseline)
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
        state_draws=state_draws,
        gem_live=gem_live,
        gem_baseline=gem_baseline,
    )
    step["city_wbz"] = city_diag or None
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
        "baseline": "π₀ = Landesprognose + WK-Zweit; Live = StaLA WKR- + Gemeinde-CSV",
        "parties": list(PARTIES),
        "party_labels": PARTY_LABELS,
        "n_precincts": int(step["n_total"] or len(panel)),
        "n_wkr": len(panel),
        "match": {"n_truth": len(panel), "n_l1": len(panel), "n_matched": len(panel), "match_rate": 1.0},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "prior_uncertainty_pp": prior_unc,
        "model": {
            "description": (
                "Sachsen-Anhalt 2026 Live-Nowcast: StaLA Wahlkreis- und "
                "Gemeinde-CSV (Zwischenergebnisse nach 18 Uhr) + Vorwahl-Prognose. "
                "Landes-Zweit = Gemeinde-Nowcast (218 Gemeinden, Überraschung "
                "gegen lokale Priors aus LTW 2021 + Uniform-Swing — korrigiert, "
                "WELCHE Gemeinden schon gezählt haben; Fallback WK-Aggregat). "
                "WK-Zweit = WK-Prognose; Erst = dieselbe WK-Regression "
                "(Zweit + LTW 2021, ohne Kandidateneffekte; 0 ohne Direktkandidat). "
                "BSW ohne Historie: Landesanteil, proportional "
                "von allen anderen; Erst 0 wo kein Direktkandidat. "
                "Szenario- und Sitz-MC auf den zweitstimme.org-Posterior-Draws "
                "(Korrelationen/Schiefe), Direktmandate pro Draw neu gezogen; "
                "±-Band mit Briefwahl-Zuschlag."
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
        "precincts": live_precincts(panel, live),
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
