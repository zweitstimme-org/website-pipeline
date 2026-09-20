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
    read_csv_rows,
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
                "WberIns", "Waehler", "Gueltig", "P01", "P02", "P03", "P04", "P05", "P06", "P24"]
        mapped = map_party_columns(cols, AFS_2026_PXX)
        self.assertEqual(mapped["cdu"], "P01")
        self.assertEqual(mapped["bsw"], "P24")

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

    def test_ankunftstafel_ids(self):
        from wahlabend_be_live import ankunft_to_addr, parse_ankunftstafel
        from wahlabend_live_common import clock_from_fields

        self.assertEqual(ankunft_to_addr("12404"), "12W404")
        self.assertEqual(ankunft_to_addr("085E"), "08B5E")
        html = """
        <div class="card_header">Ankunftstafel</div>
        <th data-sort="12404 - Grundschule in den Rollbergen">12404 - Grundschule</th>
        <td><a href="ergebnisse_wahlkreis_1204.html">1204 - Reinickendorf 4</a></td>
        <td data-sort="19:50">19:50</td>
        <th data-sort="085E - Briefwahlzentrum Otto-Hahn-Schule">085E</th>
        <td><a href="ergebnisse_wahlkreis_0805.html">0805 - Neukölln 5</a></td>
        <td data-sort="19:50">19:50</td>
        """
        rows = parse_ankunftstafel(html)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["id"], "12404")
        self.assertEqual(rows[0]["addr"], "12W404")
        self.assertEqual(rows[0]["awk"], "1204")
        self.assertEqual(rows[1]["art"], "B")
        self.assertEqual(clock_from_fields("26.09.20", "19:50:45"), "2026-09-20 19:50")


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


LAIV_WK_CSV = """Wahl zum Landtag von Mecklenburg-Vorpommern am 20. September 2026
Zwischenergebnis der Wahlkreise am 20.09.2026 um 19:15:49 Uhr - Stimmenanzahl der Parteien
(c) Der Landeswahlleiter Mecklenburg-Vorpommern

Berechnungsdatum;Ausgabe;Wahlkreis;Wahlkreisname/Land;Wahlbezirke insg.;Erf. Wahlbezirke;Wahlberechtigte;Wähler;Wahlbeteiligung;Erst-/Zweitstimme;Ungültige Stimmen;Gültige Stimmen;SPD;AfD;CDU;Die Linke;GRÜNE;FDP;BSW
20.09.2026 19:15:49;A;1;Greifswald;60;3;1790;914;51,1;1;11;903;340;340;41;83;34;21;40
20.09.2026 19:15:49;P;1;Greifswald;60;3;1790;914;51,1;1;1,2;98,8;37,7;37,7;4,5;9,2;3,8;2,3;4,4
20.09.2026 19:15:49;A;1;Greifswald;60;3;1790;914;51,1;2;8;906;300;400;50;70;30;16;40
20.09.2026 19:15:49;P;1;Greifswald;60;3;1790;914;51,1;2;0,9;99,1;33,1;44,2;5,5;7,7;3,3;1,8;4,4
20.09.2026 19:15:49;A;2;Neubrandenburg I;50;0;0;0;x;1;0;0;0;0;0;0;0;0;0
20.09.2026 19:15:49;P;2;Neubrandenburg I;50;0;0;0;x;1;0;0;0,0;0,0;0,0;0,0;0,0;0,0;0,0
20.09.2026 19:15:49;A;2;Neubrandenburg I;50;0;0;0;x;2;0;0;0;0;0;0;0;0;0
20.09.2026 19:15:49;P;2;Neubrandenburg I;50;0;0;0;x;2;0;0;0,0;0,0;0,0;0,0;0,0;0,0;0,0
20.09.2026 19:15:49;A;99;Mecklenburg-Vorpommern;110;3;1790;914;51,1;2;8;906;300;400;50;70;30;16;40
20.09.2026 19:15:49;P;99;Mecklenburg-Vorpommern;110;3;1790;914;51,1;2;0,9;99,1;33,1;44,2;5,5;7,7;3,3;1,8;4,4
"""

