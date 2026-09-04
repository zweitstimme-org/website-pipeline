# Berlin Direktkandidaten 2026 (AGH)

Quellen: Parteiwebsites (vor allem Bezirks-/Kreisverbände). Wahlkreis-IDs sind statewide 1–78
(mapped from Bezirk + local WK via `../awk_wkr_map.json`).

Nur `https://…`-Quellen werden auf der Wahlkreisvorhersage verlinkt.

| Party | Coverage | Quellen |
|-------|----------|---------|
| SPD | 78/78 | https://spd.berlin/kandidatinnen/ |
| Grüne | 78/78 | alle 12 Bezirks-/Kreisverbände (u. a. Xhain, Südwest, TS, MaHe, …) |
| Linke | 78/78 | alle 12 Bezirksverbände (u. a. CW, Spandau, MaHe, Lichtenberg, …) |
| CDU | 56/78 | CW, Spandau, Neukölln, Reinickendorf, Lichtenberg, SZ, TS, TK; Pankow 1,2,4,5,9 (statewide 13,14,16,17,21) |
| AfD | 20/78 | CW, Neukölln, Lichtenberg, Marzahn-Hellersdorf |
| FDP | 23/78 | SZ + [Pankow](https://www.fdp-pankow.de/pressemitteilung-kandidatinnen-und-kandidaten-der-fdp-pankow-fuer-die-berliner-wahlen-2026) + [Mitte](https://www.fdp-mitte.berlin/person-overview/kandidierende-fuer-die-agh-wahl-2026) |
| BSW | — | no usable Bezirk list scraped yet |

## Offene Lücken

- **CDU Direkt:** Mitte, Xhain, Pankow 3/6/7/8, Marzahn-Hellersdorf. Pankow-Quellen nennen lokale WK 1–9 — auf statewide 13–21 mappen (`awk_wkr_map.json`), nicht 1–9 als Landes-WK.
- **CDU Bezirkslisten:** Mitte, Xhain, TS, Neukölln, MaHe (haben: Pankow, CW, Spandau, SZ, TK, Lichtenberg, Reinickendorf)
- **Linke Bezirkslisten:** alle 12 Bezirke kuratiert
- **AfD / FDP / BSW Direkt:** weitere Bezirksverbände; AfD-Landesliste 1–35 (Zulassung)

Roh-HTML: `raw/` und `raw/bezirk*/`.

## Listen (`listenkandidaten_2026.csv`)

Landes- bzw. Bezirkslisten inkl. Platzhalter für fehlende Namen.
Wird von `code/listen_candidates.py` erzeugt und von `code/candidate_entry_sim.py`
für Einzugschancen genutzt (Preview: `/preview/einzug/`).

2026: CDU/SPD/Linke → Bezirkslisten; Grüne/AfD/FDP/BSW → Landesliste.
