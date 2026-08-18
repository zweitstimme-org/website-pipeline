#!/usr/bin/env python3
"""Predict candidate gender from first name (local analysis only — not website).

Pipeline:
  1. person_id override in data/candidate_gender_overrides.csv (manual / research)
  2. first-name override in data/first_name_gender_overrides.csv
  3. gender-guesser dictionary (German + international names)
  4. unknown

Writes nothing to website JSON by default. Use --write to dump local CSVs under tmp/.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "code"))

from listen_candidates import (  # noqa: E402
    STATE_DIRS,
    build_roster,
    clean_person_name,
    name_tokens,
)

OVERRIDES_PERSON = REPO / "data" / "candidate_gender_overrides.csv"
OVERRIDES_FIRST = REPO / "data" / "first_name_gender_overrides.csv"
OUT_DIR = REPO / "tmp" / "candidate_gender"

# gender-guesser labels → coarse gender + confidence
_GG_MAP = {
    "male": ("m", "high"),
    "female": ("f", "high"),
    "mostly_male": ("m", "medium"),
    "mostly_female": ("f", "medium"),
    "andy": ("u", "ambiguous"),
    "unknown": ("u", "unknown"),
}

# Titles / honorifics stripped before taking the display first name.
_TITLE_RE = __import__("re").compile(
    r"^(?:dr|prof|med|dipl|mag|ing)\.?\s+",
    __import__("re").I,
)


def extract_first_name_display(name: str) -> str:
    """First given-name token with diacritics kept (for dictionary lookup).

    Hyphenated given names stay intact (``So-Rim``, ``Jannik-Loris``).
    """
    s = clean_person_name(name)
    # Drop leading titles repeatedly
    prev = None
    while prev != s:
        prev = s
        s = _TITLE_RE.sub("", s).strip()
    if not s:
        return ""
    return s.split()[0].strip(".,;")


def extract_first_name(name: str) -> str:
    """Normalized first given-name token (override / join key)."""
    toks = name_tokens(clean_person_name(name))
    return toks[0] if toks else ""

def _load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_person_overrides(path: Path = OVERRIDES_PERSON) -> dict[str, dict]:
    """person_id → {gender, method, notes}."""
    out: dict[str, dict] = {}
    for r in _load_csv(path):
        pid = (r.get("person_id") or "").strip()
        g = (r.get("gender") or "").strip().lower()
        if not pid or g not in ("m", "f", "x", "u"):
            continue
        out[pid] = {
            "gender": g,
            "method": (r.get("method") or "manual").strip() or "manual",
            "notes": (r.get("notes") or "").strip(),
        }
    return out


def load_first_name_overrides(path: Path = OVERRIDES_FIRST) -> dict[str, dict]:
    """normalized first_name → {gender, method, notes}."""
    out: dict[str, dict] = {}
    for r in _load_csv(path):
        fn = (r.get("first_name") or "").strip().lower()
        # allow umlaut forms; normalize via name_tokens
        if fn:
            toks = name_tokens(fn)
            fn = toks[0] if toks else fn
        g = (r.get("gender") or "").strip().lower()
        if not fn or g not in ("m", "f", "x", "u"):
            continue
        out[fn] = {
            "gender": g,
            "method": (r.get("method") or "manual").strip() or "manual",
            "notes": (r.get("notes") or "").strip(),
        }
    return out


_detector = None


def _get_detector():
    global _detector
    if _detector is None:
        try:
            import gender_guesser.detector as gd
        except ImportError as e:
            raise SystemExit(
                "gender-guesser is required: pip install gender-guesser"
            ) from e
        _detector = gd.Detector(case_sensitive=False)
    return _detector


def _guess_raw(display_first: str) -> str:
    """Query gender-guesser with diacritics preserved; try hyphen parts next."""
    import unicodedata

    det = _get_detector()
    if not display_first:
        return "unknown"

    def _query(token: str) -> str:
        if not token:
            return "unknown"
        return det.get_gender(token)

    raw = _query(display_first)
    if raw != "unknown":
        return raw

    # Strip combining accents only (Michél→Michel, Kán→Kan). Do NOT expand
    # German umlauts to ae/oe/ue — that breaks Jörg/Björn lookups.
    folded = unicodedata.normalize("NFKD", display_first)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    if folded != display_first:
        raw = _query(folded)
        if raw != "unknown":
            return raw

    if "-" not in display_first:
        return "unknown"
    # Prefer a decisive (male/female/mostly_*) part over andy.
    best = "unknown"
    for part in display_first.split("-"):
        part = part.strip()
        if not part:
            continue
        raw = _query(part)
        if raw in ("male", "female", "mostly_male", "mostly_female"):
            return raw
        if folded != display_first:
            raw2 = _query(
                "".join(
                    c
                    for c in unicodedata.normalize("NFKD", part)
                    if not unicodedata.combining(c)
                )
            )
            if raw2 in ("male", "female", "mostly_male", "mostly_female"):
                return raw2
            if raw2 == "andy" and best == "unknown":
                best = raw2
        if raw == "andy" and best == "unknown":
            best = raw
    return best

def predict_gender(
    name: str,
    person_id: str | None = None,
    *,
    person_overrides: dict[str, dict] | None = None,
    first_overrides: dict[str, dict] | None = None,
) -> dict:
    """Return gender prediction for one person.

    Keys: first_name, first_name_display, gender (m/f/x/u), method, confidence,
    raw_label, notes
    """
    person_overrides = (
        person_overrides if person_overrides is not None else load_person_overrides()
    )
    first_overrides = (
        first_overrides if first_overrides is not None else load_first_name_overrides()
    )

    first = extract_first_name(name)
    display = extract_first_name_display(name)
    if person_id and person_id in person_overrides:
        o = person_overrides[person_id]
        return {
            "first_name": first,
            "first_name_display": display,
            "gender": o["gender"],
            "method": o["method"],
            "confidence": "override",
            "raw_label": "",
            "notes": o.get("notes", ""),
        }
    # Override keys are normalized; also accept display-form keys.
    for key in (first, display.lower() if display else ""):
        if key and key in first_overrides:
            o = first_overrides[key]
            return {
                "first_name": first,
                "first_name_display": display,
                "gender": o["gender"],
                "method": f"first_name:{o['method']}",
                "confidence": "override",
                "raw_label": "",
                "notes": o.get("notes", ""),
            }
    if not first and not display:
        return {
            "first_name": "",
            "first_name_display": "",
            "gender": "u",
            "method": "no_first_name",
            "confidence": "unknown",
            "raw_label": "",
            "notes": "",
        }

    raw = _guess_raw(display or first)
    gender, conf = _GG_MAP.get(raw, ("u", "unknown"))
    return {
        "first_name": first,
        "first_name_display": display,
        "gender": gender,
        "method": "first_name:gender_guesser",
        "confidence": conf,
        "raw_label": raw,
        "notes": "",
    }

def collect_people(states: list[str] | None = None) -> list[dict]:
    """Deduped known (non-placeholder) candidates across states."""
    states = states or list(STATE_DIRS)
    person_ov = load_person_overrides()
    first_ov = load_first_name_overrides()
    rows: list[dict] = []
    for st in states:
        rost = build_roster(st.upper())
        for pid, info in rost["people"].items():
            if info.get("is_placeholder"):
                continue
            name = (info.get("name") or "").strip()
            if not name:
                continue
            pred = predict_gender(
                name,
                pid,
                person_overrides=person_ov,
                first_overrides=first_ov,
            )
            rows.append(
                {
                    "state": st.upper(),
                    "party": info.get("party") or "",
                    "person_id": pid,
                    "name": name,
                    "first_name": pred["first_name"],
                    "first_name_display": pred.get("first_name_display", ""),
                    "gender": pred["gender"],
                    "method": pred["method"],
                    "confidence": pred["confidence"],
                    "raw_label": pred["raw_label"],
                    "notes": pred["notes"],
                    "wkr_direct": info.get("wkr_direct") or "",
                    "list_type": info.get("list_type") or "",
                    "list_pos": info.get("list_pos") or "",
                    "source": info.get("source") or "",
                }
            )
    return rows


def needs_review(row: dict) -> bool:
    """Flag for handcoding / research."""
    if row["gender"] in ("u", "x"):
        return True
    if row["confidence"] in ("unknown", "ambiguous", "medium"):
        return True
    return False


def write_analysis(rows: list[dict], out_dir: Path = OUT_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    fields = [
        "state",
        "party",
        "person_id",
        "name",
        "first_name",
        "first_name_display",
        "gender",
        "method",
        "confidence",
        "raw_label",
        "notes",
        "wkr_direct",
        "list_type",
        "list_pos",
        "source",
    ]
    all_path = out_dir / "predictions.csv"
    with all_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    review = [r for r in rows if needs_review(r)]
    # Deduplicate by first_name for a compact research queue
    by_fn: dict[str, list[dict]] = defaultdict(list)
    for r in review:
        by_fn[r["first_name"] or "?"].append(r)

    review_fn_path = out_dir / "first_names_to_review.csv"
    with review_fn_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "first_name",
                "n_candidates",
                "suggested_gender",
                "confidence",
                "raw_label",
                "example_names",
                "example_person_ids",
                "gender_override",
                "notes",
            ],
        )
        w.writeheader()
        for fn, group in sorted(by_fn.items(), key=lambda x: (-len(x[1]), x[0])):
            genders = Counter(g["gender"] for g in group)
            confs = Counter(g["confidence"] for g in group)
            raws = Counter(g["raw_label"] for g in group if g["raw_label"])
            examples = group[:5]
            w.writerow(
                {
                    "first_name": fn,
                    "n_candidates": len(group),
                    "suggested_gender": genders.most_common(1)[0][0],
                    "confidence": confs.most_common(1)[0][0],
                    "raw_label": raws.most_common(1)[0][0] if raws else "",
                    "example_names": " | ".join(e["name"] for e in examples),
                    "example_person_ids": " | ".join(e["person_id"] for e in examples),
                    "gender_override": "",  # fill m/f/x/u then copy to overrides
                    "notes": "",
                }
            )

    review_people_path = out_dir / "people_to_review.csv"
    with review_people_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(review, key=lambda r: (r["first_name"], r["state"], r["name"])))

    print(f"Wrote {all_path} ({len(rows)} people)")
    print(f"Wrote {review_fn_path} ({len(by_fn)} first names)")
    print(f"Wrote {review_people_path} ({len(review)} people)")


def print_summary(rows: list[dict]) -> None:
    n = len(rows)
    g = Counter(r["gender"] for r in rows)
    conf = Counter(r["confidence"] for r in rows)
    review_n = sum(1 for r in rows if needs_review(r))
    print(f"People (non-placeholder): {n}")
    print(
        f"  gender: m={g.get('m', 0)} ({100 * g.get('m', 0) / n:.1f}%)  "
        f"f={g.get('f', 0)} ({100 * g.get('f', 0) / n:.1f}%)  "
        f"u={g.get('u', 0)}  x={g.get('x', 0)}"
    )
    print(
        f"  confidence: high={conf.get('high', 0)}  medium={conf.get('medium', 0)}  "
        f"ambiguous={conf.get('ambiguous', 0)}  unknown={conf.get('unknown', 0)}  "
        f"override={conf.get('override', 0)}"
    )
    print(f"  needs review: {review_n} people")

    print("\nBy state:")
    for st in sorted({r["state"] for r in rows}):
        sub = [r for r in rows if r["state"] == st]
        gg = Counter(r["gender"] for r in sub)
        nn = len(sub)
        print(
            f"  {st}: n={nn}  m={gg.get('m', 0)} ({100 * gg.get('m', 0) / nn:.0f}%)  "
            f"f={gg.get('f', 0)} ({100 * gg.get('f', 0) / nn:.0f}%)  "
            f"u={gg.get('u', 0)}"
        )

    print("\nBy party (all states):")
    for party in sorted({r["party"] for r in rows}):
        sub = [r for r in rows if r["party"] == party]
        gg = Counter(r["gender"] for r in sub)
        nn = len(sub)
        if nn == 0:
            continue
        print(
            f"  {party:7} n={nn:4}  m={100 * gg.get('m', 0) / nn:5.1f}%  "
            f"f={100 * gg.get('f', 0) / nn:5.1f}%  u={gg.get('u', 0)}"
        )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--states", nargs="+", default=["BE", "MV", "ST"])
    ap.add_argument(
        "--write",
        action="store_true",
        help=f"Write CSVs under {OUT_DIR}",
    )
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    args = ap.parse_args()

    rows = collect_people([s.upper() for s in args.states])
    print_summary(rows)
    if args.write:
        write_analysis(rows, args.out)


if __name__ == "__main__":
    main()
