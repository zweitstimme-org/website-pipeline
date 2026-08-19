#!/usr/bin/env python3
"""Simulate P(entry) for Direkt- and Listenkandidaten (BE / MV / ST).

Reuses statewide posterior draws + district Erst model from parliament_size_sim.
Berlin Bezirkslisten: sub-allocate party seats to Bezirke via Hare/Niemeyer on
swung Bezirk Zweitstimmen (historical WK panel → proportional swing → aggregate).

Writes output/forecast_candidate_entry.json.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from district_forecast import (
    PARTIES,
    RNG_SEED,
    STATE_CONFIG,
    apply_fielding,
    fielding_mask,
    load_candidates,
    load_erst_model,
    load_panel,
    load_state_forecast,
    load_statewide_share_draws,
    party_label,
    party_labels,
    predict_erst,
    proportional_swing,
    statewide_from_districts,
)
from candidate_gender import load_first_name_overrides, load_person_overrides, predict_gender
from listen_candidates import BEZ_NAMES, build_roster, write_listen_csv
from parliament_size_sim import ALLOCATORS, STATE_RULES, hare_niemeyer

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "output" / "forecast_candidate_entry.json"

MODELED = ("spd", "afd", "cdu", "linke", "gruene", "fdp", "bsw")


def _gender_stats(
    cands: list[dict],
    *,
    weight_key: str | None = None,
    min_expected: float | None = None,
) -> dict:
    """Share of named candidates by gender (first-name estimate + overrides).

    If ``weight_key`` is set (e.g. ``p_list`` / ``p_direct``), percentages are
    probability-weighted among binary-labeled names. ``p_*`` are 0–100, so
    expected count is Σp/100. When ``min_expected`` is set and the expected
    count is below that threshold, percentages stay ``None`` (UI hides the row).
    """
    named = [c for c in cands if not c.get("is_placeholder") and c.get("gender")]
    n = len(named)
    empty = {
        "n": 0,
        "n_f": 0,
        "n_m": 0,
        "n_x": 0,
        "n_u": 0,
        "pct_f": None,
        "pct_m": None,
    }
    if n == 0:
        if weight_key:
            empty["weighted"] = True
            empty["weight_key"] = weight_key
            empty["expected"] = 0.0
        return empty
    n_f = sum(1 for c in named if c["gender"] == "f")
    n_m = sum(1 for c in named if c["gender"] == "m")
    n_x = sum(1 for c in named if c["gender"] == "x")
    n_u = sum(1 for c in named if c["gender"] == "u")
    out: dict = {
        "n": n,
        "n_f": n_f,
        "n_m": n_m,
        "n_x": n_x,
        "n_u": n_u,
        "pct_f": None,
        "pct_m": None,
    }
    if weight_key:
        w_f = sum(
            float(c.get(weight_key) or 0) for c in named if c["gender"] == "f"
        )
        w_m = sum(
            float(c.get(weight_key) or 0) for c in named if c["gender"] == "m"
        )
        denom = w_f + w_m
        expected = round(denom / 100.0, 1)
        out["weighted"] = True
        out["weight_key"] = weight_key
        out["expected"] = expected
        if denom > 0 and (min_expected is None or expected >= min_expected):
            out["pct_f"] = round(100.0 * w_f / denom, 1)
            out["pct_m"] = round(100.0 * w_m / denom, 1)
        else:
            out["no_seats_expected"] = True
        return out
    denom = n_f + n_m
    if denom:
        out["pct_f"] = round(100.0 * n_f / denom, 1)
        out["pct_m"] = round(100.0 * n_m / denom, 1)
    return out


def _gender_breakdown(cands: list[dict]) -> dict:
    """Overall / list / district (+ probability-weighted) gender shares."""
    named = [c for c in cands if not c.get("is_placeholder") and c.get("gender")]
    list_c = [c for c in named if c.get("list_pos") is not None]
    dir_c = [c for c in named if c.get("wkr_direct") is not None]
    return {
        "overall": _gender_stats(named),
        "list": _gender_stats(list_c),
        "district": _gender_stats(dir_c),
        "list_weighted": _gender_stats(
            list_c, weight_key="p_list", min_expected=1.0
        ),
        "district_weighted": _gender_stats(
            dir_c, weight_key="p_direct", min_expected=1.0
        ),
    }


def _fill_landesliste(
    slots: list[dict],
    n_list_seats: int,
    seated_direct: set[str],
) -> set[str]:
    """Return person_ids entering via list (skipping those already on Direkt)."""
    if n_list_seats <= 0:
        return set()
    entered: set[str] = set()
    ordered = sorted(slots, key=lambda r: r["list_pos"])
    for r in ordered:
        if len(entered) >= n_list_seats:
            break
        pid = r["person_id"]
        if pid in seated_direct:
            continue
        entered.add(pid)
    return entered


def _fill_bezirkslisten(
    slots: list[dict],
    party_seats: int,
    directs_by_bez: dict[str, set[str]],
    bez_votes: dict[str, float],
) -> set[str]:
    """Allocate party seats to Bezirke, fill list remainders; cap at S−D."""
    if party_seats <= 0:
        return set()
    # Drop empty-vote bezirke but keep all 12 keys for stability
    votes = {b: max(0.0, float(bez_votes.get(b, 0.0))) for b in BEZ_NAMES}
    if sum(votes.values()) <= 0:
        # equal fallback
        votes = {b: 1.0 for b in BEZ_NAMES}
    allocated = hare_niemeyer(votes, party_seats)
    all_direct = set()
    for s in directs_by_bez.values():
        all_direct |= s
    d_total = len(all_direct)
    budget = max(0, party_seats - d_total)

    slots_by_bez: dict[str, list[dict]] = defaultdict(list)
    for r in slots:
        if r.get("bezirk"):
            slots_by_bez[r["bezirk"]].append(r)
    for b in slots_by_bez:
        slots_by_bez[b].sort(key=lambda r: r["list_pos"])

    # Prefer Bezirke with unused quota (allocated − directs)
    remainders = []
    for b in BEZ_NAMES:
        d = len(directs_by_bez.get(b, set()))
        rem = max(0, allocated.get(b, 0) - d)
        if rem > 0:
            remainders.append((b, rem, votes.get(b, 0.0)))
    # Fill higher vote bezirke first when budget < sum(remainders)
    remainders.sort(key=lambda x: (-x[1], -x[2], x[0]))

    entered: set[str] = set()
    for b, rem, _ in remainders:
        if budget <= 0:
            break
        take = min(rem, budget)
        seated = directs_by_bez.get(b, set())
        n = 0
        for r in slots_by_bez.get(b, []):
            if n >= take:
                break
            pid = r["person_id"]
            if pid in seated or pid in entered:
                continue
            entered.add(pid)
            n += 1
        budget -= n
    return entered


def simulate_state(state: str, nsim: int | None, seed: int) -> dict:
    state = state.upper()
    cfg = STATE_CONFIG[state]
    rules = STATE_RULES[state]
    alloc_fn = ALLOCATORS[state]
    labels = party_labels(state)
    code_of = {labels[p]: p for p in PARTIES}

    write_listen_csv(state)  # refresh placeholders / known parses
    roster = build_roster(state)
    people = roster["people"]
    list_slots = roster["list_slots"]
    direkt_index = roster["direkt_index"]
    list_type = roster["list_type"]
    wkr_to_bez = roster["wkr_to_bez"]

    slots_by_party: dict[str, list[dict]] = defaultdict(list)
    for r in list_slots:
        slots_by_party[r["party"]].append(r)

    districts = load_panel(cfg["panel"])
    candidates = load_candidates(cfg.get("candidates"), state=state)
    candidates_complete = bool(cfg.get("candidates_complete"))
    state_l1 = statewide_from_districts(districts, "zweit_l1")
    fit, low, high, state_meta = load_state_forecast(cfg["state_forecast"])
    model = load_erst_model()
    beta_hat = np.array(model["coef"], dtype=float)
    vcov = np.array(model["vcov"], dtype=float)
    sigma = float(model["sigma"])
    rng = np.random.default_rng(seed)
    draws, draws_source = load_statewide_share_draws(
        cfg["state_forecast"], nsim, rng, fit, low, high
    )
    nsim = int(draws.shape[0])
    coef_draws = rng.multivariate_normal(beta_hat, vcov, size=nsim)
    state_l1_vec = np.array([state_l1[p] for p in PARTIES])
    party_index = {p: i for i, p in enumerate(PARTIES)}

    # Counters per person_id
    n_entry = defaultdict(int)
    n_direct = defaultdict(int)
    n_list = defaultdict(int)

    # District winners: same loop order as district_forecast.run_forecast
    # (district outer, sim inner) so p_direct matches forecast_districts_*.json.
    sim_directs_lbl: list[dict[str, int]] = [
        {labels[p]: 0 for p in PARTIES} for _ in range(nsim)
    ]
    sim_winners: list[dict[str, set[str]]] = [defaultdict(set) for _ in range(nsim)]
    sim_directs_by_bez: list[dict[str, dict[str, set[str]]]] = [
        defaultdict(lambda: defaultdict(set)) for _ in range(nsim)
    ]
    sim_bez_votes: list[dict[str, dict[str, float]]] = [
        defaultdict(lambda: defaultdict(float)) for _ in range(nsim)
    ]

    for d in districts:
        wkr = int(d["wkr"])
        z_l1 = np.array([d["zweit_l1"][p] for p in PARTIES])
        e_l1 = np.array([d["erst_l1"][p] for p in PARTIES])
        mask = fielding_mask(wkr, candidates, complete=candidates_complete)
        for i in range(nsim):
            z_new = proportional_swing(z_l1, state_l1_vec, draws[i])
            e_new = predict_erst(z_new, e_l1, coef_draws[i], sigma, rng, party_index)
            e_new = apply_fielding(e_new, mask)
            win_i = int(np.argmax(e_new))
            win_code = PARTIES[win_i]
            win_lbl = labels[win_code]
            sim_directs_lbl[i][win_lbl] += 1
            pid = direkt_index.get((win_code, wkr))
            if pid:
                sim_winners[i][win_code].add(pid)
                if state == "BE":
                    bez = wkr_to_bez.get(wkr)
                    if bez:
                        sim_directs_by_bez[i][win_code][bez].add(pid)

            if state == "BE":
                bez = wkr_to_bez.get(wkr)
                if bez:
                    weight = float(d.get("zs_valid_l1") or d.get("valid_l1") or 1.0)
                    for j, p in enumerate(PARTIES):
                        if p == "others":
                            continue
                        sim_bez_votes[i][p][bez] += float(z_new[j]) * weight

    for i in range(nsim):
        draw = draws[i]
        directs_lbl = sim_directs_lbl[i]
        winners = sim_winners[i]
        directs_by_bez = sim_directs_by_bez[i]
        bez_votes = sim_bez_votes[i]

        vs = {labels[p]: float(draw[j]) for j, p in enumerate(PARTIES)}
        res = alloc_fn(vs, directs_lbl, rules["base"])
        seats_lbl = res["seats"]

        entered_direct_all: set[str] = set()
        entered_list_all: set[str] = set()

        # Direkt winners keep their seat even if the party misses the 5% list
        # hurdle (MV/ST: no Grundmandatsklausel; BE: one Direkt clears the
        # hurdle via Grundmandat). Below-hurdle parties get no list seats;
        # allocators shrink the proportional pool by those Direktmandate.
        for code, seated_d in winners.items():
            if code in MODELED:
                entered_direct_all |= seated_d

        for lbl, n_seats in seats_lbl.items():
            code = code_of.get(lbl)
            if not code or code not in MODELED:
                continue
            seated_d = winners.get(code, set())
            n_list_seats = max(0, int(n_seats) - len(seated_d))
            lt = list_type.get(code, "landes")
            if lt == "bezirk" and state == "BE":
                got = _fill_bezirkslisten(
                    slots_by_party.get(code, []),
                    int(n_seats),
                    directs_by_bez.get(code, {}),
                    bez_votes.get(code, {}),
                )
            else:
                got = _fill_landesliste(
                    slots_by_party.get(code, []),
                    n_list_seats,
                    seated_d,
                )
            entered_list_all |= got

        entered = entered_direct_all | entered_list_all
        for pid in entered:
            n_entry[pid] += 1
        for pid in entered_direct_all:
            n_direct[pid] += 1
        for pid in entered_list_all:
            n_list[pid] += 1

    # Build party → candidate rows (people who are on a list or have a Direkt slot)
    party_people: dict[str, dict[str, dict]] = defaultdict(dict)
    for pid, info in people.items():
        party = info["party"]
        if party not in MODELED:
            continue
        # Skip pure list placeholders beyond a useful depth? Keep all generated slots.
        party_people[party][pid] = info

    # Also ensure every list slot person is included
    for r in list_slots:
        party_people[r["party"]].setdefault(r["person_id"], people[r["person_id"]])

    person_ov = load_person_overrides()
    first_ov = load_first_name_overrides()
    try:
        from incumbents import attach_incumbent_fields, load_incumbent_index, lookup_incumbent

        inc_index = load_incumbent_index()
    except Exception:
        attach_incumbent_fields = None  # type: ignore
        lookup_incumbent = None  # type: ignore
        inc_index = {}
    try:
        from aw_candidacies import attach_aw_fields, load_aw_index, lookup_aw

        aw_index = load_aw_index()
    except Exception:
        attach_aw_fields = None  # type: ignore
        lookup_aw = None  # type: ignore
        aw_index = {}

    parties_out = []
    for party in MODELED:
        lt = list_type.get(party, "landes")
        cands = []
        for pid, info in party_people.get(party, {}).items():
            pe = 100.0 * n_entry[pid] / nsim
            pd = 100.0 * n_direct[pid] / nsim
            pl = 100.0 * n_list[pid] / nsim
            # Integer %; direct/list are mutually exclusive → keep pe = pd + pl.
            pe_i = int(round(pe))
            pd_i = min(pe_i, int(round(pd)))
            pl_i = pe_i - pd_i
            # Drop never-relevant deep placeholders (0% and list_pos > 15 with no direct)
            if (
                info.get("is_placeholder")
                and pe < 0.05
                and not info.get("wkr_direct")
                and (info.get("list_pos") or 99) > 20
            ):
                continue
            if pe < 0.05 and info.get("is_placeholder") and info.get("list_pos") and not info.get(
                "wkr_direct"
            ):
                # keep top of list for transparency even if ~0
                if info["list_pos"] > 12:
                    continue
            bez = info.get("bezirk") or ""
            row = {
                "person_id": pid,
                "name": info["name"],
                "is_placeholder": bool(info.get("is_placeholder")),
                "list_type": info.get("list_type") or lt,
                "bezirk": bez,
                "bezirk_name": BEZ_NAMES.get(bez, "") if bez else "",
                "list_pos": info.get("list_pos"),
                "wkr_direct": info.get("wkr_direct"),
                "source": info.get("source") or "",
                "p_entry": pe_i,
                "p_direct": pd_i,
                "p_list": pl_i,
                **{
                    k: info[k]
                    for k in (
                        "birth_year",
                        "birth_place",
                        "residence",
                        "profession",
                    )
                    if info.get(k) not in (None, "")
                },
            }
            if not row["is_placeholder"]:
                pred = predict_gender(
                    info["name"],
                    pid,
                    person_overrides=person_ov,
                    first_overrides=first_ov,
                )
                row["gender"] = pred["gender"]
                row["gender_confidence"] = pred["confidence"]
                if inc_index and lookup_incumbent and attach_incumbent_fields:
                    attach_incumbent_fields(
                        row, lookup_incumbent(inc_index, state, party, row["name"])
                    )
                if aw_index and lookup_aw and attach_aw_fields:
                    attach_aw_fields(
                        row, lookup_aw(aw_index, state, party, row["name"])
                    )
            cands.append(row)
        # Listenplatz order; Bezirkslisten grouped by Bezirk code then rank
        cands.sort(
            key=lambda c: (
                c.get("bezirk") or "\uffff",
                c.get("bezirk_name") or "",
                c["list_pos"] is None,
                c["list_pos"] or 999,
                c["name"],
            )
        )
        # Trim trailing list placeholders per Bezirk (or Landesliste)
        if lt == "bezirk":
            by_bez: dict[str, list] = defaultdict(list)
            other = []
            for c in cands:
                if c.get("list_pos") is None:
                    other.append(c)
                else:
                    by_bez[c.get("bezirk") or ""].append(c)
            trimmed = []
            for bez in sorted(by_bez):
                group = by_bez[bez]
                while group and group[-1].get("is_placeholder"):
                    group.pop()
                trimmed.extend(group)
            cands = trimmed + other
        else:
            listed = [c for c in cands if c.get("list_pos") is not None]
            other = [c for c in cands if c.get("list_pos") is None]
            while listed and listed[-1].get("is_placeholder"):
                listed.pop()
            cands = listed + other

        n_known = sum(1 for c in cands if not c["is_placeholder"])
        n_ph = sum(1 for c in cands if c["is_placeholder"])
        gender = _gender_breakdown(cands)
        gender_by_bezirk = {}
        if lt == "bezirk":
            by_bez: dict[str, list] = defaultdict(list)
            for c in cands:
                if c.get("list_pos") is None:
                    continue
                by_bez[c.get("bezirk") or ""].append(c)
            for bez, group in by_bez.items():
                gender_by_bezirk[bez] = _gender_breakdown(group)
        parties_out.append(
            {
                "party": party,
                "partei": party_label(party, state),
                "list_type": lt,
                "n_candidates": len(cands),
                "n_named": n_known,
                "n_placeholder": n_ph,
                "gender": gender,
                "gender_by_bezirk": gender_by_bezirk,
                "candidates": cands,
            }
        )

    return {
        "state_code": state,
        "label": rules["label"],
        "chamber": rules["chamber"],
        "nsim": nsim,
        "statewide_draws": draws_source,
        "statewide_last_poll_date": state_meta.get("last_poll_date"),
        "list_note_de": (
            "Berlin: CDU/SPD/Linke mit Bezirkslisten (Sitze nach Bezirk-Zweitstimmen "
            "aus proportionalem Swing der historischen WK-Ergebnisse); "
            "Grüne/AfD/FDP/BSW mit Landesliste. Grundmandatsklausel: ein Direktmandat "
            "reicht für den Parteieinzug. Fehlende Namen = Platzhalter "
            "(als verschiedene Personen behandelt)."
            if state == "BE"
            else (
                "Landesliste: nach Listenplatz, Direktmandatierte werden auf der "
                "Liste übersprungen. Keine Grundmandatsklausel — unter 5 % gibt es keine "
                "Listensitze, aber gewonnene Direktmandate bleiben."
                if state == "ST"
                else "Landesliste: nach Listenplatz, Direktmandatierte werden auf der "
                "Liste übersprungen. Keine Grundmandatsklausel — unter 5 % gibt es keine "
                "Listensitze, aber gewonnene Direktmandate bleiben. Fehlende Namen = Platzhalter."
            )
        ),
        "sources_official": state == "ST",
        "parties": parties_out,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--states", nargs="+", default=["BE", "MV", "ST"])
    ap.add_argument(
        "--nsim",
        type=int,
        default=None,
        help="Cap on statewide draws (default: all posterior draws)",
    )
    ap.add_argument("--seed", type=int, default=RNG_SEED)
    args = ap.parse_args()

    states_out = {}
    # Preserve other states when only a subset is re-simulated.
    if OUT.exists() and set(s.upper() for s in args.states) != {"BE", "MV", "ST"}:
        try:
            prev = json.loads(OUT.read_text(encoding="utf-8"))
            states_out.update(prev.get("states") or {})
        except (json.JSONDecodeError, OSError):
            pass
    for st in args.states:
        print(f"Simulating candidate entry: {st.upper()} ...")
        states_out[st.upper()] = simulate_state(st.upper(), args.nsim, args.seed)
        print(f"  nsim={states_out[st.upper()]['nsim']}")

    nsims = {s["nsim"] for s in states_out.values()}
    sources = {s.get("statewide_draws") for s in states_out.values()}
    payload = {
        "metadata": {
            "model": "candidate_entry_v1",
            "nsim": next(iter(nsims), args.nsim),
            "statewide_draws": next(iter(sources), None),
            "seed": args.seed,
            "last_update": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "caveat_de": "",
            "gender_note_de": (
                "Geschlechteranteile geschätzt anhand der Vornamen "
                "(Wörterbuch + manuelle Korrekturen). Keine amtliche Angabe."
            ),
        },
        "states": states_out,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT} (states: {', '.join(sorted(states_out))})")


if __name__ == "__main__":
    main()
