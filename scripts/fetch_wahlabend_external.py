#!/usr/bin/env python3
"""Merge ARD/ZDF Prognose and Hochrechnung from wahlrecht.de into wahlabend_external.json."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data" / "wahlabend_external.json"
UA = "Mozilla/5.0 (compatible; zweitstimme-nowcast/1.0)"

PAGES = {
    "be": "https://www.wahlrecht.de/news/2026/abgeordnetenhauswahl-berlin-2026.html",
    "mv": "https://www.wahlrecht.de/news/2026/landtagswahl-mecklenburg-vorpommern-2026.html",
}

PARTY_TITLE = {
    "spd": "spd",
    "afd": "afd",
    "cdu": "cdu",
    "fdp": "fdp",
    "bsw": "bsw",
    "die linke": "lin",
    "linke": "lin",
    "lin": "lin",
    "grüne": "gru",
    "gruene": "gru",
    "gruen": "gru",
    "gru": "gru",
    "sonstige": "oth",
    "son": "oth",
    "oth": "oth",
}

INSTITUTE = (
    ("infratest", "infratest_dimap"),
    ("forschungsgruppe", "forschungsgruppe_wahlen"),
    ("forsch", "forschungsgruppe_wahlen"),
)

ROW_RE = re.compile(r"<tr\b([^>]*)>(.*?)</tr>", re.I | re.S)
TH_RE = re.compile(r"<th\b[^>]*>(.*?)</th>", re.I | re.S)
TD_SHARE_RE = re.compile(
    r'<td\b[^>]*title="Stimmanteil\s*[–-]\s*([^"]+)"[^>]*>(.*?)</td>',
    re.I | re.S,
)
ATTR_RE = re.compile(r'\b(id|title)="([^"]*)"', re.I)
CLOCK_RE = re.compile(r"\b(\d{1,2}:\d{2})\b")


def _strip(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html or "")


def _pct(text: str) -> float | None:
    raw = _strip(text)
    m = re.search(r"(\d+(?:[.,]\d+)?)", raw.replace("\xa0", " "))
    if not m:
        return None
    return float(m.group(1).replace(",", "."))


def _party(title: str) -> str | None:
    key = re.sub(r"\s+", " ", (title or "").strip().lower())
    key = key.replace("ü", "ue").replace("ä", "ae").replace("ö", "oe")
    if key in PARTY_TITLE:
        return PARTY_TITLE[key]
    for alias, code in PARTY_TITLE.items():
        if alias in key:
            return code
    return None


def _institute(blob: str) -> str:
    low = (blob or "").lower()
    for needle, code in INSTITUTE:
        if needle in low:
            return code
    if "ard" in low:
        return "infratest_dimap"
    if "zdf" in low:
        return "forschungsgruppe_wahlen"
    return ""


def _publisher(ths: list[str], row_id: str) -> str:
    blob = " ".join(ths + [row_id]).lower()
    if "zdf" in blob:
        return "ZDF"
    if "ard" in blob:
        return "ARD"
    return ""


def _kind(title: str, time: str) -> str | None:
    low = (title or "").lower()
    if "hochrechnung" in low:
        return "hochrechnung"
    if "prognose" in low:
        return "prognose"
    if time == "18:00":
        return "prognose"
    if time:
        return "hochrechnung"
    return None


def parse_wahlrecht_rows(html: str) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for attrs, body in ROW_RE.findall(html or ""):
        attr = {k.lower(): v for k, v in ATTR_RE.findall(attrs)}
        title = attr.get("title") or ""
        row_id = attr.get("id") or ""
        if "[A]" in body or "fn0" in body:
            continue
        if "wahlergebnis" in row_id.lower() or "vergleich" in title.lower():
            continue
        shares: dict[str, float] = {}
        for pname, cell in TD_SHARE_RE.findall(body):
            code = _party(pname)
            val = _pct(cell)
            if code and val is not None:
                shares[code] = val
        if sum(shares.values()) <= 50:
            continue
        ths = [_strip(t).replace("\xa0", " ").strip() for t in TH_RE.findall(body)]
        clock = ""
        for bit in ths:
            m = CLOCK_RE.search(bit)
            if m and "XX" not in m.group(1):
                clock = m.group(1)
                break
        if not clock:
            m = CLOCK_RE.search(title) or CLOCK_RE.search(row_id.replace("-", ":"))
            if m and "XX" not in m.group(1):
                clock = m.group(1)
        kind = _kind(title, clock)
        pub = _publisher(ths, row_id)
        if not kind or not pub or not clock:
            continue
        key = (kind, pub, clock)
        if key in seen:
            continue
        seen.add(key)
        inst = _institute(" ".join(ths + [title, row_id]))
        note = f"wahlrecht.de {kind} {pub} {clock}."
        row = {
            "kind": kind,
            "institute": inst or None,
            "publisher": pub,
            "time": clock,
            "shares": shares,
            "note": note,
        }
        if not row["institute"]:
            row.pop("institute")
        out.append(row)
    out.sort(key=lambda r: (0 if r["kind"] == "prognose" else 1, r["time"], r["publisher"]))
    return out


def _src_key(row: dict) -> tuple[str, str, str]:
    return (
        str(row.get("kind") or "").lower(),
        str(row.get("publisher") or "").upper(),
        str(row.get("time") or ""),
    )


def merge_state(existing: list[dict], scraped: list[dict]) -> tuple[list[dict], int]:
    by = {_src_key(s): dict(s) for s in existing if _src_key(s) != ("", "", "")}
    added = 0
    for row in scraped:
        key = _src_key(row)
        if key not in by:
            by[key] = row
            added += 1
    ordered = sorted(
        by.values(),
        key=lambda r: (0 if r.get("kind") == "prognose" else 1, str(r.get("time") or ""), str(r.get("publisher") or "")),
    )
    return ordered, added


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as resp:
        raw = resp.read()
    for enc in ("utf-8", "iso-8859-1", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def load_doc(path: Path) -> dict:
    if not path.exists():
        return {"be": {"sources": []}, "mv": {"sources": []}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"be": {"sources": []}, "mv": {"sources": []}}


def run(dest: Path, html_by_state: dict[str, str] | None = None) -> dict:
    doc = load_doc(dest)
    summary = {}
    for state, url in PAGES.items():
        html = (html_by_state or {}).get(state)
        if html is None:
            html = fetch(url)
        scraped = parse_wahlrecht_rows(html)
        block = doc.get(state) if isinstance(doc.get(state), dict) else {}
        sources = list(block.get("sources") or [])
        merged, added = merge_state(sources, scraped)
        doc[state] = {**block, "sources": merged}
        summary[state] = {"scraped": len(scraped), "added": added, "total": len(merged)}
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dest", nargs="?", type=Path, default=DEST)
    args = ap.parse_args()
    try:
        summary = run(args.dest)
    except Exception as exc:  # noqa: BLE001 — live loop should not abort
        print(f"WARN wahlrecht scrape failed: {exc}", file=sys.stderr)
        raise SystemExit(0)
    bits = [f"{k} +{v['added']}/{v['scraped']} → {v['total']}" for k, v in summary.items()]
    print("external wahlrecht: " + ", ".join(bits))


if __name__ == "__main__":
    main()
