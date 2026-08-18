#!/usr/bin/env python3
"""Build statewide Zweitstimme priors (lead≈0) for historical Berlin AGH elections.

π₀ = normalized mean of BE Landtag/AGH polls with published_date ≤ election day
(last ``window_days``). Stand-in for state-models lead-0 until we backcast Stan.

Writes berlin/wahlabend/processed/prior_be_agh{YYYY}.json
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "berlin" / "wahlabend" / "processed"
API = "https://api.zweitstimme.org"

# Map API party keys → nowcast codes
PARTY_MAP = {
    "spd": "spd",
    "cdu": "cdu",
    "csu": "cdu",
    "gruene": "gruene",
    "gruenen": "gruene",
    "grüne": "gruene",
    "linke": "linke",
    "afd": "afd",
    "fdp": "fdp",
    "bsw": "others",
    "sonstige": "others",
    "others": "others",
    "oth": "others",
}
NOWCAST_PARTIES = ("spd", "cdu", "gruene", "linke", "afd", "fdp", "others")

ELECTIONS = {
    2016: date(2016, 9, 18),
    2023: date(2023, 2, 12),
}


def _get_polls(scope: str, published_from: date, published_to: date) -> list[dict]:
    items: list[dict] = []
    page = 1
    while True:
        q = urllib.parse.urlencode(
            {
                "scope": scope,
                "published_from": published_from.isoformat(),
                "published_to": published_to.isoformat(),
                "limit": 100,
                "page": page,
            }
        )
        url = f"{API}/v2/polls?{q}"
        with urllib.request.urlopen(url, timeout=60) as r:
            payload = json.loads(r.read().decode())
        batch = payload.get("data") or []
        items.extend(batch)
        pag = payload.get("pagination") or {}
        if page >= int(pag.get("total_pages") or page) or not batch:
            break
        page += 1
    return items


def _party_shares(poll: dict) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    results = poll.get("results") or []
    for row in results:
        if not isinstance(row, dict):
            continue
        name = row.get("party_key") or row.get("party_short_name") or ""
        code = PARTY_MAP.get(str(name).lower().strip(), "others")
        val = row.get("percentage")
        if val is None:
            val = row.get("share")
        try:
            out[code] += float(val)
        except (TypeError, ValueError):
            continue
    return out


def _norm(shares: dict[str, float]) -> dict[str, float]:
    # values may be 0–1 or 0–100
    vals = {p: float(shares.get(p, 0.0)) for p in NOWCAST_PARTIES}
    s = sum(vals.values())
    if s <= 0:
        return {p: 1.0 / len(NOWCAST_PARTIES) for p in NOWCAST_PARTIES}
    if s > 1.5:  # percent points
        vals = {p: v / 100.0 for p, v in vals.items()}
        s = sum(vals.values())
    # fold remainder into others, then renorm
    if s < 0.98:
        vals["others"] += max(0.0, 1.0 - s)
        s = sum(vals.values())
    return {p: vals[p] / s for p in NOWCAST_PARTIES}


def prior_for_election(election_date: date, window_days: int = 21) -> dict:
    start = election_date - timedelta(days=window_days)
    polls = _get_polls("be", start, election_date)
    # keep only dated ≤ election day
    usable = []
    for p in polls:
        d = p.get("published_date") or p.get("survey_end_date")
        if not d:
            continue
        pd = date.fromisoformat(str(d)[:10])
        if pd <= election_date:
            usable.append((pd, p))
    usable.sort(key=lambda x: x[0])
    if not usable:
        raise SystemExit(f"No BE polls ≤ {election_date}")

    # weight recent polls higher (recency)
    weights = []
    share_rows = []
    for pd, p in usable:
        sh = _norm(_party_shares(p))
        # days before election: 0 → weight 1
        age = (election_date - pd).days
        w = 1.0 / (1.0 + 0.15 * age)
        weights.append(w)
        share_rows.append(sh)

    wsum = sum(weights)
    mean = {
        p: sum(weights[i] * share_rows[i][p] for i in range(len(share_rows))) / wsum
        for p in NOWCAST_PARTIES
    }
    mean = _norm(mean)
    # Soft ~80 % half-width from cross-poll dispersion (1.28·SD), pp.
    # Stand-in for state-models fit/low/high until a lead-0 backcast exists.
    unc_pp: dict[str, float] = {}
    for p in NOWCAST_PARTIES:
        var = sum(
            weights[i] * (share_rows[i][p] - mean[p]) ** 2 for i in range(len(share_rows))
        ) / wsum
        sd_pp = (var ** 0.5) * 100.0
        unc_pp[p] = round(max(1.5, 1.28 * sd_pp), 2)
    return {
        "state_code": "BE",
        "election_date": election_date.isoformat(),
        "lead_horizon_days": 0,
        "method": "poll_mean_lead0_interim",
        "note": (
            "Recency-weighted mean of BE polls published in the "
            f"{window_days}d up to election day. uncertainty_pp = 1.28·SD "
            "across those polls (soft 80 %). Replace with state-models "
            "lead-0/1 polls-only backcast (+ posterior intervals) when available."
        ),
        "n_polls": len(usable),
        "poll_dates": [d.isoformat() for d, _ in usable],
        "institutes": sorted(
            {
                (p.get("institute_key") or p.get("institute_name") or "?")
                for _, p in usable
            }
        ),
        "shares": {p: round(mean[p], 6) for p in NOWCAST_PARTIES},
        "shares_pct": {p: round(mean[p] * 100, 3) for p in NOWCAST_PARTIES},
        "uncertainty_pp": unc_pp,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--years", nargs="+", type=int, default=[2016, 2023])
    ap.add_argument("--window-days", type=int, default=21)
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for y in args.years:
        if y not in ELECTIONS:
            raise SystemExit(f"Unknown year {y}; known {list(ELECTIONS)}")
        prior = prior_for_election(ELECTIONS[y], window_days=args.window_days)
        path = OUT_DIR / f"prior_be_agh{y}.json"
        path.write_text(json.dumps(prior, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote {path}")
        print("  shares%", prior["shares_pct"], "n_polls", prior["n_polls"])


if __name__ == "__main__":
    main()
