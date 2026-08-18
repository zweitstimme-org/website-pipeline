#!/usr/bin/env bash
# Build website-mock locally (same as the real site) and push to gh-pages.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MOCK_DIR="${REPO_ROOT}/website-mock"
HUGO="${REPO_ROOT}/.bin/hugo"
BASE_URL="${PAGES_BASE_URL:-https://zweitstimme-org.github.io/website-pipeline/}"
BRANCH="${PAGES_BRANCH:-gh-pages}"

if [[ ! -d "${MOCK_DIR}/.git" && ! -f "${MOCK_DIR}/config.toml" ]]; then
  echo "website-mock/ missing. Clone website-source into website-mock/ first." >&2
  exit 1
fi
if [[ ! -x "${HUGO}" ]]; then
  echo "Hugo not found at ${HUGO}" >&2
  exit 1
fi

echo "Seeding forecast / stimmung JSON into website-mock/static/data ..."
mkdir -p "${MOCK_DIR}/static/data" "${MOCK_DIR}/static/js"
shopt -s nullglob
for f in \
  "${REPO_ROOT}"/output/forecast_state_*.json \
  "${REPO_ROOT}"/output/forecast_districts_*.json \
  "${REPO_ROOT}"/output/forecast_parliament_size.json \
  "${REPO_ROOT}"/output/forecast_candidate_entry.json \
  "${REPO_ROOT}"/output/wahlabend_nowcast_replay.json \
  "${REPO_ROOT}"/output/wahlabend_nowcast_st.json \
  "${REPO_ROOT}"/output/wahlabend_nowcast_mv.json \
  "${REPO_ROOT}"/output/ltw_wahlkreise_*.geojson \
  "${REPO_ROOT}"/output/display_mode.json \
  "${REPO_ROOT}"/output/stimmung_*.json \
  "${REPO_ROOT}"/output/current_stimmung.json \
  "${REPO_ROOT}"/output/party_order.json \
  "${REPO_ROOT}"/output/polls_supplement.json
do
  [[ -f "$f" ]] || continue
  cp "$f" "${MOCK_DIR}/static/data/"
  echo "  $(basename "$f")"
done
if [[ -f "${REPO_ROOT}/data/election_calendar.json" ]]; then
  cp "${REPO_ROOT}/data/election_calendar.json" "${MOCK_DIR}/static/data/"
fi
if [[ -f "${REPO_ROOT}/data/json_output/election_dates.json" ]]; then
  cp "${REPO_ROOT}/data/json_output/election_dates.json" "${MOCK_DIR}/static/data/election_dates.json"
fi

echo "Building versioned Forecast API into website-mock/static/api ..."
python3 "${REPO_ROOT}/scripts/build_forecast_api.py" \
  --out "${MOCK_DIR}/static" \
  --data "${MOCK_DIR}/static/data" \
  --data "${REPO_ROOT}/output" \
  --data "${REPO_ROOT}/data" \
  --legacy-static "${MOCK_DIR}/static" \
  --legacy-static "${REPO_ROOT}/website-source/static"

# Fallback: state geo folders when output/ was not rebuilt (UI-only preview deploys).
for state_geo in \
  "${REPO_ROOT}/berlin/geo/ltw_wahlkreise_be.geojson" \
  "${REPO_ROOT}/mecklenburg-vorpommern/geo/ltw_wahlkreise_mv.geojson" \
  "${REPO_ROOT}/sachsen-anhalt/geo/ltw_wahlkreise_st.geojson"
do
  base="$(basename "${state_geo}")"
  if [[ -f "${state_geo}" && ! -f "${MOCK_DIR}/static/data/${base}" ]]; then
    cp "${state_geo}" "${MOCK_DIR}/static/data/${base}"
    echo "  ${base} (from state geo/)"
  fi
done

if [[ -d "${REPO_ROOT}/website-integration/static/js" ]]; then
  cp -r "${REPO_ROOT}/website-integration/static/js/." "${MOCK_DIR}/static/js/"
