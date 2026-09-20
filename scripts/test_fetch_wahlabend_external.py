#!/usr/bin/env python3
"""Tests for wahlrecht.de Prognose/Hochrechnung scrape."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_wahlabend_external as fwe  # noqa: E402

MV_HTML = """
<table>
<tr id="wahlergebnis_2021" title="Ergebnis der Landtagswahl 2021">
 <td class="l" colspan="3">Landtagswahl 2021 (zum Vergleich)</td>
 <td class="r" title="Stimmanteil – SPD">39,6 %</td>
</tr>
<tr id="ard_18-00" title="18-Uhr-Prognose Infratest dimap">
 <th class="l">18:00</th><th class="l">ARD</th><th class="l">Infratest dimap</th>
 <td class="r" title="Stimmanteil – SPD">35,5 %</td>
 <td class="r" title="Stimmanteil – AfD">37,0 %</td>
 <td class="r" title="Stimmanteil – CDU">5,5 %</td>
 <td class="r" title="Stimmanteil – DIE LINKE">7,5 %</td>
 <td class="r" title="Stimmanteil – GRÜNE">5,5 %</td>
 <td class="r" title="Stimmanteil – FDP">1,2 %</td>
 <td class="r" title="Stimmanteil – BSW">5,0 %</td>
 <td class="r" title="Stimmanteil – Sonstige">2,8 %</td>
</tr>
<tr id="zdf_18-00" title="18-Uhr-Prognose Forschungsgruppe Wahlen">
 <th class="l">18:00</th><th class="l">ZDF</th>
 <th class="l" title="Forschungsgruppe Wahlen">Forsch’gr. Wahlen <a href="#fn0">[A]</a></th>
 <td class="r" title="Stimmanteil – SPD">36,5 %</td>
 <td class="r" title="Stimmanteil – AfD">38,0 %</td>
 <td class="r" title="Stimmanteil – CDU">5,0 %</td>
 <td class="r" title="Stimmanteil – DIE LINKE">6,0 %</td>
 <td class="r" title="Stimmanteil – GRÜNE">5,5 %</td>
 <td class="r" title="Stimmanteil – FDP">1,0 %</td>
 <td class="r" title="Stimmanteil – BSW">4,8 %</td>
 <td class="r" title="Stimmanteil – Sonstige">3,2 %</td>
</tr>
<tr id="zdf_18-27" title="18:27-Uhr-Hochrechnung Forschungsgruppe Wahlen">
 <th class="l">18:27</th><th class="l">ZDF</th>
 <th class="l" title="Forschungsgruppe Wahlen">Forsch’gr. Wahlen</th>
 <td class="r" title="Stimmanteil – SPD">36,3 %</td>
 <td class="r" title="Stimmanteil – AfD">37,8 %</td>
 <td class="r" title="Stimmanteil – CDU">5,1 %</td>
 <td class="r" title="Stimmanteil – DIE LINKE">6,2 %</td>
 <td class="r" title="Stimmanteil – GRÜNE">5,5 %</td>
 <td class="r" title="Stimmanteil – FDP">1,0 %</td>
 <td class="r" title="Stimmanteil – BSW">4,8 %</td>
 <td class="r" title="Stimmanteil – Sonstige">3,3 %</td>
</tr>
<tr id="ard_18-28" title="18:28-Uhr-Hochrechnung Infratest dimap">
 <th class="l">18:28</th><th class="l">ARD</th><th class="l">Infratest dimap</th>
 <td class="r" title="Stimmanteil – SPD">35,6 %</td>
 <td class="r" title="Stimmanteil – AfD">37,1 %</td>
 <td class="r" title="Stimmanteil – CDU">5,4 %</td>
 <td class="r" title="Stimmanteil – DIE LINKE">7,4 %</td>
 <td class="r" title="Stimmanteil – GRÜNE">5,5 %</td>
 <td class="r" title="Stimmanteil – FDP">1,1 %</td>
 <td class="r" title="Stimmanteil – BSW">5,0 %</td>
 <td class="r" title="Stimmanteil – Sonstige">2,9 %</td>
</tr>
</table>
"""


class ParseWahlrechtTests(unittest.TestCase):
    def test_skips_result_and_alt_seat_rows(self):
        rows = fwe.parse_wahlrecht_rows(MV_HTML)
        keys = [(r["kind"], r["publisher"], r["time"]) for r in rows]
        self.assertEqual(
            keys,
            [
                ("prognose", "ARD", "18:00"),
                ("hochrechnung", "ZDF", "18:27"),
                ("hochrechnung", "ARD", "18:28"),
            ],
        )
        zdf = next(r for r in rows if r["time"] == "18:27")
        self.assertEqual(zdf["shares"]["afd"], 37.8)
        self.assertEqual(zdf["shares"]["spd"], 36.3)
        self.assertEqual(zdf["shares"]["lin"], 6.2)
        self.assertEqual(zdf["institute"], "forschungsgruppe_wahlen")

    def test_merge_appends_new_hochrechnung(self):
        existing = [
            {
                "kind": "prognose",
                "publisher": "ARD",
                "time": "18:00",
                "shares": {"spd": 35.5, "afd": 37.0},
                "note": "keep me",
            }
        ]
        scraped = fwe.parse_wahlrecht_rows(MV_HTML)
        merged, added = fwe.merge_state(existing, scraped)
        self.assertEqual(added, 2)
        ard = next(r for r in merged if r["kind"] == "prognose" and r["publisher"] == "ARD")
        self.assertEqual(ard["note"], "keep me")
        self.assertTrue(any(r["kind"] == "hochrechnung" and r["publisher"] == "ZDF" for r in merged))

    def test_run_writes_mv_hochrechnung(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "ext.json"
            dest.write_text(json.dumps({"mv": {"sources": []}, "be": {"sources": []}}), encoding="utf-8")
            summary = fwe.run(dest, html_by_state={"mv": MV_HTML, "be": ""})
            self.assertEqual(summary["mv"]["added"], 3)
            doc = json.loads(dest.read_text(encoding="utf-8"))
            kinds = [s["kind"] for s in doc["mv"]["sources"]]
            self.assertIn("hochrechnung", kinds)


if __name__ == "__main__":
    unittest.main()
