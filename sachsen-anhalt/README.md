# Sachsen-Anhalt Landtag districts

## Data

| Path | Source |
|------|--------|
| `raw/lt21dat1.csv` | StaLA ST endgültige Ergebnisse LTW 2021 (WKR) |
| `geo/raw/Wahlkreise_LTW_2026.geojson` | Official 2026 Wahlkreise (same numbering as 2021) |
| `ltw21_st_abs.csv` | Normalized Erst/Zweit panel |
| `../output/ltw_wahlkreise_st.geojson` | Simplified GeoJSON for the website |
| `../output/forecast_districts_st.json` | Swing MVP district forecast |

Shape: https://statistik.sachsen-anhalt.de/…/Wahlkreise_LTW_2026_geosjon-Datei.zip  
Results: https://wahlergebnisse.sachsen-anhalt.de/wahlen/lt21/erg/csv/lt21dat1.csv

## Forecast

```bash
python3 code/prepare_district_data.py --state ST
python3 code/district_forecast.py --state ST
# or: make district-forecast
```

Uniform Zweitstimme swing from 2021 districts to `forecast_state_st.json`,
then Erststimme = Zweit + (Erst−Zweit gap from 2021). No candidate effects yet.