LAIV_WB_CSV = """Wahl zum Landtag von Mecklenburg-Vorpommern am 20. September 2026
Zwischenergebnis der Wahlbezirke am 20.09.2026 um 19:15:49 Uhr - Stimmenanzahl der Parteien
(c) Der Landeswahlleiter

Berechnungsdatum;Ausgabe;Kreis;Kreisname;Wahlkreis;Wahlkreisname;Amt;Amtsname;Gemeinde;Gemeindename;Wahlbezirk;Wahlbezirksname;Wahlberechtigte;Wähler;Wahlbeteiligung;Erst-/Zweitstimme;Ungültige Stimmen;Gültige Stimmen;SPD;AfD;CDU;Die Linke;GRÜNE;FDP;BSW
20.09.2026 19:15:49;A;3;Rostock;4;Rostock I;1;Rostock;13003000;Rostock;1;1/Rostock;0;0;x;2;0;0;0;0;0;0;0;0;0
20.09.2026 19:15:49;P;3;Rostock;4;Rostock I;1;Rostock;13003000;Rostock;1;1/Rostock;0;0;x;2;0;0;0,0;0,0;0,0;0,0;0,0;0,0;0,0
20.09.2026 19:15:49;A;7;Seenplatte;16;Neubrandenburg I;2;Amt;13071001;Alte Gemeinde;1;1/Dorf;400;280;70,0;2;4;276;80;120;20;18;10;8;20
20.09.2026 19:15:49;P;7;Seenplatte;16;Neubrandenburg I;2;Amt;13071001;Alte Gemeinde;1;1/Dorf;400;280;70,0;2;1,4;98,6;29,0;43,5;7,2;6,5;3,6;2,9;7,2
"""


class LaivCsvParseTests(unittest.TestCase):
    def _write(self, td: str, name: str, text: str) -> Path:
        p = Path(td) / name
        p.write_text(text, encoding="cp1252")
        return p

    def test_skips_wahlkreise_title_line(self):
        with tempfile.TemporaryDirectory() as td:
            p = self._write(td, "l_wahlkreise.csv", LAIV_WK_CSV)
            rows, cols = read_csv_rows(p)
        self.assertIn("Wahlkreis", cols)
        self.assertIn("SPD", cols)
        self.assertGreaterEqual(len(rows), 4)

    def test_wk_uses_absolute_zweit_and_erf_soll(self):
        from wahlabend_mv_live import parse_laiv_units

        with tempfile.TemporaryDirectory() as td:
            p = self._write(td, "l_wahlkreise.csv", LAIV_WK_CSV)
            wkr = parse_laiv_units(p, key_fields=("wahlkreis", "wk-nr", "wk"))
        self.assertEqual(wkr["1"]["gueltig"], 906)
        self.assertEqual(wkr["1"]["counts"]["afd"], 400)
        self.assertEqual(wkr["1"]["counts"]["spd"], 300)
        self.assertEqual(wkr["1"]["ist"], 3)
        self.assertEqual(wkr["1"]["soll"], 60)
        self.assertEqual(wkr["1"]["erst_gueltig"], 903)
        self.assertEqual(wkr["2"]["gueltig"], 0)
        self.assertEqual(wkr["2"]["soll"], 50)
        self.assertEqual(wkr["99"]["ist"], 3)
        self.assertEqual(wkr["99"]["soll"], 110)
        self.assertIsNone(wkr["99"]["wkr"])

    def test_precinct_keys_do_not_collide(self):
        from wahlabend_mv_live import parse_laiv_units

        with tempfile.TemporaryDirectory() as td:
            p = self._write(td, "l_wahlbezirke.csv", LAIV_WB_CSV)
            wb = parse_laiv_units(p, key_fields=("wahlbezirk", "wbz"))
        self.assertEqual(len(wb), 2)
        counted = [u for u in wb.values() if u["gueltig"] > 0]
        self.assertEqual(len(counted), 1)
        self.assertEqual(counted[0]["gueltig"], 276)
        self.assertEqual(counted[0]["wkr"], "16")


if __name__ == "__main__":
    unittest.main()
