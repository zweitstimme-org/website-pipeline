# Sachsen-Anhalt Direktkandidaten 2026

Official StaLa lists are **complete**: missing `(party, WK)` means the party
does not field a Direktkandidat. `district_forecast.py` zeros that party's
Erststimme and renormalizes the others to 100 % (`candidates_complete`).

## Source (official)

Primary: Statistisches Landesamt / Landeswahlleiterin Excel
[Zugelassene Wahlvorschläge](https://statistik.sachsen-anhalt.de/themen/gebiet-und-wahlen/wahlen/landtagswahl-2026/wahlvorschlaege)
(`official/stala_bewerber_ltw2026.xlsx`).

Bio fields (Geburtsjahr/-ort, Wohnort, Beruf) live in `official_bio.csv`
and are shown via the **i** button on the ST Direkt-/Einzugs-Preview.

Magdeburg WK 10–13 also in [Amtsblatt Nr. 17/2026](https://www.magdeburg.de/loadDocument.phtml?ObjSvrID=698&ObjID=30862&ObjLa=1&Ext=PDF)
(`official/magdeburg_amtsblatt_17_2026.pdf`).

Pre-official curated files archived under
`archive/pre_stala_2026-08-05/` (with `COMPARE.md`).

## Coverage (tracked parties)

| Party | WKs | Source |
|-------|-----|--------|
| CDU / SPD / Linke / Grüne / AfD / FDP | 41/41 | StaLa Excel |
| BSW | 27/41 | StaLa Excel (no Direkt in remaining WKs) |
| FW | 11/41 | StaLa Excel |

See `official/source_urls.json` for Kreis-PDF downloads kept for reference.
