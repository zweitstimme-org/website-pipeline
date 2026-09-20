#!/usr/bin/env python3
"""Shared helpers for Berlin / MV 2026 live Wahlabend nowcasts.

Used by wahlabend_be_live.py and wahlabend_mv_live.py. JSON shape matches
the ST live UI (wahlabend-nowcast.js).
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "output"
SCENARIO_CFG = REPO / "data" / "state_forecast_scenarios.json"
EXTERNAL_JSON = REPO / "data" / "wahlabend_external.json"

PARTIES = ("cdu", "afd", "spd", "linke", "gruene", "bsw", "fdp", "others")
MAIN = ("cdu", "afd", "spd", "linke", "gruene", "bsw", "fdp")
EPS = 1e-12
HALF_LIFE = 0.05
Z83 = 1.37
N_MC = 800
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

DRAWS_KEYS = ("cdu", "afd", "spd", "lin", "gru", "bsw", "fdp", "oth")

_SCENARIO_ALIAS = {
    "gru": "gruene",
    "gruene": "gruene",
    "lin": "linke",
    "linke": "linke",
}

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
NAME_TO_BEZ = {v.lower(): k for k, v in BEZ_NAMES.items()}

INSTITUTE_LABEL = {
    "infratest_dimap": "Infratest dimap",
    "forschungsgruppe_wahlen": "Forschungsgruppe Wahlen",
    "ard": "ARD",
    "zdf": "ZDF",
}

# AfS 2026 AGH Zweit/Erst P01… columns follow the published ballot table
# (https://www.wahlen-berlin.de/wahlen/Be2026/AFSPRAES/agh/). Unmapped Pxx
# fold into others via (Gültig − named).
AFS_2026_PXX = {
    1: "cdu",
    2: "spd",
    3: "gruene",
    4: "linke",
    5: "afd",
    6: "fdp",
    24: "bsw",  # DSB 2026: P17 is SGP; BSW is P24
}

AWK_MAP_PATH = REPO / "berlin" / "awk_wkr_map.json"


def _scenario_party(p: str) -> str:
    return _SCENARIO_ALIAS.get((p or "").strip().lower(), (p or "").strip().lower())


def _num(x) -> float:
    if x is None or x == "" or x in ("-", "x", "X", ".", "–"):
        return 0.0
    if isinstance(x, (int, float)):
        return float(x) if math.isfinite(float(x)) else 0.0
    s = str(x).strip().replace("\xa0", "").replace(" ", "")
    if s.endswith("%"):
        s = s[:-1]
    # German 12.345,67 vs 12,34 vs 12.34
    if re.search(r"\d\.\d{3}", s) and "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(",") == 1 and s.count(".") == 0:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _shares(counts: dict[str, float]) -> dict[str, float]:
    tot = sum(max(0.0, float(counts.get(p, 0.0))) for p in PARTIES) + EPS
    return {p: max(0.0, float(counts.get(p, 0.0))) / tot for p in PARTIES}


def _pct(sh: dict[str, float]) -> dict[str, float]:
    return {p: round(float(sh.get(p, 0.0)) * 100.0, 2) for p in PARTIES}


def _wkr_id(raw) -> str:
    s = str(raw or "").strip()
    try:
        return str(int(float(s)))
    except ValueError:
        m = re.search(r"(\d+)", s)
        return str(int(m.group(1))) if m else (s.lstrip("0") or "0")


def load_awk_to_wkr(path: Path | None = None) -> dict[str, str]:
    """AfS awk `0101` → statewide WK id `1`."""
    p = path or AWK_MAP_PATH
    if not p.exists():
        return {}
    try:
        inv = json.loads(p.read_text(encoding="utf-8")).get("awk_to_wkr") or {}
    except json.JSONDecodeError:
        return {}
    out: dict[str, str] = {}
    for k, v in inv.items():
        key = str(k).strip().zfill(4)
        out[key] = str(int(v)) if str(v).isdigit() or isinstance(v, int) else _wkr_id(v)
    return out


def awk_code(bez: str, local) -> str | None:
    bez_s = str(bez or "").strip().zfill(2)
    try:
        loc = int(float(str(local).strip()))
    except (TypeError, ValueError):
        return None
    if not bez_s.isdigit() or loc <= 0:
        return None
    return f"{bez_s}{loc:02d}"


def _load_json(path: Path | None, url: str | None = None) -> dict:
    if path and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if url:
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    raise FileNotFoundError(str(path or url))


def _load_json_optional(path: Path | None, url: str | None = None) -> dict | None:
    try:
        return _load_json(path, url)
    except Exception:
        return None


def statewide_prior(forecast: dict) -> dict[str, float]:
    raw = {p: 0.0 for p in PARTIES}
    for row in forecast.get("parties") or []:
        code = FORECAST_PARTY.get(str(row.get("party_code") or "").lower())
        if not code:
            continue
        raw[code] += float(row.get("fit") or 0.0)
    return _shares(raw)


def load_state_draws(doc: dict | None) -> np.ndarray | None:
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


def squeeze_in(shares: dict[str, float], party: str, target: float) -> dict[str, float]:
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


def load_wkr_panel(path: Path) -> dict[str, dict]:
    """LTW/AGH WK panel CSV (gültige_stimmen_zweit + party_zweit / _erst)."""
    out: dict[str, dict] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            wid = _wkr_id(row.get("wahlkreis"))
            g = _num(row.get("gültige_stimmen_zweit"))
            counts = {p: _num(row.get(f"{p}_zweit")) for p in PARTIES}
            if g <= 0:
                g = sum(counts.values())
            erst = {p: _num(row.get(f"{p}_erst")) for p in PARTIES}
            out[wid] = {
                "id": wid,
                "name": str(row.get("wahlkreisname") or f"WK {wid}").strip(),
                "gueltig_l1": g,
                "shares_l1": _shares(counts),
                "erst_l1": erst,
                "gueltig_erst_l1": _num(row.get("gültige_stimmen_erst")),
                "turnout_l1": _num(row.get("wahlbeteiligung")),
            }
    return out


def blend_wk_history(
    panel: dict[str, dict],
    alt_shares: dict[str, dict[str, float]],
    *,
    weight_alt: float = 0.55,
) -> dict[str, dict]:
    """Blend L1 panel shares with another election's WK shares (e.g. BTW 2025).

    ``alt_shares[wid]`` is a simplex. Missing WKs keep L1. BSW from alt is
    kept even when L1 is 0.
    """
    w = float(np.clip(weight_alt, 0.0, 1.0))
    for wid, row in panel.items():
        alt = alt_shares.get(wid)
        if not alt:
            continue
        blended = {
            p: (1.0 - w) * row["shares_l1"].get(p, 0.0) + w * float(alt.get(p, 0.0))
            for p in PARTIES
        }
        # If L1 has no BSW, take alt BSW fully then renormalize.
        if row["shares_l1"].get("bsw", 0.0) <= EPS and float(alt.get("bsw", 0.0)) > EPS:
            blended = squeeze_in(_shares(blended), "bsw", float(alt["bsw"]))
        else:
            blended = _shares(blended)
        row["shares_hist"] = blended
        row["hist_source"] = "blend"
    for row in panel.values():
        row.setdefault("shares_hist", dict(row["shares_l1"]))
        row.setdefault("hist_source", "l1")
    return panel


def district_priors(
    districts: dict,
    panel: dict[str, dict],
    land: dict[str, float],
    *,
    hist_key: str = "shares_hist",
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
    hist_land = _shares(
        {
            p: sum(
                panel[w]["gueltig_l1"] * panel[w].get(hist_key, panel[w]["shares_l1"])[p]
                for w in panel
            )
            for p in PARTIES
        }
    )
    bsw_land = float(land.get("bsw") or 0.0)
    priors: dict[str, dict] = {}
    for wid, row in panel.items():
        if wid in by_z and sum(by_z[wid].values()) > 0:
            sh = _shares(by_z[wid])
        else:
            base = row.get(hist_key) or row["shares_l1"]
            swung = {}
            for p in PARTIES:
                if hist_land[p] > EPS:
                    swung[p] = base[p] * (land[p] / hist_land[p])
                else:
                    swung[p] = 0.0
            sh = _shares(swung)
        if sh.get("bsw", 0.0) <= EPS and bsw_land > EPS:
            sh = squeeze_in(sh, "bsw", bsw_land)
        priors[wid] = sh
    total_g = sum(panel[w]["gueltig_l1"] for w in panel) + EPS
    agg = {
        p: sum(panel[w]["gueltig_l1"] * priors[w][p] for w in panel) / total_g
        for p in PARTIES
    }
    scale = {}
    for p in PARTIES:
        scale[p] = land[p] / agg[p] if agg[p] > EPS else 1.0
    for wid in priors:
        priors[wid] = _shares({p: priors[wid][p] * scale[p] for p in PARTIES})
    erst_prior: dict[str, dict] = {}
    for wid, row in panel.items():
        if wid in by_e and sum(by_e[wid].values()) > 0:
            e = _shares(by_e[wid])
        else:
            l1e = row["erst_l1"]
            e_tot = sum(l1e.values()) + EPS
            e_sh = {p: l1e[p] / e_tot for p in PARTIES}
            e = _shares(
                {p: max(0.0, priors[wid][p] + (e_sh[p] - row["shares_l1"][p])) for p in PARTIES}
            )
        if wid not in bsw_direkt:
            e["bsw"] = 0.0
            e = _shares(e)
        erst_prior[wid] = e
    return priors, erst_prior, bsw_direkt


def _frac_votes_unit(gueltig: float, ist: float, soll: float, g_l1: float, tr: float) -> float:
    if soll > 0 and ist >= soll and gueltig > 0:
        return 1.0
    if g_l1 > 0 and gueltig > 0:
        return float(np.clip(gueltig / (g_l1 * max(tr, 0.2)), 0.0, 0.999))
    if soll > 0:
        return float(np.clip(ist / soll, 0.0, 0.999))
    return 0.0 if gueltig <= 0 else 0.5


def nowcast_wkrs(
    panel: dict[str, dict],
    prior: dict[str, dict],
    live_wkr: dict[str, dict],
    bsw_direkt: set[str] | None = None,
    erst_prior: dict[str, dict] | None = None,
    prior_unc_pp: dict[str, float] | None = None,
    tr: float = 1.0,
) -> tuple[dict[str, dict], dict]:
    reported: dict[str, dict] = {}
    for wid, row in live_wkr.items():
        if wid not in panel:
            continue
        soll = _num(row.get("soll") or row.get("Soll.Wahlbezirke"))
        ist = _num(row.get("ist") or row.get("Ist.Wahlbezirke"))
        gueltig = _num(row.get("gueltig"))
        counts = row.get("counts") or {p: 0.0 for p in PARTIES}
        if gueltig <= 0:
            gueltig = sum(float(counts.get(p, 0.0)) for p in PARTIES)
        erst_c = row.get("erst_counts") or {p: 0.0 for p in PARTIES}
        erst_g = _num(row.get("erst_gueltig"))
        if erst_g <= 0:
            erst_g = sum(float(erst_c.get(p, 0.0)) for p in PARTIES)
        frac = (ist / soll) if soll > 0 else 0.0
        if frac <= 0 and gueltig > 0:
            g_l1 = panel.get(wid, {}).get("gueltig_l1", 0.0)
            frac = min(0.98, gueltig / g_l1) if g_l1 > 0 else 0.5
        if frac <= 0 and gueltig <= 0:
            continue
        frac_v = _frac_votes_unit(
            gueltig, ist, soll, panel.get(wid, {}).get("gueltig_l1", 0.0), tr
        )
        reported[wid] = {
            "frac": min(1.0, frac),
            "frac_v": frac_v,
            "ist": ist,
            "soll": soll,
            "counts": counts,
            "gueltig": gueltig,
            "shares": _shares(counts) if gueltig > 0 else dict(prior[wid]),
            "erst_counts": erst_c,
            "erst_gueltig": erst_g,
            "erst_shares": _shares(erst_c) if erst_g > 0 else None,
            "wber": _num(row.get("wber")),
            "waehler": _num(row.get("waehler")),
            "winner": str(row.get("winner") or "").strip(),
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
        obs = {
            p: sum(reported[w]["gueltig"] * reported[w]["shares"][p] for w in rep_ids) / tw
            for p in PARTIES
        }
        pri_r = {
            p: sum(reported[w]["gueltig"] * prior[w][p] for w in rep_ids) / tw
            for p in PARTIES
        }
        surprise = {p: obs[p] - pri_r[p] for p in PARTIES}
        total_g = sum(panel[w]["gueltig_l1"] for w in panel) + EPS
        frac_votes = (
            sum(panel[w]["gueltig_l1"] * reported.get(w, {}).get("frac_v", 0.0) for w in panel)
            / total_g
        )
        w = frac_votes / (frac_votes + HALF_LIFE)

    nc: dict[str, dict] = {}
    for wid, row in panel.items():
        pri = prior[wid]
        if wid in reported and reported[wid]["frac"] >= 0.999 and reported[wid]["gueltig"] > 0:
            sh = dict(reported[wid]["shares"])
            mix = 1.0
        elif wid in reported and reported[wid]["gueltig"] > 0:
            mix = reported[wid]["frac_v"]
            raw_open = {p: max(0.0, pri[p] + w * surprise[p]) for p in PARTIES}
            open_sh = _shares(raw_open)
            sh = {
                p: mix * reported[wid]["shares"][p] + (1.0 - mix) * open_sh[p]
                for p in PARTIES
            }
            sh = _shares(sh)
        else:
            mix = 0.0
            raw = {p: max(0.0, pri[p] + w * surprise[p]) for p in PARTIES}
            sh = _shares(raw)
        if erst_prior and wid in erst_prior:
            raw_e = {p: max(0.0, erst_prior[wid][p] + w * surprise[p]) for p in PARTIES}
        else:
            l1e = row["erst_l1"]
            l1z = row["shares_l1"]
            e_tot = sum(l1e.values()) + EPS
            e_sh = {p: l1e[p] / e_tot for p in PARTIES}
            raw_e = {p: max(0.0, sh[p] + (e_sh[p] - l1z[p])) for p in PARTIES}
        proj_e = _shares(raw_e)
        if bsw_direkt is not None and wid not in bsw_direkt:
            proj_e["bsw"] = 0.0
            proj_e = _shares(proj_e)
        if wid in reported and reported[wid]["erst_shares"]:
            mix_e = reported[wid]["frac_v"]
            erst_sh = _shares(
                {
                    p: mix_e * reported[wid]["erst_shares"][p] + (1.0 - mix_e) * proj_e[p]
                    for p in PARTIES
                }
            )
        else:
            erst_sh = proj_e
        live_row = live_wkr.get(wid) or {}
        n_rep = int(reported.get(wid, {}).get("ist", 0) or 0)
        n_tot = int(reported.get(wid, {}).get("soll", 0) or 0)
        if n_rep <= 0:
            n_rep = int(_num(live_row.get("ist")))
        if n_tot <= 0:
            n_tot = int(_num(live_row.get("soll")))
        nc[wid] = {
            "nowcast": sh,
            "erst": erst_sh,
            "frac": reported.get(wid, {}).get("frac", 0.0),
            "frac_v": reported.get(wid, {}).get("frac_v", 0.0),
            "n_reported": n_rep,
            "n_total": n_tot,
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


# ---------------------------------------------------------------------------
# External Prognose / Hochrechnung
# ---------------------------------------------------------------------------


def _share_row_to_frac(shares: dict) -> dict[str, float]:
    raw = {p: 0.0 for p in PARTIES}
    for k, v in (shares or {}).items():
        code = FORECAST_PARTY.get(str(k).lower())
        if not code:
            continue
        raw[code] += _num(v)
    # Input may be percent (sum~100) or fractions (sum~1).
    tot = sum(raw.values())
    if tot > 1.5:
        raw = {p: raw[p] / 100.0 for p in PARTIES}
    return _shares(raw)


def load_external(state: str, path: Path | None = None) -> dict | None:
    """Latest usable external source for a state (prognose / hochrechnung)."""
    p = path or EXTERNAL_JSON
    if not p.exists():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    block = doc.get(state.lower()) or {}
    sources = list(block.get("sources") or [])
    usable = []
    for s in sources:
        kind = str(s.get("kind") or "").lower()
        if kind not in ("prognose", "hochrechnung", "beteiligung"):
            continue
        sh = _share_row_to_frac(s.get("shares") or {})
        if kind != "beteiligung" and sum(sh.values()) <= 0.5:
            continue
        usable.append({**s, "kind": kind, "_frac": sh})
    if not usable:
        return None
    rank = {"beteiligung": 0, "prognose": 1, "hochrechnung": 2}
    usable.sort(key=lambda s: (rank.get(s["kind"], 0), str(s.get("time") or "")))
    latest = usable[-1]
    turnout_src = None
    for s in reversed(usable):
        if s.get("turnout") is not None:
            turnout_src = s
            break
    label = _external_label(latest)
    unc = _num(latest.get("uncertainty_pp"))
    if unc <= 0:
        # Conservative ± vs historical TV RMSE (was 0.8 / 1.5).
        unc = 1.6 if latest["kind"] == "hochrechnung" else 3.0
    return {
        "kind": latest["kind"],
        "label": label,
        "frac": latest["_frac"],
        "uncertainty_pp": unc,
        "turnout": _num(turnout_src["turnout"]) if turnout_src and turnout_src.get("turnout") is not None else None,
        "time": latest.get("time"),
        "institute": latest.get("institute"),
        "all": usable,
    }


def _external_label(src: dict) -> str:
    kind = src.get("kind") or ""
    kind_de = {
        "prognose": "Prognose",
        "hochrechnung": "Hochrechnung",
        "beteiligung": "Beteiligung",
    }.get(kind, kind)
    inst = INSTITUTE_LABEL.get(str(src.get("institute") or "").lower(), src.get("publisher") or src.get("institute") or "")
    t = src.get("time") or ""
    bits = [kind_de]
    if inst:
        bits.append(str(inst))
    if t:
        bits.append(str(t))
    return " ".join(bits)


def blend_with_external(
    precinct_frac: dict[str, float],
    precinct_unc: dict[str, float],
    frac_votes: float,
    external: dict | None,
    prior_unc: dict[str, float],
    *,
    half_life: float = HALF_LIFE,
) -> tuple[dict[str, float], dict[str, float], dict]:
    """Replace π₀ with Prognose/Hochrechnung, then blend toward precinct nowcast."""
    if not external or external.get("kind") == "beteiligung":
        return precinct_frac, precinct_unc, {
            "source": "nowcast" if frac_votes > 1e-6 else "forecast",
            "label": "Nowcast" if frac_votes > 1e-6 else "Vorwahlprognose zweitstimme.org",
            "w_precinct": round(float(np.clip(frac_votes / (frac_votes + half_life), 0, 1)), 4) if frac_votes > 0 else 0.0,
        }
    ext = external["frac"]
    w = float(frac_votes / (frac_votes + half_life)) if frac_votes > 0 else 0.0
    blended = _shares(
        {p: (1.0 - w) * ext[p] + w * precinct_frac[p] for p in PARTIES}
    )
    ext_unc = external.get("uncertainty")
    if not isinstance(ext_unc, dict) or not ext_unc:
        u0 = float(external.get("uncertainty_pp") or prior_unc.get("cdu", 2.3))
        ext_unc = {p: u0 for p in PARTIES}
    # Shrink the TV/HR band with the uncounted share. Do NOT mix in the
    # pre-election prior (±4–8 pp): w hits ~0.5 at only 5 % counted, so
    # that blend made Landes-± jump from ~0.8 to ~3 as soon as precincts
    # arrived. Counted votes are known; remainder keeps the TV scale.
    open_frac = max(0.0, 1.0 - float(frac_votes))
    unc = {
        p: round(max(0.0, float(ext_unc.get(p, prior_unc.get(p, 2.3))) * open_frac), 2)
        for p in PARTIES
    }
    src = "nowcast" if w >= 0.55 else external["kind"]
    label = external["label"] if w < 0.55 else f"Nowcast ({external['label']})"
    return blended, unc, {
        "source": src,
        "label": label,
        "w_precinct": round(w, 4),
        "external_kind": external["kind"],
    }


def turnout_mixture(
    *,
    prior_pp: float,
    last_office_pp: float,
    recent_federal_pp: float,
    naive: float | None,
    reported_frac: float,
    n_complete: int,
    brief_visible: bool,
    external_turnout: float | None = None,
    open_unc_pp: float = 15.0,
    floor_unc_pp: float = 8.0,
) -> dict:
    """Wide early turnout band (ST 2026 was 77.8 vs 60.3 ±7)."""
    mix_prior = 0.5 * last_office_pp + 0.5 * recent_federal_pp
    point = float(external_turnout) if external_turnout else float(prior_pp or mix_prior)
    # Volume from complete units pulls the point, but slowly.
    w_count = n_complete / (n_complete + 8.0)
    if naive is not None and reported_frac >= 0.985:
        return {
            "nowcast": round(float(naive), 2),
            "naive": round(float(naive), 2),
            "prior": round(point, 2),
            "truth": None,
            "uncertainty": 0.0 if reported_frac >= 0.999 else 0.5,
            "frac_wber_reported": round(reported_frac, 4),
            "abs_err": None,
        }
    if naive is not None and n_complete > 0:
        nc = point + (float(naive) - point) * w_count
    else:
        nc = point
    open_w = max(0.0, 1.0 - reported_frac)
    unc = open_unc_pp * open_w
    if not brief_visible:
        unc = max(unc, floor_unc_pp)
    if reported_frac < 0.02:
        unc = max(unc, open_unc_pp)
    unc = float(np.clip(unc, 0.0, 20.0))
    return {
        "nowcast": round(float(np.clip(nc, 40.0, 95.0)), 2),
        "naive": round(float(naive), 2) if naive is not None else round(point, 2),
        "naive_note": "Urne-only (Briefwähler fehlen im Zähler)",
        "prior": round(point, 2),
        "last_office": last_office_pp,
        "recent_federal": recent_federal_pp,
        "n_complete": n_complete,
        "truth": None,
        "uncertainty": round(unc, 2),
        "frac_wber_reported": round(reported_frac, 4),
        "abs_err": None,
    }


# ---------------------------------------------------------------------------
# Scenarios + history
# ---------------------------------------------------------------------------


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


def load_scenario_defs(state: str, *, hurdle: float = 0.05) -> list[dict]:
    st = state.upper()
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
    default_hurdle = {"BE": ["fdp", "bsw"], "MV": ["cdu", "fdp", "gru", "bsw"]}.get(st, ["fdp", "bsw"])
    for raw in cfg.get("above_hurdle_parties_by_state", {}).get(st, default_hurdle):
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
    coalitions.extend(cfg.get("coalitions_by_state", {}).get(st) or [])
    excluded = set(cfg.get("exclude_scenario_ids_by_state", {}).get(st) or [])
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
    for row in cfg.get("majority_excluding_by_state", {}).get(st) or []:
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
    state: str,
    n_draws: int = N_MC,
    state_draws: np.ndarray | None = None,
    prior_unc_pp: dict[str, float] | None = None,
) -> dict:
    defs = load_scenario_defs(state)
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
        items.append(
            {
                "id": d["id"],
                "category": d["category"],
                "label_de": d["label_de"],
                "p": round(p_hat * 100.0, 1),
                "p_start": round(p_hat * 100.0, 1),
                "truth": None,
                "call": p_hat >= 0.5,
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
    return steps


def _step_progress(step: dict) -> tuple:
    frac = step.get("frac_reported")
    n_rep = step.get("n_reported")
    try:
        frac_n = round(float(frac), 4) if frac is not None else None
    except (TypeError, ValueError):
        frac_n = frac
    return (frac_n, n_rep)


def _n_reported(step: dict) -> int:
    try:
        return int(step.get("n_reported") or 0)
    except (TypeError, ValueError):
        return 0


def _progress_key(step: dict) -> tuple[float, int]:
    try:
        frac = float(step.get("frac_reported") or 0.0)
    except (TypeError, ValueError):
        frac = 0.0
    return (frac, _n_reported(step))


def _same_progress(a: dict, b: dict) -> bool:
    return _step_progress(a) == _step_progress(b) or _progress_key(a) == _progress_key(b)


def _trim_progress_regressions(steps: list[dict]) -> list[dict]:
    """Keep a non-decreasing count path.

    Empty refetches must not sit after a counted snapshot — the UI shows
    the last step, so a trailing 0 % row hides the nowcast.
    """
    keep: list[dict] = []
    best = (-1.0, -1)
    for s in steps:
        p = _progress_key(s)
        if keep and _same_progress(keep[-1], s):
            keep[-1] = s
            continue
        if p < best:
            continue
        keep.append(s)
        if p > best:
            best = p
    return keep


def _monotonic_land_uncertainty(steps: list[dict]) -> list[dict]:
    """Landes-± must not grow as more precincts arrive."""
    prev_u: dict[str, float] | None = None
    prev_p = (-1.0, -1)
    for s in steps:
        u = s.get("uncertainty")
        if not isinstance(u, dict) or not u:
            continue
        p = _progress_key(s)
        if prev_u and p > prev_p:
            s["uncertainty"] = {
                k: round(
                    min(
                        float(u.get(k, prev_u.get(k, 0.0))),
                        float(prev_u.get(k, u.get(k, 0.0))),
                    ),
                    2,
                )
                for k in PARTIES
            }
        prev_u = s.get("uncertainty") if isinstance(s.get("uncertainty"), dict) else prev_u
        prev_p = p
    return steps


def merge_history(prev: dict | None, step: dict) -> list[dict]:
    steps = []
    if prev:
        sc = (prev.get("scenarios") or {}).get("live") or (prev.get("scenarios") or {}).get("random")
        if sc:
            steps = list(sc.get("steps") or [])
    steps = _trim_progress_regressions(steps)
    if steps:
        last = steps[-1]
        if _progress_key(step) < _progress_key(last):
            return _stamp_p_start(_monotonic_land_uncertainty(steps))
        last_key = (last.get("clock"), last.get("frac_reported"), last.get("n_reported"))
        new_key = (step.get("clock"), step.get("frac_reported"), step.get("n_reported"))
        if last_key == new_key or _same_progress(last, step):
            steps[-1] = step
            return _stamp_p_start(_monotonic_land_uncertainty(steps))
    steps.append(step)
    return _stamp_p_start(_monotonic_land_uncertainty(_trim_progress_regressions(steps)))


def _leader(sh: dict[str, float]) -> str:
    return max(MAIN, key=lambda p: sh.get(p, 0.0))


def wkr_races(
    panel: dict[str, dict],
    nc: dict[str, dict],
    wk_unc_pp: dict[str, dict[str, float]],
    prior_unc: dict[str, float],
) -> tuple[dict[str, dict], dict[str, dict]]:
    races: dict[str, dict] = {}
    wkr_out: dict[str, dict] = {}
    for wid in panel:
        now = nc[wid]["nowcast"]
        erst = nc[wid]["erst"]
        src = erst if sum(erst.values()) > 0 else now
        ranked = sorted(MAIN, key=lambda p: src.get(p, 0.0), reverse=True)
        top2 = ranked[:2]
        margin = (src[top2[0]] - src[top2[1]]) * 100.0
        frac_w = float(nc[wid].get("frac_v") or nc[wid].get("frac") or 0.0)
        open_w = max(0.0, 1.0 - frac_w)
        u_map = wk_unc_pp.get(wid) or {}
        u_w = {
            p: round(float(u_map.get(p, prior_unc.get(p, 4.0))) * open_w, 2) for p in MAIN
        }
        m_u = 0.5 * (u_w.get(top2[0], 3.0) + u_w.get(top2[1], 3.0))
        z = margin / (m_u + 0.5)
        p_lead = float(0.5 * (1 + math.erf(z / math.sqrt(2))))
        complete = frac_w >= 0.999
        likely = p_lead >= 0.90
        called = p_lead >= 0.999 and frac_w > 0 and (complete or margin >= (1 - frac_w) * 40)
        lp = _leader(src)
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
            "ballot": "erst" if nc[wid]["reported"] and erst else "erst_proxy",
            "official_winner": nc[wid]["winner"] or None,
        }
    return races, wkr_out


def night_entry_mc(
    nc_land_pct: dict[str, float],
    unc_pp: dict[str, float],
    races: dict[str, dict],
    rng: np.random.Generator,
    *,
    allocate,
    base_seats: int,
    n_draws: int = N_MC,
    state_draws: np.ndarray | None = None,
    prior_unc_pp: dict[str, float] | None = None,
) -> dict:
    directs = {p: 0 for p in MAIN}
    for r in races.values():
        if r["a"] in directs:
            directs[r["a"]] += 1
    x = sample_land_draws(nc_land_pct, unc_pp, prior_unc_pp, state_draws, rng, n_draws)
    xpct = x * 100.0
    nc = np.array([float(nc_land_pct.get(p, 0.0)) for p in PARTIES])
    delta = xpct - nc
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
        alloc = allocate(frac, dirs)
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
        "p_size_gt_base": round(float((sz > base_seats).mean()), 3),
        "seats": {p: q(seats_acc[p]) for p in MAIN},
        "directs": directs,
        "list_seats": {p: q(list_acc[p]) for p in MAIN},
    }


def precinct_ist_soll(
    land_row: dict | None,
    nc: dict,
    *,
    extra_ist: int = 0,
    extra_soll: int = 0,
    expected_soll: int = 0,
    n_wkr: int = 0,
) -> tuple[int, int]:
    """Land-level Wahlbezirk Ist/Soll. Never fall back to the WK count."""
    land_row = land_row or {}
    ist = int(sum(int(nc[w].get("n_reported") or 0) for w in nc))
    soll = int(sum(int(nc[w].get("n_total") or 0) for w in nc))
    ist = max(ist, int(_num(land_row.get("ist"))), int(extra_ist))
    soll = max(soll, int(_num(land_row.get("soll"))), int(extra_soll), int(expected_soll))
    if n_wkr and 0 < soll <= n_wkr and expected_soll > n_wkr:
        soll = int(expected_soll)
    return ist, soll


def live_meta(kind: str, kind_label: str, step: dict, source_url: str) -> dict:
    return {
        "source_url": source_url,
        "result_kind": kind,
        "result_kind_label": kind_label,
        "clock": step.get("clock"),
        "ist_wb": step["n_reported"],
        "soll_wb": step["n_total"],
        "ist_wkr": step.get("n_wkr_reported"),
        "soll_wkr": step.get("n_wkr_total"),
        "unit": "wahlbezirke",
        "unit_label": "Wahlbezirken",
        "mix_live": step.get("mix_live"),
        "mix_prior": step.get("mix_prior"),
        "prediction_source": (step.get("prediction") or {}).get("source"),
        "prediction_source_label": (step.get("prediction") or {}).get("label"),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "run_url": (
            f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
            f"{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/"
            f"{os.environ['GITHUB_RUN_ID']}"
            if os.environ.get("GITHUB_RUN_ID") and os.environ.get("GITHUB_REPOSITORY")
            else None
        ),
    }


def load_listen_roster(path: Path) -> dict[str, dict]:
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
            lt = (r.get("list_type") or "landes").strip().lower() or "landes"
            slot = out.setdefault(party, {"list_type": lt, "landes": [], "bezirk": {}})
            if lt == "bezirk":
                bez = str(r.get("bezirk") or "").zfill(2)
                slot["list_type"] = "bezirk"
                slot["bezirk"].setdefault(bez, []).append(entry)
            else:
                slot["landes"].append(entry)
    for slot in out.values():
        slot["landes"].sort(key=lambda e: e["pos"])
        for rows in slot["bezirk"].values():
            rows.sort(key=lambda e: e["pos"])
    return out


def load_direkt_roster(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            wid = _wkr_id(r.get("wkr"))
            name = (r.get("name") or "").strip()
            if not wid or not name:
                continue
            party = FORECAST_PARTY.get(str(r.get("party") or r.get("partei") or "").lower())
            cell = {
                "name": name,
                "is_placeholder": False,
                "source": (r.get("source") or "").strip(),
                "party_raw": (r.get("partei") or r.get("party") or "").strip(),
            }
            slot = out.setdefault(wid, {})
            if party and party in MAIN:
                slot[party] = cell
            else:
                extra = slot.setdefault("_extra", [])
                extra.append(cell)
    return out


def live_precincts(panel: dict[str, dict], live_wkr: dict[str, dict]) -> list[dict]:
    out: list[dict] = []
    for wid in sorted(panel, key=lambda x: int(x) if str(x).isdigit() else 99):
        row = live_wkr.get(wid) or {}
        counts = row.get("counts") or {p: 0.0 for p in PARTIES}
        erst = row.get("erst_counts") or {p: 0.0 for p in PARTIES}
        out.append(
            {
                "id": wid,
                "wkr": wid,
                "art": "S",
                "name": panel[wid]["name"],
                "bezirk": panel[wid].get("bezirk"),
                "gueltig": int(round(_num(row.get("gueltig")))),
                "gueltig_erst": int(round(_num(row.get("erst_gueltig")))),
                "wber": int(round(_num(row.get("wber")))),
                "waehler": int(round(_num(row.get("waehler")))),
                "counts": {p: int(round(float(counts.get(p, 0.0)))) for p in PARTIES},
                "counts_erst": {p: int(round(float(erst.get(p, 0.0)))) for p in PARTIES},
            }
        )
    return out


def _csv_header_line(lines: list[str]) -> int:
    """Index of the real delimiter-separated header, skipping LAIV titles.

    LAIV files start with 'Zwischenergebnis der Wahlkreise …' — that line
    contains 'wahlkreis' but is not a header. Require several delimited
    fields plus a known column token.
    """
    tokens = (
        "berechnungsdatum",
        "ausgabe",
        "adresse",
        "gebietsart",
        "wahlberecht",
        "gültig",
        "gueltig",
        "p01",
        ";spd;",
        ";cdu;",
        ";afd;",
    )
    start = 0
    for i, line in enumerate(lines[:16]):
        if not line or not line.strip():
            continue
        semi, comma = line.count(";"), line.count(",")
        delim = ";" if semi >= comma else ","
        if line.count(delim) < 3:
            continue
        low = f";{line.lower().replace(',', ';')};"
        if any(tok in low or tok in line.lower() for tok in tokens):
            return i
        start = i
    return start


def read_csv_rows(path: Path) -> tuple[list[dict], list[str]]:
    """Read a CSV trying utf-8-sig then latin-1, comma then semicolon."""
    if not path.exists() or path.stat().st_size < 8:
        return [], []
    raw = path.read_bytes()
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return [], []
    lines = text.splitlines()
    start = _csv_header_line(lines)
    body = "\n".join(lines[start:])
    dialect_delim = ";" if body[:400].count(";") >= body[:400].count(",") else ","
    f = io.StringIO(body)
    reader = csv.DictReader(f, delimiter=dialect_delim)
    rows = list(reader)
    cols = list(reader.fieldnames or [])
    return rows, cols


def map_party_columns(cols: list[str], pxx_map: dict[int, str] | None = None) -> dict[str, str]:
    """Header fragment → party code. Named columns win; else AfS P01… codes."""
    out: dict[str, str] = {}
    patterns = [
        ("bsw", ("bsw", "wagenknecht")),
        ("gruene", ("grüne", "gruene", "buendnis 90", "bündnis 90")),
        ("linke", ("linke", "die linke")),
        ("cdu", ("cdu",)),
        ("spd", ("spd",)),
        ("afd", ("afd",)),
        ("fdp", ("fdp",)),
    ]
    for col in cols:
        s = re.sub(r"\s+", " ", str(col or "")).strip().lower()
        if not s or re.fullmatch(r"p\d+", s) or re.fullmatch(r"p\d+p", s):
            continue
        if "prozent" in s or "percent" in s:
            continue
        for code, frags in patterns:
            if code in out:
                continue
            if any(frag in s for frag in frags):
                out[code] = col
                break
    if len(out) >= 3:
        return out
    pmap = pxx_map if pxx_map is not None else AFS_2026_PXX
    for col in cols:
        m = re.fullmatch(r"P(\d+)", str(col or "").strip(), re.I)
        if not m:
            continue
        code = pmap.get(int(m.group(1)))
        if code and code not in out:
            out[code] = col
    return out


def counts_from_row(row: dict, party_cols: dict[str, str], gueltig_keys: list[str] | None = None) -> tuple[dict[str, float], float]:
    named = {p: _num(row.get(col)) for p, col in party_cols.items()}
    gueltig = 0.0
    for k in gueltig_keys or ["Gueltig", "Gültige Stimmen", "Gültige", "Gültig"]:
        if k in row:
            gueltig = _num(row.get(k))
            if gueltig > 0:
                break
    if gueltig <= 0:
        for k, v in row.items():
            lk = str(k).lower().replace("ü", "ue").replace("ä", "ae")
            if lk.endswith("p") or "prozent" in lk or "percent" in lk:
                continue
            if "gueltig" in lk and "unguelt" not in lk and "erst" not in lk:
                gueltig = _num(v)
                if gueltig > 0:
                    break
    named_sum = sum(named.values())
    if gueltig <= 0:
        gueltig = named_sum
    counts = {p: 0.0 for p in PARTIES}
    counts.update(named)
    counts["others"] = max(0.0, gueltig - named_sum)
    return counts, gueltig


def row_has_votes(row: dict) -> bool:
    """True if an AfS/LAIV result row reports any counted ballots."""
    for k in ("Gueltig", "Gültige Stimmen", "Gültige", "Waehler", "Wähler", "Wählende", "P01", "P02", "SPD", "CDU"):
        if _num(row.get(k)) > 0:
            return True
    for k, v in row.items():
        lk = str(k).lower().replace("ü", "ue")
        if lk.endswith("p") or "prozent" in lk:
            continue
        if lk in ("gueltig", "waehler", "waehlende", "wberins") or re.fullmatch(r"p\d+", lk):
            if _num(v) > 0:
                return True
    return False


def clock_from_fields(*vals: str) -> str | None:
    parts = [str(v).strip() for v in vals if v and str(v).strip()]
    if not parts:
        return None
    blob = " ".join(parts)
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%y.%m.%d %H:%M:%S",
        "%y.%m.%d %H:%M",
        "%y.%m.%d%H:%M:%S",
        "%d.%m.%y %H:%M:%S",
    ):
        try:
            return datetime.strptime(blob.replace("T", " ")[:19], fmt).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    return blob[:16]


def github_now() -> str:
    return datetime.now(timezone.utc).isoformat()
