#!/usr/bin/env Rscript
# Build forecast predictor rows for state-models-jelst from polling API + fundamentals.

suppressPackageStartupMessages({
  library(jsonlite)
  library(httr)
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

source(file.path(REPO_ROOT, "R", "config.R"))
source(file.path(REPO_ROOT, "R", "party_mapper.R"))
source(file.path(REPO_ROOT, "R", "fetch_polls.R"))

STATE_MODEL_PARTY <- c("afd", "bsw", "cdu", "fdp", "gru", "lin", "spd", "oth")
FORECAST_CORE_PARTIES <- c("afd", "bsw", "cdu", "fdp", "gru", "lin", "spd")
PARTY_TO_MODEL <- c(
  "AfD" = "afd", "BSW" = "bsw", "CDU/CSU" = "cdu", "FDP" = "fdp",
  "GRÜNE" = "gru", "LINKE" = "lin", "SPD" = "spd", "Sonstige" = "oth"
)

# Training horizons in the vendor model (2 days / 2 weeks / 2 months).
LEAD_HORIZONS <- c(days = 2L, weeks = 14L, months = 60L)
POLL_WINDOW_DAYS <- 14L
# Vendor training uses logit(share); clamp tiny/zero shares so logit is finite.
LOGIT_SHARE_FLOOR <- 0.001

safe_val <- function(x, key) {
  if (is.null(x) || !key %in% names(x)) return(NA_real_)
  x[[key]]
}

logit <- function(p) log(p / (1 - p))

safe_logit <- function(p, floor = LOGIT_SHARE_FLOOR) {
  if (length(p) == 0 || is.na(p) || !is.finite(p) || p <= 0) {
    return(logit(floor))
  }
  if (p >= 1) return(logit(1 - floor))
  logit(max(p, floor))
}

# Vendor pollslr_* / votesharelr_* are logit(share), not log-ratios vs CDU.
compute_logit_shares <- function(shares, floor = LOGIT_SHARE_FLOOR) {
  out <- setNames(rep(NA_real_, length(STATE_MODEL_PARTY)), STATE_MODEL_PARTY)
  if (is.null(shares) || length(shares) == 0) return(out)
  for (p in STATE_MODEL_PARTY) {
    val <- safe_val(shares, p)
    if (is.na(val) || !is.finite(val) || val <= 0) next
    out[[p]] <- safe_logit(val, floor)
  }
  out
}

# Vendor fed_trends_lr_* ≈ logit(federal poll) − logit(last federal result).
compute_federal_trends <- function(fed_shares, fed_last_shares) {
  out <- setNames(rep(NA_real_, length(STATE_MODEL_PARTY)), STATE_MODEL_PARTY)
  if (is.null(fed_shares)) return(out)
  for (p in STATE_MODEL_PARTY) {
    cur <- safe_val(fed_shares, p)
    prev <- safe_val(fed_last_shares, p)
    if (is.na(cur) || !is.finite(cur) || cur <= 0) next
    out[[p]] <- safe_logit(cur) - safe_logit(prev)
  }
  out
}

latest_poll_date <- function(polls) {
  if (length(polls) == 0) return(as.Date(NA))
  dates <- as.Date(vapply(polls, function(p) {
    as.character(p$publish_date %||% NA_character_)
  }, character(1)))
  dates <- dates[!is.na(dates)]
  if (length(dates) == 0) return(as.Date(NA))
  max(dates)
}

# Pick the vendor lead closest to how far Stand is from election day.
choose_lead <- function(stand_date, election_date) {
  days_out <- as.numeric(as.Date(election_date) - as.Date(stand_date))
  if (!is.finite(days_out) || days_out < 0) return("months")
  # Midpoints between 2 / 14 / 60.
  if (days_out <= 8) "days"
  else if (days_out <= 37) "weeks"
  else "months"
}

# Sonstige share in the 8-party model universe = residual after the 7 core parties.
fill_oth_residual <- function(shares) {
  if (is.null(shares) || length(shares) == 0) return(shares)
  core_sum <- sum(vapply(FORECAST_CORE_PARTIES, function(p) {
    v <- safe_val(shares, p)
    if (is.na(v) || !is.finite(v)) 0 else v
  }, numeric(1)), na.rm = TRUE)
  if (core_sum > 0) {
    shares[["oth"]] <- max(0, 1 - min(core_sum, 1))
  }
  shares
}

# Average polls in [asof_date - 14, asof_date]. Stand = newest poll in window.
compute_poll_aggregate_asof <- function(polls, asof_date, window_days = POLL_WINDOW_DAYS) {
  if (length(polls) == 0 || is.na(asof_date)) return(NULL)
  asof_date <- as.Date(asof_date)
  window_start <- asof_date - as.integer(window_days)
  relevant <- Filter(function(p) {
    d <- as.Date(p$publish_date)
    !is.na(d) && d >= window_start && d <= asof_date
  }, polls)

  if (length(relevant) == 0) return(NULL)

  sums <- setNames(rep(0, length(STATE_MODEL_PARTY)), STATE_MODEL_PARTY)
  counts <- setNames(rep(0, length(STATE_MODEL_PARTY)), STATE_MODEL_PARTY)
  included_dates <- as.Date(character(0))

  for (poll in relevant) {
    mapped <- poll_to_party_map(poll)
    core_pct <- 0
    for (display_name in names(mapped)) {
      if (!display_name %in% names(PARTY_TO_MODEL)) next
      model_party <- PARTY_TO_MODEL[[display_name]]
      if (is.null(model_party) || identical(model_party, "oth")) next
      sums[[model_party]] <- sums[[model_party]] + mapped[[display_name]]
      counts[[model_party]] <- counts[[model_party]] + 1
      core_pct <- core_pct + mapped[[display_name]]
    }
    # Residual to 100% among the 8-party forecast universe (includes FW etc.).
    if (core_pct > 0) {
      sums[["oth"]] <- sums[["oth"]] + max(0, 100 - core_pct)
      counts[["oth"]] <- counts[["oth"]] + 1
      d <- as.Date(poll$publish_date)
      if (!is.na(d)) included_dates <- c(included_dates, d)
    }
  }

  shares <- vapply(STATE_MODEL_PARTY, function(p) {
    if (counts[[p]] > 0) sums[[p]] / counts[[p]] / 100 else NA_real_
  }, numeric(1))

  stand <- if (length(included_dates) > 0) max(included_dates) else asof_date
  structure(
    shares,
    last_poll_date = as.character(stand),
    n_polls = length(unique(included_dates)),
    window_start = as.character(window_start),
    window_end = as.character(asof_date)
  )
}

last_state_election_results <- function(state_code, results_file = STATE_ELECTION_RESULTS_FILE) {
  curated_path <- file.path(DATA_DIR, "last_election_results.json")
  if (file.exists(curated_path)) {
    curated <- jsonlite::fromJSON(curated_path, simplifyVector = FALSE)
    entry <- (curated$states %||% list())[[toupper(state_code)]]
    if (!is.null(entry) && !is.null(entry$shares)) {
      shares <- setNames(rep(NA_real_, length(STATE_MODEL_PARTY)), STATE_MODEL_PARTY)
      for (disp in names(entry$shares)) {
        if (!disp %in% names(PARTY_TO_MODEL)) next
        code <- unname(PARTY_TO_MODEL[[disp]])
        val <- suppressWarnings(as.numeric(entry$shares[[disp]]))
        if (is.finite(val)) shares[[code]] <- if (val > 1) val / 100 else val
      }
      shares <- fill_oth_residual(shares)
      return(list(
        electiondate = entry$election_date %||% NA_character_,
        shares = shares
      ))
    }
  }

  if (!file.exists(results_file)) return(list())
  df <- read.csv(results_file, stringsAsFactors = FALSE)
  land <- tolower(state_code)
  df <- df[tolower(df$land) == land, ]
  if (nrow(df) == 0) return(list())

  latest_date <- max(as.Date(df$electiondate))
  latest <- df[as.Date(df$electiondate) == latest_date, ]
  shares <- setNames(latest$vote_share / 100, latest$party)
  shares <- fill_oth_residual(shares)
  list(
    electiondate = as.character(latest_date),
    electiondate_l1 = as.character(as.Date(latest$electiondate_l1[1])),
    shares = shares
  )
}

last_federal_election_shares <- function() {
  shares <- setNames(rep(NA_real_, length(STATE_MODEL_PARTY)), STATE_MODEL_PARTY)
  # BTW 2025 fallback if curated file is missing.
  defaults <- c(
    afd = 0.208, bsw = 0.0498, cdu = 0.285, fdp = 0.043,
    gru = 0.116, lin = 0.088, spd = 0.164, oth = 0.045
  )
  for (p in names(defaults)) shares[[p]] <- defaults[[p]]

  curated_path <- file.path(DATA_DIR, "last_election_results.json")
  if (file.exists(curated_path)) {
    curated <- jsonlite::fromJSON(curated_path, simplifyVector = FALSE)
    fed <- curated$federal %||% list()
    if (!is.null(fed$shares)) {
      for (disp in names(fed$shares)) {
        if (!disp %in% names(PARTY_TO_MODEL)) next
        code <- unname(PARTY_TO_MODEL[[disp]])
        val <- suppressWarnings(as.numeric(fed$shares[[disp]]))
        if (is.finite(val)) shares[[code]] <- if (val > 1) val / 100 else val
      }
    }
  }
  fill_oth_residual(shares)
}

build_forecast_row <- function(state_code, election_date) {
  scope <- STATE_CODE_TO_SCOPE[[state_code]]
  if (is.null(scope)) stop("Unknown state code: ", state_code)

  state_lower <- tolower(state_code)
  elec_ind <- paste0(state_lower, "_", election_date)

  state_polls <- fetch_polls_all(scope, max_total = 3000)
  federal_polls <- fetch_polls_all("federal", max_total = 3000)

  fundamentals <- fromJSON(STATE_FUNDAMENTALS_FILE, simplifyVector = FALSE)
  state_fund <- fundamentals$states[[state_code]] %||% list(gov = NA, pm = NA)
  last_results <- last_state_election_results(state_code)
  fed_last <- last_federal_election_shares()

  # Stand = newest state poll. Aggregate the 14 days ending there, then pick
  # the vendor lead (days/weeks/months) that matches distance to election.
  stand_date <- latest_poll_date(state_polls)
  lead <- choose_lead(stand_date, election_date)
  lead_model <- paste0(lead, "_all")
  lead_horizon <- LEAD_HORIZONS[[lead]]

  state_shares <- compute_poll_aggregate_asof(state_polls, stand_date)
  fed_shares <- compute_poll_aggregate_asof(federal_polls, stand_date)
  if (is.null(fed_shares)) {
    fed_stand <- latest_poll_date(federal_polls)
    if (!is.na(fed_stand) && !is.na(stand_date) && fed_stand > stand_date) {
      fed_stand <- stand_date
    }
    fed_shares <- compute_poll_aggregate_asof(federal_polls, fed_stand)
  }

  last_poll_date <- attr(state_shares, "last_poll_date")
  if (is.null(last_poll_date) || is.na(last_poll_date) || !nzchar(last_poll_date)) {
    last_poll_date <- if (is.na(stand_date)) NA_character_ else as.character(stand_date)
  }

  pollslr <- compute_logit_shares(state_shares)
  fed_trends_lr <- compute_federal_trends(fed_shares, fed_last)

  l1_shares <- setNames(rep(NA_real_, length(STATE_MODEL_PARTY)), STATE_MODEL_PARTY)
  for (p in STATE_MODEL_PARTY) {
    val <- safe_val(last_results$shares, p)
    if (!is.na(val) && val > 1) val <- val / 100
    l1_shares[[p]] <- val
  }
  l1_shares <- fill_oth_residual(l1_shares)
  votesharelr_l1 <- compute_logit_shares(l1_shares)

  rows <- list()
  for (party in STATE_MODEL_PARTY) {
    gov_party <- tolower(state_fund$gov %||% "")
    pm_party <- tolower(state_fund$pm %||% "")

    # BW/RP 2026 adaptation: do not use the paper's new_party indicator —
    # polls already capture new-party dynamics. Column stays 0 because the
    # pre-fitted vendor RDS still expects the predictor.
    new_party_flag <- 0L

    votesharelr_l1_val <- safe_val(votesharelr_l1, party)
    # Parties missing at the last Landtag election (e.g. BSW): logit L1 = 0.
    if (is.na(votesharelr_l1_val) && is.na(l1_shares[[party]])) {
      votesharelr_l1_val <- 0
    }

    fed_trend_val <- safe_val(fed_trends_lr, party)
    if (is.na(fed_trend_val)) fed_trend_val <- 0

    pollslr_val <- safe_val(pollslr, party)
    if (is.na(pollslr_val)) pollslr_val <- votesharelr_l1_val
    if (is.na(pollslr_val)) pollslr_val <- fed_trend_val
    if (is.na(pollslr_val)) pollslr_val <- 0

    polls_share <- safe_val(state_shares, party)
    fed_poll_share <- safe_val(fed_shares, party)
    polls_na <- as.integer(is.na(polls_share))

    # Active lead's predictors in all horizon columns; run matching *_all model.
    rows[[length(rows) + 1]] <- list(
      elec_ind = elec_ind,
      state = state_lower,
      party = party,
      year = as.integer(format(as.Date(election_date), "%Y")),
      electiondate = election_date,
      election_type = "future",
      gov = as.integer(identical(gov_party, party)),
      pm = as.integer(identical(pm_party, party)),
      new_party = new_party_flag,
      voteshare_l1 = l1_shares[[party]],
      votesharelr_l1 = votesharelr_l1_val,
      electiondate_l1 = last_results$electiondate %||% NA_character_,
      polls_days = polls_share,
      polls_weeks = polls_share,
      polls_months = polls_share,
      pollslr_days = pollslr_val,
      pollslr_weeks = pollslr_val,
      pollslr_months = pollslr_val,
      fed_polls_days = fed_poll_share,
      fed_polls_weeks = fed_poll_share,
      fed_polls_months = fed_poll_share,
      fed_trends_lr_days = fed_trend_val,
      fed_trends_lr_weeks = fed_trend_val,
      fed_trends_lr_months = fed_trend_val,
      pollsNA_days = polls_na,
      pollsNA_weeks = polls_na,
      pollsNA_months = polls_na,
      date_days = last_poll_date,
      date_weeks = last_poll_date,
      date_months = last_poll_date
    )
  }

  structure(
    rows,
    last_poll_date = last_poll_date,
    lead = lead,
    lead_model = lead_model,
    lead_horizon_days = as.integer(lead_horizon),
    poll_window_days = POLL_WINDOW_DAYS
  )
}

if (sys.nframe() == 0) {
  args <- commandArgs(trailingOnly = TRUE)
  if (length(args) < 2) {
    stop("Usage: build_forecast_row.R <STATE_CODE> <ELECTION_DATE>")
  }
  row <- build_forecast_row(toupper(args[[1]]), args[[2]])
  cat(toJSON(row, auto_unbox = TRUE, pretty = TRUE), "\n")
  cat(
    "# attrs: lead=", attr(row, "lead"),
    " model=", attr(row, "lead_model"),
    " stand=", attr(row, "last_poll_date"),
    " n_parties=", length(row), "\n",
    sep = ""
  )
}
