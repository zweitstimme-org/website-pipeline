#!/usr/bin/env python3
"""Keep homepage evaluation banners on website-source across Stimmung publishes.

Daily Stimmung copies extend_head.html and sometimes home_info_de.html from git
main, which historically did not include the banner. This script runs after those
copies and:

- copies home_notices.json / home_notices.html / home-notices.js when present
- re-inserts the homepage script+CSS into extend_head.html if a publish dropped it
- re-inserts the Hugo partial into home_info_de.html if that file was overwritten
- appends banner CSS to custom.css when missing
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

HEAD_MARKER = "home-notices.js"
PARTIAL_MARKER = "home_notices.html"
CSS_MARKER = "home-eval-banner"

HEAD_SNIPPET = """\
{{- /* Homepage banners: keep this in extend_head so Stimmung cannot drop it. */ -}}
{{- if .IsHome }}
<style>
.home-eval-banners{max-width:700px;margin:0 auto 1.15rem}
.home-eval-banner{margin:0 0 .55rem;padding:.7rem 1rem;border:1px solid #e6e6e6;border-left:3px solid var(--primary,#3a4654);border-radius:0 8px 8px 0;background:#f6f7f8;text-align:center;font-size:.95rem;line-height:1.4}
.home-eval-banner:last-child{margin-bottom:0}
.home-eval-banner a{color:var(--primary);font-weight:600;text-decoration:none!important}
.home-eval-banner a:hover,.home-eval-banner a:focus-visible{text-decoration:underline!important}
</style>
<script src="{{ "js/home-notices.js" | relURL }}" defer></script>
{{- end }}
"""

CSS_BLOCK = """
/* Homepage banners — restored by scripts/ensure_home_notices.py */
.home-eval-banners {
    max-width: 700px;
    margin: 0 auto 1.15rem;
}
.home-eval-banner {
    margin: 0 0 0.55rem;
    padding: 0.7rem 1rem;
    border: 1px solid #e6e6e6;
    border-left: 3px solid var(--primary, #3a4654);
    border-radius: 0 8px 8px 0;
    background: #f6f7f8;
    text-align: center;
    font-size: 0.95rem;
    line-height: 1.4;
}
.home-eval-banner:last-child { margin-bottom: 0; }
.home-eval-banner--quiet {
    padding: 0.45rem 1rem;
    font-size: 0.88rem;
    background: transparent;
}
.home-eval-banner a {
    color: var(--primary);
    font-weight: 600;
    text-decoration: none !important;
}
.home-eval-banner a:hover,
.home-eval-banner a:focus-visible {
    text-decoration: underline !important;
}
"""

VORHERSAGE_NEEDLE = """\
<section id="vorhersage-section"{{- if eq (mod (int ($homeLayout.Get "i")) 2) 0 }} class="section-alt"{{- end }}>
  {{- $homeLayout.Add "i" 1 -}}
  <div class="content-wrapper">
    <h2 class="home-section-title">Vorhersagen</h2>"""

VORHERSAGE_REPL = """\
<section id="vorhersage-section"{{- if eq (mod (int ($homeLayout.Get "i")) 2) 0 }} class="section-alt"{{- end }}>
  {{- $homeLayout.Add "i" 1 -}}
  <div class="content-wrapper">
    {{ partial "home_notices.html" . }}
    <h2 class="home-section-title">Vorhersagen</h2>"""

INTRO_NEEDLE = """\
        <p id="home-recent-polls" class="home-recent-polls" hidden></p>
      </div>"""

INTRO_REPL = """\
        <p id="home-recent-polls" class="home-recent-polls" hidden></p>
        {{- if not $homeShowForecasts }}
        {{ partial "home_notices.html" . }}
        {{- end }}
      </div>"""


def _copy_if_exists(src: Path, dest: Path) -> bool:
    if not src.is_file():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return True


def copy_notice_files(integration: Path, website: Path) -> list[str]:
    actions = []
    files = [
        (integration / "data" / "home_notices.json", website / "data" / "home_notices.json"),
        (integration / "data" / "home_notices.json", website / "static" / "data" / "home_notices.json"),
        (integration / "layouts" / "partials" / "home_notices.html", website / "layouts" / "partials" / "home_notices.html"),
        (integration / "static" / "js" / "home-notices.js", website / "static" / "js" / "home-notices.js"),
    ]
    for src, dest in files:
        if _copy_if_exists(src, dest):
            actions.append(f"copied {dest.relative_to(website)}")
    return actions


def ensure_extend_head(path: Path) -> str | None:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    if HEAD_MARKER in text:
        return None
    # Keep the pixel comment first when present; otherwise prepend.
    comment = "{{- /* Cookie-less pageview ping. Counts zweitstimme.org and the GitHub Pages preview. */ -}}\n"
    if text.startswith(comment):
        updated = comment + HEAD_SNIPPET + text[len(comment) :]
    else:
        updated = HEAD_SNIPPET + text
    path.write_text(updated, encoding="utf-8")
    return f"patched {path.name} (script include)"


def ensure_home_info(path: Path) -> list[str]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    updated = text
    actions = []
    if VORHERSAGE_NEEDLE in updated:
        updated = updated.replace(VORHERSAGE_NEEDLE, VORHERSAGE_REPL, 1)
        actions.append("vorhersage partial")
    if INTRO_NEEDLE in updated:
        updated = updated.replace(INTRO_NEEDLE, INTRO_REPL, 1)
        actions.append("intro partial")
    if updated == text:
        return []
    path.write_text(updated, encoding="utf-8")
    return [f"patched {path.name} ({', '.join(actions)})"]


def ensure_custom_css(path: Path) -> str | None:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    if CSS_MARKER in text:
        return None
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(text + CSS_BLOCK, encoding="utf-8")
    return f"patched {path.name} (banner CSS)"


def ensure(website: Path, integration: Path | None = None) -> list[str]:
    actions: list[str] = []
    if integration is not None:
        actions.extend(copy_notice_files(integration, website))
    head = ensure_extend_head(website / "layouts" / "partials" / "extend_head.html")
    if head:
        actions.append(head)
    actions.extend(
        ensure_home_info(
            website / "themes" / "PaperMod" / "layouts" / "partials" / "home_info_de.html"
        )
    )
    css = ensure_custom_css(website / "assets" / "css" / "extended" / "custom.css")
    if css:
        actions.append(css)
    return actions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--website-dir", required=True, type=Path)
    parser.add_argument("--integration", type=Path, default=None)
    args = parser.parse_args(argv)
    website = args.website_dir.resolve()
    integration = args.integration.resolve() if args.integration else None
    if not website.is_dir():
        print(f"website dir not found: {website}", file=sys.stderr)
        return 1
    actions = ensure(website, integration)
    if actions:
        for line in actions:
            print(f"home_notices: {line}")
    else:
        print("home_notices: already present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
