# Berlin Listen (Seeds / Harvest)

Bezirkslisten (SPD/CDU/Linke) and Landeslisten (others). Positions 1–5 are
locked to AGH Musterstimmzettel (`../official/list_tops.csv`) on every
`listen_candidates.py` rebuild. Use these CSVs for places 6+ and for
Direkt-linking (`wkr_direct`).

| Party | Status | Source notes |
|-------|--------|--------------|
| SPD | partial Bezirkslisten (all 12) | spd.berlin; tops from ballots |
| CDU | all 12 Bezirkslisten (tops official; some Bezirke party-site longer) | cdu-sz / cdu-spandau / ballots |
| Linke | all 12 Bezirke kuratiert | Bezirk websites; **TS (07) = AGH, not BVV** |
| AfD | Landesliste (1–5 official ballot names) | ballots + noafd.info |
| Grüne | Landesliste 1–50 | https://www.gruene-berlin.de/unsere-kandidatinnen-als-liste/ |
| FDP | Landesliste 1–24 | https://www.fdp-berlin.de/ein-starkes-team-fuer-eine-stadt-die-wieder-funktioniert |
| BSW | Landesliste 1–20 | bsw.berlin; tops from ballots |

Do not copy Bezirksverordnetenversammlung lists into AGH seeds. The Linke
Tempelhof-Schöneberg AGH list is
https://www.dielinke-tempelhof-schoeneberg.de/wahlen/berlin-wahlen-2026/
(`linke_07.csv` / the `07` rows of `linke_bezirk.csv`).
