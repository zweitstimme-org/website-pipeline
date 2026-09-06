#!/usr/bin/env bash
# Scrape Halle+Magdeburg city portals locally and push the JSONs to the
# st-live-data branch. Needed because Magdeburg's portal times out from
# GitHub-hosted runners; the nowcast workflow falls back to this branch.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WT=/tmp/st-live-data-wt
BRANCH=st-live-data

cd "${ROOT}"
python3 code/city_wbz_fetch.py || echo "WARN scrape partial" >&2

if [[ ! -d "${WT}" ]]; then
  git fetch origin "${BRANCH}" 2>/dev/null || true
  if git show-ref --verify --quiet "refs/remotes/origin/${BRANCH}"; then
    git worktree add "${WT}" -B "${BRANCH}" "origin/${BRANCH}"
  else
    git worktree add --detach "${WT}"
    git -C "${WT}" checkout --orphan "${BRANCH}"
    git -C "${WT}" rm -rf --quiet . 2>/dev/null || true
  fi
fi

mkdir -p "${WT}/sachsen-anhalt/wahlabend/live"
for c in halle magdeburg; do
  f="sachsen-anhalt/wahlabend/live/${c}_wbz_2026.json"
  [[ -f "${ROOT}/${f}" ]] && cp -f "${ROOT}/${f}" "${WT}/${f}"
done
cd "${WT}"
git add -A
if git diff --cached --quiet; then
  echo "no change"
  exit 0
fi
git commit -q -m "city wbz $(date -u +%H:%M:%SZ)"
git push -q -f origin "${BRANCH}"
echo "pushed ${BRANCH} $(date -u +%H:%M:%SZ)"
