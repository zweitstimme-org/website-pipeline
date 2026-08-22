#!/usr/bin/env python3
"""Landtag / AGH district (Direktmandat) forecast — calibrated federal-style model.

Zweit: proportional swing from last election to statewide posterior draws
(`forecast_state_*_draws.json`; fallback: independent normals from the 5/6 interval).
Erst: OLS  resp_E ~ resp_Z + res_l1_E + no_cand_l1  (coefs in data/district_model_coefs.json).
When STATE_CONFIG marks candidates_complete (ST), parties without a Direktkandidat
are set to 0 Erststimme and the remainder is renormalized to 100%.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]

PARTIES = ("spd", "afd", "cdu", "linke", "gruene", "fdp", "bsw", "others")
MODELED_PARTIES = ("spd", "afd", "cdu", "linke", "gruene", "fdp")
# Display labels: CSU only in Bayern; elsewhere CDU (never "CDU/CSU" for Landtag/AGH).
CODE_TO_LABEL = {
    "spd": "SPD",
    "afd": "AfD",
    "cdu": "CDU",
    "linke": "LINKE",
    "gruene": "GRÜNE",
    "fdp": "FDP",
    "bsw": "BSW",
    "others": "Sonstige",
}
LABEL_TO_CODE = {v: k for k, v in CODE_TO_LABEL.items()}
LABEL_TO_CODE.update(
    {
        "CDU/CSU": "cdu",
        "CSU": "cdu",
        "GRÜNE": "gruene",
        "GRUENE": "gruene",
        "And": "others",
    }
)


def party_label(code: str, state: str | None = None) -> str:
    """Union party display name for a state (CSU only in BY)."""
    if code == "cdu":
        return "CSU" if str(state or "").upper() == "BY" else "CDU"
    return CODE_TO_LABEL[code]


def party_labels(state: str | None = None) -> dict[str, str]:
    return {p: party_label(p, state) for p in PARTIES}

CI_Z = 1.4
# Fallback only when posterior draws are missing. Live runs use all draws
# from forecast_state_*_draws.json (typically 4000).
NSIM_DEFAULT = 2000
RNG_SEED = 20260730
# state-models draw codes → district PARTIES
DRAW_CODE_TO_PARTY = {
    "cdu": "cdu",
    "spd": "spd",
    "gru": "gruene",
    "gruene": "gruene",
    "fdp": "fdp",
    "lin": "linke",
    "linke": "linke",
    "afd": "afd",
    "bsw": "bsw",
    "oth": "others",
    "others": "others",
}
MODEL_PATH = REPO / "data" / "district_model_coefs.json"
EPS = 1e-6

STATE_CONFIG = {
    "MV": {
        "panel": REPO / "mecklenburg-vorpommern" / "LTWMeckPom" / "ltw21_meckpom_abs.csv",
        "state_forecast": REPO / "output" / "forecast_state_mv.json",
        "out": REPO / "output" / "forecast_districts_mv.json",
        "panel_source": "LTWMeckPom/ltw21_meckpom_abs.csv",
        "l1_label": "2021",
        "candidates": REPO / "mecklenburg-vorpommern" / "candidates" / "direktkandidaten_2026.csv",
    },
    "ST": {
        "panel": REPO / "sachsen-anhalt" / "ltw21_st_abs.csv",
        "state_forecast": REPO / "output" / "forecast_state_st.json",
        "out": REPO / "output" / "forecast_districts_st.json",
        "panel_source": "sachsen-anhalt/ltw21_st_abs.csv (LTW 2021 WKR)",
        "l1_label": "2021",
        "candidates": REPO / "sachsen-anhalt" / "candidates" / "direktkandidaten_2026.csv",
        # Official StaLa Bewerberverzeichnis: missing (party, WK) = no Direktkandidat.
        "candidates_complete": True,
    },
    "BE": {
        "panel": REPO / "berlin" / "agh23_be_abs.csv",
        "state_forecast": REPO / "output" / "forecast_state_be.json",
        "out": REPO / "output" / "forecast_districts_be.json",
        "panel_source": "berlin/agh23_be_abs.csv (AGH 2023 remapped to 2026 WKs)",
        "l1_label": "2023",
        "candidates": REPO / "berlin" / "candidates" / "direktkandidaten_2026.csv",
    },
}


def _pct(num: float, den: float) -> float:
    if den <= 0:
        return 0.0
    return float(num) / float(den)


def load_candidates(
    path: Path | None, *, state: str | None = None
) -> dict[tuple[int, str], dict]:
    out: dict[tuple[int, str], dict] = {}
    if not path or not path.exists():
        return out
    bio_index = {}
    if state:
        try:
            from candidate_bio import attach_bio_fields, load_official_bio, lookup_bio

            bio_index = load_official_bio(state)
        except Exception:
            attach_bio_fields = None  # type: ignore
            lookup_bio = None  # type: ignore
    inc_index: dict = {}
    attach_incumbent_fields = None
    lookup_incumbent = None
    aw_index: dict = {}
    attach_aw_fields = None
    lookup_aw = None
    if state:
        try:
            from incumbents import (
                attach_incumbent_fields,
                load_incumbent_index,
                lookup_incumbent,
            )

            inc_index = load_incumbent_index()
        except Exception:
            attach_incumbent_fields = None  # type: ignore
            lookup_incumbent = None  # type: ignore
        try:
            from aw_candidacies import attach_aw_fields, load_aw_index, lookup_aw

            aw_index = load_aw_index()
        except Exception:
            attach_aw_fields = None  # type: ignore
            lookup_aw = None  # type: ignore
    # First-name gender estimate (same pipeline as candidate_entry_sim).
    predict_gender = None
    person_ov: dict = {}
    first_ov: dict = {}
    normalize_name = None
    try:
        from candidate_gender import (
            load_first_name_overrides,
            load_person_overrides,
            predict_gender,
        )
        from listen_candidates import normalize_name

        person_ov = load_person_overrides()
        first_ov = load_first_name_overrides()
    except Exception:
        predict_gender = None  # type: ignore
        normalize_name = None  # type: ignore
    state_lc = str(state or "").lower()
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                wkr = int(r["wkr"])
            except (KeyError, TypeError, ValueError):
                continue
            code = (r.get("party") or "").strip().lower()
            name = (r.get("name") or "").strip()
            source = (r.get("source") or "").strip()
            if code and name:
                entry: dict = {"name": name}
                if source.startswith("http://") or source.startswith("https://"):
                    entry["source"] = source
                if bio_index and lookup_bio and attach_bio_fields:
                    attach_bio_fields(entry, lookup_bio(bio_index, code, name))
                if inc_index and lookup_incumbent and attach_incumbent_fields:
                    attach_incumbent_fields(
                        entry, lookup_incumbent(inc_index, state, code, name)
                    )
                if aw_index and lookup_aw and attach_aw_fields:
                    attach_aw_fields(
                        entry, lookup_aw(aw_index, state or "", code, name)
                    )
                if predict_gender and normalize_name and state_lc:
                    norm = normalize_name(name) or f"d{wkr}"
                    pid = f"{state_lc}:{code}:person:{norm}"
                    pred = predict_gender(
                        name,
                        pid,
                        person_overrides=person_ov,
                        first_overrides=first_ov,
                    )
                    entry["gender"] = pred["gender"]
                    entry["gender_confidence"] = pred["confidence"]
                out[(wkr, code)] = entry
    return out


def load_panel(path: Path) -> list[dict]:
    rows = []
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            wkr = int(r["wahlkreis"])
            ge = float(r["gültige_stimmen_erst"] if "gültige_stimmen_erst" in r else r["gültige_erststimmen"])
            gz = float(r["gültige_stimmen_zweit"] if "gültige_stimmen_zweit" in r else r["gültige_zweitstimmen"])
            e = {}
            z = {}
            for p in PARTIES:
                e_key = f"{p}_erst"
                z_key = f"{p}_zweit"
                if e_key not in r or p == "bsw" and (r.get(e_key) in (None, "")):
                    e[p] = 0.0
                else:
                    e[p] = _pct(float(r[e_key] or 0), ge)
                if z_key not in r or p == "bsw" and (r.get(z_key) in (None, "")):
                    z[p] = 0.0
                else:
                    z[p] = _pct(float(r[z_key] or 0), gz)
            e_sum = sum(e.values()) or 1.0
            z_sum = sum(z.values()) or 1.0
            e = {k: v / e_sum for k, v in e.items()}
            z = {k: v / z_sum for k, v in z.items()}
            rows.append(
                {
                    "wkr": wkr,
                    "wkr_name": r["wahlkreisname"],
                    "valid_l1": int(ge),
                    "zs_valid_l1": int(gz),
                    "erst_l1": e,
                    "zweit_l1": z,
                }
            )
    rows.sort(key=lambda x: x["wkr"])
    return rows


def statewide_from_districts(districts: list[dict], key: str) -> dict[str, float]:
    weight_key = "valid_l1" if key == "erst_l1" else "zs_valid_l1"
    totals = {p: 0.0 for p in PARTIES}
    wsum = 0.0
    for d in districts:
        w = float(d[weight_key])
        wsum += w
        for p in PARTIES:
            totals[p] += d[key][p] * w
    if wsum <= 0:
        return {p: 1.0 / len(PARTIES) for p in PARTIES}
    return {p: totals[p] / wsum for p in PARTIES}


def load_state_forecast(path: Path) -> tuple[dict, dict, dict, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    fit, low, high = {}, {}, {}
    for row in payload.get("parties") or []:
        label = row.get("party")
        code = LABEL_TO_CODE.get(label)
        if not code:
            continue
        fit[code] = float(row["fit"]) / 100.0
        low[code] = float(row["low"]) / 100.0
        high[code] = float(row["high"]) / 100.0
    for p in PARTIES:
        fit.setdefault(p, 0.0)
        low.setdefault(p, max(0.0, fit[p] - 0.03))
        high.setdefault(p, min(1.0, fit[p] + 0.03))
    s = sum(fit.values()) or 1.0
    fit = {p: fit[p] / s for p in PARTIES}
    return fit, low, high, payload.get("metadata") or {}


def load_erst_model(path: Path = MODEL_PATH) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Run build_district_train_panel.py and estimate_district_model.py first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def draw_state_shares(
    fit: dict[str, float],
    low: dict[str, float],
    high: dict[str, float],
    nsim: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Independent-normal fallback from the published 5/6 interval.

    Prefer ``load_statewide_share_draws`` (posterior) whenever the draws
    file exists — independent margins miss the joint posterior.
    """
    means = np.array([fit[p] for p in PARTIES], dtype=float)
    sds = []
    for p in PARTIES:
        half = max(high[p] - fit[p], fit[p] - low[p], 0.005)
        sds.append(half / CI_Z)
    sds = np.array(sds, dtype=float)
    draws = rng.normal(loc=means, scale=sds, size=(nsim, len(PARTIES)))
    draws = np.clip(draws, 0.0, None)
    row_sums = draws.sum(axis=1, keepdims=True)
    row_sums = np.where(row_sums <= 0, 1.0, row_sums)
    return draws / row_sums


