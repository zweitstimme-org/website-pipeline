# Federal forecast pipeline skeleton (Zweitstimme model)

This directory wraps the `prediction-2025` (or future `prediction-next`) R + Stan
federal forecasting model for automated GitHub Actions runs on the self-hosted runner.

## Prerequisites

- R 4.4+ with `rstan`, Stan toolchain, and packages from `prediction-2025/auxiliary/packages.r`
- Self-hosted runner with ≥20 CPU cores and ~64 GB RAM for full MCMC runs
- Clone the model repo next to this pipeline or set `FEDERAL_MODEL_DIR`

## Inputs (per election cycle)

| Input | Source | Notes |
|-------|--------|-------|
| Polls | `api.zweitstimme.org` (preferred) or wahlrecht.de XML fallback | Set `POLL_SOURCE=api` |
| Structural data | `pre_train_data_*.xlsx` / RDS | Manual update per election |
| District boundaries | `germany-*-wahlkreise.geojson` | For map generation only |
| Candidate panel | Bewerberverzeichnis CSV | Required ~6 months before election |
| District remapping | `btwkr*_umrechnung_*.csv` | When boundaries change |

## Outputs

Written to `output/` and published to `website-source/static/data/`:

- `forecast_federal.json` — party point estimates + 83%/95% intervals
- `pred_probabilities.json` — coalition probabilities
- `forecast_districts.json` — Wahlkreis Erst/Zweitstimme forecasts

## Running locally

```bash
export FEDERAL_MODEL_DIR=/mnt/cerfort/forecasts/prediction-2025
export ELECTION_DATE=2029-02-25
Rscript federal-model/run_federal_forecast.R
```

## GitHub Actions

See `.github/workflows/federal-forecast.yml`. Runs only when a Bundestagswahl in
`data/election_calendar.json` is within 90 days, or on manual `workflow_dispatch`.