fi
if [[ -f "${REPO_ROOT}/website-integration/themes/PaperMod/layouts/partials/home_info_de.html" ]]; then
  mkdir -p "${MOCK_DIR}/themes/PaperMod/layouts/partials"
  cp "${REPO_ROOT}/website-integration/themes/PaperMod/layouts/partials/home_info_de.html" \
    "${MOCK_DIR}/themes/PaperMod/layouts/partials/home_info_de.html"
fi
# Unlinked internal preview page (Direktmandate) — not in menus.
if [[ -f "${REPO_ROOT}/website-integration/themes/PaperMod/layouts/partials/district_forecast_map.html" ]]; then
  cp "${REPO_ROOT}/website-integration/themes/PaperMod/layouts/partials/district_forecast_map.html" \
    "${MOCK_DIR}/themes/PaperMod/layouts/partials/district_forecast_map.html"
fi
if [[ -f "${REPO_ROOT}/website-integration/themes/PaperMod/layouts/_default/districts-preview.html" ]]; then
  mkdir -p "${MOCK_DIR}/themes/PaperMod/layouts/_default"
  cp "${REPO_ROOT}/website-integration/themes/PaperMod/layouts/_default/districts-preview.html" \
    "${MOCK_DIR}/themes/PaperMod/layouts/_default/districts-preview.html"
fi
if [[ -f "${REPO_ROOT}/website-integration/themes/PaperMod/layouts/partials/preview_notice.html" ]]; then
  mkdir -p "${MOCK_DIR}/themes/PaperMod/layouts/partials"
  cp "${REPO_ROOT}/website-integration/themes/PaperMod/layouts/partials/preview_notice.html" \
    "${MOCK_DIR}/themes/PaperMod/layouts/partials/preview_notice.html"
fi
if [[ -f "${REPO_ROOT}/website-integration/themes/PaperMod/layouts/partials/candidate_entry.html" ]]; then
  cp "${REPO_ROOT}/website-integration/themes/PaperMod/layouts/partials/candidate_entry.html" \
    "${MOCK_DIR}/themes/PaperMod/layouts/partials/candidate_entry.html"
fi
if [[ -f "${REPO_ROOT}/website-integration/themes/PaperMod/layouts/_default/candidate-entry.html" ]]; then
  mkdir -p "${MOCK_DIR}/themes/PaperMod/layouts/_default"
  cp "${REPO_ROOT}/website-integration/themes/PaperMod/layouts/_default/candidate-entry.html" \
    "${MOCK_DIR}/themes/PaperMod/layouts/_default/candidate-entry.html"
fi
if [[ -f "${REPO_ROOT}/website-integration/themes/PaperMod/layouts/partials/candidate_profile.html" ]]; then
  cp "${REPO_ROOT}/website-integration/themes/PaperMod/layouts/partials/candidate_profile.html" \
    "${MOCK_DIR}/themes/PaperMod/layouts/partials/candidate_profile.html"
fi
if [[ -f "${REPO_ROOT}/website-integration/themes/PaperMod/layouts/_default/candidate-profile.html" ]]; then
  mkdir -p "${MOCK_DIR}/themes/PaperMod/layouts/_default"
  cp "${REPO_ROOT}/website-integration/themes/PaperMod/layouts/_default/candidate-profile.html" \
    "${MOCK_DIR}/themes/PaperMod/layouts/_default/candidate-profile.html"
fi
if [[ -f "${REPO_ROOT}/website-integration/themes/PaperMod/layouts/partials/wahlabend_nowcast.html" ]]; then
  cp "${REPO_ROOT}/website-integration/themes/PaperMod/layouts/partials/wahlabend_nowcast.html" \
    "${MOCK_DIR}/themes/PaperMod/layouts/partials/wahlabend_nowcast.html"