def state_forecast_draws_path(forecast_path: Path) -> Path:
    return forecast_path.with_name(forecast_path.stem + "_draws.json")


def _draw_key_to_party(key: str) -> str | None:
    k = str(key).strip()
    if not k or k == "draw":
        return None
    low = k.lower()
    if low in PARTIES:
        return low
    if low in DRAW_CODE_TO_PARTY:
        return DRAW_CODE_TO_PARTY[low]
    return LABEL_TO_CODE.get(k)


def load_state_posterior_draws(path: Path) -> np.ndarray | None:
    """(n_draws, n_parties) vote shares in PARTIES order, or None if missing."""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    raw = payload.get("draws")
    if not isinstance(raw, list):
        inner = payload.get("data")
        raw = inner.get("draws") if isinstance(inner, dict) else None
    if not isinstance(raw, list) or not raw:
        return None

    mat = np.zeros((len(raw), len(PARTIES)), dtype=float)
    idx = {p: i for i, p in enumerate(PARTIES)}
    i_oth = idx["others"]
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            continue
        for key, val in row.items():
            code = _draw_key_to_party(key)
            if code is None:
                continue
            try:
                v = float(val or 0.0)
            except (TypeError, ValueError):
                continue
            if not np.isfinite(v):
                continue
            slot = idx.get(code, i_oth)
            mat[i, slot] += v
    mat = np.clip(mat, 0.0, None)
    if float(mat.max()) > 1.5:
        mat = mat / 100.0
    row_sums = mat.sum(axis=1, keepdims=True)
    if not np.any(row_sums > 0):
        return None
    row_sums = np.where(row_sums <= 0, 1.0, row_sums)
    return mat / row_sums


