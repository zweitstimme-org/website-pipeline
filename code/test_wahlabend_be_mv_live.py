#!/usr/bin/env python3
"""Tests for BE/MV live nowcast helpers (forecast-only, no live CSVs required)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from wahlabend_live_common import (
    PARTIES,
    _shares,
    blend_with_external,
    load_external,
    merge_history,
    turnout_mixture,
)


class TurnoutMixtureTests(unittest.TestCase):
    def test_opening_band_covers_st_style_miss(self):
        t = turnout_mixture(
            prior_pp=70.0,
            last_office_pp=62.9,
            recent_federal_pp=78.0,
            naive=None,
            reported_frac=0.0,
            n_complete=0,
            brief_visible=False,
        )
        self.assertGreaterEqual(t["uncertainty"], 15.0)
        lo = t["nowcast"] - t["uncertainty"]
        hi = t["nowcast"] + t["uncertainty"]
        self.assertLessEqual(lo, 62.9)
        self.assertGreaterEqual(hi, 77.8)

    def test_endgame_uses_naive(self):
        t = turnout_mixture(
            prior_pp=70.0,
            last_office_pp=62.9,
            recent_federal_pp=78.0,
            naive=76.4,
            reported_frac=0.99,
            n_complete=70,
            brief_visible=True,
        )
        self.assertEqual(t["nowcast"], 76.4)
        self.assertLessEqual(t["uncertainty"], 0.5)


class ExternalBlendTests(unittest.TestCase):
    def test_prognose_replaces_prior_at_zero_count(self):
        prior = _shares({"cdu": 0.20, "spd": 0.15, "gruene": 0.16, "linke": 0.18, "afd": 0.14, "fdp": 0.04, "bsw": 0.05, "others": 0.08})
        unc = {p: 5.0 for p in PARTIES}
        prior_unc = {p: 5.0 for p in PARTIES}
        ext = {
            "kind": "prognose",
            "label": "Prognose Infratest dimap 18:00",
            "frac": _shares({"cdu": 0.22, "spd": 0.14, "gruene": 0.17, "linke": 0.19, "afd": 0.15, "fdp": 0.03, "bsw": 0.04, "others": 0.06}),
            "uncertainty_pp": 1.5,
            "turnout": 68.0,
        }
        blended, bunc, meta = blend_with_external(prior, unc, 0.0, ext, prior_unc)
        self.assertAlmostEqual(blended["cdu"], ext["frac"]["cdu"], places=5)
        self.assertEqual(meta["source"], "prognose")
        self.assertLess(bunc["cdu"], 2.0)

    def test_load_external_picks_latest_hochrechnung(self):
        doc = {
            "be": {
                "sources": [
                    {
                        "kind": "prognose",
                        "institute": "infratest_dimap",
                        "time": "18:00",
                        "shares": {"cdu": 20, "spd": 14, "gru": 16, "lin": 18, "afd": 15, "fdp": 4, "bsw": 5, "oth": 8},
                        "uncertainty_pp": 1.5,
                    },
                    {
                        "kind": "hochrechnung",
                        "institute": "infratest_dimap",
                        "time": "20:15",
                        "shares": {"cdu": 21, "spd": 14, "gru": 16, "lin": 19, "afd": 16, "fdp": 3, "bsw": 4, "oth": 7},
                        "uncertainty_pp": 0.8,
                    },
                ]
            }
        }
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "ext.json"
            p.write_text(json.dumps(doc), encoding="utf-8")
            ext = load_external("be", p)
        self.assertIsNotNone(ext)
        self.assertEqual(ext["kind"], "hochrechnung")
        self.assertGreater(ext["frac"]["linke"], 0.1)

    def test_merge_history_replaces_same_progress(self):
        prev = {"scenarios": {"live": {"steps": [{"clock": "a", "frac_reported": 0.0, "n_reported": 0, "nowcast": {"cdu": 1}}]}}}
        step = {"clock": "b", "frac_reported": 0.0, "n_reported": 0, "nowcast": {"cdu": 2}}
        steps = merge_history(prev, step)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["nowcast"]["cdu"], 2)


class AfsParserTests(unittest.TestCase):
    def test_pxx_and_awk_nummer(self):
        from wahlabend_be_live import parse_afs_aggregate
        from wahlabend_live_common import map_party_columns, AFS_2026_PXX

        cols = ["Adresse", "Gebietsart", "Gebietsname", "Nummer", "AnzWbez", "AusWbez",
                "WberIns", "Waehler", "Gueltig", "P01", "P02", "P03", "P04", "P05", "P06", "P17"]
        mapped = map_party_columns(cols, AFS_2026_PXX)
        self.assertEqual(mapped["cdu"], "P01")
        self.assertEqual(mapped["bsw"], "P17")

        header = ";".join(cols)
        land = "GI9900;Bundesland;Berlin;00;2254;12;2450000;180000;175000;40000;28000;30000;32000;25000;5000;8000"
        wk = "AI0101;Abgeordnetenhauswahlkreis;Mitte 1;0101;51;4;32000;21000;20000;4500;3000;4000;3500;2800;400;900"
        bez = "VI0100;Bezirk;Mitte;01;200;10;180000;120000;115000;20000;15000;18000;22000;14000;3000;5000"
        skip = "BT0074;Bundestagswahlkreis;Berlin-Mitte;74;0;0;0;0;0;0;0;0;0;0;0;0"
        text = header + "\n" + wk + "\n" + bez + "\n" + skip + "\n" + land + "\n"
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.csv"
            p.write_text(text, encoding="utf-8")
            parsed = parse_afs_aggregate(p)
        self.assertEqual(parsed["kind"], "Z")
        self.assertGreater(parsed["land"]["gueltig"], 0)
        self.assertIn("1", parsed["wkr"])
        self.assertAlmostEqual(parsed["wkr"]["1"]["counts"]["cdu"], 4500)
        self.assertAlmostEqual(parsed["wkr"]["1"]["counts"]["bsw"], 900)
        self.assertEqual(parsed["wkr"]["1"]["ist"], 4)
        self.assertEqual(parsed["wkr"]["1"]["soll"], 51)
        self.assertIn("01", parsed["bezirk"])
        self.assertNotIn("74", parsed["wkr"])

    def test_real_testdata_stays_empty_or_parses_wkr(self):
        from wahlabend_be_live import LIVE_DIR, parse_afs_aggregate

        path = LIVE_DIR / "Datenexport_AGH2026_Zweitstimme_A_BE.csv"
        if not path.exists():
            self.skipTest("no live AfS testdata")
        parsed = parse_afs_aggregate(path)
        self.assertTrue(parsed["land"] or parsed["wkr"])
        soll = int((parsed.get("land") or {}).get("soll") or 0)
        if parsed["wkr"]:
            self.assertIn("1", parsed["wkr"])
            soll = max(soll, sum(int(u.get("soll") or 0) for u in parsed["wkr"].values()))
        self.assertGreater(soll, 78)
        if parsed["kind"] != "empty":
            self.assertGreater(parsed["land"]["gueltig"], 0)


class LiveScriptsSmokeTests(unittest.TestCase):
    def test_be_forecast_only(self):
        from wahlabend_be_live import run

        payload = run(None, None)
        self.assertEqual(payload["state"], "be")
        step = payload["scenarios"]["live"]["steps"][-1]
        self.assertIn("cdu", step["nowcast"])
        self.assertGreaterEqual(step["turnout"]["uncertainty"], 8.0)
        self.assertEqual(len(payload["geo_units"]["wkr"]), 78)
        self.assertGreater(payload["n_precincts"], 78)
        self.assertGreater(payload["live"]["soll_wb"], 78)
        self.assertEqual(payload["live"]["soll_wkr"], 78)
        self.assertTrue(payload["features"]["bezirkslisten"])
        self.assertIn("bsw", step["nowcast"])
        self.assertGreater(step["nowcast"]["bsw"], 0)

    def test_mv_forecast_only(self):
        from wahlabend_mv_live import run

        payload = run(None, None)
        self.assertEqual(payload["state"], "mv")
        step = payload["scenarios"]["live"]["steps"][-1]
        self.assertIn("spd", step["nowcast"])
        self.assertGreaterEqual(step["turnout"]["uncertainty"], 8.0)
        self.assertEqual(len(payload["geo_units"]["wkr"]), 36)
        self.assertGreater(payload["n_precincts"], 36)
        self.assertGreater(payload["live"]["soll_wb"], 36)
        self.assertEqual(payload["live"]["soll_wkr"], 36)
        self.assertIn("bsw", step["nowcast"])
        self.assertGreater(step["nowcast"]["bsw"], 0)


if __name__ == "__main__":
    unittest.main()
