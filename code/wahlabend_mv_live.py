#!/usr/bin/env python3
"""Live Mecklenburg-Vorpommern LTW 2026 nowcast from LAIV CSVs.

Local history: LTW 2021 WK panel (Wahlbezirke when the XLSX is present).
Optional BTW 2025 WB blend if a processed JSON exists. π₀ = forecast_state_mv.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from parliament_size_sim import allocate_mv
from wahlabend_live_common import (
    EPS,
    EXTERNAL_JSON,
    MAIN,
    OUT_DIR,
    PARTIES,
    PARTY_LABELS,
    REPO,
    _load_json,
    _load_json_optional,
    _num,
    _pct,
    _shares,
    _wkr_id,
    blend_wk_history,
    blend_with_external,
    clock_from_fields,
    counts_from_row,
    district_priors,
    district_wk_unc_pp,
    github_now,
    live_meta,
    live_precincts,
    load_direkt_roster,
    load_external,
    load_listen_roster,
    load_state_draws,
    load_wkr_panel,
    map_party_columns,
    merge_history,
    night_entry_mc,
    night_scenario_probs,
    nowcast_wkrs,
    precinct_ist_soll,
    prior_uncertainty_pp,
    read_csv_rows,
    row_has_votes,
    statewide_prior,
    turnout_mixture,
    unc_phase,
    wkr_races,
)

LIVE_DIR = REPO / "mecklenburg-vorpommern" / "wahlabend" / "live"
RAW = REPO / "mecklenburg-vorpommern" / "wahlabend" / "raw"
PANEL_PATH = REPO / "mecklenburg-vorpommern" / "LTWMeckPom" / "ltw21_meckpom_abs.csv"

FORECAST_STATE_URL = "https://zweitstimme.org/data/forecast_state_mv.json"
FORECAST_DISTRICT_URL = "https://zweitstimme.org/data/forecast_districts_mv.json"
FORECAST_DRAWS_URL = "https://zweitstimme.org/data/forecast_state_mv_draws.json"
LAIV_PAGE = "https://www.laiv-mv.de/Wahlen/Landtagswahlen/2026/Ergebnisse/"

LAST_OFFICE_TURNOUT = 70.8  # LTW 2021
RECENT_FEDERAL_TURNOUT = 80.0  # MV BTW 2025 (approx.)
TURNOUT_PRIOR = 74.0
# LTW 2021 replay precinct count; live LAIV Soll replaces this when present.
EXPECTED_PRECINCTS = 1759

KIND_LABEL = {
    "empty": "Noch keine Auszählung",
    "Z": "Zwischenergebnis",
    "V": "Vorläufiges Ergebnis",
    "E": "Endgültiges Ergebnis",
}


def _row_is_percent(row: dict) -> bool:
    blob = " ".join(str(v or "") for v in list(row.values())[:8]).lower()
    return "%" in blob or "prozent" in blob or "anteil" in blob


def _row_wkr(row: dict) -> str | None:
    for k, v in row.items():
        lk = str(k).lower()
        if any(tok in lk for tok in ("wahlkreis", "wk-nr", "wk_nr", "wknr")) or lk in ("wk", "wk-nr"):
            s = str(v or "").strip()
            if not s or s in ("-", "."):
                continue
            try:
                n = int(float(s))
            except (TypeError, ValueError):
                m = re.search(r"(\d+)", s)
                n = int(m.group(1)) if m else 0
            if 1 <= n <= 36:
                return str(n)
    return None


def _row_is_erst(row: dict) -> bool:
    blob = " ".join(str(k) + " " + str(v or "") for k, v in list(row.items())[:12]).lower()
    if "zweit" in blob:
        return False
    return "erst" in blob


def parse_laiv_units(path: Path, *, key_fields: tuple[str, ...]) -> dict[str, dict]:
    """Parse a LAIV CSV into units keyed by WK / AGS / WB id.

    LAIV files have a 4-line preamble and four records per unit
    (Erst abs / Erst % / Zweit abs / Zweit %). We keep absolute Zweit
    (and Erst when present).
    """
    rows, cols = read_csv_rows(path)
    if not rows or not any(row_has_votes(r) for r in rows):
        return {}
    party_cols = map_party_columns(cols)
    if not party_cols:
        return {}

    def key_of(row: dict) -> str | None:
        for k in list(row.keys()):
            lk = str(k).lower()
            if any(f in lk for f in key_fields):
                val = str(row.get(k) or "").strip()
                if val and val not in ("-", "."):
                    if "wahlkreis" in lk or "wk" == lk:
                        return _wkr_id(val)
                    return val
        # fallback: first numeric-looking cell
        for k, v in row.items():
            s = str(v or "").strip()
            if s.isdigit() and 1 <= int(s) <= 99 and "wahlkreis" in str(k).lower():
                return str(int(s))
        return None

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        kid = key_of(row)
        if not kid:
            continue
        grouped.setdefault(kid, []).append(row)

    out: dict[str, dict] = {}
    for kid, recs in grouped.items():
        zweit_abs = erst_abs = None
        ist = soll = wber = waehler = 0.0
        clock = None
        name = ""
        for row in recs:
            clock = clock or clock_from_fields(
                row.get("Datum") or "",
                row.get("Uhrzeit") or row.get("Zeit") or row.get("Zeitstempel") or "",
            )
            for k, v in row.items():
                lk = str(k).lower()
                if "wahlberecht" in lk:
                    wber = max(wber, _num(v))
                elif "wähler" in lk or "wählende" in lk:
                    waehler = max(waehler, _num(v))
                elif "ist" in lk and "bezirk" in lk:
                    ist = max(ist, _num(v))
                elif "soll" in lk and "bezirk" in lk:
                    soll = max(soll, _num(v))
                elif "name" in lk or "bezeichnung" in lk:
                    name = name or str(v or "").strip()
            if _row_is_percent(row):
                continue
            counts, gueltig = counts_from_row(row, party_cols)
            if gueltig <= 0:
                continue
            if _row_is_erst(row):
                erst_abs = (counts, gueltig)
            else:
                zweit_abs = (counts, gueltig)
        if not zweit_abs:
            continue
        counts, gueltig = zweit_abs
        unit = {
            "counts": counts,
            "gueltig": gueltig,
            "wber": wber,
            "waehler": waehler,
            "ist": ist,
            "soll": soll,
            "name": name,
            "clock": clock,
            "wkr": next((w for w in (_row_wkr(r) for r in recs) if w), None),
        }
        if erst_abs:
            unit["erst_counts"] = erst_abs[0]
            unit["erst_gueltig"] = erst_abs[1]
        out[kid] = unit
    return out


def parse_laiv_live() -> dict:
    wkr_path = LIVE_DIR / "l_wahlkreise.csv"
    gem_path = LIVE_DIR / "l_gemeinden.csv"
    wb_path = LIVE_DIR / "l_wahlbezirke.csv"
    # Also pick up whatever the fetch script saved.
    extras = list(LIVE_DIR.glob("*.csv"))
    wkr = parse_laiv_units(wkr_path, key_fields=("wahlkreis", "wk-nr", "wk_nr", "wk"))
    for p in extras:
        if "wahlkreis" in p.name.lower() and p != wkr_path:
            wkr.update(parse_laiv_units(p, key_fields=("wahlkreis", "wk-nr", "wk")))
    gem = parse_laiv_units(gem_path, key_fields=("ags", "gemeinde", "schlüssel", "schluessel"))
    wb = parse_laiv_units(wb_path, key_fields=("wahlbezirk", "wbz", "wb-nr"))
    for p in extras:
        n = p.name.lower()
        if "gemeinde" in n and p != gem_path:
            gem.update(parse_laiv_units(p, key_fields=("ags", "gemeinde", "schlüssel")))
        if "wahlbezirk" in n and p != wb_path:
            wb.update(parse_laiv_units(p, key_fields=("wahlbezirk", "wbz")))
    land = {}
    clock = None
    ist = soll = 0.0
    if wkr:
        land_counts = {p: 0.0 for p in PARTIES}
        g = wber = waehler = 0.0
        for u in wkr.values():
            for p in PARTIES:
                land_counts[p] += float(u["counts"].get(p, 0.0))
            g += u["gueltig"]
            wber += u.get("wber") or 0.0
            waehler += u.get("waehler") or 0.0
            ist += u.get("ist") or 0.0
            soll += u.get("soll") or 0.0
            clock = clock or u.get("clock")
        land = {
            "counts": land_counts,
            "gueltig": g,
            "wber": wber,
            "waehler": waehler,
            "ist": ist,
            "soll": soll,
        }
    kind = "empty"
    if any(_num(u.get("gueltig")) > 0 for u in wkr.values()) or wb or gem:
        kind = "Z"
    return {"land": land, "wkr": wkr, "gemeinden": gem, "wb": wb, "clock": clock, "kind": kind}


def load_btw2025_wk_shares(panel: dict[str, dict]) -> dict[str, dict[str, float]]:
    """Optional processed BTW 2025 WK shares (not required for live)."""
    path = RAW / "btw2025_wk_shares.json"
    if not path.exists():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    out = {}
    for k, v in (doc.get("wkr") or doc or {}).items():
        if not isinstance(v, dict):
            continue
        wid = _wkr_id(k)
        if wid in panel:
            out[wid] = _shares(v)
    return out


def roll_to_wkr(units: dict[str, dict], panel: dict[str, dict]) -> dict[str, dict]:
    by: dict[str, dict] = {}
    for rec in units.values():
        wid = str(rec.get("wkr") or "")
        if not wid or wid not in panel:
            continue
        if _num(rec.get("gueltig")) <= 0:
            continue
        slot = by.setdefault(
            wid,
            {
                "counts": {p: 0.0 for p in PARTIES},
                "gueltig": 0.0,
                "ist": 0.0,
                "soll": 0.0,
                "wber": 0.0,
                "waehler": 0.0,
                "erst_counts": {p: 0.0 for p in PARTIES},
                "erst_gueltig": 0.0,
            },
        )
        for p in PARTIES:
            slot["counts"][p] += float((rec.get("counts") or {}).get(p, 0.0))
            slot["erst_counts"][p] += float((rec.get("erst_counts") or {}).get(p, 0.0))
        slot["gueltig"] += rec["gueltig"]
        slot["erst_gueltig"] += _num(rec.get("erst_gueltig"))
        slot["ist"] += 1
        slot["wber"] += _num(rec.get("wber"))
        slot["waehler"] += _num(rec.get("waehler"))
    return by


def allocate_from_nowcast(frac: dict[str, float], dirs: dict[str, int]) -> dict:
    votes = {p: float(frac.get(p, 0.0)) for p in MAIN}
    directs = {p: int(dirs.get(p, 0)) for p in MAIN}
    return allocate_mv(votes, directs)


def build_step(
    panel,
    prior,
    live,
    land_prior,
    rng,
    *,
    bsw_direkt,
    erst_prior,
    prior_unc,
    wk_unc,
    state_draws,
    external,
) -> dict:
    live_wkr = dict(live.get("wkr") or {})
    source = "wkr"
    wb = live.get("wb") or {}
    gem = live.get("gemeinden") or {}
    wkr_votes = sum(_num(u.get("gueltig")) for u in live_wkr.values())
    if wkr_votes < 1:
        rolled_gem = roll_to_wkr(gem, panel)
        rolled_wb = roll_to_wkr(wb, panel)
        rolled = rolled_gem or rolled_wb
        if rolled:
            live_wkr = rolled
            source = "gemeinden" if rolled_gem else "wahlbezirke"
    elif wb:
        # Prefer precinct counts inside a WK when the WK file is a running total
        # that might lag Brief/Urne split; keep WK totals as the default.
        source = "wkr"
    nc, diag = nowcast_wkrs(
        panel,
        prior,
        live_wkr,
        bsw_direkt=bsw_direkt,
        erst_prior=erst_prior,
        prior_unc_pp=prior_unc,
    )
    total_g = sum(panel[w]["gueltig_l1"] for w in panel) + EPS
    nc_land = {
        p: sum(panel[w]["gueltig_l1"] * nc[w]["nowcast"][p] for w in panel) / total_g
        for p in PARTIES
    }
    # If land row has more votes than WK mix (gemeinde feed ahead), use it as
    # the reported land observation blended via surprise already in WK nowcast.
    land_row = live.get("land") or {}
    if _num(land_row.get("gueltig")) > 0 and diag["n_wkr_touch"] == 0:
        nc_land = _shares(land_row.get("counts") or nc_land)
        source = "land"
    frac_v = float(diag.get("frac_votes") or 0.0)
    unc = dict(diag["uncertainty"])
    nc_land, unc, pred = blend_with_external(nc_land, unc, frac_v, external, prior_unc)

    n_rep = sum(1 for w in nc.values() if w["reported"])
    n_tot = len(panel)
    extra_ist = len([u for u in wb.values() if _num(u.get("gueltig")) > 0]) if wb else 0
    extra_soll = len(wb) if wb else 0
    ist, soll = precinct_ist_soll(
        land_row,
        nc,
        extra_ist=extra_ist,
        extra_soll=extra_soll,
        expected_soll=EXPECTED_PRECINCTS,
        n_wkr=n_tot,
    )
    frac_wb = (ist / soll) if soll else frac_v

    wber = _num(land_row.get("wber"))
    waehler = _num(land_row.get("waehler"))
    naive = 100.0 * waehler / wber if wber > 1000 and waehler > 0 else None
    n_complete = sum(1 for w in nc.values() if w.get("frac", 0) >= 0.999)
    turnout = turnout_mixture(
        prior_pp=TURNOUT_PRIOR,
        last_office_pp=LAST_OFFICE_TURNOUT,
        recent_federal_pp=RECENT_FEDERAL_TURNOUT,
        naive=naive,
        reported_frac=frac_wb,
        n_complete=n_complete,
        brief_visible=False,
        external_turnout=(external or {}).get("turnout"),
    )
    races, wkr_out = wkr_races(panel, nc, wk_unc, prior_unc)
    entry_mc = night_entry_mc(
        _pct(nc_land),
        unc,
        races,
        rng,
        allocate=allocate_from_nowcast,
        base_seats=71,
        state_draws=state_draws,
        prior_unc_pp=prior_unc,
    )
    scen = night_scenario_probs(
        _pct(nc_land),
        unc,
        rng,
        state="MV",
        state_draws=state_draws,
        prior_unc_pp=prior_unc,
    )
    clock = live.get("clock") or datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    return {
        "frac_reported": round(frac_wb if soll else frac_v, 4),
        "n_reported": int(ist),
        "n_total": int(soll) if soll else EXPECTED_PRECINCTS,
        "clock": clock,
        "clock_source": "laiv",
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
        "nowcast_source": source,
        "uncertainty": unc,
        "turnout": turnout,
        "by_wkr": wkr_out,
        "by_bezirk": {},
        "entry_mc": entry_mc,
        "scenario_probs": scen,
        "eval": None,
        "result_kind": live.get("kind") or "empty",
        "n_wkr_touch": diag["n_wkr_touch"],
        "n_wkr_reported": int(n_rep),
        "n_wkr_total": int(n_tot),
        "prediction": pred,
        "uncertainty_note": {
            "phase": unc_phase(frac_wb if soll else frac_v),
            "land": (
                "Landes-± startet mit Vorwahlprognose bzw. Prognose/Hochrechnung "
                "und schrumpft mit dem offenen Stimmenanteil."
            ),
            "wkr": "Wahlkreis-± = Regressionsband × offener Anteil.",
        },
    }


def run(prev_path: Path | None, external_path: Path | None) -> dict:
    panel = load_wkr_panel(PANEL_PATH)
    alt = load_btw2025_wk_shares(panel)
    if alt:
        blend_wk_history(panel, alt, weight_alt=0.45)
    else:
        for row in panel.values():
            row["shares_hist"] = dict(row["shares_l1"])
            row["hist_source"] = "ltw2021"
    state_fc = _load_json(REPO / "output" / "forecast_state_mv.json", FORECAST_STATE_URL)
    dist_fc = _load_json(REPO / "output" / "forecast_districts_mv.json", FORECAST_DISTRICT_URL)
    draws_doc = _load_json_optional(
        REPO / "output" / "forecast_state_mv_draws.json", FORECAST_DRAWS_URL
    )
    state_draws = load_state_draws(draws_doc)
    land_prior = statewide_prior(state_fc)
    if state_draws is not None:
        m = state_draws.mean(axis=0)
        land_prior = _shares({p: float(m[i]) for i, p in enumerate(PARTIES)})
    prior_unc = prior_uncertainty_pp(state_fc)
    prior, erst_prior, bsw_direkt = district_priors(
        dist_fc, panel, land_prior, hist_key="shares_hist"
    )
    wk_unc = district_wk_unc_pp(dist_fc)
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    live = parse_laiv_live()
    external = load_external("mv", external_path or EXTERNAL_JSON)
    import numpy as np

    rng = np.random.default_rng(20260920)
    step = build_step(
        panel,
        prior,
        live,
        land_prior,
        rng,
        bsw_direkt=bsw_direkt,
        erst_prior=erst_prior,
        prior_unc=prior_unc,
        wk_unc=wk_unc,
        state_draws=state_draws,
        external=external,
    )
    prev = None
    if prev_path and prev_path.exists():
        try:
            prev = json.loads(prev_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prev = None
    steps = merge_history(prev, step)
    payload = {
        "election": "LTW2026",
        "state": "mv",
        "state_label": "Mecklenburg-Vorpommern",
        "last_election": {
            "year": 2021,
            "label": "LTW 2021",
            "turnout": LAST_OFFICE_TURNOUT,
            "parliament_size": 79,
        },
        "baseline": "π₀ = Landesprognose; L1 = LTW 2021"
        + (" + BTW 2025" if alt else "")
        + "; Live = LAIV CSV",
        "parties": list(PARTIES),
        "party_labels": PARTY_LABELS,
        "n_precincts": int(step["n_total"] or EXPECTED_PRECINCTS),
        "n_wkr": len(panel),
        "match": {
            "n_truth": len(panel),
            "n_l1": len(panel),
            "n_matched": len(alt) if alt else len(panel),
            "match_rate": round((len(alt) / len(panel)) if alt else 1.0, 4),
        },
        "generated_at": github_now(),
        "prior_uncertainty_pp": prior_unc,
        "model": {
            "description": (
                "Mecklenburg-Vorpommern LTW 2026 Live-Nowcast. Lokale Priors: "
                "LTW 2021 Wahlkreise (BTW 2025, falls vorhanden), ausgerichtet "
                "auf die zweitstimme.org-Landesprognose. Live: LAIV CSV "
                "(Wahlkreis / Gemeinde / Wahlbezirk). Prognose/Hochrechnung "
                "aus wahlabend_external.json ersetzt π₀ und Szenarien."
            )
        },
        "call_threshold": 0.90,
        "hard_call_threshold": 0.999,
        "geo_units": {
            "land": [{"id": "MV", "label": "Mecklenburg-Vorpommern"}],
            "bezirk": [],
            "wkr": [
                {"id": wid, "label": f"{wid} {panel[wid]['name']}", "bezirk": None}
                for wid in sorted(panel, key=lambda x: int(x) if x.isdigit() else 99)
            ],
        },
        "scenarios": {
            "live": {
                "label": "LAIV Live-CSV",
                "steps": steps,
                "wkr_calls": {},
                "summary": {},
            }
        },
        "scenario": "live",
        "features": {"bezirkslisten": False, "listen_einzug": True},
        "listen_mode": "landes",
        "listen_roster_2026": load_listen_roster(
            REPO / "mecklenburg-vorpommern" / "candidates" / "listenkandidaten_2026.csv"
        ),
        "listen_roster_note": (
            "Landeslisten 2026 (LAIV Bewerberverzeichnis). Keine Grundmandatsklausel."
        ),
        "direkt_candidates_2026": load_direkt_roster(
            REPO / "mecklenburg-vorpommern" / "candidates" / "direktkandidaten_2026.csv"
        ),
        "live": live_meta(
            step.get("result_kind") or "empty",
            KIND_LABEL.get(step.get("result_kind") or "empty", "LAIV"),
            step,
            LAIV_PAGE,
        ),
        "precincts": live_precincts(panel, live.get("wkr") or {}),
    }
    return payload


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT_DIR / "wahlabend_nowcast_mv_live.json")
    ap.add_argument("--prev", type=Path, default=None)
    ap.add_argument("--external", type=Path, default=None)
    args = ap.parse_args()
    prev = args.prev or args.out
    payload = run(prev, args.external)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    live = payload["live"]
    step = payload["scenarios"]["live"]["steps"][-1]
    print(
        f"wrote {args.out}  kind={live.get('result_kind')}  "
        f"{live.get('ist_wb')}/{live.get('soll_wb')}  "
        f"SPD={step['nowcast'].get('spd')}  "
        f"src={live.get('prediction_source_label')}  "
        f"steps={len(payload['scenarios']['live']['steps'])}"
    )


if __name__ == "__main__":
    main()
