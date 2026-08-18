#!/usr/bin/env bash
# Copy pipeline JSON + website-integration patches into website-source and push.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="${REPO_ROOT}/output"
WEBSITE_REPO="${WEBSITE_REPO:-website-source}"
WEBSITE_DIR="${WEBSITE_DIR:-${REPO_ROOT}/${WEBSITE_REPO}}"
DATA_TARGET="${WEBSITE_DIR}/static/data"
INTEGRATION="${REPO_ROOT}/website-integration"

if [[ ! -d "${WEBSITE_DIR}/.git" ]]; then
  echo "Cloning ${WEBSITE_REPO}..."
  git clone --depth 1 "https://github.com/zweitstimme-org/${WEBSITE_REPO}.git" "${WEBSITE_DIR}"
fi

mkdir -p "${DATA_TARGET}"

copy_if_exists() {
  local src="$1"
  local dest="$2"
  if [[ -f "${src}" ]]; then
    cp "${src}" "${dest}"
    echo "Copied $(basename "${src}")"
  fi
}

shopt -s nullglob
for file in \
  stimmung_federal.json \
  stimmung_states.json \
  current_stimmung.json \
  election_calendar.json \
  display_mode.json \
  party_order.json \
  polls_supplement.json \
  forecast_federal.json \
  forecast_parliament_size.json \
  pred_probabilities.json
do
  copy_if_exists "${OUTPUT_DIR}/${file}" "${DATA_TARGET}/${file}"
done

# Calendar may also live under data/
copy_if_exists "${REPO_ROOT}/data/election_calendar.json" "${DATA_TARGET}/election_calendar.json"
copy_if_exists "${REPO_ROOT}/data/json_output/election_dates.json" "${DATA_TARGET}/election_dates.json"

for forecast in "${OUTPUT_DIR}"/forecast_state_*.json; do
  cp "${forecast}" "${DATA_TARGET}/"
  echo "Copied $(basename "${forecast}")"
done

# Stimmung jobs rebuild display_mode without forecast_*.json in output/, which
# would flip forecast_available to false and hide Vorhersagen on the live site.
# Reconcile against forecast files that remain (or were just copied) in static/data.
if [[ -f "${DATA_TARGET}/display_mode.json" ]]; then
  python3 - "${DATA_TARGET}" <<'PY'
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
print("Reconciled display_mode forecast_available with static/data/*.json")
PY
fi

# District / Wahlkreis forecasts stay on the mock (gh-pages) preview only —
# do not publish forecast_districts_*.json or Wahlkreis geojson to live.

if [[ -d "${OUTPUT_DIR}/archive" ]]; then
  mkdir -p "${DATA_TARGET}/archive"
  cp -r "${OUTPUT_DIR}/archive/"* "${DATA_TARGET}/archive/" 2>/dev/null || true
  echo "Copied forecast archive files"
fi

if [[ -d "${INTEGRATION}/static/js" ]]; then
  mkdir -p "${WEBSITE_DIR}/static/js"
  cp -r "${INTEGRATION}/static/js/." "${WEBSITE_DIR}/static/js/"
  # Mock-only: do not ship Wahlkreis / candidate-entry preview scripts to live.
  rm -f "${WEBSITE_DIR}/static/js/district-forecast-map.js"
  rm -f "${WEBSITE_DIR}/static/js/candidate-entry.js"
  rm -f "${WEBSITE_DIR}/static/js/candidate-profile.js"
  echo "Synced static/js (without district-forecast-map.js / candidate-entry.js / candidate-profile.js)"
fi
if [[ -d "${INTEGRATION}/static/images" ]]; then
  mkdir -p "${WEBSITE_DIR}/static/images"
  cp -r "${INTEGRATION}/static/images/." "${WEBSITE_DIR}/static/images/"
  echo "Synced static/images"
fi

if [[ -f "${INTEGRATION}/themes/PaperMod/layouts/partials/home_info_de.html" ]]; then
  mkdir -p "${WEBSITE_DIR}/themes/PaperMod/layouts/partials"
  cp "${INTEGRATION}/themes/PaperMod/layouts/partials/home_info_de.html" \
    "${WEBSITE_DIR}/themes/PaperMod/layouts/partials/home_info_de.html"
  echo "Synced home_info_de.html"
