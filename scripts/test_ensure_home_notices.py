#!/usr/bin/env python3
"""Tests for scripts/ensure_home_notices.py"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import ensure_home_notices as ehn  # noqa: E402

HEAD = """{{- /* Cookie-less pageview ping. Counts zweitstimme.org and the GitHub Pages preview. */ -}}
{{- if or .Params.robotsNoIndex .Params.liveMode }}
<meta name="robots" content="noindex, nofollow, noarchive">
{{- end }}
"""

HOME_INFO = """        <p id="home-recent-polls" class="home-recent-polls" hidden></p>
      </div>
    </div>
  </section>

{{- if $homeShowForecasts }}
<section id="vorhersage-section"{{- if eq (mod (int ($homeLayout.Get "i")) 2) 0 }} class="section-alt"{{- end }}>
  {{- $homeLayout.Add "i" 1 -}}
  <div class="content-wrapper">
    <h2 class="home-section-title">Vorhersagen</h2>
"""


class EnsureHomeNoticesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.website = Path(self.tmp.name) / "website"
        self.integration = Path(self.tmp.name) / "integration"
        (self.website / "layouts" / "partials").mkdir(parents=True)
        (self.website / "themes" / "PaperMod" / "layouts" / "partials").mkdir(parents=True)
        (self.website / "assets" / "css" / "extended").mkdir(parents=True)
        (self.integration / "data").mkdir(parents=True)
        (self.integration / "layouts" / "partials").mkdir(parents=True)
        (self.integration / "static" / "js").mkdir(parents=True)
        (self.website / "layouts" / "partials" / "extend_head.html").write_text(HEAD)
        (self.website / "themes" / "PaperMod" / "layouts" / "partials" / "home_info_de.html").write_text(
            HOME_INFO
        )
        (self.website / "assets" / "css" / "extended" / "custom.css").write_text("body { margin: 0; }\n")
        (self.integration / "data" / "home_notices.json").write_text('{"notices":[]}\n')
        (self.integration / "layouts" / "partials" / "home_notices.html").write_text("banner\n")
        (self.integration / "static" / "js" / "home-notices.js").write_text("/* js */\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_restores_dropped_includes(self):
        actions = ehn.ensure(self.website, self.integration)
        self.assertTrue(any("extend_head" in a for a in actions))
        head = (self.website / "layouts" / "partials" / "extend_head.html").read_text()
        self.assertIn("home-notices.js", head)
        self.assertTrue(head.startswith("{{- /* Cookie-less pageview ping."))
        home = (
            self.website / "themes" / "PaperMod" / "layouts" / "partials" / "home_info_de.html"
        ).read_text()
        self.assertIn('{{ partial "home_notices.html" . }}', home)
        css = (self.website / "assets" / "css" / "extended" / "custom.css").read_text()
        self.assertIn(".home-eval-banner", css)
        self.assertTrue((self.website / "data" / "home_notices.json").is_file())
        self.assertTrue((self.website / "static" / "js" / "home-notices.js").is_file())

    def test_idempotent_when_already_present(self):
        ehn.ensure(self.website, self.integration)
        again = ehn.ensure(self.website, self.integration)
        self.assertTrue(any(a.startswith("copied ") for a in again))
        self.assertFalse(any("patched" in a for a in again))


if __name__ == "__main__":
    unittest.main()
