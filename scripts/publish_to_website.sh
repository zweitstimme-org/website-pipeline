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

# Do not overwrite live forecasts with stale output/ (e.g. after a UI-only publish).
# Exit 0 = copied (or new); exit 1 = kept dest; exit 2 = skipped / missing src.
copy_forecast_if_newer() {
  local src="$1"
  local dest="$2"
  if [[ ! -f "${src}" ]]; then
    return 2
  fi
  python3 - "$src" "$dest" <<'PY'
import json, sys
from datetime import datetime
from pathlib import Path

src, dest = Path(sys.argv[1]), Path(sys.argv[2])

def parse_ts(meta: dict):
    if not isinstance(meta, dict):
        return None
    # Prefer model freshness (last_update) over poll Stand so a re-fit on the
    # same poll still ships. Fall back to poll / as-of dates when needed.
    for key in ("last_update", "last_poll_date", "asof_date", "generated_at"):
        val = meta.get(key)
        if not val:
            continue
        s = str(val)[:10]
        try:
            return datetime.strptime(s, "%Y-%m-%d")
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(str(val).replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass
    return None

def score(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    # Unwrap API envelopes; draws store timing at the top level (no metadata).
    inner = data.get("data") if data.get("api_version") and isinstance(data.get("data"), dict) else data
    if not isinstance(inner, dict):
        return None
    meta = inner.get("metadata") if isinstance(inner.get("metadata"), dict) else {}
    return parse_ts(meta) or parse_ts(inner)

if not dest.exists():
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(src.read_bytes())
    print(f"Copied {src.name} (new)")
    sys.exit(0)

src_ts = score(src)
dest_ts = score(dest)
if src_ts is None:
    print(f"Skip {src.name}: unreadable source metadata")
    sys.exit(2)
if dest_ts is None or src_ts >= dest_ts:
    dest.write_bytes(src.read_bytes())
    print(f"Copied {src.name} ({src_ts.date()} >= {dest_ts.date() if dest_ts else 'none'})")
    sys.exit(0)
print(f"Keep {dest.name} on website-source ({dest_ts.date()} > {src_ts.date()} in output/)")
sys.exit(1)
PY
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

# Summary forecasts only (not *_draws.json). When a summary ships, always ship
# its companion draws so /api/v2/state/{land}/draws.json cannot lag the forecast.
for forecast in "${OUTPUT_DIR}"/forecast_state_??.json; do
  [[ -f "${forecast}" ]] || continue
  base="$(basename "${forecast}")"
  if copy_forecast_if_newer "${forecast}" "${DATA_TARGET}/${base}"; then
    draws="${forecast%.json}_draws.json"
    if [[ -f "${draws}" ]]; then
      cp "${draws}" "${DATA_TARGET}/$(basename "${draws}")"
      echo "Copied $(basename "${draws}") (paired with ${base})"
    else
      echo "Warning: ${base} updated but no companion $(basename "${draws}") in output/" >&2
    fi
  fi
done
# Draws for states whose summary was kept (dest newer) but draws file alone is newer.
for draws in "${OUTPUT_DIR}"/forecast_state_*_draws.json; do
  [[ -f "${draws}" ]] || continue
  copy_forecast_if_newer "${draws}" "${DATA_TARGET}/$(basename "${draws}")" || true
done
# Federal posterior draws (timing at top level, same as state draws).
copy_forecast_if_newer "${OUTPUT_DIR}/forecast_federal_draws.json" \
  "${DATA_TARGET}/forecast_federal_draws.json" || true

# Stimmung jobs rebuild display_mode without forecast_*.json in output/, which
# would flip forecast_available to false and omit Vorhersagen from the Hugo HTML.
# Reconcile against forecast files that remain (or were just copied) in static/data.
# Also keep post-election forecasts on the homepage archive for 7 days.
if [[ -f "${DATA_TARGET}/display_mode.json" ]]; then
  python3 "${REPO_ROOT}/scripts/reconcile_display_mode.py" "${DATA_TARGET}"
fi

# Hugo reads data/display_mode.json at build time to include or omit Vorhersage
# sections (and stripe section-alt backgrounds) without a client-side restripe.
if [[ -f "${DATA_TARGET}/display_mode.json" ]]; then
  mkdir -p "${WEBSITE_DIR}/data"
  cp "${DATA_TARGET}/display_mode.json" "${WEBSITE_DIR}/data/display_mode.json"
  echo "Copied display_mode.json to Hugo data/"
fi

# District / Wahlkreis + Einzugschancen (live). Wahlabend stays preview-only.
copy_forecast_if_newer "${OUTPUT_DIR}/forecast_candidate_entry.json" \
  "${DATA_TARGET}/forecast_candidate_entry.json" || true
copy_forecast_if_newer "${OUTPUT_DIR}/forecast_parliament_size.json" \
  "${DATA_TARGET}/forecast_parliament_size.json" || true
for forecast in "${OUTPUT_DIR}"/forecast_districts_*.json; do
  [[ -f "${forecast}" ]] || continue
  copy_forecast_if_newer "${forecast}" "${DATA_TARGET}/$(basename "${forecast}")" || true
done
for geo in "${OUTPUT_DIR}"/ltw_wahlkreise_*.geojson; do
  [[ -f "${geo}" ]] || continue
  cp "${geo}" "${DATA_TARGET}/"
  echo "Copied $(basename "${geo}")"
done
for state_geo in \
  "${REPO_ROOT}/berlin/geo/ltw_wahlkreise_be.geojson" \
  "${REPO_ROOT}/mecklenburg-vorpommern/geo/ltw_wahlkreise_mv.geojson" \
  "${REPO_ROOT}/sachsen-anhalt/geo/ltw_wahlkreise_st.geojson"
do
  base="$(basename "${state_geo}")"
  if [[ -f "${state_geo}" && ! -f "${DATA_TARGET}/${base}" ]]; then
    cp "${state_geo}" "${DATA_TARGET}/${base}"
    echo "Copied ${base} (from state geo/)"
  fi
done

if [[ -d "${OUTPUT_DIR}/archive" ]]; then
  mkdir -p "${DATA_TARGET}/archive"
  cp -r "${OUTPUT_DIR}/archive/"* "${DATA_TARGET}/archive/" 2>/dev/null || true
  echo "Copied forecast archive files"
fi

# Live Wahlkreis map UI (stripes / seat ranges) may be ahead of git HEAD.
# Stimmung-only CI checkouts must not roll that back to an older integration copy.
integration_map_js_is_older_than_live() {
  local src="${INTEGRATION}/static/js/district-forecast-map.js"
  local dest="${WEBSITE_DIR}/static/js/district-forecast-map.js"
  [[ -f "${dest}" ]] || return 1
  [[ -f "${src}" ]] || return 0
  if rg -q 'districtNeedsStripes|dstripe|simulateDirectRanges' "${dest}" 2>/dev/null \
    && ! rg -q 'districtNeedsStripes|dstripe|simulateDirectRanges' "${src}" 2>/dev/null; then
    return 0
  fi
  return 1
}

if [[ -d "${INTEGRATION}/static/js" ]]; then
  mkdir -p "${WEBSITE_DIR}/static/js"
  for js in "${INTEGRATION}/static/js/"*.js; do
    [[ -f "${js}" ]] || continue
    base="$(basename "${js}")"
    dest="${WEBSITE_DIR}/static/js/${base}"
    if [[ -f "${dest}" ]] && [[ "${base}" == "candidate-entry.js" || "${base}" == "district-forecast-map.js" ]] \
      && rg -q 'scenario-prob-panel' "${dest}" 2>/dev/null \
      && ! rg -q 'scenario-prob-panel' "${js}" 2>/dev/null; then
      echo "Keep static/js/${base} (website-source has newer Einzug/Wahlkreis UI)"
      continue
    fi
    if [[ "${base}" == "district-forecast-map.js" ]] && integration_map_js_is_older_than_live; then
      echo "Keep static/js/${base} (website-source has newer Wahlkreis stripe/seat UI)"
      continue
    fi
    cp "${js}" "${dest}"
  done
  # Wahlabend replay UI stays on the Pages mock only.
  rm -f "${WEBSITE_DIR}/static/js/wahlabend-nowcast.js"
  echo "Synced static/js (without wahlabend-nowcast)"
fi
if [[ -d "${INTEGRATION}/static/images" ]]; then
  mkdir -p "${WEBSITE_DIR}/static/images"
  cp -r "${INTEGRATION}/static/images/." "${WEBSITE_DIR}/static/images/"
  echo "Synced static/images"
fi
if [[ -f "${INTEGRATION}/assets/css/extended/custom.css" ]]; then
  mkdir -p "${WEBSITE_DIR}/assets/css/extended"
  cp "${INTEGRATION}/assets/css/extended/custom.css" \
    "${WEBSITE_DIR}/assets/css/extended/custom.css"
  echo "Synced custom.css"
fi

if [[ -f "${INTEGRATION}/themes/PaperMod/layouts/partials/home_info_de.html" ]]; then
  if integration_map_js_is_older_than_live; then
    echo "Keep home_info_de.html (paired with live Wahlkreis map UI)"
  else
    mkdir -p "${WEBSITE_DIR}/themes/PaperMod/layouts/partials"
    cp "${INTEGRATION}/themes/PaperMod/layouts/partials/home_info_de.html" \
      "${WEBSITE_DIR}/themes/PaperMod/layouts/partials/home_info_de.html"
    echo "Synced home_info_de.html"
  fi
fi
if [[ -f "${INTEGRATION}/themes/PaperMod/layouts/_default/api-docs.html" ]]; then
  mkdir -p "${WEBSITE_DIR}/themes/PaperMod/layouts/_default"
  cp "${INTEGRATION}/themes/PaperMod/layouts/_default/api-docs.html" \
    "${WEBSITE_DIR}/themes/PaperMod/layouts/_default/api-docs.html"
  echo "Copied Forecast API Swagger layout"
fi
if [[ -f "${INTEGRATION}/layouts/partials/extend_head.html" ]]; then
  mkdir -p "${WEBSITE_DIR}/layouts/partials"
  cp "${INTEGRATION}/layouts/partials/extend_head.html" \
    "${WEBSITE_DIR}/layouts/partials/extend_head.html"
  echo "Synced extend_head.html (cookie-less hit pixel)"
fi
# Research / FAQ / blog-archive hub layouts.
if [[ -d "${INTEGRATION}/layouts/_default" ]]; then
  mkdir -p "${WEBSITE_DIR}/layouts/_default"
  for layout in forschung.html faq.html article.html posts-hub.html; do
    if [[ -f "${INTEGRATION}/layouts/_default/${layout}" ]]; then
      cp "${INTEGRATION}/layouts/_default/${layout}" \
        "${WEBSITE_DIR}/layouts/_default/${layout}"
      echo "Copied layout ${layout}"
    fi
  done
fi

copy_theme_file() {
  local rel="$1"
  local src="${INTEGRATION}/themes/PaperMod/${rel}"
  local dest="${WEBSITE_DIR}/themes/PaperMod/${rel}"
  if [[ ! -f "${src}" ]]; then
    return 0
  fi
  # Stimmung-only publishes must not roll back Einzug/Wahlkreis UI that is already live.
  if [[ -f "${dest}" ]] && rg -q 'scenario-prob-panel|district-preview-nav' "${dest}" 2>/dev/null \
    && ! rg -q 'scenario-prob-panel|district-preview-nav' "${src}" 2>/dev/null; then
    echo "Keep ${rel} (website-source has newer Einzug/Wahlkreis UI than integration)"
    return 0
  fi
  # Same for the Direktmandate map partial when live JS still has stripes/seat ranges.
  if [[ "${rel}" == "layouts/partials/district_forecast_map.html" ]] \
    && integration_map_js_is_older_than_live; then
    echo "Keep ${rel} (paired with live Wahlkreis map UI)"
    return 0
  fi
  mkdir -p "$(dirname "${dest}")"
  cp "${src}" "${dest}"
  echo "Copied ${rel}"
}

# Wahlkreise + Einzug + Kandidat:innen (public).
copy_theme_file "layouts/partials/district_forecast_map.html"
copy_theme_file "layouts/_default/districts-preview.html"
copy_theme_file "layouts/partials/candidate_entry.html"
copy_theme_file "layouts/_default/candidate-entry.html"
copy_theme_file "layouts/partials/candidate_profile.html"
copy_theme_file "layouts/_default/candidate-profile.html"

copy_content_dir() {
  local name="$1"
  local src="${INTEGRATION}/content/${name}"
  local dest="${WEBSITE_DIR}/content/${name}"
  if [[ -d "${src}" ]]; then
    mkdir -p "${dest}"
    cp -r "${src}/." "${dest}/"
    echo "Copied content/${name}"
  fi
}
copy_content_dir "direktmandate"
copy_content_dir "einzug"
copy_content_dir "kandidat"

# Preview-only: Polymarket comparison. Strip Wahlabend + map-only embed.
rm -rf "${WEBSITE_DIR}/content/preview"
mkdir -p "${WEBSITE_DIR}/content/preview/polymarket"
if [[ -f "${INTEGRATION}/content/preview/polymarket/index.md" ]]; then
  cp "${INTEGRATION}/content/preview/polymarket/index.md" \
    "${WEBSITE_DIR}/content/preview/polymarket/index.md"
fi
copy_theme_file "layouts/partials/preview_notice.html"
copy_theme_file "layouts/partials/polymarket_compare.html"
copy_theme_file "layouts/_default/polymarket-preview.html"
if [[ -f "${INTEGRATION}/static/data/polymarket_compare.json" ]]; then
  mkdir -p "${WEBSITE_DIR}/static/data"
  cp "${INTEGRATION}/static/data/polymarket_compare.json" \
    "${WEBSITE_DIR}/static/data/polymarket_compare.json"
elif [[ -f "${OUTPUT_DIR}/polymarket_compare.json" ]]; then
  mkdir -p "${WEBSITE_DIR}/static/data"
  cp "${OUTPUT_DIR}/polymarket_compare.json" \
    "${WEBSITE_DIR}/static/data/polymarket_compare.json"
fi
rm -f "${WEBSITE_DIR}/themes/PaperMod/layouts/partials/wahlabend_nowcast.html" \
  "${WEBSITE_DIR}/themes/PaperMod/layouts/_default/wahlabend-preview.html" \
  "${WEBSITE_DIR}/themes/PaperMod/layouts/_default/districts-preview-maponly.html" \
  "${WEBSITE_DIR}/static/js/wahlabend-nowcast.js"
echo "Published Wahlkreise / Einzug / Kandidat:innen; kept Polymarket preview; omitted Wahlabend"

for page in api.md impressum.md faq.md datenschutz.md; do
  if [[ -f "${INTEGRATION}/content/${page}" ]]; then
    cp "${INTEGRATION}/content/${page}" "${WEBSITE_DIR}/content/${page}"
    echo "Copied ${page}"
  fi
done

# Section index pages (Forschung hub, Blog/Archiv cards, Team).
copy_index_page() {
  local src="$1"
  local dest="$2"
  if [[ -f "${src}" ]]; then
    mkdir -p "$(dirname "${dest}")"
    cp "${src}" "${dest}"
    echo "Copied $(basename "$(dirname "${dest}")")/$(basename "${dest}")"
  fi
}
copy_index_page "${INTEGRATION}/content/research/_index.md" \
  "${WEBSITE_DIR}/content/research/_index.md"
copy_index_page "${INTEGRATION}/content/blog/_index.md" \
  "${WEBSITE_DIR}/content/blog/_index.md"
copy_index_page "${INTEGRATION}/content/archive/_index.md" \
  "${WEBSITE_DIR}/content/archive/_index.md"
copy_index_page "${INTEGRATION}/content/team/index.md" \
  "${WEBSITE_DIR}/content/team/index.md"

if [[ -f "${INTEGRATION}/data/faq.yaml" ]]; then
  mkdir -p "${WEBSITE_DIR}/data"
  cp "${INTEGRATION}/data/faq.yaml" "${WEBSITE_DIR}/data/faq.yaml"
  echo "Copied faq.yaml"
fi

# Footer: Forecast API (/docs/api) + Polling API + LinkedIn.
if [[ -f "${WEBSITE_DIR}/config.toml" ]]; then
  python3 "${REPO_ROOT}/scripts/patch_hugo_footer.py" "${WEBSITE_DIR}/config.toml"
fi

# Versioned Forecast API under static/api/ (v1 legacy federal, v2 federal + state + Stimmung).
# Prefer output/ over static/data so a fresh forecast+draws run wins even if a
# prior publish left stale companion files in website-source.
echo "Building versioned Forecast API ..."
python3 "${REPO_ROOT}/scripts/build_forecast_api.py" \
  --out "${WEBSITE_DIR}/static" \
  --data "${OUTPUT_DIR}" \
  --data "${DATA_TARGET}" \
  --data "${REPO_ROOT}/data" \
  --legacy-static "${WEBSITE_DIR}/static"

BLOG_POSTS_DIR="${INTEGRATION}/content/blog/posts"
# Wahlabend-Nowcast methodology stays on the Pages mock only.
LIVE_BLOG_SKIP=(
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

# Overview text now lives on the Forschung hub; drop the old list item.
if [[ -d "${WEBSITE_DIR}/content/research/posts/overview" ]]; then
  rm -rf "${WEBSITE_DIR}/content/research/posts/overview"
  echo "Removed research/posts/overview (merged into Forschung hub)"
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
