# Berlin Abgeordnetenhaus districts

## Data

| Path | Source |
|------|--------|
| `raw/be_agh2026_2023.xlsx` | AfS BBB: 2023 Zweitstimmen remapped to 2026 WKs |
| `raw/be_agh2023.xlsx` | AfS BBB: 2023 Erst/Zweit by Wahlbezirk |
| `geo/raw/agh2026_awk.geojson` | GDI Berlin WFS `wahlgebiete_agh2026:agh2026_awk` |
| `agh23_be_abs.csv` | Normalized panel (78 WKs, statewide numbers 1–78) |
| `../output/ltw_wahlkreise_be.geojson` | Simplified GeoJSON for the website |
| `../output/forecast_districts_be.json` | Swing MVP district forecast |

2026 WK division differs slightly from 2023 (e.g. Friedrichshain-Kreuzberg /
Treptow-Köpenick). Zweitstimmen use the official remap; Erststimmen use 2023
local-WK totals where the local number still exists, else gap = 0.

## Forecast

```bash
python3 code/prepare_district_data.py --state BE
python3 code/district_forecast.py --state BE
# or: make district-forecast
```

Uniform Zweitstimme swing from the remapped 2023 panel to `forecast_state_be.json`,
then Erststimme = Zweit + (Erst−Zweit gap). No candidate effects yet.
