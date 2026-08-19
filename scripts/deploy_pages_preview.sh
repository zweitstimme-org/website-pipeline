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

echo "Refreshing Polymarket comparison snapshot ..."
python3 "${REPO_ROOT}/scripts/fetch_polymarket_compare.py" \
  || echo "Polymarket snapshot failed (using existing JSON if any)."

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
  "${REPO_ROOT}"/output/polls_supplement.json \
  "${REPO_ROOT}"/output/polymarket_compare.json \
  "${REPO_ROOT}"/website-integration/static/data/polymarket_compare.json
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
if [[ -d "${REPO_ROOT}/website-integration/static/data" ]]; then
  mkdir -p "${MOCK_DIR}/static/data"
  cp -r "${REPO_ROOT}/website-integration/static/data/." "${MOCK_DIR}/static/data/"
fi
if [[ -d "${REPO_ROOT}/website-integration/static/images" ]]; then
  mkdir -p "${MOCK_DIR}/static/images"
  cp -r "${REPO_ROOT}/website-integration/static/images/." "${MOCK_DIR}/static/images/"
fi
if [[ -f "${REPO_ROOT}/website-integration/themes/PaperMod/layouts/partials/home_info_de.html" ]]; then
  mkdir -p "${MOCK_DIR}/themes/PaperMod/layouts/partials"
  cp "${REPO_ROOT}/website-integration/themes/PaperMod/layouts/partials/home_info_de.html" \
    "${MOCK_DIR}/themes/PaperMod/layouts/partials/home_info_de.html"
fi
if [[ -f "${REPO_ROOT}/website-integration/themes/PaperMod/layouts/_default/api-docs.html" ]]; then
  mkdir -p "${MOCK_DIR}/themes/PaperMod/layouts/_default"
  cp "${REPO_ROOT}/website-integration/themes/PaperMod/layouts/_default/api-docs.html" \
    "${MOCK_DIR}/themes/PaperMod/layouts/_default/api-docs.html"
fi
if [[ -f "${REPO_ROOT}/website-integration/layouts/partials/extend_head.html" ]]; then
  mkdir -p "${MOCK_DIR}/layouts/partials"
  cp "${REPO_ROOT}/website-integration/layouts/partials/extend_head.html" \
    "${MOCK_DIR}/layouts/partials/extend_head.html"
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
if [[ -f "${REPO_ROOT}/website-integration/themes/PaperMod/layouts/partials/polymarket_compare.html" ]]; then
  cp "${REPO_ROOT}/website-integration/themes/PaperMod/layouts/partials/polymarket_compare.html" \
    "${MOCK_DIR}/themes/PaperMod/layouts/partials/polymarket_compare.html"
fi
if [[ -f "${REPO_ROOT}/website-integration/themes/PaperMod/layouts/_default/polymarket-preview.html" ]]; then
  mkdir -p "${MOCK_DIR}/themes/PaperMod/layouts/_default"
  cp "${REPO_ROOT}/website-integration/themes/PaperMod/layouts/_default/polymarket-preview.html" \
    "${MOCK_DIR}/themes/PaperMod/layouts/_default/polymarket-preview.html"
fi
if [[ -d "${REPO_ROOT}/website-integration/content/preview" ]]; then
  mkdir -p "${MOCK_DIR}/content/preview"
  cp -r "${REPO_ROOT}/website-integration/content/preview/." "${MOCK_DIR}/content/preview/"
fi
# Public Wahlkreis / Einzug / Kandidat pages (moved off /preview/).
rm -rf \
  "${MOCK_DIR}/content/preview/direktmandate" \
  "${MOCK_DIR}/content/preview/einzug" \
  "${MOCK_DIR}/content/preview/kandidat"
for page_dir in direktmandate einzug kandidat; do
  if [[ -d "${REPO_ROOT}/website-integration/content/${page_dir}" ]]; then
    mkdir -p "${MOCK_DIR}/content/${page_dir}"
    cp -r "${REPO_ROOT}/website-integration/content/${page_dir}/." \
      "${MOCK_DIR}/content/${page_dir}/"
  fi
