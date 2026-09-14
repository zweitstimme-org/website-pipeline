#!/usr/bin/env python3
"""Keep frozen races off live Wahlkreise / Einzug tiles.

Daily Stimmung copies ``district_forecast_map.html`` and ``candidate-entry.js``
from git main, which can still list Sachsen-Anhalt as a live forecast. Homepage
hide does not cover those subpages. After every publish, strip archived /
editorially hidden states from the live tiles so leftover JSON cannot resurrect
them. Archived maps stay on /archive/posts/vergangene-vorhersagen/.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_OVERRIDES = (
    REPO_ROOT / "website-integration" / "data" / "homepage_overrides.json"
)


def _add_code(codes: set[str], value) -> None:
    c = str(value or "").strip().upper()
    if c and c not in {"BUND", "FEDERAL"}:
        codes.add(c)


def frozen_state_codes(website: Path, integration: Path | None = None) -> set[str]:
    codes: set[str] = set()
    paths = []
    if integration is not None:
        paths.append(integration / "data" / "homepage_overrides.json")
        paths.append(integration / "static" / "data" / "homepage_overrides.json")
    paths.extend(
        [
            INTEGRATION_OVERRIDES,
            website / "data" / "homepage_overrides.json",
            website / "static" / "data" / "homepage_overrides.json",
        ]
    )
    for path in paths:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        rows = payload.get("hide_from_homepage") if isinstance(payload, dict) else None
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    _add_code(codes, row.get("state_code"))

    dm_paths = [
        website / "static" / "data" / "display_mode.json",
        website / "data" / "display_mode.json",
    ]
    if integration is not None:
        dm_paths.append(integration / "static" / "data" / "display_mode.json")
    for path in dm_paths:
        if not path.is_file():
            continue
        try:
            dm = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(dm, dict):
            continue
        for row in dm.get("homepage_hide") or []:
            if isinstance(row, dict):
                _add_code(codes, row.get("state_code"))
        archive = dm.get("archive") if isinstance(dm.get("archive"), dict) else {}
        for row in archive.get("forecasts") or []:
            if isinstance(row, dict) and str(row.get("scope") or "") != "federal":
                _add_code(codes, row.get("state_code"))
        break
    return codes


def _button_re(code: str) -> re.Pattern[str]:
    return re.compile(
        r'<button\b[^>]*\bdata-code=(["\']?)'
        + re.escape(code)
        + r'\1[^>]*>.*?</button>\s*',
        re.I | re.S,
    )


def _state_obj_re(code: str) -> re.Pattern[str]:
    return re.compile(
        r"\s*\{\s*code:\s*\""
        + re.escape(code)
        + r"\"\s*,\s*label:\s*\"[^\"]*\"\s*,\s*date:\s*\"[^\"]*\"\s*\},?\s*"
    )


def _mark_first_button_active(html: str) -> str:
    if re.search(r'data-code=(["\']?)[A-Z]{2}\1[^>]*\bis-active', html, re.I):
        return html

    def repl(match: re.Match[str]) -> str:
        tag = match.group(0)
        if "is-active" not in tag:
            tag = tag.replace(
                "district-preview-target",
                "district-preview-target is-active selected",
                1,
            )
        if 'aria-pressed="false"' in tag:
            tag = tag.replace('aria-pressed="false"', 'aria-pressed="true"', 1)
        return tag

    return re.sub(
        r"<button\b[^>]*\bdistrict-preview-target[^>]*>",
        repl,
        html,
        count=1,
        flags=re.I,
    )


def strip_district_html(text: str, codes: set[str]) -> str:
    updated = text
    for code in sorted(codes):
        updated = _button_re(code).sub("", updated)
        updated = updated.replace(f"let initial = '{code}'", "let initial = 'BE'")
        updated = updated.replace(f'let initial = "{code}"', 'let initial = "BE"')
        updated = re.sub(rf"""(['"]){re.escape(code)}\1\s*,\s*""", "", updated)
        updated = re.sub(rf"""\s*,\s*(['"]){re.escape(code)}\1""", "", updated)
    return _mark_first_button_active(updated)


def _strip_live_state_objects(text: str, codes: set[str]) -> str:
    updated = text
    for code in sorted(codes):
        updated = _state_obj_re(code).sub("\n    ", updated)
        updated = updated.replace(
            f'params.get("state") || "{code}"',
            'params.get("state") || "BE"',
        )
        updated = updated.replace(
            f'?.code || "{code}"',
            '?.code || "BE"',
        )
        updated = updated.replace(
            f"?.code || '{code}'",
            "?.code || 'BE'",
        )
    return updated


def strip_candidate_entry_js(text: str, codes: set[str]) -> str:
    # Leave ARCHIVE_STATES intact; only the live STATES / LIVE_STATES list
    # must not advertise a frozen race.
    marker = "const ARCHIVE_STATES"
    if marker in text:
        head, tail = text.split(marker, 1)
        return _strip_live_state_objects(head, codes) + marker + tail
    return _strip_live_state_objects(text, codes)


def _write_if_changed(path: Path, updated: str, original: str) -> str | None:
    if updated == original:
        return None
    path.write_text(updated, encoding="utf-8")
    return f"patched {path.name}"


def ensure(website: Path, integration: Path | None = None) -> list[str]:
    codes = frozen_state_codes(website, integration)
    if not codes:
        return []
    actions: list[str] = []
    district = (
        website
        / "themes"
        / "PaperMod"
        / "layouts"
        / "partials"
        / "district_forecast_map.html"
    )
    if district.is_file():
        original = district.read_text(encoding="utf-8")
        note = _write_if_changed(district, strip_district_html(original, codes), original)
        if note:
            actions.append(note)
    entry = website / "static" / "js" / "candidate-entry.js"
    if entry.is_file():
        original = entry.read_text(encoding="utf-8")
        note = _write_if_changed(
            entry, strip_candidate_entry_js(original, codes), original
        )
        if note:
            actions.append(note)
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
            print(f"frozen_forecast_pages: {line}")
    else:
        print("frozen_forecast_pages: already absent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
