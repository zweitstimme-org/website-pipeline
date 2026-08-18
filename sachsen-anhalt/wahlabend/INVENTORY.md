# Sachsen-Anhalt Wahlabend / Nowcast — Dateninventar

Ziel: Nowcast analog Berlin, Replay **LTW 2021** (L1 = 2016), Live-Pfad für **LTW 2026** (6. Sept.).

## Live-Feed (2026)

| Quelle | Inhalt |
|--------|--------|
| [lt26/downloads](https://wahlergebnisse.sachsen-anhalt.de/wahlen/lt26/downloads.html) | Ab 2. Augusthälfte Leerdateien; am Wahltag **Zwischenergebnisse**; vorläufig in der Nacht/am Morgen |
| vor 18 Uhr | Repräsentative **Wahlbeteiligung** (Urnen-Stichprobe) |
| nach 18 Uhr | Auszählungs-Zwischenstände |

Format der Live-Dateien: noch TBD (sobald StaLA Leerdateien publiziert) → `wahlabend/raw/live/`.

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
# Preview: /preview/wahlabend/?state=st
```

## Regeln

- 41 Wahlkreise, Hare/Niemeyer, Ausgleich iterativ; **keine** Grundmandatsklausel für Listeneinzug.
- Landesliste only (kein Bezirkslisten-Split wie Berlin).