fi
if [[ -f "${INTEGRATION}/themes/PaperMod/layouts/_default/api-docs.html" ]]; then
  mkdir -p "${WEBSITE_DIR}/themes/PaperMod/layouts/_default"
  cp "${INTEGRATION}/themes/PaperMod/layouts/_default/api-docs.html" \
    "${WEBSITE_DIR}/themes/PaperMod/layouts/_default/api-docs.html"
  echo "Copied Forecast API Swagger layout"
fi

# Wahlkreis-Vorhersage UI is mock-only (website-mock / gh-pages).
# Strip any previously published preview assets from website-source.
rm -rf "${WEBSITE_DIR}/content/preview"
rm -f "${WEBSITE_DIR}/themes/PaperMod/layouts/partials/district_forecast_map.html"
rm -f "${WEBSITE_DIR}/themes/PaperMod/layouts/_default/districts-preview.html"
rm -f "${WEBSITE_DIR}/themes/PaperMod/layouts/partials/candidate_entry.html"
rm -f "${WEBSITE_DIR}/themes/PaperMod/layouts/_default/candidate-entry.html"
rm -f "${WEBSITE_DIR}/themes/PaperMod/layouts/partials/candidate_profile.html"
rm -f "${WEBSITE_DIR}/themes/PaperMod/layouts/_default/candidate-profile.html"
rm -f "${WEBSITE_DIR}/themes/PaperMod/layouts/partials/preview_notice.html"
rm -f "${DATA_TARGET}"/forecast_districts.json \
  "${DATA_TARGET}"/forecast_districts_*.json \
  "${DATA_TARGET}"/forecast_candidate_entry.json \
  "${DATA_TARGET}"/ltw_wahlkreise_*.geojson \
  "${WEBSITE_DIR}/static/js/district-forecast-map.js" \
  "${WEBSITE_DIR}/static/js/candidate-entry.js" \
  "${WEBSITE_DIR}/static/js/candidate-profile.js"
echo "Ensured Wahlkreis / candidate-entry preview assets are absent from live website-source"

for page in api.md impressum.md faq.md; do
  if [[ -f "${INTEGRATION}/content/${page}" ]]; then
    cp "${INTEGRATION}/content/${page}" "${WEBSITE_DIR}/content/${page}"
    echo "Copied ${page}"
  fi
done

# Footer label + URL: human docs at /docs/api (JSON catalog stays under /api/).
if [[ -f "${WEBSITE_DIR}/config.toml" ]]; then
  python3 - "${WEBSITE_DIR}/config.toml" <<'PY'
from pathlib import Path
import re
import sys
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
changed = False
new, n = re.subn(
    r'name\s*=\s*"API"(\s*\n\s*url\s*=\s*")(?:/api"|/docs/api")',
    r'name = "Forecast API"\1"/docs/api"',
    text,
    count=1,
)
if n:
    text = new
    changed = True
else:
    new, n = re.subn(
        r'(name\s*=\s*"Forecast API"\s*\n\s*url\s*=\s*)"/api"',
        r'\1"/docs/api"',
        text,
        count=1,
    )
    if n:
        text = new
        changed = True
if changed:
    path.write_text(text, encoding="utf-8")
    print('Updated footer → Forecast API @ /docs/api')
else:
    print("Footer Forecast API /docs/api already set (or not found)")
PY
fi

# Versioned Forecast API under static/api/ (v1 federal, v2 state + Stimmung).
echo "Building versioned Forecast API ..."
python3 "${REPO_ROOT}/scripts/build_forecast_api.py" \
  --out "${WEBSITE_DIR}/static" \
  --data "${DATA_TARGET}" \
  --data "${OUTPUT_DIR}" \
  --data "${REPO_ROOT}/data" \
  --legacy-static "${WEBSITE_DIR}/static"