fi
if [[ -f "${REPO_ROOT}/website-integration/themes/PaperMod/layouts/_default/wahlabend-preview.html" ]]; then
  mkdir -p "${MOCK_DIR}/themes/PaperMod/layouts/_default"
  cp "${REPO_ROOT}/website-integration/themes/PaperMod/layouts/_default/wahlabend-preview.html" \
    "${MOCK_DIR}/themes/PaperMod/layouts/_default/wahlabend-preview.html"
fi
if [[ -d "${REPO_ROOT}/website-integration/content/preview" ]]; then
  mkdir -p "${MOCK_DIR}/content/preview"
  cp -r "${REPO_ROOT}/website-integration/content/preview/." "${MOCK_DIR}/content/preview/"
fi
for page in api.md impressum.md faq.md; do
  if [[ -f "${REPO_ROOT}/website-integration/content/${page}" ]]; then
    cp "${REPO_ROOT}/website-integration/content/${page}" "${MOCK_DIR}/content/${page}"
  fi
done
# Footer: human docs at /docs/api (JSON catalog stays under /api/).
if [[ -f "${MOCK_DIR}/config.toml" ]]; then
  python3 - "${MOCK_DIR}/config.toml" <<'PY'
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
    print("Updated preview footer → Forecast API @ /docs/api")
else:
    print("Preview footer Forecast API /docs/api already set (or not found)")
PY
fi
# Keep methodology explainers in sync with website-integration.
for meth in district-forecast-methodology state-forecast-methodology wahlabend-nowcast-methodology; do
  if [[ -d "${REPO_ROOT}/website-integration/content/blog/posts/${meth}" ]]; then
    mkdir -p "${MOCK_DIR}/content/blog/posts/${meth}"
    cp -r "${REPO_ROOT}/website-integration/content/blog/posts/${meth}/." \
      "${MOCK_DIR}/content/blog/posts/${meth}/"
  fi
done

# hugo-cite still uses echoParam; Hugo 0.134+ errors on that deprecation.
if [[ -d "${MOCK_DIR}/themes/hugo-cite" ]]; then
  while IFS= read -r -d '' f; do
    # BSD sed (macOS) needs -i ''; GNU sed accepts -i'' as well.
    sed -i.bak 's/echoParam \. "\([^"]*\)"/index . "\1"/g' "$f"
    rm -f "${f}.bak"
  done < <(find "${MOCK_DIR}/themes/hugo-cite" -name '*.html' -print0)
fi

echo "Building Hugo site → ${BASE_URL}"
# Do not enable canonifyURLs: with this baseURL it doubles the path
# (/website-pipeline/website-pipeline/assets/...), so CSS fails to load.
# Homepage root-absolute links are fixed via relURL in home_info_de.html.
(
  cd "${MOCK_DIR}"
  "${HUGO}" --minify --baseURL "${BASE_URL}"
)

TMP_PUBLISH="$(mktemp -d)"
cleanup() { rm -rf "${TMP_PUBLISH}"; }
trap cleanup EXIT

echo "Publishing ${MOCK_DIR}/public to origin/${BRANCH} ..."
# --copy-links: Hugo may leave symlinks (e.g. election_dates.json) that break Pages upload.
rsync -a --copy-links "${MOCK_DIR}/public/" "${TMP_PUBLISH}/"
# Preview only — never claim the production domain.
rm -f "${TMP_PUBLISH}/CNAME"
touch "${TMP_PUBLISH}/.nojekyll"

# Prefer newer pipeline JSON already on gh-pages over stale local output/.
# UI-only redeploys must not clobber fresh Action-published forecasts/stimmung.
# Set SKIP_REMOTE_DATA_MERGE=1 to publish local output/ as-is (e.g. date corrections).
if [[ "${SKIP_REMOTE_DATA_MERGE:-0}" == "1" ]]; then
  echo "Skipping remote data/ merge (SKIP_REMOTE_DATA_MERGE=1)."
