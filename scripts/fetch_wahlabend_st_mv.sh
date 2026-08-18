#!/usr/bin/env bash
# Fetch ST/MV Wahlabend raw inputs (historical WB end results + night-feed placeholders).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UA="${CURL_UA:-Mozilla/5.0}"

fetch() {
  local dest="$1" url="$2"
  mkdir -p "$(dirname "${dest}")"
  if [[ -f "${dest}" && -s "${dest}" ]]; then
    echo "have $(basename "${dest}")"
    return 0
  fi
  echo "GET $(basename "${dest}")"
  curl -fsSL -A "${UA}" -o "${dest}" "${url}"
}

ST_RAW="${ROOT}/sachsen-anhalt/wahlabend/raw"
MV_RAW="${ROOT}/mecklenburg-vorpommern/wahlabend/raw"
mkdir -p "${ST_RAW}" "${MV_RAW}"

# --- Sachsen-Anhalt (StaLA) ---
ST_BASE='https://wahlergebnisse.sachsen-anhalt.de/wahlen'
fetch "${ST_RAW}/lt21dat1.csv" "${ST_BASE}/lt21/erg/csv/lt21dat1.csv"
fetch "${ST_RAW}/lt21dat2.csv" "${ST_BASE}/lt21/erg/csv/lt21dat2.csv"
fetch "${ST_RAW}/LT2021_WBZ.xlsx" "${ST_BASE}/lt21/erg/csv/LT2021_WBZ.xlsx"
fetch "${ST_RAW}/lt16dat2.csv" "${ST_BASE}/lt16/erg/csv/lt16dat2.csv"
fetch "${ST_RAW}/LT2016_GEM.csv" "${ST_BASE}/lt16/erg/csv/LT2016_GEM.csv"
fetch "${ST_RAW}/LT2016_WBZ.xlsx" "${ST_BASE}/lt16/erg/csv/LT2016_WBZ.xlsx"

# Night feed (Leerdateien ab 2. Augusthälfte 2026; live Zwischenergebnisse am Wahltag)
# Documented landing: …/lt26/downloads.html — filenames TBD when StaLA publishes empties.
mkdir -p "${ST_RAW}/live"
echo "ST live dir ready → ${ST_RAW}/live (poll …/lt26/downloads.html on election night)"

# --- Mecklenburg-Vorpommern (LAIV) ---
# Prefer copies from LTWMeckPom raw-data if present; else leave hooks for LAIV 2026 CSVs.
MV_SRC="${ROOT}/mecklenburg-vorpommern/LTWMeckPom/raw-data"
if [[ -d "${MV_SRC}" ]]; then
  python3 - <<'PY' "${MV_SRC}" "${MV_RAW}"
import shutil, sys
from pathlib import Path
src, dst = Path(sys.argv[1]), Path(sys.argv[2])
dst.mkdir(parents=True, exist_ok=True)
for f in src.iterdir():
    if not f.is_file():
        continue
    name = f.name
    if "2021" in name and name.lower().endswith(".xlsx") and ("WBZ" in name.upper() or "Endg" in name):
        shutil.copy2(f, dst / "LTW2021_WBZ.xlsx")
        print("copied", name, "→ LTW2021_WBZ.xlsx")
    if "2016" in name and name.lower().endswith(".xlsx") and ("Wahlbezirk" in name or "WBZ" in name.upper() or "Endg" in name):
        shutil.copy2(f, dst / "LTW2016_WBZ.xlsx")
        print("copied", name, "→ LTW2016_WBZ.xlsx")
PY
fi

# Night feed: LAIV publishes empty CSVs before election, then timestamped updates ~19:00.
# https://www.laiv-mv.de/Wahlen/Landtagswahlen/2026/Ergebnisse/
mkdir -p "${MV_RAW}/live"
echo "MV live dir ready → ${MV_RAW}/live (l_wahlbezirke.csv / l_gemeinden.csv / l_wahlkreise.csv)"

echo "Done."
echo "  ST → ${ST_RAW}"
echo "  MV → ${MV_RAW}"
