#!/usr/bin/env bash
# Fetch Berlin AGH 2026 AfS _A_ / _W_ CSVs (Erst + Zweit) and snapshot them.
# AfS asks for a poll interval of two minutes or more.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${ROOT}/berlin/wahlabend/live"
SNAP_ROOT="${DEST}/snapshots"
UA="${CURL_UA:-Mozilla/5.0 (compatible; zweitstimme-nowcast/1.0)}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
SNAP="${SNAP_ROOT}/${TS}"
mkdir -p "${DEST}" "${SNAP}"

BASES=(
  "https://www.wahlen-berlin.de/wahlen/Be2026/AFSPRAES/agh"
  "https://www.wahlen-berlin.de/wahlen/BE2026/AFSPRAES/agh"
)

FILES=(
  Datenexport_AGH2026_Zweitstimme_A_BE.csv
  Datenexport_AGH2026_Erststimme_A_BE.csv
  Datenexport_AGH2026_Zweitstimme_W_BE.csv
  Datenexport_AGH2026_Erststimme_W_BE.csv
)

hdr_val() {
  local file="$1" key="$2"
  grep -i "^${key}:" "${file}" | head -n 1 | sed 's/^[^:]*:[[:space:]]*//;s/\r$//'
}

fetch_one() {
  local name="$1"
  local tmp hdr
  tmp="$(mktemp)"
  hdr="$(mktemp)"
  local ok=0
  for base in "${BASES[@]}"; do
    echo "GET ${base}/${name}"
    if curl -fsSL -A "${UA}" -D "${hdr}" -o "${tmp}" --max-time 45 "${base}/${name}"; then
      # Reject HTML error shells
      if head -c 32 "${tmp}" | grep -qi '<html\|<!doctype'; then
        echo "  WARN: HTML instead of CSV at ${base}"
        continue
      fi
      ok=1
      break
    fi
  done
  if [[ "${ok}" != "1" ]]; then
    rm -f "${tmp}" "${hdr}"
    echo "WARN: failed to fetch ${name}" >&2
    return 0
  fi
  cp -f "${tmp}" "${DEST}/${name}"
  cp -f "${tmp}" "${SNAP}/${name}"
  local sha lm etag clen
  sha="$(sha256sum "${tmp}" | awk '{print $1}')"
  lm="$(hdr_val "${hdr}" last-modified)"
  etag="$(hdr_val "${hdr}" etag)"
  clen="$(wc -c < "${tmp}" | tr -d ' ')"
  python3 - "${SNAP_ROOT}/manifest.jsonl" "${TS}" "${name}" "${sha}" "${lm}" "${etag}" "${clen}" <<'PY'
import json, sys
from pathlib import Path
path, ts, name, sha, lm, etag, clen = sys.argv[1:8]
rec = {
    "ts_utc": ts,
    "file": name,
    "sha256": sha,
    "bytes": int(clen),
    "last_modified": lm or None,
    "etag": etag or None,
}
p = Path(path)
p.parent.mkdir(parents=True, exist_ok=True)
with p.open("a", encoding="utf-8") as f:
    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
print(f"  snap {ts}/{name}  {clen} B  sha={sha[:12]}  lm={lm or '—'}")
PY
  rm -f "${tmp}" "${hdr}"
}

for f in "${FILES[@]}"; do
  fetch_one "${f}"
done
echo "Done → ${DEST}"