else
echo "Merging newer data/ files from origin/${BRANCH} (if any) ..."
REMOTE_DATA="$(mktemp -d)"
if git clone --depth 1 --branch "${BRANCH}" \
    "$(git -C "${REPO_ROOT}" remote get-url origin)" "${REMOTE_DATA}" >/dev/null 2>&1; then
  python3 - <<'PY' "${REMOTE_DATA}/data" "${TMP_PUBLISH}/data"
import json, sys
from pathlib import Path

remote_dir = Path(sys.argv[1])
local_dir = Path(sys.argv[2])
local_dir.mkdir(parents=True, exist_ok=True)

def stamp(path: Path):
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return None
    meta = payload.get("metadata") if isinstance(payload, dict) else None
    if isinstance(meta, dict) and meta.get("last_update"):
        return str(meta["last_update"])
    if isinstance(payload, dict) and payload.get("last_update"):
        return str(payload["last_update"])
    return None

kept = 0
# Forecast JSON: prefer newer remote by last_update stamp.
for remote in remote_dir.rglob("*.json"):
    rel = remote.relative_to(remote_dir)
    dest = local_dir / rel
    remote_stamp = stamp(remote)
    local_stamp = stamp(dest) if dest.exists() else None
    # Keep remote when local is missing, unstamped, or older.
    if (not dest.exists()) or (remote_stamp and (not local_stamp or remote_stamp > local_stamp)):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(remote.read_bytes())
        kept += 1
        print(f"  keep remote data/{rel}")
# GeoJSON / other static data: keep remote whenever local is missing
# (UI-only deploys often omit output/ltw_wahlkreise_*.geojson).
for remote in remote_dir.rglob("*"):
    if not remote.is_file() or remote.suffix.lower() == ".json":
        continue
    rel = remote.relative_to(remote_dir)
    dest = local_dir / rel
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(remote.read_bytes())
        kept += 1
        print(f"  keep remote data/{rel}")
print(f"Merged {kept} newer remote data file(s).")
PY
else
  echo "  (could not clone ${BRANCH}; publishing local data as-is)"
fi
rm -rf "${REMOTE_DATA}"
fi

# Root-absolute /images/, /data/, /js/, etc. break on project Pages.
# Prefix them with the repo base path (once).
BASE_PATH="$(python3 - <<'PY' "${BASE_URL}"
from urllib.parse import urlparse
import sys
path = urlparse(sys.argv[1]).path.rstrip("/")
print(path if path else "")
PY
)"
if [[ -n "${BASE_PATH}" ]]; then
  echo "Rewriting root-absolute asset paths for ${BASE_PATH}/ ..."
  python3 - <<'PY' "${TMP_PUBLISH}" "${BASE_PATH}"
import pathlib, re, sys

root = pathlib.Path(sys.argv[1])
base = sys.argv[2].rstrip("/")
# Do NOT include bare "/posts/" — it matches inside "/blog/posts/",
# "/research/posts/", "/archive/posts/" and doubles the base path.
prefixes = (
    "/images/", "/data/", "/js/", "/assets/", "/blog/",
    "/team/", "/faq/", "/impressum/", "/research/", "/archive/", "/api/",
    "/pred_probabilities.json", "/forecast.json", "/forecast_districts.json",
    "/draws.json", "/last_updated.json", "/pred_vacant.json",
)
# Only rewrite root-absolute paths (start of an href/url value), and only
# when they are not already prefixed with the project base path.
pats = [
    re.compile(
        r"(?<!" + re.escape(base) + r")"
        r'(?<=["\'=\s(,])'
        r"(" + re.escape(p) + r")"
    )
    for p in prefixes
]
files = (
    list(root.rglob("*.html"))
    + list(root.rglob("*.js"))
    + list(root.rglob("*.css"))
    + list(root.rglob("*.xml"))
)
n = 0
for f in files:
    text = f.read_text(encoding="utf-8", errors="surrogateescape")
    orig = text
    for pat in pats:
        text = pat.sub(base + r"\1", text)
    if text != orig:
        f.write_text(text, encoding="utf-8", errors="surrogateescape")
        n += 1
