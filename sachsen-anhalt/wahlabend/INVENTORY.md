# Sachsen-Anhalt Wahlabend / Nowcast — Dateninventar

Ziel: Nowcast analog Berlin. Replay **LTW 2021** (L1 = 2016) bleibt unter
`/preview/wahlabend/?state=st`. Live **LTW 2026** (6. Sept.) auf der
vertraulichen Seite `/preview/sachsen-anhalt/`.

## Live-Feed (2026)

StaLA veröffentlicht **dieselben Dateien** und überschreibt sie nach 18 Uhr
(Zwischenergebnis `Z`, später vorläufig `V`). `cache-control: no-cache`.

Landing: [lt26/downloads](https://wahlergebnisse.sachsen-anhalt.de/wahlen/lt26/downloads.html)

| Datei | Rolle |
|--------|--------|
| `Ergebnisse_Land_RKR_WKR_LT_2026.csv` | Land / Kreise / **41 WK** (U, B, Summe). Input für Erst/WK/Sitze. |
| `Ergebnisse_Gemeinden_LT_2026.csv` | **218 Gemeinden** (gleiche Spalten). Input für den Landes-Zweit-Nowcast: Überraschung gegen lokale Priors (LTW 2021 `lt21dat2.csv` + Uniform-Swing) korrigiert die Auszähl-Komposition (Land vor Stadt). Fallback: WK-Aggregat, wenn Gemeinde-Datei fehlt/veraltet (< 0,8 × Land-Ist). |
| `DSB_LT_2026.pdf` | Datensatzbeschreibung Land/WK/Kreis/Gemeinde |
| `DSB_WBZ_LT_2026.pdf` | Datensatzbeschreibung **Wahlbezirke** — CSV noch nicht verlinkt (404) |

`Ergebnisart`: `L` Leerdatei · `Z` Zwischen · `V` vorläufig · `E` endgültig.
Spalten u. a. `Datum`, `Uhrzeit`, `Soll.Wahlbezirke`, `Ist.Wahlbezirke`.

**CORS:** Der Browser darf die StaLA-CSV nicht direkt laden (`Access-Control-Allow-Origin` fehlt).
Deshalb holt GitHub Actions die Datei alle 5 Minuten und schreibt
`data/wahlabend_nowcast_st_live.json`. Die Seite rechnet nicht selbst gegen wahlergebnisse.sachsen-anhalt.de.

**Snapshots:** Jeder Poll legt `live/snapshots/YYYYMMDDTHHMMSSZ/` an (Land/WK, Gemeinden, ggf. WBZ) plus `manifest.jsonl` (sha256, Last-Modified, ETag). Die Action kopiert die Ordner nach `gh-pages` `data/st_live/snapshots/` (append, kein Überschreiben älterer Polls) und hängt ein 90-Tage-Artifact an. `live/` bleibt lokal gitignored.

## Wahlbezirke 2016 → 2021 (keine flächendeckende Neuzeichnung)

Die IDs haben sich oft geändert, die Geographie meist nicht:

- 90/218 Gemeinden: identische Urnen-Nummern
- 47: teilweise Überlappung
- 81: **keine** gemeinsame Urnen-Nummer, oft aber gleiche Anzahl und sequentielle Umnummerierung (`{1,2}→{10,11}`, Börde `{1,2,3}→{20001,…}` = AGS-kodiert)
- Briefwahl: 215 → 428 Bezirke; Magdeburg 2021 erstmals feste Briefwahlbezirke — das ist Zuordnung, keine Fläche

Exakter Match `AGS|WBnr|Art` trifft nur ~73 % der WB / ~68 % der Stimmen. Unmatched bekommen den **Gemeinde-Rest**: 2016er AGS×Art **minus der schon gematchten WB** (nicht das volle Gemeindeergebnis).

**Areal-weighted interpolation** (wie Berlin 2016→2026) braucht Polygone **beider** Jahre. Vorhanden sind nur **Wahlkreis**-GeoJSON (`geo/ltw_wahlkreise_st*.geojson`). StaLA/LVermGeo liefern keine landesweiten WB-Shapefiles (WB werden in der Gemeinde gebildet, ~max. 2500 Einwohner; Magdeburg hat PDF-Karten, kein GIS-Layer). Ohne beide Polygonlagen kein echtes areal weighting.

Praktisch: innerhalb der Gemeinde Nummern sortieren/AGS-kodierte IDs remapen; Rest auf AGS-Summe. Brief nicht areal, sondern historisch zuordnen.

```bash
make wahlabend-st-live   # fetch + output/wahlabend_nowcast_st_live.json
```

## Historie (Replay)

| Datei | Rolle |
|-------|-------|
| `raw/LT2021_WBZ.xlsx` | Wahrheit 2021, ~2600 WB |
| `raw/LT2016_WBZ.xlsx` | L1 2016, ~2500 WB |
| `raw/lt21dat1.csv` / `lt21dat2.csv` | Land/Kreis/WKR + Gemeinden |
| `raw/LT2016_GEM.csv` | Gemeinden 2016 |

Match L1↔2021: `AGS + Wahlbezirk-Nr + U/B` wo möglich.

## Pipeline

```bash
bash scripts/fetch_wahlabend_st_mv.sh
make wahlabend-ltw          # ST + MV replay JSON
# Replay-Vorschau: /preview/wahlabend/?state=st
# Live, vertraulich: /preview/sachsen-anhalt/
```

## Regeln

- 41 Wahlkreise, Hare/Niemeyer, Ausgleich iterativ; **keine** Grundmandatsklausel für Listeneinzug.
- Landesliste only (kein Bezirkslisten-Split wie Berlin).