done
for page in api.md impressum.md faq.md datenschutz.md; do
  if [[ -f "${REPO_ROOT}/website-integration/content/${page}" ]]; then
    cp "${REPO_ROOT}/website-integration/content/${page}" "${MOCK_DIR}/content/${page}"
  fi
done
# Footer: Forecast API (/docs/api) + Polling API + LinkedIn.
if [[ -f "${MOCK_DIR}/config.toml" ]]; then
  python3 "${REPO_ROOT}/scripts/patch_hugo_footer.py" "${MOCK_DIR}/config.toml"
fi
# Keep methodology explainers in sync with website-integration.
for meth in district-forecast-methodology state-forecast-methodology wahlabend-nowcast-methodology; do
  if [[ -d "${REPO_ROOT}/website-integration/content/blog/posts/${meth}" ]]; then
    mkdir -p "${MOCK_DIR}/content/blog/posts/${meth}"
    cp -r "${REPO_ROOT}/website-integration/content/blog/posts/${meth}/." \
      "${MOCK_DIR}/content/blog/posts/${meth}/"
  fi
done

# Research / FAQ / Team / blog-archive hubs (same as live, plus preview-only pages above).
INT="${REPO_ROOT}/website-integration"
if [[ -f "${INT}/content/research/_index.md" ]]; then
  mkdir -p "${MOCK_DIR}/content/research"
  cp "${INT}/content/research/_index.md" "${MOCK_DIR}/content/research/_index.md"
fi
if [[ -d "${INT}/content/research/posts" ]]; then
  mkdir -p "${MOCK_DIR}/content/research/posts"
  cp -r "${INT}/content/research/posts/." "${MOCK_DIR}/content/research/posts/"
fi
if [[ -f "${INT}/content/blog/_index.md" ]]; then
  mkdir -p "${MOCK_DIR}/content/blog"
  cp "${INT}/content/blog/_index.md" "${MOCK_DIR}/content/blog/_index.md"
fi
if [[ -f "${INT}/content/archive/_index.md" ]]; then
  mkdir -p "${MOCK_DIR}/content/archive"
  cp "${INT}/content/archive/_index.md" "${MOCK_DIR}/content/archive/_index.md"
fi
if [[ -f "${INT}/content/team/index.md" ]]; then
  mkdir -p "${MOCK_DIR}/content/team"
  cp "${INT}/content/team/index.md" "${MOCK_DIR}/content/team/index.md"
fi
if [[ -f "${INT}/data/faq.yaml" ]]; then
  mkdir -p "${MOCK_DIR}/data"
  cp "${INT}/data/faq.yaml" "${MOCK_DIR}/data/faq.yaml"
fi
if [[ -f "${INT}/assets/css/extended/custom.css" ]]; then
  mkdir -p "${MOCK_DIR}/assets/css/extended"
  cp "${INT}/assets/css/extended/custom.css" "${MOCK_DIR}/assets/css/extended/custom.css"
fi
if [[ -d "${INT}/layouts/_default" ]]; then
  mkdir -p "${MOCK_DIR}/layouts/_default"
  for layout in forschung.html faq.html article.html posts-hub.html; do
    if [[ -f "${INT}/layouts/_default/${layout}" ]]; then
      cp "${INT}/layouts/_default/${layout}" "${MOCK_DIR}/layouts/_default/${layout}"
    fi
  done
fi

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

# Prefer newer pipeline JSON from gh-pages *and* the live site over stale local output/.
# UI-only redeploys used to clobber Action-published forecasts because this script
# force-pushes an orphan gh-pages tree seeded from local output/ (often days old).
# Merging only origin/gh-pages is not enough: once a stale force-push lands, later
# deploys keep copying that stale tree. Live zweitstimme.org/data/ is the source of
# truth for statewide forecasts / Stimmung.
# Set SKIP_REMOTE_DATA_MERGE=1 to publish local output/ as-is (e.g. date corrections).
LIVE_DATA_BASE="${LIVE_DATA_BASE:-https://zweitstimme.org/data}"
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
  echo "  (could not clone ${BRANCH}; will still merge from live site)"
