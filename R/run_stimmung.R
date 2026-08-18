#!/usr/bin/env Rscript
# Compute Aktuelle Stimmung (Kalman) for federal and all states.

suppressPackageStartupMessages({
  if (!requireNamespace("jsonlite", quietly = TRUE)) {
    source(file.path(dirname(sys.frame(1)$ofile), "install.R"))
  }
})

get_script_dir <- function() {
  args <- commandArgs(trailingOnly = FALSE)
  file_arg <- grep("^--file=", args, value = TRUE)
  if (length(file_arg) > 0) {
    return(normalizePath(dirname(sub("^--file=", "", file_arg[1])), mustWork = FALSE))
  }
  normalizePath(getwd(), mustWork = FALSE)
}

SCRIPT_DIR <- get_script_dir()
REPO_ROOT <- normalizePath(file.path(SCRIPT_DIR, ".."), mustWork = FALSE)

source(file.path(SCRIPT_DIR, "config.R"))
source(file.path(SCRIPT_DIR, "party_mapper.R"))
source(file.path(SCRIPT_DIR, "fetch_polls.R"))
source(file.path(SCRIPT_DIR, "kalman.R"))
source(file.path(SCRIPT_DIR, "display_mode.R"))
source(file.path(SCRIPT_DIR, "party_order.R"))

dir.create(OUTPUT_DIR, recursive = TRUE, showWarnings = FALSE)

core_parties <- CORE_PARTIES
optional_parties <- c("FW", "SSW", "PIRATEN", "REP")
all_parties <- c(core_parties, optional_parties, "Sonstige")

end_iso <- format(Sys.Date(), "%Y-%m-%d")
start_iso <- format(Sys.Date() - STIMMUNG_HISTORY_DAYS, "%Y-%m-%d")

compute_scope_stimmung <- function(scope, label = scope) {
  cat(sprintf("Computing Stimmung for %s...\n", label))
  polls <- fetch_polls_all(scope, date_from = start_iso, date_to = end_iso, max_total = 5000)

  if (length(polls) == 0) {
    warning(sprintf("No polls found for scope %s", scope))
    return(NULL)
  }

  range <- polls_date_range(polls)
  effective_start <- start_iso
  if (!is.na(range$start) && range$start > effective_start) {
    effective_start <- range$start
  }

  if (identical(scope, "federal")) {
    q_default <- KALMAN_Q
    r_default <- KALMAN_R
  } else {
    q_default <- STATE_KALMAN_PARAMS$long$q
    r_default <- STATE_KALMAN_PARAMS$long$r
  }

  if (CALIBRATE_KALMAN) {
    calib <- calibrate_kalman_qr(
      polls,
      parties = core_parties,
      q_default = q_default,
      r_default = r_default
    )
    q <- calib$q
    r <- calib$r
    cat(sprintf(
      "  Kalman q=%.3f r=%.3f (%s, n_pairs=%d)\n",
      q, r,
      if (isTRUE(calib$calibrated)) "calibrated" else "fallback",
      as.integer(calib$n_pairs %||% 0L)
    ))
  } else {
    calib <- list(q = q_default, r = r_default, calibrated = FALSE, n_pairs = 0L, fallback = TRUE)
    q <- q_default
    r <- r_default
  }

  kalman <- latent_support_from_polls(
    polls,
    start_iso = effective_start,
    end_iso = end_iso,
    parties = all_parties,
    q = q,
    r = r,
    use_smoother = USE_SMOOTHER,
    # Only core parties: optional ones (FW, SSW, ...) are institute-specific
    # and must not get phantom 2% observations.
    impute_parties = core_parties
  )

  normalized <- apply_inclusion_and_normalize(
    kalman, polls, core_parties, optional_parties,
    uncertainty_sigma = KALMAN_UNCERTAINTY_SIGMA
  )
  use_key <- if (USE_SMOOTHER) "smoothed" else "filtered"

  list(
    metadata = list(
      scope = scope,
      label = label,
      last_update = format(Sys.time(), "%Y-%m-%dT%H:%M:%OS"),
      start_date = effective_start,
      end_date = end_iso,
      polls_used = length(polls),
      date_range = range,
      use_smoother = USE_SMOOTHER,
      kalman = list(
        q = q,
        r = r,
        uncertainty_sigma = KALMAN_UNCERTAINTY_SIGMA,
        calibrated = isTRUE(calib$calibrated),
        n_pairs = as.integer(calib$n_pairs %||% 0L),
        q_default = q_default,
        r_default = r_default
      )
    ),
    dates = normalized$dates,
    series = normalized$series,
    raw_series = kalman$series[[use_key]],
    uncertainty = kalman$uncertainty[[use_key]],
    uncertainty_low = normalized$uncertainty_low,
    uncertainty_high = normalized$uncertainty_high,
    current = normalized$current,
    trends = normalized$trends,
    include_optional = normalized$include_optional,
    active_parties = normalized$active_parties
  )
}

federal <- compute_scope_stimmung("federal", "Bundestag")

states_payload <- list(
  metadata = list(
    last_update = format(Sys.time(), "%Y-%m-%dT%H:%M:%OS"),
    scopes = STATE_SCOPES
  ),
  states = list()
)

current_states <- list()

for (scope in STATE_SCOPES) {
  state_code <- SCOPE_TO_STATE_CODE[[scope]]
  result <- compute_scope_stimmung(scope, state_code)
  if (is.null(result)) next
  states_payload$states[[state_code]] <- result
  current_states[[state_code]] <- list(
    current_support = result$current,
    trends = result$trends,
    active_parties = result$active_parties,
    polls_used = result$metadata$polls_used,
    date_range = result$metadata$date_range,
    last_update = result$metadata$last_update
  )
}

current_payload <- list(
  federal = if (!is.null(federal)) list(
    current_support = federal$current,
    trends = federal$trends,
    active_parties = federal$active_parties,
    polls_used = federal$metadata$polls_used,
    date_range = federal$metadata$date_range,
    last_update = federal$metadata$last_update
  ) else NULL,
  states = current_states,
  last_update = format(Sys.time(), "%Y-%m-%dT%H:%M:%OS")
)

write_json_safe <- function(obj, path) {
  jsonlite::write_json(obj, path, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null")
}

if (!is.null(federal)) {
  write_json_safe(federal, file.path(OUTPUT_DIR, "stimmung_federal.json"))
}
write_json_safe(states_payload, file.path(OUTPUT_DIR, "stimmung_states.json"))
write_json_safe(current_payload, file.path(OUTPUT_DIR, "current_stimmung.json"))

calendar <- build_election_calendar()
build_display_mode(calendar)
build_party_order()

cat("Stimmung pipeline complete. Output written to", OUTPUT_DIR, "\n")
