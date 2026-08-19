#!/usr/bin/env python3
"""Patch Hugo config.toml footer: Forecast API + Polling API + LinkedIn."""

from __future__ import annotations

import re
import sys
from pathlib import Path

POLLING_URL = "https://api.zweitstimme.org/docs"
POLLING_ENTRY = (
    "\n"
    '      [[languages.de.menu.footer]]\n'
    '      name = "Polling API"\n'
    f'      url = "{POLLING_URL}"\n'
    "      weight = 35\n"
)
LINKEDIN_URL = "https://www.linkedin.com/company/zweitstimme-org"
LINKEDIN_ENTRY = (
    "\n"
    '      [[languages.de.menu.footer]]\n'
    '      name = "LinkedIn"\n'
    f'      url = "{LINKEDIN_URL}"\n'
    "      weight = 45\n"
)
SOCIAL_ICON_BLOCK = re.compile(
    r'(  \[\[params\.socialIcons\]\]\n'
    r'  name = "(?P<name>[^"]+)"\n'
    r'  url = "(?P<url>[^"]*)"\n)'
)
LINKEDIN_SOCIAL_ENTRY = (
    "\n"
    "  [[params.socialIcons]]\n"
    '  name = "linkedin"\n'
    f'  url = "{LINKEDIN_URL}"\n'
)
FOOTER_BLOCK = re.compile(
    r'(      \[\[languages\.de\.menu\.footer\]\]\n'
    r'      name = "(?P<name>[^"]+)"\n'
    r'      url = "(?P<url>[^"]*)"\n'
    r'      weight = (?P<weight>\d+)\n)'
)


def _ensure_forecast_api(text: str, notes: list[str]) -> str:
    new, n = re.subn(
        r'name\s*=\s*"API"(\s*\n\s*url\s*=\s*")(?:/api"|/docs/api")',
        r'name = "Forecast API"\1/docs/api"',
        text,
        count=1,
    )
    if n:
        notes.append("Forecast API @ /docs/api")
        return new
    new, n = re.subn(
        r'(name\s*=\s*"Forecast API"\s*\n\s*url\s*=\s*)"/api"',
        r'\1"/docs/api"',
        text,
        count=1,
    )
    if n:
        notes.append("Forecast API url → /docs/api")
        return new
    return text


def _ensure_polling_api(text: str, notes: list[str]) -> str:
    match = None
    for m in FOOTER_BLOCK.finditer(text):
        if m.group("name") == "Polling API":
            match = m
            break
    if match:
        if match.group("url") == POLLING_URL:
            notes.append("Polling API already set")
            return text
        start, end = match.span("url")
        notes.append("Polling API url updated")
        return text[:start] + POLLING_URL + text[end:]

    insert_at = None
    for m in FOOTER_BLOCK.finditer(text):
        if m.group("name") == "Forecast API":
            insert_at = m.end()
            break
    if insert_at is None:
        for m in FOOTER_BLOCK.finditer(text):
            if m.group("name") == "Impressum":
                insert_at = m.end()
                break
    if insert_at is None:
        notes.append("Polling API not added (footer menu not found)")
        return text

    notes.append("Polling API added")
    return text[:insert_at] + POLLING_ENTRY + text[insert_at:]


def _ensure_linkedin_footer(text: str, notes: list[str]) -> str:
    match = None
    for m in FOOTER_BLOCK.finditer(text):
        if m.group("name") == "LinkedIn":
            match = m
            break
    if match:
        if match.group("url") == LINKEDIN_URL:
            notes.append("LinkedIn already set")
            return text
        start, end = match.span("url")
        notes.append("LinkedIn url updated")
        return text[:start] + LINKEDIN_URL + text[end:]

    insert_at = None
    for m in FOOTER_BLOCK.finditer(text):
        if m.group("name") == "Twitter":
            insert_at = m.end()
            break
    if insert_at is None:
        for m in FOOTER_BLOCK.finditer(text):
            if m.group("name") == "Github":
                insert_at = m.start()
                break
    if insert_at is None:
        notes.append("LinkedIn not added (footer menu not found)")
        return text

    notes.append("LinkedIn added")
    return text[:insert_at] + LINKEDIN_ENTRY + text[insert_at:]


def _ensure_linkedin_social_icon(text: str, notes: list[str]) -> str:
    match = None
    for m in SOCIAL_ICON_BLOCK.finditer(text):
        if m.group("name").lower() == "linkedin":
            match = m
            break
    if match:
        if match.group("url") == LINKEDIN_URL:
            notes.append("LinkedIn icon already set")
            return text
        start, end = match.span("url")
        notes.append("LinkedIn icon url updated")
        return text[:start] + LINKEDIN_URL + text[end:]

    insert_at = None
    for m in SOCIAL_ICON_BLOCK.finditer(text):
        if m.group("name").lower() == "twitter":
            insert_at = m.end()
            break
    if insert_at is None:
        last = None
        for m in SOCIAL_ICON_BLOCK.finditer(text):
            last = m
        if last is not None:
            insert_at = last.end()
    if insert_at is None:
        notes.append("LinkedIn icon not added (socialIcons not found)")
        return text

    notes.append("LinkedIn icon added")
    return text[:insert_at] + LINKEDIN_SOCIAL_ENTRY + text[insert_at:]


def patch(text: str) -> tuple[str, list[str]]:
    notes: list[str] = []
    text = _ensure_forecast_api(text, notes)
    text = _ensure_polling_api(text, notes)
    text = _ensure_linkedin_footer(text, notes)
    text = _ensure_linkedin_social_icon(text, notes)
    return text, notes


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: patch_hugo_footer.py <config.toml>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    original = path.read_text(encoding="utf-8")
    updated, notes = patch(original)
    if updated != original:
        path.write_text(updated, encoding="utf-8")
    print("Footer: " + ("; ".join(notes) if notes else "no changes"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