BLOG_POSTS_DIR="${INTEGRATION}/content/blog/posts"
# Preview-only methodology (Wahlkreis / Wahlabend) stays on gh-pages mock, not live.
LIVE_BLOG_SKIP=(
  district-forecast-methodology
  wahlabend-nowcast-methodology
)
if [[ -d "${BLOG_POSTS_DIR}" ]]; then
  for post_dir in "${BLOG_POSTS_DIR}"/*/; do
    [[ -d "${post_dir}" ]] || continue
    post_name="$(basename "${post_dir}")"
    skip=0
    for s in "${LIVE_BLOG_SKIP[@]}"; do
      if [[ "${post_name}" == "${s}" ]]; then skip=1; break; fi
    done
    if [[ "${skip}" -eq 1 ]]; then
      echo "Skipping preview-only blog post ${post_name}"
      continue
    fi
    mkdir -p "${WEBSITE_DIR}/content/blog/posts/${post_name}"
    cp -r "${post_dir}." "${WEBSITE_DIR}/content/blog/posts/${post_name}/"
    echo "Copied blog post ${post_name}"
  done
fi

# Drop preview methodology posts if a previous publish left them on live.
for s in "${LIVE_BLOG_SKIP[@]}"; do
  if [[ -d "${WEBSITE_DIR}/content/blog/posts/${s}" ]]; then
    rm -rf "${WEBSITE_DIR}/content/blog/posts/${s}"
    echo "Removed preview blog post ${s} from live website-source"
  fi
done

# Post moved archive → blog; drop the stale archive copy so Hugo's alias redirect wins.
if [[ -d "${WEBSITE_DIR}/content/archive/posts/polling-calculation-methods" ]]; then
  rm -rf "${WEBSITE_DIR}/content/archive/posts/polling-calculation-methods"
  echo "Removed stale archive copy of polling-calculation-methods (now a blog post)"
fi

ARCHIVE_POSTS_DIR="${INTEGRATION}/content/archive/posts"
if [[ -d "${ARCHIVE_POSTS_DIR}" ]]; then
  for post_dir in "${ARCHIVE_POSTS_DIR}"/*/; do
    [[ -d "${post_dir}" ]] || continue
    post_name="$(basename "${post_dir}")"
    mkdir -p "${WEBSITE_DIR}/content/archive/posts/${post_name}"
    cp -r "${post_dir}." "${WEBSITE_DIR}/content/archive/posts/${post_name}/"
    echo "Copied archive post ${post_name}"
  done
fi

RESEARCH_POSTS_DIR="${INTEGRATION}/content/research/posts"
if [[ -d "${RESEARCH_POSTS_DIR}" ]]; then
  for post_path in "${RESEARCH_POSTS_DIR}"/*; do
    [[ -e "${post_path}" ]] || continue
    name="$(basename "${post_path}")"
    if [[ -d "${post_path}" ]]; then
      mkdir -p "${WEBSITE_DIR}/content/research/posts/${name}"
      cp -r "${post_path}/." "${WEBSITE_DIR}/content/research/posts/${name}/"
      echo "Copied research post ${name}"
    elif [[ -f "${post_path}" ]]; then
      mkdir -p "${WEBSITE_DIR}/content/research/posts"
      cp "${post_path}" "${WEBSITE_DIR}/content/research/posts/${name}"
      echo "Copied research file ${name}"
    fi
  done
fi

if [[ -f "${INTEGRATION}/data/bibliography.json" ]]; then
  mkdir -p "${WEBSITE_DIR}/data" "${WEBSITE_DIR}/static/data"
  cp "${INTEGRATION}/data/bibliography.json" "${WEBSITE_DIR}/data/bibliography.json"
  cp "${INTEGRATION}/data/bibliography.json" "${WEBSITE_DIR}/static/data/bibliography.json"
  echo "Copied bibliography.json"
fi

if [[ -f "${INTEGRATION}/.github/workflows/deploy.yml" ]]; then
  mkdir -p "${WEBSITE_DIR}/.github/workflows"
  cp "${INTEGRATION}/.github/workflows/deploy.yml" \
    "${WEBSITE_DIR}/.github/workflows/deploy.yml"
  echo "Synced deploy.yml"
fi

cd "${WEBSITE_DIR}"
git config user.name "${GIT_USER_NAME:-zweitstimme-pipeline-bot}"
git config user.email "${GIT_USER_EMAIL:-pipeline@zweitstimme.org}"

if git diff --quiet && git diff --cached --quiet; then
  echo "No website changes to publish."
  exit 0
fi

git add -A
# Do not skip CI: website-source deploy builds Hugo and pushes to zweitstimme-org/website.
git commit -m "chore(data): update pipeline outputs and site integration"

if [[ -n "${WEBSITE_DEPLOY_TOKEN:-}" ]]; then
  git remote set-url origin \
    "https://x-access-token:${WEBSITE_DEPLOY_TOKEN}@github.com/zweitstimme-org/${WEBSITE_REPO}.git"
fi
git push origin HEAD

echo "Published pipeline outputs to ${WEBSITE_REPO}."
