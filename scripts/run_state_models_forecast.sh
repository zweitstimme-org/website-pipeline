#!/usr/bin/env bash
# Run zweitstimme-org/state-models (exact lead days) then convert to website JSON.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_MODELS_DIR="${STATE_MODELS_DIR:-${REPO_ROOT}/../state-models}"
STATE_MODELS_DIR="$(cd "${STATE_MODELS_DIR}" && pwd)"

if [[ ! -f "${STATE_MODELS_DIR}/run_pipeline.R" ]]; then
  echo "STATE_MODELS_DIR missing run_pipeline.R: ${STATE_MODELS_DIR}" >&2
  echo "Clone: git clone https://github.com/zweitstimme-org/state-models.git ${STATE_MODELS_DIR}" >&2
  exit 1
fi

# Comma-separated elec_ind list, or derive from election_calendar.json (≤90 days).
if [[ -z "${ELECTIONS_TO_FORECAST:-}" ]]; then
  ELECTIONS_TO_FORECAST="$(
    python3 - <<'PY' "${REPO_ROOT}/data/election_calendar.json"
import json, sys
from datetime import date, datetime
path = sys.argv[1]
with open(path) as f:
    cal = json.load(f)
today = date.today()
window = int(cal.get("metadata", {}).get("forecast_window_days", 90))
due = []
for e in cal.get("elections", []):
    if e.get("scope") == "bund":
        continue
    d = e.get("election_date")
    code = e.get("state_code")
    if not d or not code:
        continue
    ed = datetime.strptime(d, "%Y-%m-%d").date()
    days = (ed - today).days
    if 0 < days <= window:
        due.append(f"{code.lower()}_{d}")
print(",".join(due))
PY
  )"
fi

if [[ -z "${ELECTIONS_TO_FORECAST}" ]]; then
  echo "No upcoming state elections in forecast window." >&2
  exit 0
fi

# Lead = election − last poll Stand (API + optional DAWUM scrape), not calendar today.
# run_pipeline.R recomputes the same; this seeds SKIP_ESTIMATE=1 path and logs.
API_BASE="${POLLING_API_BASE:-https://api.zweitstimme.org}"
# Let state-models / MODEL_LEADS merge DAWUM Landtag scrapes (QC/dedup) from this repo.
export WEBSITE_PIPELINE_ROOT="${WEBSITE_PIPELINE_ROOT:-${REPO_ROOT}}"
MODEL_LEADS="$(
  PYTHONPATH="${REPO_ROOT}/code${PYTHONPATH:+:${PYTHONPATH}}" python3 - <<'PY' "${ELECTIONS_TO_FORECAST}" "${API_BASE}"
import json, os, sys, urllib.request
from datetime import datetime
from pathlib import Path

elections = [x.strip() for x in sys.argv[1].split(",") if "_" in x.strip()]
api_base = sys.argv[2].rstrip("/")
land_to_scope = {"nw": "nrw"}
stands = {}
wp = os.environ.get("WEBSITE_PIPELINE_ROOT") or ""
if wp:
    sys.path.insert(0, str(Path(wp) / "code"))
try:
    from dawum_state_polls import fetch_dawum_state_polls
except Exception:
    fetch_dawum_state_polls = None

for eid in elections:
    land = eid.split("_", 1)[0].lower()
    if land in stands:
        continue
    scope = land_to_scope.get(land, land)
    url = f"{api_base}/v2/polls?scope={scope}&limit=1&sort=-published_date&include_results=true"
    with urllib.request.urlopen(url, timeout=60) as resp:
        data = json.load(resp)
    items = data.get("data") or []
    if not items:
        raise SystemExit(f"No polls for scope={scope} (land={land})")
    pub = items[0].get("published_date") or items[0].get("publish_date")
    stand = datetime.strptime(str(pub)[:10], "%Y-%m-%d").date()
    if fetch_dawum_state_polls is not None:
        for p in fetch_dawum_state_polls(scope):
            d = str(p.get("publish_date") or p.get("published_date") or "")[:10]
            if not d:
                continue
            ds = datetime.strptime(d, "%Y-%m-%d").date()
            if ds > stand:
                stand = ds
    stands[land] = stand

leads = sorted({
    (datetime.strptime(eid.split("_", 1)[1], "%Y-%m-%d").date() - stands[eid.split("_", 1)[0].lower()]).days
    for eid in elections
})
if not leads or any(d <= 0 for d in leads):
    raise SystemExit(f"Non-positive Stand-anchored lead days: {leads}; stands={stands}")
print(",".join(str(d) for d in leads))
print(
    "Stand (last poll): " + ", ".join(f"{k}={v.isoformat()}" for k, v in sorted(stands.items())),
    file=sys.stderr,
)
PY
)"

echo "STATE_MODELS_DIR=${STATE_MODELS_DIR}"
echo "ELECTIONS_TO_FORECAST=${ELECTIONS_TO_FORECAST}"
echo "MODEL_LEADS=${MODEL_LEADS}"

export ELECTIONS_TO_FORECAST
export MODEL_LEADS
# Same as BW/RP 2026: polls-only exact-lead models (not fundamentals _all).
export MODEL_POLLS_ONLY="${MODEL_POLLS_ONLY:-1}"
export MODEL_ONLY_ALL="${MODEL_ONLY_ALL:-0}"
# state-models uses Zweitstimme polling API v2 (/v2/polls).
export POLLING_API_BASE="${POLLING_API_BASE:-https://api.zweitstimme.org}"
export STATE_MODELS_DIR

# Skip Stan when leads already in model_bayes.RDS and SKIP_ESTIMATE=1.
SKIP_ESTIMATE="${SKIP_ESTIMATE:-0}"
if [[ "${SKIP_ESTIMATE}" == "1" && -f "${STATE_MODELS_DIR}/data/output/model/model_bayes.RDS" ]]; then
  echo "SKIP_ESTIMATE=1 — rebuild data + forecast only"
  (
    cd "${STATE_MODELS_DIR}"
    Rscript -e '
      elections_to_forecast <- unique(trimws(strsplit(Sys.getenv("ELECTIONS_TO_FORECAST"), ",")[[1]]))
      lead_days <- as.integer(strsplit(Sys.getenv("MODEL_LEADS"), ",")[[1]])
      dir.create("data/output", recursive = TRUE, showWarnings = FALSE)
      save(elections_to_forecast, file = "data/output/elections_to_forecast.RData")
      save(lead_days, file = "data/output/lead_days.RData")
      message("Seeded elections: ", paste(elections_to_forecast, collapse = ", "))
      message("Lead days: ", paste(lead_days, collapse = ", "))
    '
    Rscript code/01_build_data.R
    Rscript code/03_forecast.R
  )
else
  echo "Running full state-models pipeline (build + estimate + forecast)…"
  (
    cd "${STATE_MODELS_DIR}"
    Rscript run_pipeline.R
  )
fi

Rscript "${REPO_ROOT}/state-model/convert_fcst_to_json.R"
(
  cd "${REPO_ROOT}"
  Rscript -e 'source("R/config.R"); source("R/display_mode.R"); build_display_mode()'
)

# District swings + parliament-size sim depend on the new statewide fits.
SKIP_DISTRICTS="${SKIP_DISTRICTS:-0}"
if [[ "${SKIP_DISTRICTS}" != "1" ]]; then
  echo "Rebuilding district forecasts from updated state projections…"
  (
    cd "${REPO_ROOT}"
    make district-forecast
  )
fi

echo "Done. Website JSON in ${REPO_ROOT}/output/forecast_state_*.json (+ districts unless SKIP_DISTRICTS=1)"
