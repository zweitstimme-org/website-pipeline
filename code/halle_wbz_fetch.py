#!/usr/bin/env python3
"""Scrape Halle (Saale) per-Stimmbezirk election results.

Halle publishes its own live presentation (wahlergebnisse.halle.de) with one
static HTML page per Stimmbezirk (Urne) and Briefwahlbezirk. The state feed
(StaLA) only goes down to Gemeinde level, so this is the sole live source of
within-Halle counting composition (~10% of the state's voters, counted late).

2021 archive uses the SAME Stimmbezirk ids -> --election LTW2021 builds the
baseline file. Party names are stored raw; mapping happens in the nowcast.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

BASE = "https://wahlergebnisse.halle.de"
IDX = {
    "LTW2026": "idx_ergebnisse_gebiet_auswahl_7281729.json",
    "LTW2021": "idx_ergebnisse_gebiet_auswahl_163691.json",
}
UA = "Mozilla/5.0 (compatible; zweitstimme-nowcast/1.0)"
TIMEOUT = 12


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("utf-8", errors="replace")


class _Tables(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._t: list[list[str]] | None = None
        self._r: list[str] | None = None
        self._c: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._t = []
        elif tag == "tr" and self._t is not None:
            self._r = []
        elif tag in ("td", "th") and self._r is not None:
            self._c = []

    def handle_endtag(self, tag):
        if tag == "table" and self._t is not None:
            self.tables.append(self._t)
            self._t = None
        elif tag == "tr" and self._r is not None:
            self._t.append(self._r)
            self._r = None
        elif tag in ("td", "th") and self._c is not None:
            self._r.append(" ".join("".join(self._c).split()))
            self._c = None

    def handle_data(self, d):
        if self._c is not None:
            self._c.append(d)


def _int(s: str) -> int | None:
    s = s.strip().replace(".", "").replace("\xa0", "")
    if not s or s in ("-", "–", "—", "x"):
        return None
    try:
        return int(s)
    except ValueError:
        return None


def parse_page(html: str) -> dict | None:
    """None if not yet counted, else raw party votes + totals."""
    if "Kein Ergebniseingang" in html or "kein Ergebnis im Gebiet" in html:
        return None
    p = _Tables()
    p.feed(html)
    parties: dict[str, dict] = {}
    totals: dict[str, int] = {}
    # Summary rows at the bottom of the party table (not parties)
    summary = {
        "wahlberechtigte": "wber",
        "wähler": "waehler",
        "ungültige stimmen": "ungueltig",
        "gültige stimmen": "gueltig",
    }
    for tb in p.tables:
        if not tb:
            continue
        head = " ".join(tb[0]).lower()
        if "zweitstimmen" in head and "partei" in head:
            for row in tb:
                if len(row) < 6 or not row[0] or row[0] == "Partei":
                    continue
                erst, zweit = _int(row[-4]), _int(row[-2])
                key = summary.get(row[0].strip().lower())
                if key:
                    totals[f"{key}_erst"] = erst
                    totals[f"{key}_zweit"] = zweit
                else:
                    parties[row[0]] = {"erst": erst, "zweit": zweit}
        elif len(tb[0]) == 2:
            for row in tb:
                if len(row) != 2:
                    continue
                v = _int(row[1])
                if v is None:
                    continue
                k = row[0].lower()
                if k.startswith("wahlberechtigte insgesamt"):
                    totals["wber"] = v
                elif k.startswith("wähler insgesamt"):
                    totals["waehler"] = v
    if not parties:
        return None
    g_z = totals.pop("gueltig_zweit", None)
    g_e = totals.pop("gueltig_erst", None)
    out = {
        "parties": parties,
        "gueltig_zweit": g_z if g_z is not None else sum(v["zweit"] or 0 for v in parties.values()),
        "gueltig_erst": g_e if g_e is not None else sum(v["erst"] or 0 for v in parties.values()),
    }
    for src, dst in (("wber_zweit", "wber"), ("waehler_zweit", "waehler")):
        if totals.get(src) is not None:
            out[dst] = totals[src]
    for k in ("wber", "waehler"):
        if k in totals and k not in out:
            out[k] = totals[k]
    return out


def run(election: str, out: Path, workers: int = 8) -> int:
    base = f"{BASE}/{election}"
    idx = json.loads(_get(f"{base}/{IDX[election]}"))["suchindex"]
    units = []
    for e in idx:
        url = e["url"]
        m = re.match(r"ergebnisse_(stimmbezirk|briefwahlbezirk)_(\w+)\.html", url)
        if not m:
            continue
        art = "U" if m.group(1) == "stimmbezirk" else "B"
        units.append({"id": m.group(2), "art": art, "name": e["text"], "url": f"{base}/{url}"})

    def fetch(u: dict) -> tuple[str, dict]:
        rec = {"art": u["art"], "name": u["name"], "counted": False}
        try:
            res = parse_page(_get(u["url"]))
        except Exception as exc:  # noqa: BLE001 - single unit must not kill the poll
            rec["error"] = str(exc)[:120]
            return u["id"], rec
        if res is not None:
            rec.update(res)
            rec["counted"] = True
        return u["id"], rec

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = dict(ex.map(fetch, units))
    n_counted = sum(1 for r in results.values() if r["counted"])
    payload = {
        "election": election,
        "source": base,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_units": len(results),
        "n_counted": n_counted,
        "units": results,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"halle {election}: {n_counted}/{len(results)} units counted -> {out}")
    return 0


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser()
    ap.add_argument("--election", default="LTW2026", choices=list(IDX))
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    out = args.out
    if out is None:
        d = repo / "sachsen-anhalt" / "wahlabend"
        out = (
            d / "live" / "halle_wbz_2026.json"
            if args.election == "LTW2026"
            else d / "raw" / "halle_wbz_2021.json"
        )
    sys.exit(run(args.election, out))


if __name__ == "__main__":
    main()
