# Berlin Direktkandidaten 2026 (AGH)

Wahlkreis-IDs sind statewide 1–78 (mapped from Bezirk + local WK via
`../awk_wkr_map.json`).

**Authoritative names:** Landeswahlleiter AGH Musterstimmzettel
(`official/`, parsed by `code/parse_be_musterstimmzettel.py`). Missing
(party, WK) among the tracked parties = no Direktkandidat
(`candidates_complete` in the district forecast). Party websites remain
the source for list places 6+ and for public links when the name already
matched.

| Party | Coverage | Quellen |
|-------|----------|---------|
| SPD | 78/78 | Musterstimmzettel; spd.berlin |
| Grüne | 78/78 | Musterstimmzettel; Bezirks-/Kreisverbände |
| Linke | 78/78 | Musterstimmzettel; Bezirksverbände |
| CDU | 78/78 | Musterstimmzettel |
| AfD | 78/78 | Musterstimmzettel |
| FDP | 69/78 | Musterstimmzettel (real gaps: no FDP on those ballots) |
| BSW | 77/78 | Musterstimmzettel (one WK without BSW) |

Nur `https://…`-Quellen werden auf der Wahlkreisvorhersage verlinkt.

## Listen (`listenkandidaten_2026.csv`)

Landes- bzw. Bezirkslisten inkl. Platzhalter für fehlende Namen.
Wird von `code/listen_candidates.py` erzeugt (daily CI) und von
`code/candidate_entry_sim.py` für Einzugschancen genutzt.

Rebuilds **cannot** overwrite official list tops: `official/list_tops.csv`
always wins for positions 1–5. Per-Bezirk seeds (`lists/{party}_{bez}.csv`)
win over the combined harvest for places 6+.

2026: CDU/SPD/Linke → Bezirkslisten; Grüne/AfD/FDP/BSW → Landesliste.

Linke Tempelhof-Schöneberg (`lists/linke_07.csv`) is the **AGH
Bezirksliste**, not the BVV slate.
