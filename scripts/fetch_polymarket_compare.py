#!/usr/bin/env python3
"""Snapshot Polymarket German Landtag markets vs zweitstimme scenario probabilities.

Writes output/polymarket_compare.json (and website-integration/static/data/).
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "output"
STATIC_DIR = REPO / "website-integration" / "static" / "data"
ZS_API = "https://zweitstimme.org"
GAMMA = "https://gamma-api.polymarket.com"
UA = "zweitstimme-research/1.0 (polymarket compare; +https://zweitstimme.org)"

PARTY_ALIASES = {
    "cdu": "cdu",
    "csu": "cdu",
    "cdu/csu": "cdu",
    "afd": "afd",
    "spd": "spd",
    "fdp": "fdp",
    "bsw": "bsw",
    "fw": "fw",
    "freie wähler": "fw",
    "gru": "gru",
    "grüne": "gru",
    "grune": "gru",
    "gruene": "gru",
    "greens": "gru",
    "the greens": "gru",
    "lin": "lin",
    "linke": "lin",
    "the left": "lin",
    "die linke": "lin",
    "oth": "oth",
    "other": "oth",
    "another party": "oth",
}

PARTY_LABEL = {
    "afd": "AfD",
    "cdu": "CDU",
    "spd": "SPD",
    "gru": "Grüne",
    "lin": "Linke",
    "fdp": "FDP",
    "bsw": "BSW",
    "fw": "FW",
    "oth": "Sonstige",
}

STATES = {
    "ST": {
        "label": "Sachsen-Anhalt",
        "election_date": "2026-09-06",
        "code_lower": "st",
    },
    "BE": {
        "label": "Berlin",
        "election_date": "2026-09-20",
        "code_lower": "be",
    },
    "MV": {
        "label": "Mecklenburg-Vorpommern",
        "election_date": "2026-09-20",
        "code_lower": "mv",
    },
}

# Mutually exclusive party markets we map onto our scenarios.
EVENTS = {
    "ST": {
        "largest": {
            "slug": "sachsen-anhalt-parliamentary-election-winner",
            "place": 1,
            "label_de": "Stärkste Kraft",
        },
        "second": {
            "slug": "sachsen-anhalt-parliamentary-elections-2nd-place",
            "place": 2,
            "label_de": "Zweitstärkste Kraft",
        },
        "third": {
            "slug": "sachsen-anhalt-parliamentary-elections-3rd-place-20260722225837804",
            "place": 3,
            "label_de": "Drittstärkste Kraft",
        },
        "abs_maj_afd": {
            "slug": "will-afd-win-an-absolute-majority-of-seats-in-sachsen-anhalt",
            "binary": True,
            "party": "afd",
            "zs_id": "abs_maj_afd",
            "label_de": "Absolute Mehrheit AfD",
        },
    },
    "BE": {
        "largest": {
            "slug": "berlin-state-election-winner",
            "place": 1,
            "label_de": "Stärkste Kraft",
        },
        "second": {
            "slug": "berlin-state-election-2nd-place-20260708005726718",
            "place": 2,
            "label_de": "Zweitstärkste Kraft",
        },
        "third": {
            "slug": "berlin-state-election-3rd-place-20260708010022790",
            "place": 3,
            "label_de": "Drittstärkste Kraft",
        },
    },
    "MV": {
        "largest": {
            "slug": "mecklenburg-vorpommern-parliamentary-election-winner",
            "place": 1,
            "label_de": "Stärkste Kraft",
        },
        "second": {
            "slug": "mecklenburg-vorpommern-parliamentary-election-2nd-place-20260806103311321",
            "place": 2,
            "label_de": "Zweitstärkste Kraft",
        },
        "third": {
            "slug": "mecklenburg-vorpommern-parliamentary-election-3rd-place-20260806103335438",
            "place": 3,
            "label_de": "Drittstärkste Kraft",
        },
        "abs_maj_afd": {
            "slug": "will-afd-win-an-absolute-majority-of-seats-in-mecklenburg-vorpommern-20260806103954025",
            "binary": True,
            "party": "afd",
            "zs_id": "abs_maj_afd",
            "label_de": "Absolute Mehrheit AfD",
        },
    },
}

CROSS_AFD_N = {
    "slug": "afd-wins-the-most-seats-in-how-many-september-state-elections-20260630185301104",
    "label_de": "AfD stärkste Kraft in wie vielen der drei September-Wahlen?",
}


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _yes_price(market: dict) -> float | None:
    raw = market.get("outcomePrices")
    outcomes = market.get("outcomes")
    prices = None
    if isinstance(raw, str):
        try:
            prices = json.loads(raw)
        except json.JSONDecodeError:
            prices = None
    elif isinstance(raw, list):
        prices = raw
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except json.JSONDecodeError:
            outcomes = None
    if not isinstance(prices, list) or not prices:
        return None
    idx = 0
    if isinstance(outcomes, list):
        for i, name in enumerate(outcomes):
            if str(name).strip().lower() == "yes":
                idx = i
                break
    try:
        return float(prices[idx])
    except (TypeError, ValueError, IndexError):
        return None


def _volume(market: dict) -> float:
    for key in ("volumeNum", "volume", "volume24hr"):
        val = market.get(key)
        try:
            return float(val)
        except (TypeError, ValueError):
            continue
    return 0.0


def _party_from_text(*parts: str) -> str | None:
    blob = " ".join(p for p in parts if p)
    low = blob.lower()
    # Longer aliases first.
    for alias in sorted(PARTY_ALIASES, key=len, reverse=True):
        if re.search(rf"(?<![a-zäöüß]){re.escape(alias)}(?![a-zäöüß])", low):
            return PARTY_ALIASES[alias]
    return None


def _is_placeholder(title: str) -> bool:
    t = (title or "").strip()
    return bool(re.match(r"^(Party|Candidate|Will Party|Will Candidate)\s+[A-Z]\b", t))


def fetch_event(slug: str) -> dict | None:
    data = _get(f"{GAMMA}/events?slug={urllib.parse.quote(slug)}")
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict) and data.get("markets"):
        return data
    return None


def parse_party_markets(event: dict) -> list[dict]:
    rows = []
    slug = event.get("slug") or ""
    url = f"https://polymarket.com/event/{slug}" if slug else ""
    for m in event.get("markets") or []:
        title = (
            m.get("groupItemTitle")
            or m.get("question")
            or m.get("slug")
            or ""
        )
        if _is_placeholder(str(title)):
            continue
        party = _party_from_text(
            m.get("groupItemTitle") or "",
            m.get("question") or "",
            m.get("slug") or "",
        )
        p = _yes_price(m)
        vol = _volume(m)
        # Unused binary slots sit at 50/50 with no volume.
        if p is None:
            continue
        if vol <= 0 and abs(p - 0.5) < 1e-6:
            continue
        if party is None:
            continue
        mslug = m.get("slug") or slug
        rows.append(
            {
                "party": party,
                "pm": round(p * 100, 2),
                "pm_volume": round(vol, 2),
                "question": m.get("question") or title,
                "market_slug": mslug,
                "url": f"https://polymarket.com/event/{slug}/{mslug}" if mslug else url,
            }
        )
    # Keep the highest-volume row if a party appears twice.
    by_party: dict[str, dict] = {}
    for row in rows:
        prev = by_party.get(row["party"])
        if prev is None or row["pm_volume"] > prev["pm_volume"]:
            by_party[row["party"]] = row
    return list(by_party.values())


SEAT_LABEL_TO_CODE = {
    "SPD": "spd",
    "AfD": "afd",
    "CDU": "cdu",
    "LINKE": "lin",
    "GRÜNE": "gru",
    "FDP": "fdp",
    "BSW": "bsw",
    "Sonstige": "oth",
}

PLACE_SEAT_KEY = {1: "p_most_pct", 2: "p_second_pct", 3: "p_third_pct"}

SEAT_NOTE = (
    "ZS = Sitzverteilung aus Wahlkreis-Swing + Hare/Niemeyer "
    "(Direktmandate + Ausgleich). Naiv = letzte Parlamentsgröße × Stimmenanteil "
    "(Hare/Niemeyer, 5%-Hürde, ohne Wahlkreise). Polymarket löst nach Sitzen auf."
)

NAIVE_PARTIES = ["cdu", "spd", "gru", "fdp", "lin", "afd", "bsw"]
SHARE_KEY_TO_CODE = {
    "CDU/CSU": "cdu",
    "CDU": "cdu",
    "SPD": "spd",
    "GRÜNE": "gru",
    "LINKE": "lin",
    "AfD": "afd",
    "FDP": "fdp",
    "BSW": "bsw",
}


def load_last_parliament(code: str) -> dict:
    path = REPO / "data" / "last_election_results.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    block = (payload.get("states") or {}).get(code) or {}
    seats = {}
    for label, n in (block.get("seats") or {}).items():
        party = SHARE_KEY_TO_CODE.get(label)
        if party:
            seats[party] = int(n)
    return {
        "size": int(block.get("parliament_size") or 0),
        "year": str(block.get("election_date") or "")[:4],
        "seats": seats,
    }


def hare_niemeyer(votes: dict[str, float], seats: int) -> dict[str, int]:
    parties = list(votes.keys())
    total = float(sum(votes.values()))
    if total <= 0 or seats <= 0 or not parties:
        return {p: 0 for p in parties}
    quotas = [votes[p] * seats / total for p in parties]
    base = [int(q) for q in quotas]
    rem = seats - sum(base)
    order = sorted(range(len(parties)), key=lambda i: -(quotas[i] - base[i]))
    for j in range(max(0, rem)):
        base[order[j % len(order)]] += 1
    return {p: int(base[i]) for i, p in enumerate(parties)}


def naive_seats_from_draws(draws: list[dict], size: int, hurdle: float = 0.05) -> dict:
    """Last chamber size × current vote share, 5% hurdle, Hare/Niemeyer."""
    hists = {p: Counter() for p in NAIVE_PARTIES}
    most = {p: 0 for p in NAIVE_PARTIES}
    abs_maj = {p: 0 for p in NAIVE_PARTIES}
    n = 0
    for draw in draws:
        above = {
            p: float(draw.get(p) or 0.0)
            for p in NAIVE_PARTIES
            if float(draw.get(p) or 0.0) >= hurdle
        }
        seats = hare_niemeyer(above, size) if above else {}
        n += 1
        ranked = sorted(
            (
                (p, int(seats.get(p, 0)), float(draw.get(p) or 0.0))
                for p in NAIVE_PARTIES
                if int(seats.get(p, 0)) > 0
            ),
            key=lambda t: (t[1], t[2]),
            reverse=True,
        )
        if ranked:
            most[ranked[0][0]] += 1
        for p in NAIVE_PARTIES:
            s = int(seats.get(p, 0))
            hists[p][s] += 1
            if size > 0 and s * 2 > size:
                abs_maj[p] += 1
    if n <= 0:
        return {"nsim": 0, "size": size, "hurdle": hurdle, "parties": {}}
    out = {}
    for p in NAIVE_PARTIES:
        arr = []
        for k, c in hists[p].items():
            arr.extend([int(k)] * int(c))
        arr.sort()
        if not arr:
            continue

        def pctile(pctl: float) -> int:
            i = int(round(pctl / 100.0 * (len(arr) - 1)))
            return arr[min(len(arr) - 1, max(0, i))]

        out[p] = {
            "mean": round(sum(arr) / len(arr), 2),
            "median": arr[len(arr) // 2],
            "p10": pctile(10),
            "p90": pctile(90),
            "p_most_pct": round(100.0 * most[p] / n, 2),
            "p_abs_majority_pct": round(100.0 * abs_maj[p] / n, 2),
            "hist": {str(k): int(v) for k, v in sorted(hists[p].items())},
        }
    return {"nsim": n, "size": size, "hurdle": hurdle, "parties": out}


def load_parliament_seats() -> dict:
    """state_code → {party_code: seat-stats} from the district parliament sim."""
    paths = [
        OUT_DIR / "forecast_parliament_size.json",
        REPO / "website-mock" / "static" / "data" / "forecast_parliament_size.json",
    ]
    payload = None
    for path in paths:
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                break
            except (OSError, json.JSONDecodeError):
                continue
    if payload is None:
        try:
            payload = _get(f"{ZS_API}/data/forecast_parliament_size.json")
        except Exception:
            return {}
    out = {}
    for code, block in (payload.get("states") or {}).items():
        raw = block.get("party_seats") or {}
        if not raw:
            continue
        mapped = {}
        for label, stats in raw.items():
            party = SEAT_LABEL_TO_CODE.get(label) or PARTY_ALIASES.get(str(label).lower())
            if party:
                mapped[party] = stats
        if mapped:
            out[str(code).upper()] = {
                "nsim": block.get("nsim"),
                "last_poll_date": block.get("statewide_last_poll_date"),
                "parties": mapped,
            }
    return out


def parse_bin_label(title: str) -> tuple[int | None, int | None] | None:
    t = str(title or "").strip().replace("–", "-").replace("—", "-")
    m = re.fullmatch(r"<(\d+)", t)
    if m:
        return 0, int(m.group(1)) - 1
    m = re.fullmatch(r"(\d+)\+", t)
    if m:
        return int(m.group(1)), None
    m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", t)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def hist_bin_pct(hist: dict, lo: int | None, hi: int | None) -> float | None:
    if not hist:
        return None
    total = sum(int(v) for v in hist.values())
    if total <= 0:
        return None
    n = 0
    for key, count in hist.items():
        try:
            s = int(key)
        except (TypeError, ValueError):
            continue
        if lo is not None and s < lo:
            continue
        if hi is not None and s > hi:
            continue
        n += int(count)
    return round(100.0 * n / total, 2)


def parse_count_markets(event: dict) -> list[dict]:
    """Yes/No outcomes whose group title is a count like 0, 1, 2, 3."""
    rows = []
    slug = event.get("slug") or ""
    for m in event.get("markets") or []:
        title = str(m.get("groupItemTitle") or m.get("question") or "").strip()
        if not re.fullmatch(r"[0-9]+", title):
            continue
        p = _yes_price(m)
        if p is None:
            continue
        rows.append(
            {
                "n": int(title),
                "pm": round(p * 100, 2),
                "pm_volume": round(_volume(m), 2),
                "question": m.get("question") or title,
            }
        )
    rows.sort(key=lambda r: r["n"])
    return rows


def parse_bin_markets(event: dict) -> list[dict]:
    """Seat-count range markets (`<34`, `34-37`, `50+`)."""
    rows = []
    slug = event.get("slug") or ""
    for m in event.get("markets") or []:
        title = str(m.get("groupItemTitle") or "").strip()
        bounds = parse_bin_label(title)
        if bounds is None:
            continue
        p = _yes_price(m)
        if p is None:
            continue
        vol = _volume(m)
        if vol <= 0 and abs(p - 0.5) < 1e-6:
            continue
        lo, hi = bounds
        rows.append(
            {
                "label": title,
                "lo": lo,
                "hi": hi,
                "pm": round(p * 100, 2),
                "pm_volume": round(vol, 2),
                "question": m.get("question") or title,
                "url": f"https://polymarket.com/event/{slug}",
            }
        )
    def sort_key(r):
        return (r["lo"] if r["lo"] is not None else -1, r["hi"] if r["hi"] is not None else 10_000)

    rows.sort(key=sort_key)
    return rows


def discover_seat_bin_events(state_code: str) -> list[dict]:
    queries = {
        "ST": "Sachsen-Anhalt seats",
        "BE": "Berlin State Elections seats",
        "MV": "Mecklenburg-Vorpommern seats",
    }
    q = queries.get(state_code)
    if not q:
        return []
    try:
        data = _get("https://gamma-api.polymarket.com/public-search?q=" + urllib.parse.quote(q))
    except Exception:
        return []
    events = data.get("events") if isinstance(data, dict) else []
    found = []
    for ev in events or []:
        slug = str(ev.get("slug") or "")
        title = str(ev.get("title") or "")
        blob = f"{slug} {title}".lower()
        if "majority" in blob:
            continue
        if "-of-seats-" not in slug and not slug.endswith("-of-seats") and "# of seats" not in title.lower():
            continue
        party = _party_from_text(title, slug)
        if not party:
            continue
        found.append({"slug": slug, "party": party, "title": title})
    # de-dupe by slug
    by_slug = {x["slug"]: x for x in found}
    return list(by_slug.values())


def renormalize(rows: list[dict], key: str = "pm") -> None:
    total = sum(float(r.get(key) or 0) for r in rows)
    if total <= 0:
        for r in rows:
            r["pm_norm"] = None
        return
    for r in rows:
        r["pm_norm"] = round(100.0 * float(r.get(key) or 0) / total, 2)


def zs_unwrap(payload: dict) -> dict:
    return payload.get("data") if isinstance(payload.get("data"), dict) else payload


def fetch_zs_forecast(code: str) -> dict:
    return zs_unwrap(_get(f"{ZS_API}/api/v2/state/{code}.json"))


def fetch_zs_draws(code: str) -> dict:
    return zs_unwrap(_get(f"{ZS_API}/api/v2/state/{code}/draws.json"))


def place_probs(draws: list[dict], place: int) -> dict[str, float]:
    counts: dict[str, int] = {}
    n = 0
    for draw in draws:
        ranked = sorted(
            ((k, float(v)) for k, v in draw.items() if k != "oth"),
            key=lambda kv: kv[1],
            reverse=True,
        )
        if len(ranked) < place:
            continue
        winner = ranked[place - 1][0]
        counts[winner] = counts.get(winner, 0) + 1
        n += 1
    if n <= 0:
        return {}
    return {p: round(100.0 * c / n, 2) for p, c in counts.items()}


def published_scenario_map(forecast: dict) -> dict[str, dict]:
    items = ((forecast.get("scenarios") or {}).get("items")) or []
    return {str(it.get("id")): it for it in items if it.get("id")}


def zs_largest_pct(forecast: dict, draws_place: dict[str, float], party: str) -> float | None:
    sid = f"largest_party_{party}"
    pub = published_scenario_map(forecast).get(sid)
    if pub is not None and pub.get("probability") is not None:
        return float(pub["probability"])
    if party in draws_place:
        return draws_place[party]
    return None


def combine_afd_n(p_st: float, p_be: float, p_mv: float) -> dict[int, float]:
    """Independent combination of P(AfD strongest) in each state, in percent."""
    a, b, c = p_st / 100.0, p_be / 100.0, p_mv / 100.0
    q = (1 - a, 1 - b, 1 - c)
    p = (a, b, c)
    out = {0: q[0] * q[1] * q[2]}
    out[1] = p[0] * q[1] * q[2] + q[0] * p[1] * q[2] + q[0] * q[1] * p[2]
    out[2] = p[0] * p[1] * q[2] + p[0] * q[1] * p[2] + q[0] * p[1] * p[2]
    out[3] = p[0] * p[1] * p[2]
    return {k: round(100.0 * v, 2) for k, v in out.items()}


def build_place_group(
    *,
    state: str,
    spec: dict,
    event: dict,
    forecast: dict,
    place_from_draws: dict[int, dict[str, float]],
    seat_stats: dict | None,
) -> dict:
    pm_rows = parse_party_markets(event)
    renormalize(pm_rows)
    place = int(spec["place"])
    draw_p = place_from_draws.get(place) or {}
    seats = (seat_stats or {}).get("parties") or {}
    seat_key = PLACE_SEAT_KEY[place]
    zs_by_party: dict[str, float | None] = {}
    zs_vote_by_party: dict[str, float] = {}
    parties_seen = set(draw_p) | {r["party"] for r in pm_rows} | set(seats)
    for party in parties_seen:
        vote = float(draw_p.get(party) or 0.0)
        if place == 1:
            pub = zs_largest_pct(forecast, draw_p, party)
            zs_vote_by_party[party] = float(pub if pub is not None else vote)
        else:
            zs_vote_by_party[party] = vote
        if party in seats and seats[party].get(seat_key) is not None:
            zs_by_party[party] = float(seats[party][seat_key])
        else:
            zs_by_party[party] = zs_vote_by_party[party]

    parties = sorted(
        set(zs_by_party) | {r["party"] for r in pm_rows},
        key=lambda p: -(max(zs_by_party.get(p) or 0, next((r["pm"] for r in pm_rows if r["party"] == p), 0))),
    )
    pm_map = {r["party"]: r for r in pm_rows}
    rows = []
    for party in parties:
        if party in ("fw", "oth") and (zs_by_party.get(party) or 0) < 0.5 and (pm_map.get(party, {}).get("pm") or 0) < 1:
            continue
        zs = zs_by_party.get(party)
        pm = pm_map.get(party)
        if zs is None and pm is None:
            continue
        if place == 1:
            label = f"{PARTY_LABEL.get(party, party)} stärkste Kraft"
        else:
            label = f"{PARTY_LABEL.get(party, party)} {spec['label_de']}"
        row = {
            "id": f"{'largest_party' if place == 1 else f'place{place}'}_{party}",
            "party": party,
            "label_de": label,
            "zs": None if zs is None else round(float(zs), 2),
            "zs_vote": round(float(zs_vote_by_party.get(party) or 0), 2),
            "zs_source": "seats" if party in seats else "vote",
            "pm": None if pm is None else pm["pm"],
            "pm_norm": None if pm is None else pm.get("pm_norm"),
            "pm_volume": None if pm is None else pm["pm_volume"],
            "url": None if pm is None else pm.get("url"),
        }
        if row["zs"] is not None and row["pm"] is not None:
            row["delta"] = round(row["zs"] - row["pm"], 1)
        rows.append(row)
    slug = event.get("slug") or spec["slug"]
    return {
        "id": spec.get("id") or {1: "largest", 2: "second", 3: "third"}[place],
        "label_de": spec["label_de"],
        "polymarket_title": event.get("title"),
        "polymarket_url": f"https://polymarket.com/event/{slug}",
        "polymarket_volume": event.get("volume"),
        "note_de": SEAT_NOTE,
        "rows": rows,
    }


def build_binary_group(spec: dict, event: dict, forecast: dict, seat_stats: dict | None) -> dict:
    zs_id = spec["zs_id"]
    party = spec.get("party")
    pub = published_scenario_map(forecast).get(zs_id) or {}
    zs_vote = pub.get("probability")
    seats = (seat_stats or {}).get("parties") or {}
    zs = None
    if party and party in seats and seats[party].get("p_abs_majority_pct") is not None:
        zs = float(seats[party]["p_abs_majority_pct"])
    elif zs_vote is not None:
        zs = float(zs_vote)
    markets = event.get("markets") or []
    m = markets[0] if markets else {}
    p = _yes_price(m)
    slug = event.get("slug") or spec["slug"]
    pm = None if p is None else round(p * 100, 2)
    row = {
        "id": zs_id,
        "party": party,
        "label_de": spec["label_de"],
        "zs": None if zs is None else round(float(zs), 2),
        "zs_vote": None if zs_vote is None else float(zs_vote),
        "zs_source": "seats" if party and party in seats else "vote",
        "pm": pm,
        "pm_norm": pm,
        "pm_volume": round(_volume(m), 2),
        "url": f"https://polymarket.com/event/{slug}",
    }
    if row["zs"] is not None and row["pm"] is not None:
        row["delta"] = round(row["zs"] - row["pm"], 1)
    return {
        "id": zs_id,
        "label_de": spec["label_de"],
        "polymarket_title": event.get("title"),
        "polymarket_url": f"https://polymarket.com/event/{slug}",
        "polymarket_volume": event.get("volume"),
        "note_de": SEAT_NOTE + " Absolute Mehrheit: Sitze > Hälfte der jeweiligen Parlamentsgröße.",
        "rows": [row],
    }


def range_label(lo: int, hi: int | None) -> str:
    if hi is None:
        return f"{lo}+"
    if lo == 0:
        return f"<{hi + 1}"
    return f"{lo}–{hi}"


def auto_bins_from_stats(stats: dict) -> list[tuple[int, int | None]]:
    """A few inclusive seat bins covering p10–p90, plus tails."""
    hist = stats.get("hist") or {}
    keys = []
    for k in hist:
        try:
            keys.append(int(k))
        except (TypeError, ValueError):
            continue
    if not keys:
        return []
    hi_obs = max(keys)
    p10 = int(stats.get("p10") if stats.get("p10") is not None else min(keys))
    p90 = int(stats.get("p90") if stats.get("p90") is not None else hi_obs)
    span = max(p90 - p10, hi_obs, 1)
    if span <= 8:
        width = 2
    elif span <= 16:
        width = 3
    else:
        width = 5
    start = max(0, (p10 // width) * width)
    bins: list[tuple[int, int | None]] = []
    if start > 0:
        bins.append((0, start - 1))
    x = start
    stop = max(p90, start) + width
    while x < stop:
        bins.append((x, x + width - 1))
        x += width
    if bins:
        last_lo = bins[-1][0]
        bins[-1] = (last_lo, None)
    return bins


def _naive_pct(naive: dict | None, party: str, lo: int, hi: int | None) -> float | None:
    hist = (((naive or {}).get("parties") or {}).get(party) or {}).get("hist")
    return hist_bin_pct(hist, lo, hi) if hist else None


def build_model_seat_group(party: str, stats: dict, naive: dict | None = None) -> dict | None:
    hist = stats.get("hist") or {}
    bins = auto_bins_from_stats(stats)
    if not bins or not hist:
        return None
    rows = []
    for lo, hi in bins:
        zs = hist_bin_pct(hist, lo, hi)
        rng = range_label(lo, hi)
        rows.append(
            {
                "id": f"seats_{party}_{rng}",
                "party": party,
                "label_de": f"{PARTY_LABEL.get(party, party)} {rng} Sitze",
                "zs": zs,
                "zs_naive": _naive_pct(naive, party, lo, hi),
                "zs_source": "seats",
                "pm": None,
                "pm_norm": None,
                "pm_volume": None,
                "url": None,
            }
        )
    med = stats.get("median")
    mean = stats.get("mean")
    nmed = ((naive or {}).get("parties") or {}).get(party, {}).get("median")
    extra = ""
    if med is not None:
        extra = f" Modell: Median {med} Sitze"
        if mean is not None:
            extra += f" (Mittel {mean})"
        extra += "."
    if nmed is not None:
        extra += f" Naiv: Median {nmed} Sitze."
    extra += " Kein Polymarket-Markt für diese Sitzklassen."
    return {
        "id": f"seats_{party}",
        "label_de": f"Sitze {PARTY_LABEL.get(party, party)}",
        "polymarket_title": None,
        "polymarket_url": None,
        "polymarket_volume": None,
        "note_de": SEAT_NOTE + extra,
        "rows": rows,
    }


PARTY_SEAT_ORDER = ["afd", "cdu", "spd", "lin", "gru", "bsw", "fdp"]


def include_seat_party(stats: dict) -> bool:
    if not stats:
        return False
    return (
        (stats.get("median") or 0) >= 1
        or (stats.get("p90") or 0) >= 1
        or (stats.get("mean") or 0) >= 1
        or (stats.get("p_most_pct") or 0) > 0
    )


def build_seat_overview(
    seat_stats: dict | None,
    pm_parties: set[str],
    naive: dict | None = None,
    last: dict | None = None,
) -> list[dict]:
    parties = (seat_stats or {}).get("parties") or {}
    rows = []
    for party in PARTY_SEAT_ORDER:
        stats = parties.get(party)
        if not include_seat_party(stats or {}):
            continue
        nstats = ((naive or {}).get("parties") or {}).get(party) or {}
        rows.append(
            {
                "party": party,
                "label_de": PARTY_LABEL.get(party, party),
                "median": stats.get("median"),
                "median_naive": nstats.get("median"),
                "last_seats": ((last or {}).get("seats") or {}).get(party),
                "mean": stats.get("mean"),
                "p10": stats.get("p10"),
                "p90": stats.get("p90"),
                "p_most_pct": stats.get("p_most_pct"),
                "has_pm": party in pm_parties,
            }
        )
    rows.sort(key=lambda r: (-(r.get("median") or 0), r["party"]))
    return rows


def build_seat_bin_group(
    spec: dict, event: dict, seat_stats: dict | None, naive: dict | None = None
) -> dict | None:
    party = spec["party"]
    hist = (((seat_stats or {}).get("parties") or {}).get(party) or {}).get("hist")
    pm_rows = parse_bin_markets(event)
    if not pm_rows:
        return None
    stats = ((seat_stats or {}).get("parties") or {}).get(party) or {}
    rows = []
    for pm in pm_rows:
        zs = hist_bin_pct(hist or {}, pm["lo"], pm["hi"]) if hist else None
        if pm["hi"] is None:
            rng = f"{pm['lo']}+"
        elif pm["lo"] == 0:
            rng = f"<{pm['hi'] + 1}"
        else:
            rng = f"{pm['lo']}–{pm['hi']}"
        row = {
            "id": f"seats_{party}_{pm['label']}",
            "party": party,
            "label_de": f"{PARTY_LABEL.get(party, party)} {rng} Sitze",
            "zs": zs,
            "zs_naive": _naive_pct(naive, party, pm["lo"], pm["hi"]),
            "zs_source": "seats" if zs is not None else None,
            "pm": pm["pm"],
            "pm_norm": pm["pm"],
            "pm_volume": pm["pm_volume"],
            "url": pm.get("url"),
        }
        if row["zs"] is not None and row["pm"] is not None:
            row["delta"] = round(row["zs"] - row["pm"], 1)
        rows.append(row)
    med = stats.get("median")
    mean = stats.get("mean")
    nmed = ((naive or {}).get("parties") or {}).get(party, {}).get("median")
    extra = ""
    if med is not None:
        extra = f" Modell: Median {med} Sitze"
        if mean is not None:
            extra += f" (Mittel {mean})"
        extra += "."
    if nmed is not None:
        extra += f" Naiv: Median {nmed} Sitze."
    slug = event.get("slug") or spec["slug"]
    return {
        "id": f"seats_{party}",
        "label_de": f"Sitze {PARTY_LABEL.get(party, party)}",
        "polymarket_title": event.get("title"),
        "polymarket_url": f"https://polymarket.com/event/{slug}",
        "polymarket_volume": event.get("volume"),
        "note_de": SEAT_NOTE + extra,
        "rows": rows,
    }


def main() -> int:
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    states_out = {}
    afd_largest = {}
    parliament = load_parliament_seats()
    if parliament:
        print(f"Loaded seat sims for {', '.join(sorted(parliament))}", flush=True)
    else:
        print("No party_seats in forecast_parliament_size.json — using vote-share fallback.", flush=True)

    for code, meta in STATES.items():
        print(f"Fetching zweitstimme {code} …", flush=True)
        forecast = fetch_zs_forecast(meta["code_lower"])
        draws_payload = fetch_zs_draws(meta["code_lower"])
        draws = draws_payload.get("draws") or []
        place_from_draws = {
            1: place_probs(draws, 1),
            2: place_probs(draws, 2),
            3: place_probs(draws, 3),
        }
        seat_stats = parliament.get(code)
        last = load_last_parliament(code)
        naive = naive_seats_from_draws(draws, last["size"]) if last.get("size") and draws else {}
        if naive.get("parties"):
            print(
                f"  naive seats size={last['size']} "
                f"AfD med={((naive.get('parties') or {}).get('afd') or {}).get('median')}",
                flush=True,
            )
        zs_meta = forecast.get("metadata") or {}
        place_groups = []
        seat_groups = []
        for gid, spec in EVENTS[code].items():
            print(f"  Polymarket {spec['slug']}", flush=True)
            try:
                event = fetch_event(spec["slug"])
            except urllib.error.HTTPError as exc:
                print(f"    skip HTTP {exc.code}", flush=True)
                continue
            if not event:
                print("    empty", flush=True)
                continue
            if spec.get("binary"):
                place_groups.append(build_binary_group(spec, event, forecast, seat_stats))
            else:
                spec = dict(spec, id=gid)
                place_groups.append(
                    build_place_group(
                        state=code,
                        spec=spec,
                        event=event,
                        forecast=forecast,
                        place_from_draws=place_from_draws,
                        seat_stats=seat_stats,
                    )
                )
        print(f"  seat-bin markets {code} …", flush=True)
        pm_parties: set[str] = set()
        for spec in discover_seat_bin_events(code):
            print(f"    {spec['slug']}", flush=True)
            try:
                event = fetch_event(spec["slug"])
            except urllib.error.HTTPError:
                continue
            if not event:
                continue
            grp = build_seat_bin_group(spec, event, seat_stats, naive)
            if grp:
                seat_groups.append(grp)
                pm_parties.add(spec["party"])
        parties = (seat_stats or {}).get("parties") or {}
        for party in PARTY_SEAT_ORDER:
            if party in pm_parties:
                continue
            stats = parties.get(party)
            if not include_seat_party(stats or {}):
                continue
            grp = build_model_seat_group(party, stats or {}, naive)
            if grp:
                print(f"    model bins {party}", flush=True)
                seat_groups.append(grp)
        seat_groups.sort(
            key=lambda g: -(
                ((parties.get(g["id"].removeprefix("seats_")) or {}).get("median")) or 0
            )
        )
        groups = seat_groups + place_groups
        afd_seats = parties.get("afd") or {}
        if afd_seats.get("p_most_pct") is not None:
            afd_largest[code] = float(afd_seats["p_most_pct"])
        else:
            afd_largest[code] = zs_largest_pct(forecast, place_from_draws[1], "afd") or 0.0
        states_out[code] = {
            "state_code": code,
            "label": meta["label"],
            "election_date": meta["election_date"],
            "zs": {
                "asof_date": zs_meta.get("asof_date") or draws_payload.get("asof_date"),
                "last_update": zs_meta.get("last_update") or draws_payload.get("last_update"),
                "last_poll_date": zs_meta.get("last_poll_date") or draws_payload.get("last_poll_date"),
                "model": zs_meta.get("model") or draws_payload.get("model"),
                "n_draws": draws_payload.get("n_draws") or len(draws),
                "seats": bool(seat_stats),
                "seat_nsim": (seat_stats or {}).get("nsim"),
                "naive_size": last.get("size"),
                "naive_year": last.get("year"),
            },
            "seat_overview": build_seat_overview(seat_stats, pm_parties, naive, last),
            "groups": groups,
        }

    print("Fetching cross-state AfD N …", flush=True)
    cross = None
    try:
        event = fetch_event(CROSS_AFD_N["slug"])
    except urllib.error.HTTPError as exc:
        print(f"  skip HTTP {exc.code}", flush=True)
        event = None
    if event:
        pm_rows = parse_count_markets(event)
        zs_n = combine_afd_n(
            afd_largest.get("ST", 0),
            afd_largest.get("BE", 0),
            afd_largest.get("MV", 0),
        )
        rows = []
        pm_map = {r["n"]: r for r in pm_rows}
        for n in range(4):
            pm = pm_map.get(n)
            zs = zs_n.get(n)
            row = {
                "id": f"afd_n_{n}",
                "n": n,
                "label_de": f"AfD stärkste Kraft in {n} {'Wahl' if n == 1 else 'Wahlen'}",
                "zs": zs,
                "pm": None if pm is None else pm["pm"],
                "pm_norm": None if pm is None else pm["pm"],
                "pm_volume": None if pm is None else pm["pm_volume"],
            }
            if row["zs"] is not None and row["pm"] is not None:
                row["delta"] = round(row["zs"] - row["pm"], 1)
            rows.append(row)
        slug = event.get("slug") or CROSS_AFD_N["slug"]
        cross = {
            "id": "afd_n_wins",
            "label_de": CROSS_AFD_N["label_de"],
            "polymarket_title": event.get("title"),
            "polymarket_url": f"https://polymarket.com/event/{slug}",
            "polymarket_volume": event.get("volume"),
            "note_de": (
                "Zweitstimme kombiniert die drei Länder unabhängig "
                f"(ST {afd_largest.get('ST', 0):.0f} %, BE {afd_largest.get('BE', 0):.0f} %, "
                f"MV {afd_largest.get('MV', 0):.0f} % für AfD stärkste Kraft)."
            ),
            "inputs": afd_largest,
            "rows": rows,
        }

    payload = {
        "generated_at": fetched_at,
        "source": {
            "zweitstimme": f"{ZS_API}/api/v2/state/",
            "polymarket": GAMMA,
        },
        "notes_de": [
            "Polymarket-Preise sind Ja-Anteile (letzter Mid); ungenutzte 50/50-Märkte ohne Volumen entfallen.",
            "ZS-Platzierungen und absolute Mehrheit kommen aus der Sitzsimulation (Wahlkreis-Swing + Hare/Niemeyer), analog zu Polymarket (meiste Sitze).",
            "Stimmenanteils-Szenarien der Startseite bleiben als „Stimmen“-Hinweis sichtbar, wenn sie abweichen.",
            "Sitzklassen: ZS = Wahlkreis-Simulation, Naiv = letzte Sitzzahl × Stimmenanteil (Hare, 5%-Hürde).",
        ],
        "states": states_out,
        "cross": cross,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    for dest in (OUT_DIR / "polymarket_compare.json", STATIC_DIR / "polymarket_compare.json"):
        dest.write_text(text, encoding="utf-8")
        print(f"Wrote {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
