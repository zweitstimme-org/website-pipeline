#!/usr/bin/env bash
# Fetch Mecklenburg-Vorpommern LTW 2026 LAIV CSVs (WK / Gemeinde / WB).
# Live files are on wahlen.mvnet.de; laiv-mv.de /dateien/ paths 404.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${ROOT}/mecklenburg-vorpommern/wahlabend/live"
SNAP_ROOT="${DEST}/snapshots"
UA="${CURL_UA:-Mozilla/5.0 (compatible; zweitstimme-nowcast/1.0)}"
PAGE="https://www.laiv-mv.de/Wahlen/Landtagswahlen/2026/Ergebnisse/"
LIVE_HOST="https://wahlen.mvnet.de/"
PAGE_LIVE="https://wahlen.mvnet.de/wahl/land"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
SNAP="${SNAP_ROOT}/${TS}"
mkdir -p "${DEST}" "${SNAP}"

hdr_val() {
  local file="$1" key="$2"
  grep -i "^${key}:" "${file}" | head -n 1 | sed 's/^[^:]*:[[:space:]]*//;s/\r$//'
}

save_csv() {
  local url="$1"
  local out_name="$2"
  local tmp hdr
  tmp="$(mktemp)"
  hdr="$(mktemp)"
  echo "GET ${url}"
  if ! curl -fsSL -A "${UA}" -D "${hdr}" -o "${tmp}" --max-time 60 "${url}"; then
    rm -f "${tmp}" "${hdr}"
    echo "WARN: failed ${url}" >&2
    return 0
  fi
  if head -c 32 "${tmp}" | grep -qi '<html\|<!doctype'; then
    rm -f "${tmp}" "${hdr}"
    echo "WARN: HTML instead of CSV ${url}" >&2
    return 0
  fi
  cp -f "${tmp}" "${DEST}/${out_name}"
  cp -f "${tmp}" "${SNAP}/${out_name}"
  local sha lm clen
  sha="$(sha256sum "${tmp}" | awk '{print $1}')"
  lm="$(hdr_val "${hdr}" last-modified)"
  clen="$(wc -c < "${tmp}" | tr -d ' ')"
  python3 - "${SNAP_ROOT}/manifest.jsonl" "${TS}" "${out_name}" "${sha}" "${lm}" "${clen}" <<'PY'
import json, sys
from pathlib import Path
path, ts, name, sha, lm, clen = sys.argv[1:7]
rec = {"ts_utc": ts, "file": name, "sha256": sha, "bytes": int(clen), "last_modified": lm or None}
p = Path(path)
p.parent.mkdir(parents=True, exist_ok=True)
with p.open("a", encoding="utf-8") as f:
    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
print(f"  snap {ts}/{name}  {clen} B  sha={sha[:12]}")
PY
  rm -f "${tmp}" "${hdr}"
}

html="$(mktemp)"
if curl -fsSL -A "${UA}" --max-time 45 -o "${html}" "${PAGE_LIVE}"; then
  :
elif curl -fsSL -A "${UA}" --max-time 45 -o "${html}" "${PAGE}"; then
  :
else
  echo "WARN: could not load LAIV / mvnet Ergebnisse page" >&2
  rm -f "${html}"
  html=""
fi

# Collect hrefs ending in .csv. Root-relative /dateien/... is on wahlen.mvnet.de.
if [[ -n "${html}" ]]; then
mapfile -t hrefs < <(python3 - "${html}" "${LIVE_HOST}" <<'PY'
import re, sys, urllib.parse
html = open(sys.argv[1], encoding="utf-8", errors="ignore").read()
base = sys.argv[2]
hrefs = re.findall(r'href=["\']([^"\']+\.csv)["\']', html, flags=re.I)
seen = set()
for h in hrefs:
    raw = h.replace("&amp;", "&")
    url = urllib.parse.urljoin(base, raw)
    if url not in seen:
        seen.add(url)
        print(url)
PY
)
  rm -f "${html}"
else
  hrefs=()
fi

if [[ ${#hrefs[@]} -eq 0 ]]; then
  echo "WARN: no CSV links on LAIV Ergebnisse page yet"
else
  for url in "${hrefs[@]}"; do
    base="$(basename "${url%%\?*}")"
    low="$(echo "${base}" | tr '[:upper:]' '[:lower:]')"
    out="${base}"
    case "${low}" in
      *wahlbezirk*) out="l_wahlbezirke.csv" ;;
      *gemeinde*) out="l_gemeinden.csv" ;;
      *wahlkreis*) out="l_wahlkreise.csv" ;;
      *mandat*) out="l_mandate.csv" ;;
      *wbt*|*wahlbeteil*) out="l_wbt.csv" ;;
    esac
    save_csv "${url}" "${out}"
  done
fi

# Always refresh the known 2026 mvnet paths (laiv-mv.de /dateien/ is 404).
for pair in \
  "l_wahlbezirke.csv|https://wahlen.mvnet.de/dateien/ergebnisse.2026/landtagswahl/csv/l_wahlbezirke.csv" \
  "l_gemeinden.csv|https://wahlen.mvnet.de/dateien/ergebnisse.2026/landtagswahl/csv/l_gemeinden.csv" \
  "l_wahlkreise.csv|https://wahlen.mvnet.de/dateien/ergebnisse.2026/landtagswahl/csv/l_wahlkreise.csv" \
  "l_mandate.csv|https://wahlen.mvnet.de/dateien/ergebnisse.2026/landtagswahl/csv/l_mandate.csv"
do
  out="${pair%%|*}"
  url="${pair#*|}"
  save_csv "${url}" "${out}"
done
echo "Done → ${DEST}"
