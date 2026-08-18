#!/usr/bin/env python3
"""Simulate Landtag / AGH size from statewide + district swing forecasts.

MV: Hare/Niemeyer, Ausgleich capped at 2× Überhang (+1 if even).
ST: Hare/Niemeyer, iterative +2× remaining overhang (as in LWG LSA).
BE: Hare/Niemeyer, Berlin-style size = round(max_directs / vote_share).

Writes output/forecast_parliament_size.json for the district preview UI.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from district_forecast import (
    PARTIES,
    RNG_SEED,
    STATE_CONFIG,
    draw_state_shares,
    load_erst_model,
    load_panel,
    load_state_forecast,
    party_labels,
    predict_erst,
    proportional_swing,
    statewide_from_districts,
)

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "output" / "forecast_parliament_size.json"

STATE_RULES = {
    "MV": {
        "base": 71,
        "label": "Mecklenburg-Vorpommern",
        "chamber": "Landtag",
        "method": "hare_cap2x",
        "note_de": (
            "Mindestens 71 Sitze (Hare/Niemeyer). Überhang bleibt; Ausgleich "
            "höchstens doppelt so viele Sitze wie Überhangmandate. Bei gerader "
            "Gesamtzahl +1 Sitz."
        ),
    },
    "ST": {
        "base": 83,
        "label": "Sachsen-Anhalt",
        "chamber": "Landtag",
        "method": "hare_double_iter",
        "note_de": (
            "Mindestens 83 Sitze (Hare/Niemeyer). Bei Überhang wird die Sitzzahl "
            "wiederholt um das Doppelte der verbleibenden Überhangmandate erhöht, "
            "bis der Proporz (nahezu) hergestellt ist."
        ),
    },
    "BE": {
        "base": 130,
        "label": "Berlin",
        "chamber": "Abgeordnetenhaus",
        "method": "hare_berlin_formula",
        "note_de": (
            "Mindestens 130 Sitze (Hare/Niemeyer). Überhang wird in der Regel "
            "vollständig ausgeglichen (Formel über Direktmandate / Stimmenanteil). "
            "Grundmandatsklausel: ein Direktmandat reicht für den Einzug."
        ),
    },
}


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


def _above_hurdle(
    vote_shares: dict[str, float],
    directs: dict[str, int],
    *,
    grundmandat: bool,
) -> dict[str, float]:
    above: dict[str, float] = {}
    for p, s in vote_shares.items():
        if p == "Sonstige":
            continue
        if s >= 0.05 or (grundmandat and directs.get(p, 0) >= 1):
            above[p] = s
    return above


def allocate_mv(votes: dict[str, float], directs: dict[str, int], base: int = 71) -> dict:
    above = _above_hurdle(votes, directs, grundmandat=False)
    if not above:
        return {"size": base, "seats": {}, "total_oh": 0, "incomplete": False, "adv": 0}
    below_d = sum(d for p, d in directs.items() if p not in above)
    dir_a = {p: int(directs.get(p, 0)) for p in above}
    prop = hare_niemeyer(above, base - below_d)
    oh = {p: max(0, dir_a[p] - prop[p]) for p in above}
    total_oh = sum(oh.values())
    if total_oh == 0:
        seats = {p: max(prop[p], dir_a[p]) for p in above}
        return {
            "size": sum(seats.values()) + below_d,
            "seats": seats,
            "total_oh": 0,
            "incomplete": False,
            "adv": 0,
            "oh_party": None,
        }

    max_ausgleich = 2 * total_oh
    needed = None
    for s in range(base, base + total_oh + max_ausgleich + 40):
        alloc = hare_niemeyer(above, s)
        if all(alloc[p] >= dir_a[p] for p in above):
            needed = s
            break
    if needed is None:
        s_cap = base + 3 * total_oh
        if s_cap % 2 == 0:
            s_cap += 1
        alloc = hare_niemeyer(above, s_cap)
        seats = {p: max(alloc[p], dir_a[p]) for p in above}
        adv = sum(max(0, seats[p] - alloc[p]) for p in above)
        return {
            "size": sum(seats.values()) + below_d,
            "seats": seats,
            "total_oh": total_oh,
            "incomplete": adv > 0,
            "adv": adv,
            "oh_party": max(oh, key=oh.get),
        }

    s = needed + (1 if needed % 2 == 0 else 0)
    ausgl = needed - base - total_oh
    if ausgl > max_ausgleich:
        s = base + 3 * total_oh
        if s % 2 == 0:
            s += 1
    alloc = hare_niemeyer(above, s)
    seats = {p: max(alloc[p], dir_a[p]) for p in above}
    adv = sum(max(0, seats[p] - alloc[p]) for p in above)
    return {
        "size": sum(seats.values()) + below_d,
        "seats": seats,
        "total_oh": total_oh,
        "incomplete": adv > 0,
        "adv": adv,
        "oh_party": max(oh, key=oh.get) if total_oh else None,
    }


def allocate_st(votes: dict[str, float], directs: dict[str, int], base: int = 83) -> dict:
    above = _above_hurdle(votes, directs, grundmandat=False)
    if not above:
        return {"size": base, "seats": {}, "total_oh": 0, "incomplete": False, "adv": 0}
    below_d = sum(d for p, d in directs.items() if p not in above)
    dir_a = {p: int(directs.get(p, 0)) for p in above}
    s = base - below_d
    prop0 = hare_niemeyer(above, s)
    oh0 = sum(max(0, dir_a[p] - prop0[p]) for p in above)
    if oh0 == 0:
        seats = {p: max(prop0[p], dir_a[p]) for p in above}
        return {
            "size": sum(seats.values()) + below_d,
            "seats": seats,
            "total_oh": 0,
            "incomplete": False,
            "adv": 0,
            "oh_party": None,
        }

    # Iterative: raise by 2× remaining overhang (wahlrecht.de / LWG LSA).
    round_i = 0
    while True:
        alloc = hare_niemeyer(above, s)
        rem_oh = {p: max(0, dir_a[p] - alloc[p]) for p in above}
        rem = sum(rem_oh.values())
        if rem == 0:
            seats = alloc
            break
        round_i += 1
        # After the 3rd redistribution, further rounds only while remaining
        # overhang > half Fraktionsstärke (≈ 2 seats under current practice).
        if round_i >= 3 and rem <= 2:
            seats = {p: max(alloc[p], dir_a[p]) for p in above}
            adv = sum(max(0, seats[p] - alloc[p]) for p in above)
            return {
                "size": sum(seats.values()) + below_d,
                "seats": seats,
                "total_oh": oh0,
                "incomplete": adv > 0,
                "adv": adv,
                "oh_party": max(rem_oh, key=rem_oh.get),
            }
        s = s + 2 * rem
        if s > 400:
            seats = {p: max(alloc[p], dir_a[p]) for p in above}
            adv = sum(max(0, seats[p] - alloc[p]) for p in above)
            return {
                "size": sum(seats.values()) + below_d,
                "seats": seats,
                "total_oh": oh0,
                "incomplete": True,
                "adv": adv,
                "oh_party": max(rem_oh, key=rem_oh.get),
            }

    oh_party = max(
        ((p, max(0, dir_a[p] - prop0[p])) for p in above),
        key=lambda x: x[1],
    )[0]
    return {
        "size": sum(seats.values()) + below_d,
        "seats": seats,
        "total_oh": oh0,
        "incomplete": False,
        "adv": 0,
        "oh_party": oh_party if oh0 else None,
    }


def allocate_be(votes: dict[str, float], directs: dict[str, int], base: int = 130) -> dict:
    above = _above_hurdle(votes, directs, grundmandat=True)
    if not above:
        return {"size": base, "seats": {}, "total_oh": 0, "incomplete": False, "adv": 0}
    below_d = sum(d for p, d in directs.items() if p not in above)
    dir_a = {p: int(directs.get(p, 0)) for p in above}
    pool = base - below_d
    prop = hare_niemeyer(above, pool)
    oh = {p: max(0, dir_a[p] - prop[p]) for p in above}
    total_oh = sum(oh.values())
    if total_oh == 0:
        seats = {p: max(prop[p], dir_a[p]) for p in above}
        return {
            "size": sum(seats.values()) + below_d,
            "seats": seats,
            "total_oh": 0,
            "incomplete": False,
            "adv": 0,
            "oh_party": None,
        }

    vsum = sum(above.values())
    s_candidates = [base]
    for p, d in dir_a.items():
        if d <= 0 or above[p] <= 0:
            continue
        # Berlin formula: seats_incl_oh / party_votes * all_votes
        s_candidates.append(int(round(d / (above[p] / vsum))))
    s = max(s_candidates)
    # Ensure all directs fit (rounding can undershoot)
    for _ in range(20):
        alloc = hare_niemeyer(above, s)
        if all(alloc[p] >= dir_a[p] for p in above):
            break
        s += 1
    alloc = hare_niemeyer(above, s)
    seats = {p: max(alloc[p], dir_a[p]) for p in above}
    adv = sum(max(0, seats[p] - alloc[p]) for p in above)
    return {
        "size": sum(seats.values()) + below_d,
        "seats": seats,
        "total_oh": total_oh,
        "incomplete": adv > 0,
        "adv": adv,
        "oh_party": max(oh, key=oh.get),
    }


ALLOCATORS = {"MV": allocate_mv, "ST": allocate_st, "BE": allocate_be}


def _bucket_sizes(sizes: np.ndarray, base: int) -> list[dict]:
    """Adaptive odd-ish buckets around the base size."""
    if base <= 80:
        edges = [base, base + 2, base + 8, base + 14, base + 20, base + 26, base + 32, 10_000]
        labels = [
            str(base),
            f"{base+2}–{base+6}",
            f"{base+8}–{base+12}",
            f"{base+14}–{base+18}",
            f"{base+20}–{base+24}",
            f"{base+26}–{base+30}",
            f"{base+32}+",
        ]
    elif base <= 100:
        edges = [base, base + 2, base + 10, base + 18, base + 26, base + 34, base + 42, 10_000]
        labels = [
            str(base),
            f"{base+2}–{base+8}",
            f"{base+10}–{base+16}",
            f"{base+18}–{base+24}",
            f"{base+26}–{base+32}",
            f"{base+34}–{base+40}",
            f"{base+42}+",
        ]
    else:
        edges = [base, base + 2, base + 12, base + 22, base + 32, base + 42, base + 52, 10_000]
        labels = [
            str(base),
            f"{base+2}–{base+10}",
            f"{base+12}–{base+20}",
            f"{base+22}–{base+30}",
            f"{base+32}–{base+40}",
            f"{base+42}–{base+50}",
            f"{base+52}+",
        ]
    out = []
    n = len(sizes)
    for i, label in enumerate(labels):
        lo = edges[i]
        hi = edges[i + 1]
        if i == 0:
            pct = float(np.mean(sizes == lo) * 100)
        elif i == len(labels) - 1:
            pct = float(np.mean(sizes >= lo) * 100)
        else:
            pct = float(np.mean((sizes >= lo) & (sizes < hi)) * 100)
        out.append({"label": label, "pct": round(pct, 1)})
    return out


def simulate_state(state: str, nsim: int, seed: int) -> dict:
    state = state.upper()
    cfg = STATE_CONFIG[state]
    rules = STATE_RULES[state]
    alloc_fn = ALLOCATORS[state]

    districts = load_panel(cfg["panel"])
    state_l1 = statewide_from_districts(districts, "zweit_l1")
    fit, low, high, state_meta = load_state_forecast(cfg["state_forecast"])
    model = load_erst_model()
    beta_hat = np.array(model["coef"], dtype=float)
    vcov = np.array(model["vcov"], dtype=float)
    sigma = float(model["sigma"])
    rng = np.random.default_rng(seed)
    draws = draw_state_shares(fit, low, high, nsim, rng)
    coef_draws = rng.multivariate_normal(beta_hat, vcov, size=nsim)
    state_l1_vec = np.array([state_l1[p] for p in PARTIES])
    party_index = {p: i for i, p in enumerate(PARTIES)}

    sizes = np.zeros(nsim, dtype=int)
    ohs = np.zeros(nsim, dtype=int)
    advs = np.zeros(nsim, dtype=int)
    incomplete = 0
    oh_parties: Counter = Counter()
    adv_by_party: Counter = Counter()
    size_hist: Counter = Counter()
    labels = party_labels(state)
    point_directs = {labels[p]: 0 for p in PARTIES}

    # Point estimate at fit + mean coefs (no residual noise)
    fit_vec = np.array([fit[p] for p in PARTIES])
    for d in districts:
        z_l1 = np.array([d["zweit_l1"][p] for p in PARTIES])
        e_l1 = np.array([d["erst_l1"][p] for p in PARTIES])
        z_new = proportional_swing(z_l1, state_l1_vec, fit_vec)
        e_new = predict_erst(z_new, e_l1, beta_hat, 0.0, rng, party_index)
        point_directs[labels[PARTIES[int(np.argmax(e_new))]]] += 1
    vs_fit = {labels[p]: float(fit[p]) for p in PARTIES}
    point = alloc_fn(vs_fit, point_directs, rules["base"])

    for i in range(nsim):
        draw = draws[i]
        directs = {labels[p]: 0 for p in PARTIES}
        for d in districts:
            z_l1 = np.array([d["zweit_l1"][p] for p in PARTIES])
            e_l1 = np.array([d["erst_l1"][p] for p in PARTIES])
            z_new = proportional_swing(z_l1, state_l1_vec, draw)
            e_new = predict_erst(z_new, e_l1, coef_draws[i], sigma, rng, party_index)
            directs[labels[PARTIES[int(np.argmax(e_new))]]] += 1
        vs = {labels[p]: float(draw[j]) for j, p in enumerate(PARTIES)}
        res = alloc_fn(vs, directs, rules["base"])
        sizes[i] = res["size"]
        ohs[i] = res["total_oh"]
        advs[i] = res["adv"]
        size_hist[res["size"]] += 1
        if res["incomplete"]:
            incomplete += 1
        if res["total_oh"] > 0 and res.get("oh_party"):
            oh_parties[res["oh_party"]] += 1
        if res["adv"] > 0 and res.get("oh_party"):
            adv_by_party[res["oh_party"]] += 1

    # Advantage seat distribution (MV focus; meaningful elsewhere too)
    adv_dist = {
        "0": round(float(np.mean(advs == 0) * 100), 2),
        "1": round(float(np.mean(advs == 1) * 100), 2),
        "2": round(float(np.mean(advs == 2) * 100), 2),
        "3plus": round(float(np.mean(advs >= 3) * 100), 2),
    }

    out = {
        "state_code": state,
        "label": rules["label"],
        "chamber": rules["chamber"],
        "base_seats": rules["base"],
        "method": rules["method"],
        "note_de": rules["note_de"],
        "nsim": nsim,
        "statewide_last_poll_date": state_meta.get("last_poll_date"),
        "p_overhang_pct": round(float(np.mean(ohs > 0) * 100), 1),
        "p_incomplete_pct": round(incomplete / nsim * 100, 2),
        "advantage_seats_pct": adv_dist,
        "p_advantage_ge1_pct": round(float(np.mean(advs >= 1) * 100), 2),
        "p_advantage_ge2_pct": round(float(np.mean(advs >= 2) * 100), 2),
        "oh_parties": dict(oh_parties),
        "advantage_parties": dict(adv_by_party),
        "size_mean": round(float(sizes.mean()), 1),
        "size_median": int(np.median(sizes)),
        "size_p10": int(np.percentile(sizes, 10)),
        "size_p90": int(np.percentile(sizes, 90)),
        "size_p95": int(np.percentile(sizes, 95)),
        "size_max": int(sizes.max()),
        "p_base_pct": round(float(np.mean(sizes == rules["base"]) * 100), 1),
        "buckets": _bucket_sizes(sizes, rules["base"]),
        "point": {
            "size": point["size"],
            "seats": point["seats"],
            "directs": {k: v for k, v in point_directs.items() if v},
            "total_oh": point["total_oh"],
            "incomplete": point["incomplete"],
            "adv": point["adv"],
        },
    }
    out["majority_impact"] = _majority_impact(
        state,
        draws,
        districts,
        state_l1_vec,
        rules["base"],
        alloc_fn,
        nsim,
        coef_draws,
        sigma,
        rng,
        party_index,
    )
    return out


def _seat_maj(seats: dict[str, int], parties: list[str]) -> bool:
    if not seats or any(p not in seats for p in parties):
        return False
    return sum(seats[p] for p in parties) / sum(seats.values()) > 0.5


def _vote_maj(vs: dict[str, float], parties: list[str]) -> bool:
    above = {p: s for p, s in vs.items() if s >= 0.05 and p != "Sonstige"}
    if any(p not in above for p in parties):
        return False
    return sum(above[p] for p in parties) / sum(above.values()) > 0.5


def _allocate_mv_full(
    votes: dict[str, float], directs: dict[str, int], base: int = 71
) -> dict[str, int]:
    """MV allocation ignoring the 2× Ausgleich cap."""
    above = {p: s for p, s in votes.items() if s >= 0.05 and p != "Sonstige"}
    if not above:
        return {}
    below_d = sum(d for p, d in directs.items() if p not in above)
    dir_a = {p: int(directs.get(p, 0)) for p in above}
    prop = hare_niemeyer(above, base - below_d)
    oh = sum(max(0, dir_a[p] - prop[p]) for p in above)
    if oh == 0:
        return {p: max(prop[p], dir_a[p]) for p in above}
    needed = None
    for s in range(base, base + 250):
        alloc = hare_niemeyer(above, s)
        if all(alloc[p] >= dir_a[p] for p in above):
            needed = s
            break
    if needed is None:
        needed = base + 249
    if needed % 2 == 0:
        needed += 1
    return hare_niemeyer(above, needed)


def _majority_impact(
    state: str,
    draws: np.ndarray,
    districts: list[dict],
    state_l1_vec: np.ndarray,
    base: int,
    alloc_fn,
    nsim: int,
    coef_draws: np.ndarray,
    sigma: float,
    rng: np.random.Generator,
    party_index: dict[str, int],
) -> dict:
    """Quantify vote vs seat majority; for MV also capped vs full Ausgleich."""
    if state == "BE":
        return {
            "complete_compensation": True,
            "note_de": (
                "In Berlin wird Überhang in unseren Simulationen vollständig "
                "ausgeglichen (0 % unvollständig); Sitzmehrheiten ≈ Zweitstimmenmehrheiten."
            ),
        }
    if state == "ST":
        return {
            "complete_compensation": True,
            "note_de": (
                "Ausgleich in ST stellt den Proporz in der Regel (nahezu) wieder her; "
                "Szenarien über Zweitstimmenanteile bleiben eine gute Näherung."
            ),
        }

    # MV: compare vote / full Ausgleich / capped
    scenarios = {
        "abs_maj_afd": ["AfD"],
        "coal_spd_lin": ["SPD", "LINKE"],
        "coal_spd_gru_lin": ["SPD", "GRÜNE", "LINKE"],
    }
    hits = {k: {"vote": 0, "full": 0, "capped": 0} for k in scenarios}
    incomplete = 0
    labels = party_labels(state)
    for i in range(nsim):
        draw = draws[i]
        directs = {labels[p]: 0 for p in PARTIES}
        for d in districts:
            z_l1 = np.array([d["zweit_l1"][p] for p in PARTIES])
            e_l1 = np.array([d["erst_l1"][p] for p in PARTIES])
            z_new = proportional_swing(z_l1, state_l1_vec, draw)
            e_new = predict_erst(z_new, e_l1, coef_draws[i], sigma, rng, party_index)
            directs[labels[PARTIES[int(np.argmax(e_new))]]] += 1
        vs = {labels[p]: float(draw[j]) for j, p in enumerate(PARTIES)}
        capped = alloc_fn(vs, directs, base)
        full_seats = _allocate_mv_full(vs, directs, base)
        if capped.get("incomplete"):
            incomplete += 1
        for sid, parties in scenarios.items():
            if _vote_maj(vs, parties):
                hits[sid]["vote"] += 1
            if _seat_maj(full_seats, parties):
                hits[sid]["full"] += 1
            if _seat_maj(capped.get("seats") or {}, parties):
                hits[sid]["capped"] += 1

    return {
        "complete_compensation": False,
        "nsim": nsim,
        "p_incomplete_pct": round(incomplete / nsim * 100, 2),
        "note_de": (
            "Vergleich Zweitstimmen-Mehrheit vs. Sitzmehrheit mit vollem Ausgleich "
            "vs. MV-Deckel (Ausgleich ≤ 2× Überhang). Der Deckel verschiebt "
            "Szenario-Wahrscheinlichkeiten um deutlich unter 1 Prozentpunkt; "
            "die Absolute Mehrheit der AfD bleibt praktisch unverändert. "
            "Koalitionsszenarien auf der Website bleiben daher die "
            "Zweitstimmen-Näherung."
        ),
        "scenarios": {
            sid: {
                "vote_pct": round(v["vote"] / nsim * 100, 2),
                "seats_full_ausgleich_pct": round(v["full"] / nsim * 100, 2),
                "seats_capped_pct": round(v["capped"] / nsim * 100, 2),
                "cap_minus_full_pp": round((v["capped"] - v["full"]) / nsim * 100, 2),
            }
            for sid, v in hits.items()
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nsim", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=RNG_SEED)
    ap.add_argument("--states", nargs="+", default=["MV", "ST", "BE"])
    args = ap.parse_args()

    wanted = [code.upper() for code in args.states]
    # Merge into existing output so partial runs do not drop other states.
    states: dict = {}
    if OUT.exists() and set(wanted) != {"MV", "ST", "BE"}:
        try:
            prev = json.loads(OUT.read_text(encoding="utf-8"))
            states = dict(prev.get("states") or {})
        except (json.JSONDecodeError, OSError):
            states = {}

    for code in wanted:
        print(f"Simulating {code} …")
        states[code] = simulate_state(code, args.nsim, args.seed)
        s = states[code]
        print(
            f"  size med={s['size_median']} mean={s['size_mean']} "
            f"P(oh)={s['p_overhang_pct']}% P(incomplete)={s['p_incomplete_pct']}% "
            f"P(+≥2 seats)={s['p_advantage_ge2_pct']}%"
        )

    payload = {
        "metadata": {
            "model": "district_swing + state Hare/Niemeyer size sim",
            "nsim": args.nsim,
            "seed": args.seed,
            "last_update": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "caveat_de": (
                "Indikative Größenverteilung aus dem Wahlkreis-Swing-Modell "
                "(ohne Kandidateneffekte). Keine amtliche Sitzzuteilung."
            ),
        },
        "states": states,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUT} (states: {', '.join(sorted(states))})")


if __name__ == "__main__":
    main()
