#!/usr/bin/env Rscript
# Run state election forecast using state-models-jelst fitted model.

suppressPackageStartupMessages({
  library(jsonlite)
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
STATE_MODELS_DIR <- Sys.getenv("STATE_MODELS_DIR", file.path(REPO_ROOT, "vendor", "state-models-jelst"))
OUTPUT_DIR <- file.path(REPO_ROOT, "output")

source(file.path(REPO_ROOT, "R", "config.R"))
source(file.path(REPO_ROOT, "R", "party_order.R"))
source(file.path(SCRIPT_DIR, "build_forecast_row.R"))
source(file.path(SCRIPT_DIR, "compute_scenarios.R"))

SCENARIO_CONFIG_FILE <- file.path(REPO_ROOT, "data", "state_forecast_scenarios.json")

MODEL_PARTY_LABELS <- c(
  afd = "AfD", bsw = "BSW", cdu = "CDU/CSU", fdp = "FDP",
  gru = "GRÜNE", lin = "LINKE", spd = "SPD", oth = "Sonstige"
)

# Bavaria's union party is the CSU; other states display CDU (not CDU/CSU).
display_party_label <- function(code, state_code = NULL) {
  sc <- toupper(as.character(state_code %||% ""))
  if (identical(code, "cdu")) {
    if (identical(sc, "BY")) return("CSU")
    if (identical(sc, "") || identical(sc, "BUND") || identical(sc, "DE")) return("CDU/CSU")
    return("CDU")
  }
  MODEL_PARTY_LABELS[[code]] %||% code
}

# Display parties: 7 core + Sonstige (BW/RP adaptation — Sonstige has its own
# predictors; each draw is then normalized to 100%).
FORECAST_DISPLAY_PARTIES <- c(FORECAST_SCENARIO_PARTIES, "oth")

# Like vendor get_posterior_draws, but keeps Sonstige (oth) rows. The fitted
# model has no party FE, so oth is predicted with the same coefficients.
get_posterior_draws_with_oth <- function(data, election_id, model,
                                         inv_function = function(x) exp(x) / (1 + exp(x))) {
  pred_dat <- data %>% dplyr::filter(elec_ind == election_id)
  pred_weeks <- pred_dat %>% dplyr::select(names(coef(model))[-1])
  pred_sim <- rstanarm::posterior_predict(model, pred_weeks)
  if (!is.null(inv_function)) {
    pred_sim <- apply(pred_sim, 2, inv_function)
  }
  as.data.frame(pred_sim) %>%
    dplyr::mutate(draw = dplyr::row_number()) %>%
    tidyr::pivot_longer(cols = -draw, names_to = "party", values_to = "posterior_draw") %>%
    dplyr::mutate(
      party = pred_dat$party[as.numeric(gsub("V", "", party))],
      elec_ind = election_id,
      state = unique(pred_dat$state),
      date = unique(pred_dat$electiondate)
    )
}

# Summarize posterior draws: predict all 8 parties (incl. Sonstige), normalize
# each draw to 100% (BW/RP adaptation). Scenarios still use the 7-core draws.
summarize_vote_share_draws <- function(forecast_data, election_id, model,
                                        get_posterior_draws_fn, alpha = 1 / 6,
                                        state_code = NULL) {
  draws_long <- get_posterior_draws_fn(
    data = forecast_data,
    election_id = election_id,
    model = model
  )
  parties <- FORECAST_DISPLAY_PARTIES
  draws_wide <- draws_long %>%
    dplyr::filter(party %in% parties) %>%
    dplyr::select(draw, party, posterior_draw) %>%
    tidyr::pivot_wider(names_from = party, values_from = posterior_draw)

  missing <- setdiff(parties, names(draws_wide))
  if (length(missing) > 0) {
    stop(
      "Posterior draws missing parties: ", paste(missing, collapse = ", "),
      ". build_forecast_row() must emit rows for all display parties (incl. oth)."
    )
  }

  mat <- as.matrix(draws_wide[, parties, drop = FALSE])
  mat_share <- normalize_draw_matrix(mat)

  lapply(parties, function(code) {
    col <- mat_share[, code]
    col <- col[is.finite(col)]
    # Whole percentages only — tenths imply false precision.
    list(
      party = display_party_label(code, state_code),
      party_code = code,
      fit = as.integer(round(mean(col) * 100)),
      low = as.integer(round(as.numeric(stats::quantile(col, probs = alpha / 2)) * 100)),
      high = as.integer(round(as.numeric(stats::quantile(col, probs = 1 - alpha / 2)) * 100))
    )
  })
}

scenario_config_md5 <- function(config_path = SCENARIO_CONFIG_FILE) {
  if (!file.exists(config_path)) return("")
  unname(tools::md5sum(config_path))
}

# Bump when predictor encoding changes so skip-cache cannot keep bad JSON.
PREDICTOR_ENCODING <- "logit_v1"

existing_forecast_unchanged <- function(out_file, election_date, last_poll_date, lead_model) {
  if (!file.exists(out_file)) return(FALSE)
  if (is.null(last_poll_date) || is.na(last_poll_date) || !nzchar(last_poll_date)) return(FALSE)
  existing <- tryCatch(
    jsonlite::fromJSON(out_file, simplifyVector = FALSE),
    error = function(e) NULL
  )
  if (is.null(existing) || is.null(existing$metadata)) return(FALSE)
  meta <- existing$metadata
  identical(meta$election_date %||% "", election_date) &&
    identical(meta$last_poll_date %||% "", last_poll_date) &&
    identical(meta$lead_model %||% "", lead_model %||% "") &&
    # Scenario config edits (e.g. new Berlin coalitions) must refresh JSON.
    identical(meta$scenario_config_md5 %||% "", scenario_config_md5()) &&
    identical(meta$predictor_encoding %||% "", PREDICTOR_ENCODING)
}

run_state_forecast <- function(state_code, election_date) {
  state_code <- toupper(state_code)
  state_lower <- tolower(state_code)
  elec_ind <- paste0(state_lower, "_", election_date)
  out_file <- file.path(OUTPUT_DIR, paste0("forecast_state_", state_lower, ".json"))

  model_path <- file.path(STATE_MODELS_DIR, "output", "models", "01_model_est_bayes.RDS")
  functions_path <- file.path(STATE_MODELS_DIR, "_auxilary", "functions.R")

  if (!file.exists(model_path)) {
    stop("State model not found at ", model_path, ". Clone state-models-jelst into vendor/.")
  }

  # Build predictors first (cheap). Skip Stan if polls/lead have not changed.
  rows <- build_forecast_row(state_code, election_date)
  last_poll_date <- attr(rows, "last_poll_date")
  lead <- attr(rows, "lead") %||% "days"
  lead_model <- attr(rows, "lead_model") %||% "days_all"
  lead_horizon_days <- attr(rows, "lead_horizon_days")
  if (existing_forecast_unchanged(out_file, election_date, last_poll_date, lead_model)) {
    cat(
      "Skipping reestimate for", state_code,
      "- no new polls since", last_poll_date,
      paste0("(", lead_model, ")"), "\n"
    )
    return(jsonlite::fromJSON(out_file, simplifyVector = FALSE))
  }

  suppressPackageStartupMessages({
    if (!requireNamespace("rstanarm", quietly = TRUE)) {
      source(file.path(REPO_ROOT, "R", "install.R"))
      Sys.setenv(INSTALL_STATE_MODEL_DEPS = "true")
      source(file.path(REPO_ROOT, "R", "install.R"))
    }
    library(rstanarm)
    library(dplyr)
    library(tidyr)
  })

  source(functions_path, local = TRUE)

  forecast_data <- bind_rows(rows)

  res <- readRDS(model_path)
  if (is.null(res[["lr"]][[lead_model]])) {
    stop("Lead model not found in RDS: ", lead_model)
  }
  model <- res[["lr"]][[lead_model]]
  cat(
    "Using lead model", lead_model,
    "| Stand (last poll included):", last_poll_date %||% "NA",
    "| horizon_days:", lead_horizon_days %||% "NA", "\n"
  )

  parties_out <- summarize_vote_share_draws(
    forecast_data = forecast_data,
    election_id = elec_ind,
    model = model,
    get_posterior_draws_fn = get_posterior_draws_with_oth,
    state_code = state_code
  )

  # Integer-rounding drift → nudge Sonstige (or largest party) to exact 100.
  fit_sum <- sum(vapply(parties_out, function(r) r$fit, numeric(1)))
  if (is.finite(fit_sum) && fit_sum != 100) {
    sonst_idx <- which(vapply(parties_out, function(r) identical(r$party, "Sonstige"), logical(1)))
    idx <- if (length(sonst_idx) > 0) sonst_idx[[1]] else which.max(vapply(parties_out, function(r) r$fit, numeric(1)))
    parties_out[[idx]]$fit <- as.integer(max(0L, parties_out[[idx]]$fit + (100L - as.integer(fit_sum))))
  }

  # Display order: last election vote share; Sonstige far right.
  party_order_payload <- tryCatch(build_party_order(), error = function(e) NULL)
  state_order <- character(0)
  if (!is.null(party_order_payload) && !is.null(party_order_payload$states[[state_code]])) {
    state_order <- party_order_payload$states[[state_code]]$order %||% character(0)
  }
  if (length(state_order) == 0) state_order <- FALLBACK_PARTY_ORDER
  party_rank <- function(label) {
    if (identical(label, "Sonstige")) return(1000L)
    idx <- match(label, state_order)
    # Order lists use CDU/CSU; display may be CDU or CSU.
    if (is.na(idx) && label %in% c("CSU", "CDU", "CDU/CSU")) {
      idx <- match("CDU/CSU", state_order)
      if (is.na(idx)) idx <- match("CSU", state_order)
      if (is.na(idx)) idx <- match("CDU", state_order)
    }
    if (is.na(idx)) return(500L)
    as.integer(idx)
  }
  parties_out <- parties_out[order(vapply(parties_out, function(r) party_rank(r$party), integer(1)))]

  scenarios <- compute_forecast_scenarios(
    forecast_data = forecast_data,
    election_id = elec_ind,
    model = model,
    get_posterior_draws_fn = get_posterior_draws,
    config_path = SCENARIO_CONFIG_FILE,
    state_code = state_code
  )

  payload <- list(
    metadata = list(
      state_code = state_code,
      election_date = election_date,
      election_id = elec_ind,
      model = paste0(
        "state-models-jelst lr ", lead_model,
        " (logit shares; Sonstige modeled + normalize)"
      ),
      lead = lead,
      lead_model = lead_model,
      lead_horizon_days = if (is.null(lead_horizon_days)) NULL else as.integer(lead_horizon_days),
      poll_window_days = 14L,
      last_poll_date = if (is.null(last_poll_date) || is.na(last_poll_date)) NULL else last_poll_date,
      last_update = format(Sys.time(), "%Y-%m-%dT%H:%M:%OS"),
      scenario_config_md5 = scenario_config_md5(),
      predictor_encoding = PREDICTOR_ENCODING,
      shares_normalized_to_100 = TRUE
    ),
    parties = parties_out,
    scenarios = scenarios
  )

  dir.create(OUTPUT_DIR, recursive = TRUE, showWarnings = FALSE)
  write_json(payload, out_file, auto_unbox = TRUE, pretty = TRUE, null = "null")
  cat("Wrote", out_file, "\n")
  payload
}

if (sys.nframe() == 0) {
  args <- commandArgs(trailingOnly = TRUE)
  if (length(args) < 2) {
    stop("Usage: run_state_forecast.R <STATE_CODE> <ELECTION_DATE>")
  }
  run_state_forecast(args[[1]], args[[2]])
}
