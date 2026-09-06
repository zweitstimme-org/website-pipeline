#!/usr/bin/env python3
"""Scrape per-Stimmbezirk election results from city portals (Elect iT).

Halle and Magdeburg publish their own live presentations (identical
"Wahl-Abwicklungs-System" by Elect iT: static HTML, one page per Stimmbezirk /
Briefwahlbezirk plus an area-index JSON). The state feed (StaLA) only goes
down to Gemeinde level, so these are the sole live sources of within-city
counting composition (together ~22% of the state's voters, counted late).

Both portals keep an LTW2021 archive with (mostly) stable Stimmbezirk ids ->
--election LTW2021 builds the baseline files. Party names are stored raw;
mapping happens in the nowcast.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

CITIES = {
    "halle": {
        "base": "https://wahlergebnisse.halle.de",
        "idx": {
            "LTW2026": "idx_ergebnisse_gebiet_auswahl_7281729.json",
            "LTW2021": "idx_ergebnisse_gebiet_auswahl_163691.json",
        },
    },
    "magdeburg": {
        "base": "https://wahlergebnisse.magdeburg.de",
        "idx": {
            "LTW2026": "idx_ergebnisse_gebiet_auswahl_10209262.json",
            "LTW2021": "idx_ergebnisse_gebiet_auswahl_371507.json",
        },
    },
}
UA = "Mozilla/5.0 (compatible; zweitstimme-nowcast/1.0)"
TIMEOUT = 25
RETRIES = 3


def _get(url: str) -> str:
    last: Exception | None = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001 - portals get slow on election night
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise last  # type: ignore[misc]


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
    # Summary rows at the bottom of the party table (not parties). Labels vary
    # by city: Halle "Wähler", Magdeburg "Wähler/Wählerinnen" etc. -> prefixes.
    summary_prefix = (
        ("wahlberechtigte", "wber"),
        ("wähler", "waehler"),
        ("ungültige", "ungueltig"),
        ("gültige", "gueltig"),
    )

    def _summary_key(label: str) -> str | None:
        low = label.strip().lower()
        for pref, key in summary_prefix:
            if low.startswith(pref):
                return key
        return None
    for tb in p.tables:
        if not tb:
            continue
        head = " ".join(tb[0]).lower()
        if "zweitstimmen" in head and "partei" in head:
            for row in tb:
                if len(row) < 6 or not row[0] or row[0] == "Partei":
                    continue
                erst, zweit = _int(row[-4]), _int(row[-2])
                key = _summary_key(row[0])
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
    m = re.search(r"Wahlkreis (\d+)\s*[-–]", html)
    out = {
        "wkr": m.group(1) if m else None,
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


def run(city: str, election: str, out: Path, workers: int = 8) -> int:
    cfg = CITIES[city]
    base = f"{cfg['base']}/{election}"
    idx = json.loads(_get(f"{base}/{cfg['idx'][election]}"))["suchindex"]
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
            # Halle marks uncounted pages "Kein Ergebniseingang"; Magdeburg
            # publishes zero-filled tables instead -> counted means real votes.
            rec["counted"] = bool(res.get("gueltig_zweit") or res.get("gueltig_erst"))
        return u["id"], rec

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = dict(ex.map(fetch, units))
    n_counted = sum(1 for r in results.values() if r["counted"])
    payload = {
        "city": city,
        "election": election,
        "source": base,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_units": len(results),
        "n_counted": n_counted,
        "units": results,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"{city} {election}: {n_counted}/{len(results)} units counted -> {out}")
    return 0


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="all", choices=["all", *CITIES])
    ap.add_argument("--election", default="LTW2026", choices=["LTW2026", "LTW2021"])
    ap.add_argument("--out", type=Path, default=None, help="only valid with a single --city")
    args = ap.parse_args()
    cities = list(CITIES) if args.city == "all" else [args.city]
    d = repo / "sachsen-anhalt" / "wahlabend"
    rc = 0
    for city in cities:
        out = args.out
        if out is None or len(cities) > 1:
            out = (
                d / "live" / f"{city}_wbz_2026.json"
                if args.election == "LTW2026"
                else d / "raw" / f"{city}_wbz_2021.json"
            )
        try:
            rc |= run(city, args.election, out)
        except Exception as exc:  # noqa: BLE001 - one city must not block the other
            print(f"WARN {city} scrape failed: {exc}", file=sys.stderr)
            rc |= 1
    sys.exit(rc)


if __name__ == "__main__":
    main()
