#!/usr/bin/env bash
# Apply path generalization when running prediction-2025 from the pipeline.
# Long-term: upstream prediction-2025 should use here::here() and POLL_SOURCE=api.

set -euo pipefail

FEDERAL_MODEL_DIR="${FEDERAL_MODEL_DIR:-/mnt/cerfort/forecasts/prediction-2025}"
ELECTION_DATE="${ELECTION_DATE:-2029-02-25}"

if [[ ! -d "${FEDERAL_MODEL_DIR}/code" ]]; then
  echo "Clone prediction-2025 to ${FEDERAL_MODEL_DIR} first." >&2
  exit 1
fi

export POLLING_API_BASE="${POLLING_API_BASE:-https://api.zweitstimme.org}"
export PIPELINE_OUTPUT="${PIPELINE_OUTPUT:-$(cd "$(dirname "$0")/.." && pwd)/output}"

echo "Federal model wrapper"
echo "  Model: ${FEDERAL_MODEL_DIR}"
echo "  Election: ${ELECTION_DATE}"
echo "  Poll API: ${POLLING_API_BASE}"
echo ""
echo "Next steps to fully wire automation:"
echo "  1. Replace setwd() in code/00_run-model.R with here::here() or env var"
echo "  2. Add poll fetch from FastTrack API alongside wahlrecht scraper"
echo "  3. Parameterize election date + party set in structural data prep"
echo "  4. Convert api/*.rds outputs to JSON in output/ for website publish"
echo ""
echo "Run skeleton: Rscript federal-model/run_federal_forecast.R"
