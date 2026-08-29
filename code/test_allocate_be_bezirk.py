#!/usr/bin/env python3
"""Berlin AGH: Landesliste vs Bezirkslisten overhang (no statewide netting)."""

from __future__ import annotations

import unittest

from listen_candidates import BEZ_NAMES
from parliament_size_sim import allocate_be, hare_niemeyer


def _votes() -> dict[str, float]:
    return {
        "CDU": 0.30,
        "SPD": 0.22,
        "GRÜNE": 0.16,
        "LINKE": 0.12,
        "AfD": 0.10,
        "FDP": 0.04,
        "BSW": 0.03,
        "Sonstige": 0.03,
    }


def _directs() -> dict[str, int]:
    return {
        "CDU": 48,
        "SPD": 16,
        "GRÜNE": 8,
        "LINKE": 5,
        "AfD": 1,
        "FDP": 0,
        "BSW": 0,
        "Sonstige": 0,
    }


def _uniform_bez_votes() -> dict[str, dict[str, float]]:
    bez = list(BEZ_NAMES)
    n = len(bez)
    out: dict[str, dict[str, float]] = {}
    for p, share in _votes().items():
        if p == "Sonstige":
            continue
        out[p] = {b: share / n for b in bez}
    return out


def _uniform_directs_by_bez() -> dict[str, dict[str, int]]:
    """Spread statewide directs as evenly as possible across 12 Bezirke."""
    bez = list(BEZ_NAMES)
    out: dict[str, dict[str, int]] = {p: {b: 0 for b in bez} for p in _directs()}
    for p, n in _directs().items():
        for i in range(n):
            out[p][bez[i % len(bez)]] += 1
    return out


def _concentrated_cdu_directs() -> dict[str, dict[str, int]]:
    """CDU Direktmandate piled into a few Bezirke; others stay uniform."""
    out = _uniform_directs_by_bez()
    bez = list(BEZ_NAMES)
    out["CDU"] = {b: 0 for b in bez}
    # 8 + 8 + 8 + 8 + 8 + 8 = 48 in six Bezirke; six others empty.
    for i in range(48):
        out["CDU"][bez[i % 6]] += 1
    return out


class AllocateBeBezirkTests(unittest.TestCase):
    def test_landes_without_bezirk_maps_matches_statewide_max(self):
        votes, directs = _votes(), _directs()
        res = allocate_be(votes, directs)
        above = {p: s for p, s in votes.items() if s >= 0.05}
        prop = hare_niemeyer(above, 130)
        self.assertGreaterEqual(res["seats"]["CDU"], directs["CDU"])
        self.assertGreaterEqual(res["seats"]["CDU"], prop["CDU"])
        # Formula once (no +1 bump): size from seats_incl / share, not 220+.
        self.assertLess(res["size"], 200)
        self.assertGreaterEqual(res["size"], 130)

    def test_uniform_bezirk_close_to_landes(self):
        votes, directs = _votes(), _directs()
        landes = allocate_be(votes, directs)
        bezirk = allocate_be(
            votes,
            directs,
            directs_by_bez=_uniform_directs_by_bez(),
            bez_votes=_uniform_bez_votes(),
            bezirk_parties={"CDU", "SPD", "LINKE"},
        )
        self.assertLessEqual(abs(bezirk["size"] - landes["size"]), 8)
        self.assertLessEqual(abs(bezirk["seats"]["CDU"] - landes["seats"]["CDU"]), 6)

    def test_concentrated_bezirk_raises_cdu_seats_and_chamber(self):
        votes, directs = _votes(), _directs()
        landes = allocate_be(votes, directs)
        bezirk = allocate_be(
            votes,
            directs,
            directs_by_bez=_concentrated_cdu_directs(),
            bez_votes=_uniform_bez_votes(),
            bezirk_parties={"CDU", "SPD", "LINKE"},
        )
        self.assertGreater(bezirk["seats"]["CDU"], landes["seats"]["CDU"])
        self.assertGreater(bezirk["seats"]["CDU"], directs["CDU"])
        self.assertGreater(bezirk["size"], landes["size"])
        # Official formula once — must not walk s until every Bezirk is covered.
        self.assertLess(bezirk["size"], 220)
        self.assertGreater(bezirk["size"], 130)

    def test_landesliste_parties_still_net_statewide(self):
        votes, directs = _votes(), _directs()
        res = allocate_be(
            votes,
            directs,
            directs_by_bez=_concentrated_cdu_directs(),
            bez_votes=_uniform_bez_votes(),
            bezirk_parties={"CDU", "SPD", "LINKE"},
        )
        # GRÜNE/AfD are Landesliste: seats == max(alloc, statewide directs).
        self.assertGreaterEqual(res["seats"]["GRÜNE"], directs["GRÜNE"])
        self.assertGreaterEqual(res["seats"]["AfD"], directs["AfD"])
        alloc = res["alloc"]
        self.assertEqual(res["seats"]["GRÜNE"], max(alloc["GRÜNE"], directs["GRÜNE"]))
        self.assertEqual(res["seats"]["AfD"], max(alloc["AfD"], directs["AfD"]))


if __name__ == "__main__":
    unittest.main()
