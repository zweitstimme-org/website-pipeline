#!/usr/bin/env bash
# Fetch current StaLA LTW 2026 result CSVs and keep every snapshot.
# Same URLs are overwritten after 18:00; we copy each download to snapshots/.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${ROOT}/sachsen-anhalt/wahlabend/live"
SNAP_ROOT="${DEST}/snapshots"
UA="${CURL_UA:-Mozilla/5.0 (compatible; zweitstimme-nowcast/1.0)}"
BASE="https://wahlergebnisse.sachsen-anhalt.de/wahlen/lt26/downloads"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
SNAP="${SNAP_ROOT}/${TS}"
mkdir -p "${DEST}" "${SNAP}"

hdr_val() {
  local file="$1" key="$2"
  grep -i "^${key}:" "${file}" | head -n 1 | sed 's/^[^:]*:[[:space:]]*//;s/\r$//'
}

fetch() {
  local name="$1"
  local required="${2:-0}"
  local tmp hdr
  tmp="$(mktemp)"
  hdr="$(mktemp)"
  echo "GET ${name}"
  if ! curl -fsSL -A "${UA}" -D "${hdr}" -o "${tmp}" "${BASE}/${name}"; then
    rm -f "${tmp}" "${hdr}"
    echo "WARN: failed to fetch ${name}" >&2
    if [[ "${required}" == "1" ]]; then
      return 1
    fi
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

fetch "Ergebnisse_Land_RKR_WKR_LT_2026.csv" 1
fetch "Ergebnisse_Gemeinden_LT_2026.csv" 0
# WBZ CSV is documented (DSB_WBZ_LT_2026.pdf) but not yet linked on downloads.html.
for guess in Ergebnisse_Wahlbezirke_LT_2026.csv Ergebnisse_WBZ_LT_2026.csv; do
  fetch "${guess}" 0
  if [[ -f "${SNAP}/${guess}" ]]; then
    echo "have WBZ ${guess}"
    break
  fi
done
if ls "${SNAP}"/*.csv >/dev/null 2>&1; then
  (cd "${SNAP}" && sha256sum -- *.csv > sha256sums.txt)
else
  rmdir "${SNAP}" 2>/dev/null || true
fi
echo "StaLA live dir → ${DEST}"
echo "snapshot → ${SNAP}"
