#!/usr/bin/env Rscript
# Convert state-models fcst_state.Rdata (+ draws) into website forecast_state_*.json.

suppressPackageStartupMessages({
  library(jsonlite)
  library(dplyr)
  library(tidyr)
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
OUTPUT_DIR <- file.path(REPO_ROOT, "output")
STATE_MODELS_DIR <- Sys.getenv(
  "STATE_MODELS_DIR",
  file.path(REPO_ROOT, "..", "state-models")
)
STATE_MODELS_DIR <- normalizePath(STATE_MODELS_DIR, mustWork = FALSE)

source(file.path(REPO_ROOT, "R", "config.R"))
source(file.path(REPO_ROOT, "R", "party_order.R"))
source(file.path(SCRIPT_DIR, "compute_scenarios.R"))

SCENARIO_CONFIG_FILE <- file.path(REPO_ROOT, "data", "state_forecast_scenarios.json")
ELECTION_CALENDAR_FILE <- file.path(REPO_ROOT, "data", "election_calendar.json")
PREDICTOR_ENCODING <- "state_models_exact_lead_v1"

MODEL_PARTY_LABELS <- c(
  afd = "AfD", bsw = "BSW", cdu = "CDU/CSU", fdp = "FDP",
  gru = "GRÜNE", lin = "LINKE", spd = "SPD", oth = "Sonstige"
)

`%||%` <- function(a, b) if (is.null(a) || length(a) == 0 || (length(a) == 1 && is.na(a))) b else a

display_party_label <- function(code, state_code = NULL) {
  sc <- toupper(as.character(state_code %||% ""))
  if (identical(code, "cdu")) {
    if (identical(sc, "BY")) return("CSU")
    if (identical(sc, "") || identical(sc, "BUND") || identical(sc, "DE")) return("CDU/CSU")
    return("CDU")
  }
  MODEL_PARTY_LABELS[[code]] %||% code
}

scenario_config_md5 <- function() {
  if (!file.exists(SCENARIO_CONFIG_FILE)) return("")
  unname(tools::md5sum(SCENARIO_CONFIG_FILE))
}

election_name_for_state <- function(state_code, election_date = NULL) {
  if (!file.exists(ELECTION_CALENDAR_FILE)) {
    return(paste("Landtagswahl", state_code))
  }
  cal <- tryCatch(
    jsonlite::fromJSON(ELECTION_CALENDAR_FILE, simplifyVector = FALSE),
    error = function(e) NULL
  )
  elections <- cal$elections %||% list()
  sc <- toupper(as.character(state_code))
  ed <- if (is.null(election_date) || !nzchar(as.character(election_date))) {
    NA_character_
  } else {
    as.character(election_date)
  }
  match_name <- NULL
  for (e in elections) {
    if (!identical(toupper(as.character(e$state_code %||% "")), sc)) next
    name <- as.character(e$election_name %||% "")
    if (!nzchar(name)) next
    if (!is.na(ed) && identical(as.character(e$election_date %||% ""), ed)) {
      return(name)
    }
    if (is.null(match_name)) match_name <- name
  }
  match_name %||% paste("Landtagswahl", sc)
}

round_pct <- function(x) as.integer(round(100 * as.numeric(x)))

# Round shares to integers that sum to 100 via largest remainders (no dump onto Sonstige).
round_fits_to_100 <- function(shares) {
  shares <- as.numeric(shares)
  shares[!is.finite(shares) | shares < 0] <- 0
  total <- sum(shares)
  n <- length(shares)
  if (n == 0L || total <= 0) return(integer(n))
  pct <- as.numeric(100 * shares / total)
  base <- as.integer(floor(pct + 1e-12))
  rem <- as.numeric(pct - base)
  need <- as.integer(100L - sum(base))
  if (need > 0L) {
    ord <- order(-rem, seq_len(n))
    add <- ord[seq_len(min(need, n))]
    base[add] <- base[add] + 1L
  } else if (need < 0L) {
    ord <- order(rem, seq_len(n))
    cut <- ord[seq_len(min(-need, n))]
    base[cut] <- pmax(0L, base[cut] - 1L)
  }
  as.integer(base)
}

parties_from_ci <- function(ci_rows, state_code) {
  fits <- round_fits_to_100(as.numeric(ci_rows$fit))
  parties_out <- lapply(seq_len(nrow(ci_rows)), function(i) {
    row <- ci_rows[i, ]
    list(
      party = display_party_label(as.character(row$party), state_code),
      party_code = as.character(row$party),
      fit = fits[[i]],
      low = round_pct(row$lwr),
      high = round_pct(row$upr)
    )
  })

  party_order_payload <- tryCatch(build_party_order(), error = function(e) NULL)
  state_order <- character(0)
  if (!is.null(party_order_payload) && !is.null(party_order_payload$states[[state_code]])) {
    state_order <- party_order_payload$states[[state_code]]$order %||% character(0)
  }
  if (length(state_order) == 0) {
    state_order <- c("CDU/CSU", "AfD", "SPD", "GRÜNE", "LINKE", "BSW", "FDP")
  }
  party_rank <- function(label) {
    if (identical(label, "Sonstige")) return(1000L)
    idx <- match(label, state_order)
    if (is.na(idx) && label %in% c("CSU", "CDU", "CDU/CSU")) {
      idx <- match("CDU/CSU", state_order)
      if (is.na(idx)) idx <- match("CSU", state_order)
      if (is.na(idx)) idx <- match("CDU", state_order)
    }
    if (is.na(idx)) return(500L)
    as.integer(idx)
  }
  parties_out[order(vapply(parties_out, function(r) party_rank(r$party), integer(1)))]
}

scenarios_from_draws <- function(draws_for_elec, state_code) {
  get_fn <- function(data, election_id, model) draws_for_elec
  compute_forecast_scenarios(
    forecast_data = NULL,
    election_id = unique(draws_for_elec$elec_ind)[[1]],
    model = NULL,
    get_posterior_draws_fn = get_fn,
    config_path = SCENARIO_CONFIG_FILE,
    state_code = state_code
  )
}

# Wide posterior vote-share matrix (shares sum to 1 per draw), same object as
# scenario probabilities. Party order prefers the usual set, then any extras.
draws_wide_payload <- function(draws_for) {
  if (is.null(draws_for) || nrow(draws_for) == 0) return(NULL)
  if (!all(c("draw", "party", "posterior_draw") %in% names(draws_for))) {
    return(NULL)
  }
  wide <- draws_for %>%
    select(draw, party, posterior_draw) %>%
    pivot_wider(names_from = party, values_from = posterior_draw) %>%
    arrange(draw)
  preferred <- c("cdu", "spd", "gru", "fdp", "lin", "afd", "bsw", "oth")
  party_cols <- c(
    intersect(preferred, names(wide)),
    setdiff(setdiff(names(wide), "draw"), preferred)
  )
  if (length(party_cols) == 0) return(NULL)
  mat <- as.matrix(wide[, party_cols, drop = FALSE])
  storage.mode(mat) <- "double"
  mat[!is.finite(mat)] <- 0
  rs <- rowSums(mat)
  rs[!is.finite(rs) | rs <= 0] <- 1
  mat <- sweep(mat, 1, rs, "/")
  rows <- lapply(seq_len(nrow(mat)), function(i) {
    stats::setNames(as.list(as.numeric(mat[i, ])), party_cols)
  })
  list(
    n_draws = nrow(mat),
    unit = "share",
    parties = party_cols,
    draws = rows
  )
}

# last_poll_date = newest state poll included in the model data (UI: „Letzte Umfrage“).
# last_update = when this JSON was written (UI: „Stand“). Do not conflate the two.
# state-models anchors lead/asof on that poll date as well.
load_state_last_poll_dates <- function() {
  polls_path <- file.path(STATE_MODELS_DIR, "data", "output", "01_state-polls.csv")
  if (!file.exists(polls_path)) return(list())
  polls <- tryCatch(
    utils::read.csv(polls_path, stringsAsFactors = FALSE),
    error = function(e) NULL
  )
  if (is.null(polls) || !nrow(polls) || !all(c("date", "land") %in% names(polls))) {
    return(list())
  }
  polls$date <- as.Date(polls$date)
  polls$land <- tolower(as.character(polls$land))
  if ("poll_share" %in% names(polls)) {
    polls <- polls[!is.na(polls$poll_share), , drop = FALSE]
  }
  polls <- polls[!is.na(polls$date) & nzchar(polls$land), , drop = FALSE]
  if (!nrow(polls)) return(list())
  by_land <- split(polls$date, polls$land)
  lapply(by_land, function(dates) as.character(max(dates, na.rm = TRUE)))
}

convert_all <- function(fcst_path = file.path(STATE_MODELS_DIR, "data", "output", "forecast", "fcst_state.Rdata")) {
  if (!file.exists(fcst_path)) {
    stop("Missing forecast artifact: ", fcst_path, " — run state-models pipeline first.")
  }
  e <- new.env(parent = emptyenv())
  load(fcst_path, envir = e)
  fcst_ci <- e$fcst_ci
  fcst_draws <- e$fcst_draws
  if (is.null(fcst_ci) || nrow(fcst_ci) == 0) stop("fcst_ci empty in ", fcst_path)

  last_poll_by_land <- load_state_last_poll_dates()
  elec_inds <- unique(as.character(fcst_ci$elec_ind))
  dir.create(OUTPUT_DIR, recursive = TRUE, showWarnings = FALSE)
  written <- character(0)

  for (elec_ind in elec_inds) {
    state_lower <- sub("_.*", "", elec_ind)
    state_code <- toupper(state_lower)
    election_date <- sub(".*_", "", elec_ind)
    ci_rows <- fcst_ci %>% filter(elec_ind == !!elec_ind) %>% arrange(party)
    if (nrow(ci_rows) == 0) next

    lead_horizon_days <- as.integer(ci_rows$lead_days_used[[1]])
    model_suffix <- as.character(e$model_type_suffix %||% "polls")
    if (!nzchar(model_suffix)) model_suffix <- "polls"
    lead_model <- paste0(lead_horizon_days, "_", model_suffix)
    asof <- as.character(ci_rows$stand_date[[1]] %||% e$stand_date %||% NA)
    stand <- last_poll_by_land[[state_lower]] %||% NA_character_
    if (is.na(stand) || !nzchar(stand)) {
      # Fallback only if poll CSV missing; prefer not to publish run-date as Stand.
      stand <- NA_character_
      warning("No last poll date for ", state_lower, " in 01_state-polls.csv")
    }

    parties_out <- parties_from_ci(ci_rows, state_code)
    draws_for <- fcst_draws %>% filter(elec_ind == !!elec_ind)
    scenarios <- if (nrow(draws_for) > 0) {
      scenarios_from_draws(draws_for, state_code)
    } else {
      list(min_probability_pct = 1, hurdle_pct = 5, items = list())
    }
    draws_payload <- draws_wide_payload(draws_for)
    n_draws <- if (is.null(draws_payload)) 0L else as.integer(draws_payload$n_draws)

    payload <- list(
      metadata = list(
        state_code = state_code,
        election_date = election_date,
        election_id = elec_ind,
        election_name = election_name_for_state(state_code, election_date),
        model = paste0(
          "state-models lr ", lead_model,
          " (exact lead; polls-only; Sonstige modeled + normalize; no new_party)"
        ),
        lead = as.character(lead_horizon_days),
        lead_model = lead_model,
        lead_horizon_days = lead_horizon_days,
        poll_window_days = NULL,
        last_poll_date = if (is.na(stand) || !nzchar(stand)) NULL else stand,
        asof_date = if (is.na(asof) || !nzchar(asof)) NULL else asof,
        last_update = format(
          as.POSIXct(Sys.time(), tz = "UTC"), "%Y-%m-%dT%H:%M:%SZ"
        ),
        scenario_config_md5 = scenario_config_md5(),
        predictor_encoding = PREDICTOR_ENCODING,
        shares_normalized_to_100 = TRUE,
        n_draws = n_draws,
        draws_path = paste0("/api/v2/state/", state_lower, "/draws.json"),
        source_repo = "zweitstimme-org/state-models"
      ),
      parties = parties_out,
      scenarios = scenarios
    )

    out_file <- file.path(OUTPUT_DIR, paste0("forecast_state_", state_lower, ".json"))
    write_json(payload, out_file, auto_unbox = TRUE, pretty = TRUE, null = "null")
    cat("Wrote", out_file, "\n")
    written <- c(written, out_file)

    if (!is.null(draws_payload)) {
      draws_file <- file.path(
        OUTPUT_DIR, paste0("forecast_state_", state_lower, "_draws.json")
      )
      draws_out <- list(
        metadata = payload$metadata,
        summary = list(parties = parties_out),
        n_draws = draws_payload$n_draws,
        unit = draws_payload$unit,
        normalization = "shares_sum_to_1",
        notes = paste(
          "Each draw is a posterior predictive vote-share vector (0-1),",
          "normalized so party shares sum to 1. summary.parties repeats the",
          "published point estimates and ~83% interval in percentage points."
        ),
        last_update = payload$metadata$last_update,
        asof_date = payload$metadata$asof_date,
        last_poll_date = payload$metadata$last_poll_date,
        forecast_path = paste0("/api/v2/state/", state_lower, ".json"),
        parties = draws_payload$parties,
        draws = draws_payload$draws
      )
      write_json(
        draws_out, draws_file,
        auto_unbox = TRUE, pretty = FALSE, null = "null", digits = 6
      )
      cat("Wrote", draws_file, "\n")
      written <- c(written, draws_file)
    }
  }
  invisible
}

if (sys.nframe() == 0) {
  args <- commandArgs(trailingOnly = TRUE)
  path <- if (length(args) >= 1) args[[1]] else file.path(
    STATE_MODELS_DIR, "data", "output", "forecast", "fcst_state.Rdata"
  )
  convert_all(path)
}
