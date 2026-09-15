#!/usr/bin/env python3
"""Tests for scripts/ensure_frozen_forecast_pages.py"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import ensure_frozen_forecast_pages as efp  # noqa: E402

DISTRICT = """
<div class="district-preview-targets" id="district-preview-targets">
  <button type="button" class="state-arm visible district-preview-target is-active selected" data-code="ST" aria-pressed="true">
    <div class="state-arm-name">Sachsen-Anhalt</div>
  </button>
  <button type="button" class="state-arm visible district-preview-target" data-code="BE" aria-pressed="false">
    <div class="state-arm-name">Berlin</div>
  </button>
  <button type="button" class="state-arm visible district-preview-target" data-code="MV" aria-pressed="false">
    <div class="state-arm-name">Mecklenburg-Vorpommern</div>
  </button>
</div>
<script>
  let initial = 'ST';
  if (['MV', 'ST', 'BE'].includes(st)) initial = st;
</script>
"""

ENTRY_JS = """
  const STATES = [
    { code: "ST", label: "Sachsen-Anhalt", date: "06.09.2026" },
    { code: "BE", label: "Berlin", date: "20.09.2026" },
    { code: "MV", label: "Mecklenburg-Vorpommern", date: "20.09.2026" },
  ];
  let stateCode = String(params.get("state") || "ST").toUpperCase();
  if (!states[stateCode]) stateCode = STATES.find((s) => states[s.code])?.code || "ST";
"""


class EnsureFrozenForecastPagesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.website = Path(self.tmp.name) / "website"
        (self.website / "themes" / "PaperMod" / "layouts" / "partials").mkdir(parents=True)
        (self.website / "static" / "js").mkdir(parents=True)
        (self.website / "static" / "data").mkdir(parents=True)
        (self.website / "themes" / "PaperMod" / "layouts" / "partials" / "district_forecast_map.html").write_text(
            DISTRICT
        )
        (self.website / "static" / "js" / "candidate-entry.js").write_text(ENTRY_JS)
        (self.website / "static" / "data" / "display_mode.json").write_text(
            json.dumps(
                {
                    "homepage_hide": [{"state_code": "ST", "election_date": "2026-09-06"}],
                    "archive": {
                        "forecasts": [
                            {
                                "key": "st_2026-09-06",
                                "scope": "state",
                                "state_code": "ST",
                            }
                        ]
                    },
                }
            )
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_strips_st_from_wahlkreise_and_einzug(self):
        actions = efp.ensure(self.website)
        self.assertTrue(any("district_forecast_map.html" in a for a in actions))
        self.assertTrue(any("candidate-entry.js" in a for a in actions))
        html = (
            self.website
            / "themes"
            / "PaperMod"
            / "layouts"
            / "partials"
            / "district_forecast_map.html"
        ).read_text()
        self.assertNotIn('data-code="ST"', html)
        self.assertIn('data-code="BE"', html)
        self.assertIn("is-active", html)
        self.assertNotIn("let initial = 'ST'", html)
        self.assertNotIn("'ST'", html)
        js = (self.website / "static" / "js" / "candidate-entry.js").read_text()
        self.assertNotIn('code: "ST"', js)
        self.assertIn('code: "BE"', js)
        self.assertIn('params.get("state") || "BE"', js)
        self.assertIn('?.code || "BE"', js)

    def test_idempotent_when_already_stripped(self):
        efp.ensure(self.website)
        again = efp.ensure(self.website)
        self.assertEqual(again, [])

    def test_keeps_archive_states_list(self):
        js = (
            '  const LIVE_STATES = [\n'
            '    { code: "ST", label: "Sachsen-Anhalt", date: "06.09.2026" },\n'
            '    { code: "BE", label: "Berlin", date: "20.09.2026" },\n'
            '  ];\n'
            '  const ARCHIVE_STATES = [\n'
            '    { code: "ST", label: "Sachsen-Anhalt", date: "06.09.2026" },\n'
            '  ];\n'
        )
        (self.website / "static" / "js" / "candidate-entry.js").write_text(js)
        efp.ensure(self.website)
        out = (self.website / "static" / "js" / "candidate-entry.js").read_text()
        live, archive = out.split("const ARCHIVE_STATES", 1)
        self.assertNotIn('code: "ST"', live)
        self.assertIn('code: "ST"', archive)


if __name__ == "__main__":
    unittest.main()
