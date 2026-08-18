#!/usr/bin/env bash
# Copy pipeline JSON into the gh-pages branch data/ tree and push.
# Used by GitHub Actions so https://zweitstimme-org.github.io/website-pipeline/
# tracks daily Stimmung / state-forecast runs (no full Hugo rebuild).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="${REPO_ROOT}/output"
BRANCH="${PAGES_BRANCH:-gh-pages}"
GIT_USER_NAME="${GIT_USER_NAME:-zweitstimme-pipeline-bot}"
GIT_USER_EMAIL="${GIT_USER_EMAIL:-pipeline@zweitstimme.org}"

if [[ ! -d "${OUTPUT_DIR}" ]]; then
  echo "No output/ directory — nothing to publish." >&2
  exit 0
fi

REMOTE_URL="${PAGES_REMOTE_URL:-}"
if [[ -z "${REMOTE_URL}" ]]; then
  if [[ -n "${GITHUB_TOKEN:-}" && -n "${GITHUB_REPOSITORY:-}" ]]; then
    REMOTE_URL="https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"
  else
    REMOTE_URL="$(git -C "${REPO_ROOT}" remote get-url origin)"
  fi
fi

TMP="$(mktemp -d)"
cleanup() { rm -rf "${TMP}"; }
trap cleanup EXIT

echo "Cloning ${BRANCH} ..."
git clone --depth 1 --branch "${BRANCH}" "${REMOTE_URL}" "${TMP}"

mkdir -p "${TMP}/data"
shopt -s nullglob
copied=0
for f in \
  "${OUTPUT_DIR}"/forecast_state_*.json \
  "${OUTPUT_DIR}"/forecast_districts_*.json \
  "${OUTPUT_DIR}/forecast_parliament_size.json" \
  "${OUTPUT_DIR}/forecast_candidate_entry.json" \
  "${OUTPUT_DIR}"/ltw_wahlkreise_*.geojson \
  "${OUTPUT_DIR}/display_mode.json" \
  "${OUTPUT_DIR}/stimmung_federal.json" \
  "${OUTPUT_DIR}/stimmung_states.json" \
  "${OUTPUT_DIR}/current_stimmung.json" \
  "${OUTPUT_DIR}/party_order.json" \
  "${OUTPUT_DIR}/polls_supplement.json" \
  "${OUTPUT_DIR}/forecast_federal.json"
do
  [[ -f "$f" ]] || continue
  cp "$f" "${TMP}/data/"
  echo "  $(basename "$f")"
  copied=$((copied + 1))
done

if [[ -f "${REPO_ROOT}/data/election_calendar.json" ]]; then
  cp "${REPO_ROOT}/data/election_calendar.json" "${TMP}/data/"
  echo "  election_calendar.json"
  copied=$((copied + 1))
fi
if [[ -f "${REPO_ROOT}/data/json_output/election_dates.json" ]]; then
  # Real file (not symlink) so Pages artifact upload can pack it.
  cp "${REPO_ROOT}/data/json_output/election_dates.json" "${TMP}/data/election_dates.json"
  echo "  election_dates.json"
  copied=$((copied + 1))
fi

if [[ -d "${OUTPUT_DIR}/archive" ]]; then
  mkdir -p "${TMP}/data/archive"
  for f in "${OUTPUT_DIR}/archive"/*.json; do
    [[ -f "$f" ]] || continue
    cp "$f" "${TMP}/data/archive/"
    echo "  archive/$(basename "$f")"
    copied=$((copied + 1))
  done
fi

if [[ "${copied}" -eq 0 ]]; then
  echo "No JSON outputs to copy — skipping Pages preview publish."
  exit 0
fi

# Stimmung jobs rebuild display_mode without forecast_*.json in output/, which
# would flip forecast_available to false and hide Vorhersagen. Reconcile flags
# against forecast files that remain (or were just copied) on gh-pages.
if [[ -f "${TMP}/data/display_mode.json" ]]; then
  python3 - "${TMP}/data" <<'PY'
import json, sys
from datetime import date
from pathlib import Path

data_dir = Path(sys.argv[1])
dm_path = data_dir / "display_mode.json"
dm = json.loads(dm_path.read_text())
window = int(dm.get("forecast_window_days") or 90)
today = date.today()

def within_window(info):
    ed = info.get("election_date")
    if not ed:
        return False
    try:
        days = (date.fromisoformat(ed) - today).days
    except ValueError:
        return False
    info["days_to_election"] = days
    return 0 <= days <= window

federal = dm.get("federal") or {}
if federal:
    has = (data_dir / "forecast_federal.json").exists()
    if has and within_window(federal):
        federal["mode"] = "forecast"
        federal["forecast_available"] = True
    elif not has:
        federal["forecast_available"] = False
        if federal.get("mode") == "forecast":
            federal["mode"] = "stimmung"
    dm["federal"] = federal

states = dm.get("states") or {}
for code, info in list(states.items()):
    has = (data_dir / f"forecast_state_{code.lower()}.json").exists()
    if has and within_window(info):
        info["mode"] = "forecast"
        info["forecast_available"] = True
    elif not has:
        info["forecast_available"] = False
        if info.get("mode") == "forecast":
            info["mode"] = "stimmung"
    states[code] = info
dm["states"] = states
dm_path.write_text(json.dumps(dm, indent=2, ensure_ascii=False) + "\n")
print("Reconciled display_mode forecast_available with data/*.json")
PY
fi

# Versioned Forecast API at site root /api/ (alongside /data/).
echo "Building versioned Forecast API for Pages preview ..."
python3 "${REPO_ROOT}/scripts/build_forecast_api.py" \
  --out "${TMP}" \
  --data "${TMP}/data" \
  --data "${OUTPUT_DIR}" \
  --data "${REPO_ROOT}/data" \
  --legacy-static "${REPO_ROOT}/website-source/static" \
  --legacy-static "${REPO_ROOT}/website-mock/static"

git -C "${TMP}" config user.name "${GIT_USER_NAME}"
git -C "${TMP}" config user.email "${GIT_USER_EMAIL}"
git -C "${TMP}" add data api
if git -C "${TMP}" diff --staged --quiet; then
  echo "gh-pages data/ + api/ already up to date."
  exit 0
fi

MSG="${PAGES_COMMIT_MESSAGE:-chore(pages): refresh preview data from pipeline}"
git -C "${TMP}" commit -m "${MSG}"
# Avoid racing a concurrent preview publish.
git -C "${TMP}" pull --rebase --autostash origin "${BRANCH}" || true
git -C "${TMP}" push origin "HEAD:${BRANCH}"
echo "Pushed data refresh to ${BRANCH}."
