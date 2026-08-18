"""Configuration for the zweitstimme.org polling pipeline."""

POLLING_API_BASE_URL = "https://api.zweitstimme.org"
POLLING_API_POLLS_ENDPOINT = f"{POLLING_API_BASE_URL}/v2/polls"

# Fasttrack allows up to 10_000 rows per page.
POLLING_API_PAGE_SIZE = 10_000

WAHLRECHT_ELECTION_DATES_URL = "https://www.wahlrecht.de/umfragen/landtage/"

# Fasttrack scope codes -> display state codes used on the website.
SCOPE_TO_STATE_CODE = {
    "bw": "BW",
    "by": "BY",
    "be": "BE",
    "bb": "BB",
    "hb": "HB",
    "hh": "HH",
    "he": "HE",
    "mv": "MV",
    "ni": "NI",
    "nrw": "NW",
    "rp": "RP",
    "sl": "SL",
    "sn": "SN",
    "st": "ST",
    "sh": "SH",
    "th": "TH",
}

# party_key / party_short_name -> consolidated website labels
PARTY_KEY_TO_NAME = {
    "CDU_CSU": "CDU/CSU",
    "CDU": "CDU/CSU",
    "CSU": "CDU/CSU",
    "SPD": "SPD",
    "GRUENE": "GRÜNE",
    "FDP": "FDP",
    "LINKE": "LINKE",
    "AFD": "AfD",
    "BSW": "BSW",
    "SONSTIGE": "Sonstige",
    "FREIE_WAEHLER": "Freie Wähler",
    "SSW": "SSW",
}

JSON_OUTPUT_DIR = "data/json_output"
ELECTION_DATES_FILE = f"{JSON_OUTPUT_DIR}/election_dates.json"
