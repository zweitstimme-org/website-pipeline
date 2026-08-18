# Mecklenburg-Vorpommern Landtag districts

## Data

| Path | Source |
|------|--------|
| `LTWMeckPom/` | Lisa-Marie Zikesch panel (2011–2021 Erst/Zweit by WK) |
| `geo/LTwahl_Wahlkreise/` | Official LAiV MV shape (KLWK250MV, LTW 2026 = 2021 boundaries) |
| `geo/ltw_wahlkreise_mv.geojson` | Full WGS84 export |
| `../output/ltw_wahlkreise_mv.geojson` | Simplified GeoJSON for the website |
| `../output/forecast_districts_mv.json` | Swing MVP district forecast |
| `candidates/direktkandidaten_2026.csv` | Direktkandidat*innen from party websites (display-only) |

Shape download: https://www.laiv-mv.de/static/LAIV/Geoinformation/Dateien/Karten/LTwahl_Wahlkreise.zip

## Forecast

```bash
python3 code/district_forecast.py --state MV
# or: make district-forecast
```

Uniform Zweitstimme swing from 2021 districts to the statewide
`forecast_state_mv.json`, then Erststimme = Zweit + (Erst−Zweit gap from 2021).
Candidate names are joined for the map detail table only — no candidate effects in the model yet (official LAIV lists after ~13 Aug 2026).

### Candidate sources

| Party | Coverage | URL |
|-------|----------|-----|
| SPD | 36/36 | https://spd-mv.de/wahlen/landtagswahl-2026/kandidaten-landtagswahl-2026 |
| AfD | 36/36 | https://afd-mv.de/blaue-wende-2026/#Kandidaten |
| CDU | 36/36 | https://cdu-mv.de/landtagskandidaten2026cdumv/ |
| Linke | 36/36 | https://kampagne26.die-linke-mv.de/direktkandidierende/ |
| BSW | 34/36 | https://mv.bsw-vg.de/unsere-direktkandidaten/ (no candidate WK 19, 29) |
| Grüne | 31/36 | https://gruene-mv.de/…/unsere-direktkandidatinnen-fuer-die-landtagswahl-2026/ |
| FDP | 33/36 | Parteigrafik (keine in WK 2, 3, 14) |