print(f"Updated {n} files")
PY
fi
git -C "${TMP_PUBLISH}" init -q
git -C "${TMP_PUBLISH}" checkout -q -b "${BRANCH}"
git -C "${TMP_PUBLISH}" config user.name "${GIT_USER_NAME:-zweitstimme-pipeline-bot}"
git -C "${TMP_PUBLISH}" config user.email "${GIT_USER_EMAIL:-pipeline@zweitstimme.org}"
git -C "${TMP_PUBLISH}" add -A
git -C "${TMP_PUBLISH}" commit -q -m "chore(pages): preview website-mock with latest forecasts"
ORIGIN_URL="$(git -C "${REPO_ROOT}" remote get-url origin)"
HTTPS_URL=""
SSH_URL=""
if [[ "${ORIGIN_URL}" =~ ^https://github.com/([^/]+)/([^/.]+)(\.git)?$ ]]; then
  HTTPS_URL="https://github.com/${BASH_REMATCH[1]}/${BASH_REMATCH[2]%.git}.git"
  SSH_URL="git@github.com:${BASH_REMATCH[1]}/${BASH_REMATCH[2]%.git}.git"
elif [[ "${ORIGIN_URL}" =~ ^git@github.com:([^/]+)/([^/.]+)(\.git)?$ ]]; then
  SSH_URL="${ORIGIN_URL}"
  HTTPS_URL="https://github.com/${BASH_REMATCH[1]}/${BASH_REMATCH[2]%.git}.git"
else
  HTTPS_URL="${ORIGIN_URL}"
fi
# Prefer HTTPS when credentials exist (common on CI/agents without SSH keys).
# SSH remains available via PAGES_PUSH_SSH=1 for hosts that need it.
PUSH_URL="${HTTPS_URL:-$ORIGIN_URL}"
if [[ "${PAGES_PUSH_SSH:-0}" == "1" && -n "${SSH_URL}" ]]; then
  PUSH_URL="${SSH_URL}"
fi
git -C "${TMP_PUBLISH}" remote add origin "${PUSH_URL}"
echo "Pushing gh-pages via ${PUSH_URL} ..."
if ! git -C "${TMP_PUBLISH}" -c http.postBuffer=524288000 push -f origin "HEAD:${BRANCH}"; then
  if [[ -n "${SSH_URL}" && "${PUSH_URL}" != "${SSH_URL}" ]]; then
    echo "HTTPS push failed; retrying via SSH ..."
    git -C "${TMP_PUBLISH}" remote set-url origin "${SSH_URL}"
    git -C "${TMP_PUBLISH}" -c http.postBuffer=524288000 push -f origin "HEAD:${BRANCH}"
  else
    exit 1
  fi
fi

# Pages is Actions-based (deploy-pages.yml). Push to gh-pages does not run that
# workflow (no .github on the prebuilt branch), so dispatch it explicitly.
echo "Triggering GitHub Pages deploy workflow ..."
TOKEN="$(
  printf 'protocol=https\nhost=github.com\n\n' | git credential fill 2>/dev/null \
    | awk -F= '/^password=/{print $2}'
)"
if [[ -n "${TOKEN}" ]]; then
  HTTP_CODE="$(
    curl -s -o /dev/null -w '%{http_code}' -X POST \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "Accept: application/vnd.github+json" \
      "https://api.github.com/repos/zweitstimme-org/website-pipeline/actions/workflows/deploy-pages.yml/dispatches" \
      -d '{"ref":"main"}'
  )"
  if [[ "${HTTP_CODE}" == "204" ]]; then
    echo "  workflow_dispatch accepted (HTTP 204)"
  else
    echo "  warning: workflow_dispatch returned HTTP ${HTTP_CODE}" >&2
  fi
else
  echo "  warning: no git credential; trigger Actions → Deploy site preview manually" >&2
fi

echo "Done. Site: ${BASE_URL}"
echo "Ensure Pages source is GitHub Actions (Settings → Pages)."