fi
rm -rf "${REMOTE_DATA}"

echo "Merging newer statewide JSON from ${LIVE_DATA_BASE}/ ..."
python3 - <<'PY' "${TMP_PUBLISH}/data" "${LIVE_DATA_BASE}"
import json, sys, urllib.error, urllib.request
from pathlib import Path

local_dir = Path(sys.argv[1])
live_base = sys.argv[2].rstrip("/")
local_dir.mkdir(parents=True, exist_ok=True)

def stamp_bytes(raw: bytes):
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    meta = payload.get("metadata")
    if isinstance(meta, dict) and meta.get("last_update"):
        return str(meta["last_update"])
    if payload.get("last_update"):
        return str(payload["last_update"])
    return None

def stamp_path(path: Path):
    try:
        return stamp_bytes(path.read_bytes())
    except Exception:
        return None

# Live does not ship mock-only district/geo files. Statewide forecasts + Stimmung only.
names = [
    "display_mode.json",
    "election_calendar.json",
    "election_dates.json",
    "current_stimmung.json",
    "stimmung_federal.json",
    "stimmung_states.json",
    "party_order.json",
    "polls_supplement.json",
    "forecast_federal.json",
]
for path in sorted(local_dir.glob("forecast_state_*.json")):
    names.append(path.name)
# Always try the current Landtag files even if local output/ omitted them.
for code in ("st", "be", "mv"):
    names.append(f"forecast_state_{code}.json")
    names.append(f"forecast_state_{code}_draws.json")

kept = 0
seen = set()
for name in names:
    if name in seen:
        continue
    seen.add(name)
    url = f"{live_base}/{name}"
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            continue
        print(f"  skip live {name}: HTTP {e.code}", file=sys.stderr)
        continue
    except Exception as e:
        print(f"  skip live {name}: {e}", file=sys.stderr)
        continue
    dest = local_dir / name
    live_stamp = stamp_bytes(raw)
    local_stamp = stamp_path(dest) if dest.exists() else None
    if (not dest.exists()) or (live_stamp and (not local_stamp or live_stamp > local_stamp)):
        dest.write_bytes(raw)
        kept += 1
        print(f"  keep live data/{name}")
print(f"Merged {kept} newer live data file(s).")
PY
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
  python3 - <<'PY' "${TMP_PUBLISH}" "${BASE_PATH}" "${BASE_URL}"
import pathlib
import re
import sys
from urllib.parse import urlparse

root = pathlib.Path(sys.argv[1])
base = sys.argv[2].rstrip("/")
base_url = sys.argv[3]
parsed = urlparse(base_url)
host = f"{parsed.scheme}://{parsed.netloc}"

prefixes = (
    "/images/", "/data/", "/js/", "/assets/", "/blog/",
    "/team/", "/faq/", "/impressum/", "/datenschutz/", "/research/", "/archive/", "/api/",
    "/preview/",
    "/direktmandate/", "/einzug/", "/kandidat/",
    "/pred_probabilities.json", "/forecast.json", "/forecast_districts.json",
    "/draws.json", "/last_updated.json", "/pred_vacant.json",
)
pats = []
for p in prefixes:
    # Directory prefixes must be followed by a path segment. Otherwise
    # JS detectors like indexOf('/preview/') become indexOf('/<repo>/preview/')
    # and siteBase() collapses to '/'.
    tail = r"(?=[A-Za-z0-9._~-])" if p.endswith("/") else ""
    pats.append(
        re.compile(
            r"(?<!" + re.escape(base) + r")"
            r'(?<=["\'=\s(,])'
            r"(" + re.escape(p) + r")"
            + tail
        )
    )
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
    if host and base:
        text = text.replace(host + "/api/", host + base + "/api/")
        text = re.sub(
            r"(data-root=)"
            + re.escape(host + "/")
            + r"(?!"
            + re.escape(base.lstrip("/") + "/")
            + r")",
            r"\1" + host + base + "/",
            text,
        )
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