def load_statewide_share_draws(
    forecast_path: Path,
    nsim: int | None,
    rng: np.random.Generator,
    fit: dict[str, float],
    low: dict[str, float],
    high: dict[str, float],
) -> tuple[np.ndarray, str]:
    """Statewide share matrix: posterior draws, else summary-interval fallback.

    Returns ``(draws, source)`` with ``source`` in ``{"posterior", "summary_normal"}``.
    Does not consume ``rng`` when posterior draws are used (keeps Erst-model
    coefficient draws aligned across district / entry / parliament sims).
    """
    draws_path = state_forecast_draws_path(forecast_path)
    post = load_state_posterior_draws(draws_path)
    if post is not None and post.shape[0] > 0:
        if nsim is not None and int(nsim) < post.shape[0]:
            return post[: int(nsim)], "posterior"
        return post, "posterior"
    n = int(nsim) if nsim is not None else NSIM_DEFAULT
    print(
        f"  note: no posterior draws at {draws_path.name}; "
        f"sampling {n} from summary 5/6 interval",
        flush=True,
    )
    return draw_state_shares(fit, low, high, n, rng), "summary_normal"


def proportional_swing(
    district_l1: np.ndarray, state_l1: np.ndarray, state_new: np.ndarray
) -> np.ndarray:
    """Federal-style: district_Z *= (1 + (state_new - state_l1) / state_l1)."""
    out = np.zeros_like(district_l1)
    for i in range(len(state_l1)):
        if state_l1[i] > EPS:
            prop = (state_new[i] - state_l1[i]) / state_l1[i]
            out[i] = district_l1[i] * (1.0 + prop)
        else:
            # new / near-zero lag: seed from statewide level
            out[i] = state_new[i]
    out = np.clip(out, 0.0, None)
    s = out.sum()
    if s <= 0:
        out = np.clip(state_new, 0.0, None)
        s = out.sum() or 1.0
    return out / s


