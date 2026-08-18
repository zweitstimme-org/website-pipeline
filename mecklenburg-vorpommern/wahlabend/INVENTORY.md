# Mecklenburg-Vorpommern Wahlabend / Nowcast — Dateninventar

Ziel: Nowcast analog Berlin, Replay **LTW 2021** (L1 = 2016), Live-Pfad für **LTW 2026** (20. Sept.).

## Live-Feed (2026)

| Quelle | Inhalt |
|--------|--------|
| [LAIV 2026 Ergebnisse](https://www.laiv-mv.de/Wahlen/Landtagswahlen/2026/Ergebnisse/) | Leer-CSVs vor der Wahl; ab ~**19 Uhr** fortlaufend **WB / Gemeinde / WK** mit **Zeitstempel** |

Erwartete Dateien (wie 2021): `l_wahlbezirke.csv`, `l_gemeinden.csv`, `l_wahlkreise.csv`, `l_mandate.csv` → `wahlabend/raw/live/`.

Zeile 2 der CSV kennzeichnet Zwischenergebnis / vorläufig / endgültig.

## Historie (Replay)

| Datei | Rolle |
|-------|-------|
| `raw/LTW2021_WBZ.xlsx` | Wahrheit 2021 (`nach Wahlbezirken`, WB > 900 = Brief) |
| `raw/LTW2016_WBZ.xlsx` | L1 2016 |
| `../LTWMeckPom/ltw11-21_meckpom_abs.csv` | WK-Panel 2011–2021 (Fallback) |

Match: `Gemeinde-AGS + Wahlbezirk-Nr`.

## Pipeline

```bash
bash scripts/fetch_wahlabend_st_mv.sh
make wahlabend-ltw
# Preview: /preview/wahlabend/?state=mv
```

## Regeln

- 36 Wahlkreise, Hare/Niemeyer, Ausgleich **max. 2× Überhang**; keine Grundmandatsklausel.
- Landesliste only.
