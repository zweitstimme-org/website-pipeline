# Pipeline configuration shared across R scripts.

if (!exists("REPO_ROOT")) {
  REPO_ROOT <- normalizePath(getwd(), mustWork = FALSE)
}

POLLING_API_BASE <- Sys.getenv("POLLING_API_BASE", "https://api.zweitstimme.org")
POLLING_API_PAGE_SIZE <- as.integer(Sys.getenv("POLLING_API_PAGE_SIZE", "10000"))
# Official DAWUM dump (Parliament_ID → Land klar). Used to fill state scopes
# while FastTrack mis-tags / drops those rows (docs/POLLING_API_SCOPE.md).
DAWUM_API_URL <- Sys.getenv("DAWUM_API_URL", "https://api.dawum.de/")

OUTPUT_DIR <- file.path(REPO_ROOT, "output")
DATA_DIR <- file.path(REPO_ROOT, "data")

ELECTION_CALENDAR_FILE <- file.path(DATA_DIR, "election_calendar.json")
ELECTION_DATES_FILE <- file.path(DATA_DIR, "json_output", "election_dates.json")
STATE_FUNDAMENTALS_FILE <- file.path(DATA_DIR, "state_fundamentals.json")
STATE_ELECTION_RESULTS_FILE <- file.path(DATA_DIR, "state-election-results.csv")

FORECAST_WINDOW_DAYS <- as.integer(Sys.getenv("FORECAST_WINDOW_DAYS", "90"))
STIMMUNG_HISTORY_DAYS <- as.integer(Sys.getenv("STIMMUNG_HISTORY_DAYS", "3650"))

# Kalman fallback defaults (used when calibration has too few poll pairs, or when
# CALIBRATE_KALMAN=false). Override with KALMAN_Q / KALMAN_R env vars.
KALMAN_Q <- as.numeric(Sys.getenv("KALMAN_Q", "0.1"))
KALMAN_R <- as.numeric(Sys.getenv("KALMAN_R", "1.0"))
# Estimate q/r from consecutive poll pairs each run (E[Δy²] = 2r + q·gap).
CALIBRATE_KALMAN <- identical(tolower(Sys.getenv("CALIBRATE_KALMAN", "true")), "true")
# RTS smoother for the plotted history (best retrospective estimate). The
# current value stays causal either way: at the last day the smoother equals
# the forward filter, matching the forecast's latent at its as-of date.
USE_SMOOTHER <- identical(tolower(Sys.getenv("USE_SMOOTHER", "true")), "true")
# Unreported-party impute, mirroring state-models 01_build_data.R: institutes
# often omit parties below ~3%; hold them at STIMMUNG_IMPUTE_PCT for
# STIMMUNG_IMPUTE_HOLD_DAYS after their last in-scope report, then let them drop.
STIMMUNG_IMPUTE_PCT <- as.numeric(Sys.getenv("STIMMUNG_IMPUTE_PCT", "2"))
STIMMUNG_IMPUTE_HOLD_DAYS <- as.integer(Sys.getenv("STIMMUNG_IMPUTE_HOLD_DAYS", "90"))
# Band width multiplier on posterior std-dev (1.0 = ±1σ). Uses smoothed variance when USE_SMOOTHER=true.
KALMAN_UNCERTAINTY_SIGMA <- as.numeric(Sys.getenv("KALMAN_UNCERTAINTY_SIGMA", "1.0"))

# Time-varying party inclusion ("activity") based on the recent poll universe.
# The reference window on any day contains all polls of the trailing
# WINDOW_DAYS, extended to at least the last MIN_K polls (for sparse state
# polling). A party becomes active once it appears in >= ENTER_FRAC of the
# window; it exits once its share of the window drops below EXIT_FRAC (in
# sparse windows additionally only after no poll listed it for
# EXIT_GRACE_DAYS). In between (hysteresis) the previous state is kept.
# Outside its active window a party is hidden and its share flows into
# Sonstige.
PARTY_ACTIVITY_WINDOW_DAYS <- as.integer(Sys.getenv("PARTY_ACTIVITY_WINDOW_DAYS", "90"))
PARTY_ACTIVITY_MIN_K <- as.integer(Sys.getenv("PARTY_ACTIVITY_MIN_K", "5"))
PARTY_ACTIVITY_ENTER_FRAC <- as.numeric(Sys.getenv("PARTY_ACTIVITY_ENTER_FRAC", "0.4"))
PARTY_ACTIVITY_EXIT_FRAC <- as.numeric(Sys.getenv("PARTY_ACTIVITY_EXIT_FRAC", "0.1"))
PARTY_ACTIVITY_EXIT_GRACE_DAYS <- as.integer(Sys.getenv("PARTY_ACTIVITY_EXIT_GRACE_DAYS", "30"))

# Fallback Kalman params when per-scope calibration lacks enough pairs or yields
# a non-positive estimate. Pipeline re-estimates each run via calibrate_kalman_qr()
# (within-day r, then residual day-to-day q).
STATE_KALMAN_PARAMS <- list(
  default = list(q = 0.1, r = 1.0),
  long = list(q = 0.05, r = 1.5)
)

STATE_SCOPES <- c(
  "bw", "by", "be", "bb", "hb", "hh", "he", "mv", "ni", "nrw", "rp", "sl", "sn", "st", "sh", "th"
)

STATE_CODE_TO_SCOPE <- c(
  BW = "bw", BY = "by", BE = "be", BB = "bb", HB = "hb", HH = "hh", HE = "he",
  MV = "mv", NI = "ni", NW = "nrw", RP = "rp", SL = "sl", SN = "sn", ST = "st", SH = "sh", TH = "th"
)

SCOPE_TO_STATE_CODE <- setNames(names(STATE_CODE_TO_SCOPE), STATE_CODE_TO_SCOPE)

CORE_PARTIES <- c("CDU/CSU", "AfD", "SPD", "GRÜNE", "LINKE", "BSW", "FDP")
OPTIONAL_PARTIES <- c("FW", "SSW", "PIRATEN", "REP", "Freie Wähler")
ALL_PARTIES <- c(CORE_PARTIES, OPTIONAL_PARTIES, "Sonstige")

`%||%` <- function(x, y) if (is.null(x)) y else x