def predict_erst(
    z_new: np.ndarray,
    e_l1: np.ndarray,
    beta: np.ndarray,
    sigma: float,
    rng: np.random.Generator,
    party_index: dict[str, int],
) -> np.ndarray:
    """Apply OLS to modeled parties; residual mass → bsw/others by L1 structure."""
    e = np.zeros(len(PARTIES), dtype=float)
    modeled_sum = 0.0
    for p in MODELED_PARTIES:
        i = party_index[p]
        no_cand = 1.0 if e_l1[i] <= EPS else 0.0
        mu = beta[0] + beta[1] * z_new[i] + beta[2] * e_l1[i] + beta[3] * no_cand
        if sigma > 0:
            mu = mu + rng.normal(0.0, sigma)
        e[i] = max(0.0, float(mu))
        modeled_sum += e[i]

    # Cap modeled block; distribute remainder to bsw/others
    if modeled_sum > 1.0:
        e = e / modeled_sum
        modeled_sum = 1.0
    rem = max(0.0, 1.0 - modeled_sum)
    i_bsw = party_index["bsw"]
    i_oth = party_index["others"]
    # Prefer current statewide residual structure via z_new for new parties
    z_res = z_new[i_bsw] + z_new[i_oth]
    if z_res > EPS:
        e[i_bsw] = rem * (z_new[i_bsw] / z_res)
        e[i_oth] = rem * (z_new[i_oth] / z_res)
    else:
        e[i_oth] = rem
    s = e.sum()
    return e / s if s > 0 else z_new.copy()


def fielding_mask(
    wkr: int,
    candidates: dict[tuple[int, str], dict],
    *,
    complete: bool,
) -> np.ndarray:
    """True = party can receive Erststimme in this WK.

    When candidate lists are complete, only named Direktkandidat:innen field;
    ``others`` always remains as residual. Incomplete lists → everyone fields.
    """
    mask = np.ones(len(PARTIES), dtype=bool)
    if not complete:
        return mask
    for i, code in enumerate(PARTIES):
        if code == "others":
            continue
        mask[i] = (wkr, code) in candidates
    return mask


