#!/usr/bin/env bash
# Fetch Berlin Wahlabend / nowcast raw inputs into berlin/wahlabend/raw/
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${ROOT}/berlin/wahlabend/raw"
mkdir -p "${DEST}"
UA="${CURL_UA:-Mozilla/5.0}"

fetch() {
  local out="$1" url="$2"
  if [[ -f "${DEST}/${out}" && -s "${DEST}/${out}" ]]; then
    echo "have ${out}"
    return 0
  fi
  echo "GET ${out}"
  curl -fsSL -A "${UA}" -o "${DEST}/${out}" "${url}"
}

fetch DL_BE_AH2026_Strukturdaten.xlsx \
  'https://download.statistik-berlin-brandenburg.de/aa56eddd2ea25921/1dd6f94397c4/DL_BE_AH2026_Strukturdaten.xlsx'
fetch DL_BE_AGH2026_AGH2023.xlsx \
  'https://download.statistik-berlin-brandenburg.de/eddea71cdf4e6f2b/291e0923b0a7/DL_BE_AGH2026_AGH2023.xlsx'
fetch DL_BE_AGH2026_BT2025.xlsx \
  'https://download.statistik-berlin-brandenburg.de/1e70272a9cea4ac4/0cf516026bf3/DL_BE_AGH2026_BT2025.xlsx'
fetch DL_BE_AGHBVV2023.xlsx \
  'https://download.statistik-berlin-brandenburg.de/c6fffa8361dd1404/a8cc1bc593d9/DL_BE_AGHBVV2023.xlsx'
fetch DL_BE_AGH2023_AH2016.xlsx \
  'https://wahlen-berlin.de/wahlen/BE2023/strukturdaten/DL_BE_AGH2023_AH2016.xlsx'
fetch DL_BE_AGH2023_Strukturdaten.xlsx \
  'https://wahlen-berlin.de/wahlen/BE2023/strukturdaten/DL_BE_AGH2023_Strukturdaten.xlsx'
fetch Datenexport_AGH2023_Zweitstimme_W_BE.csv \
  'https://www.wahlen-berlin.de/wahlen/BE2023/AFSPRAES/agh/Datenexport_AGH2023_Zweitstimme_W_BE.csv'

echo "Done → ${DEST}"