def apply_fielding(shares: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Zero non-fielding parties and renormalize to 100%."""
    out = np.where(mask, shares, 0.0)
    out = np.clip(out, 0.0, None)
    s = float(out.sum())
    if s <= EPS:
        # Degenerate: keep residual on others if present, else uniform over fielding.
        out = np.zeros_like(shares)
        i_oth = PARTIES.index("others")
        if mask[i_oth]:
            out[i_oth] = 1.0
        else:
            n = int(mask.sum()) or 1
            out[mask] = 1.0 / n
        return out
    return out / s


def run_forecast(state: str, nsim: int | None = None, seed: int = RNG_SEED) -> dict:
    state = state.upper()
    cfg = STATE_CONFIG[state]
    if not cfg["panel"].exists():
        raise FileNotFoundError(f"Missing panel for {state}: {cfg['panel']}")
    if not cfg["state_forecast"].exists():
        raise FileNotFoundError(f"Missing statewide forecast for {state}: {cfg['state_forecast']}")

    model = load_erst_model()
    beta_hat = np.array(model["coef"], dtype=float)
    vcov = np.array(model["vcov"], dtype=float)
    sigma = float(model["sigma"])

    districts = load_panel(cfg["panel"])
    candidates = load_candidates(cfg.get("candidates"), state=state)
    candidates_complete = bool(cfg.get("candidates_complete"))
    state_l1 = statewide_from_districts(districts, "zweit_l1")
    fit, low, high, state_meta = load_state_forecast(cfg["state_forecast"])
    rng = np.random.default_rng(seed)
    state_draws, draws_source = load_statewide_share_draws(
        cfg["state_forecast"], nsim, rng, fit, low, high
    )
    nsim = int(state_draws.shape[0])
    # One coefficient draw per statewide simulation (federal-style uncertainty).
    coef_draws = rng.multivariate_normal(beta_hat, vcov, size=nsim)

    state_l1_vec = np.array([state_l1[p] for p in PARTIES])
    party_index = {p: i for i, p in enumerate(PARTIES)}
    n_d = len(districts)
    n_p = len(PARTIES)

    erst_mean = np.zeros((n_d, n_p))
    erst_sq = np.zeros((n_d, n_p))
    zs_mean = np.zeros((n_d, n_p))
    win_counts = np.zeros((n_d, n_p), dtype=int)

    for di, d in enumerate(districts):
        e_l1 = np.array([d["erst_l1"][p] for p in PARTIES])
        z_l1 = np.array([d["zweit_l1"][p] for p in PARTIES])
        mask = fielding_mask(
            d["wkr"], candidates, complete=candidates_complete
        )
        e_acc = np.zeros(n_p)
        e_acc2 = np.zeros(n_p)
        z_acc = np.zeros(n_p)
        for s in range(nsim):
            z_new = proportional_swing(z_l1, state_l1_vec, state_draws[s])
            e_new = predict_erst(z_new, e_l1, coef_draws[s], sigma, rng, party_index)
            e_new = apply_fielding(e_new, mask)
            e_acc += e_new
            e_acc2 += e_new * e_new
            z_acc += z_new
            win_counts[di, int(np.argmax(e_new))] += 1
        erst_mean[di] = e_acc / nsim
        erst_sq[di] = e_acc2 / nsim
        zs_mean[di] = z_acc / nsim

    erst_sd = np.sqrt(np.clip(erst_sq - erst_mean**2, 0.0, None))
    z95 = 1.96

    labels = party_labels(state)
    items = []
    for di, d in enumerate(districts):
        probs = win_counts[di] / float(nsim)
        winner_idx = int(np.argmax(probs))
        mask = fielding_mask(
            d["wkr"], candidates, complete=candidates_complete
        )
        for pi, code in enumerate(PARTIES):
            # Complete lists: omit parties that do not field a Direktkandidat.
            if candidates_complete and code != "others" and not mask[pi]:
                continue
            value = float(erst_mean[di, pi] * 100.0)
            sd = float(erst_sd[di, pi] * 100.0)
            cand = candidates.get((d["wkr"], code)) or {}
            item = {
                "wkr": d["wkr"],
                "wkr_name": d["wkr_name"],
                "land": state,
                "party": code,
                "partei": labels[code],
                "name": cand.get("name"),
                "winner": bool(pi == winner_idx),
                "probability": int(round(probs[pi] * 100.0)),
                "value": round(value, 1),
                "low": round(max(0.0, value - z95 * sd), 1),
                "high": round(min(100.0, value + z95 * sd), 1),
                "value_l1": round(float(d["erst_l1"][code] * 100.0), 1),
                "zs_value": round(float(zs_mean[di, pi] * 100.0), 1),
                "zs_value_l1": round(float(d["zweit_l1"][code] * 100.0), 1),
                "valid_l1": d["valid_l1"],
                "zs_valid_l1": d["zs_valid_l1"],
            }
            if cand.get("source"):
                item["name_source"] = cand["source"]
            for bio_key in ("birth_year", "birth_place", "residence", "profession"):
                if cand.get(bio_key) not in (None, ""):
                    item[bio_key] = cand[bio_key]
            if cand.get("gender") in ("m", "f", "x", "u"):
                item["gender"] = cand["gender"]
                if cand.get("gender_confidence"):
                    item["gender_confidence"] = cand["gender_confidence"]
            if cand.get("is_incumbent"):
                item["is_incumbent"] = True
                for ik in (
                    "incumbent_chamber",
                    "incumbent_url",
                    "incumbent_mandate",
                    "incumbent_match",
                ):
                    if cand.get(ik) not in (None, ""):
                        item[ik] = cand[ik]
            if cand.get("aw_url"):
                item["aw_url"] = cand["aw_url"]
            items.append(item)

    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S")
    model_note = (
        "district_calibrated_v1 (prop. Zweit swing + OLS Erst on "
        "projected Zweit: resp_E ~ Z_hat + res_l1_E + no_cand_l1"
    )
    if candidates_complete:
        model_note += "; fielding from complete candidate list → 0 + renorm)"
    else:
        model_note += "; no candidate covariates)"
    meta = {
        "state_code": state,
        "election_date": state_meta.get("election_date"),
        "model": model_note,
        "model_coefs": str(MODEL_PATH.relative_to(REPO)),
        "model_formula": model.get("formula"),
        "model_n": model.get("n"),
        "model_loo_mae": model.get("loo_mae"),
        "nsim": nsim,
        "seed": seed,
        "last_update": now,
        "statewide_source": cfg["state_forecast"].name,
        "statewide_draws": draws_source,
        "statewide_draws_file": state_forecast_draws_path(cfg["state_forecast"]).name,
        "panel_source": cfg["panel_source"],
        "l1_label": cfg["l1_label"],
        "last_poll_date": state_meta.get("last_poll_date"),
        "statewide_last_poll_date": state_meta.get("last_poll_date"),
        "parties": list(labels.values()),
        "candidates_complete": candidates_complete,
        "gender_note_de": (
            "Geschlechteranteile geschätzt anhand der Vornamen "
            "(Wörterbuch + manuelle Korrekturen). Keine amtliche Angabe."
        ),
    }
    if candidates_complete:
        meta["candidates_note_de"] = (
            "Amtliches Bewerberverzeichnis: fehlt eine Partei in einem "
            "Wahlkreis, tritt sie dort nicht mit Erststimme an — Anteil 0, "
            "Rest wird auf die antretenden Parteien normalisiert."
        )
    return {
        "metadata": meta,
        "items": items,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--state",
        choices=sorted(STATE_CONFIG.keys()) + ["all"],
        default="all",
        help="State code or 'all' (BE, ST, MV)",
    )
    ap.add_argument(
        "--nsim",
        type=int,
        default=None,
        help="Cap on statewide draws (default: all posterior draws)",
    )
    ap.add_argument("--seed", type=int, default=RNG_SEED)
    ap.add_argument("--out", type=Path, default=None, help="Override output path (single state only)")
    args = ap.parse_args()

    states = sorted(STATE_CONFIG.keys()) if args.state == "all" else [args.state.upper()]
    if args.out is not None and len(states) != 1:
        raise SystemExit("--out requires a single --state")

    for state in states:
        payload = run_forecast(state, nsim=args.nsim, seed=args.seed)
        out = args.out or STATE_CONFIG[state]["out"]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        winners = {}
        for it in payload["items"]:
            if it["winner"]:
                winners[it["partei"]] = winners.get(it["partei"], 0) + 1
        print(
            f"Wrote {out} ({len(payload['items'])} rows, "
            f"nsim={payload['metadata']['nsim']}, "
            f"draws={payload['metadata'].get('statewide_draws')})"
        )
        print(f"  {state} predicted Direktmandate:", dict(sorted(winners.items(), key=lambda x: -x[1])))


if __name__ == "__main__":
    main()
