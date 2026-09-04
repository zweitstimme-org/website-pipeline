# Compute scenario probabilities from state-model posterior draws.

FORECAST_SCENARIO_PARTIES <- c("afd", "bsw", "cdu", "fdp", "gru", "lin", "spd")
FORECAST_OTH_PARTY <- "oth"

# Seat-eligible parties only. Sonstige stay in the vote-share denominator
# (legal 5% of valid votes) but get no seats and cannot be "stärkste Kraft".
parliamentary_shares <- function(shares) {
  shares[setdiff(names(shares), FORECAST_OTH_PARTY)]
}

PARTY_LABELS_DE <- c(
  afd = "AfD",
  bsw = "BSW",
  cdu = "CDU/CSU",
  fdp = "FDP",
  gru = "Grüne",
  lin = "Linke",
  spd = "SPD"
)

party_label_de <- function(code, state_code = NULL) {
  sc <- toupper(as.character(state_code %||% ""))
  if (identical(code, "cdu")) {
    if (identical(sc, "BY")) return("CSU")
    # Federal keeps CDU/CSU; states outside Bavaria use CDU.
    if (identical(sc, "") || identical(sc, "BUND") || identical(sc, "DE")) return("CDU/CSU")
    return("CDU")
  }
  PARTY_LABELS_DE[[code]] %||% code
}

# Rewrite canned scenario copy that hardcodes CDU/CSU for the state.
localize_scenario_label <- function(label, state_code = NULL) {
  sc <- toupper(as.character(state_code %||% ""))
  if (identical(sc, "BY")) {
    return(gsub("CDU/CSU", "CSU", label, fixed = TRUE))
  }
  if (nzchar(sc) && !sc %in% c("BUND", "DE")) {
    return(gsub("CDU/CSU", "CDU", label, fixed = TRUE))
  }
  label
}

coalition_has_majority <- function(shares, coalition_parties, hurdle = 0.05) {
  parl <- parliamentary_shares(shares)
  if (length(parl) == 0 || !all(coalition_parties %in% names(parl))) {
    return(FALSE)
  }
  coalition_shares <- parl[coalition_parties]
  if (any(coalition_shares < hurdle)) {
    return(FALSE)
  }
  above_hurdle <- sum(parl[parl >= hurdle])
  if (above_hurdle <= 0) {
    return(FALSE)
  }
  sum(coalition_shares) / above_hurdle > 0.5
}

# Majority of seats among parties above the hurdle, after dropping `exclude`.
# E.g. exclude=AfD → “Parlamentsmehrheit ohne AfD”.
majority_excluding_parties <- function(shares, exclude_parties, hurdle = 0.05) {
  parl <- parliamentary_shares(shares)
  if (length(parl) == 0) {
    return(FALSE)
  }
  above_names <- names(parl)[parl >= hurdle]
  if (length(above_names) == 0) {
    return(FALSE)
  }
  above_sum <- sum(parl[above_names])
  if (above_sum <= 0) {
    return(FALSE)
  }
  excl <- intersect(unique(as.character(exclude_parties)), names(parl))
  bloc <- setdiff(above_names, excl)
  if (length(bloc) == 0) {
    return(FALSE)
  }
  sum(parl[bloc]) / above_sum > 0.5
}

normalize_draw_matrix <- function(mat) {
  row_sums <- rowSums(mat)
  row_sums[row_sums <= 0] <- NA_real_
  mat / row_sums
}

load_scenario_config <- function(config_path) {
  if (!file.exists(config_path)) {
    stop("Scenario config not found: ", config_path)
  }
  jsonlite::fromJSON(config_path, simplifyVector = FALSE)
}

add_largest_party_scenarios <- function(scenario_defs, parties, hurdle, state_code = NULL) {
  for (party in parties) {
    label_party <- party_label_de(party, state_code)
    scenario_defs[[length(scenario_defs) + 1]] <- list(
      id = paste0("largest_party_", party),
      category = "largest_party",
      label_de = paste(label_party, "stärkste Kraft"),
      evaluate = local({
        p <- party
        function(shares) {
          parl <- parliamentary_shares(shares)
          if (!p %in% names(parl)) return(FALSE)
          shares[[p]] >= max(parl, na.rm = TRUE)
        }
      })
    )
  }
  scenario_defs
}

add_above_hurdle_scenarios <- function(scenario_defs, parties, hurdle, state_code = NULL) {
  for (party in parties) {
    label_party <- party_label_de(party, state_code)
    scenario_defs[[length(scenario_defs) + 1]] <- list(
      id = paste0("above_hurdle_", party),
      category = "above_hurdle",
      label_de = paste(label_party, "über 5%-Hürde"),
      evaluate = local({
        p <- party
        h <- hurdle
        function(shares) {
          if (!p %in% names(shares)) return(FALSE)
          shares[[p]] >= h
        }
      })
    )
  }
  scenario_defs
}

add_coalition_scenarios <- function(scenario_defs, coalitions, hurdle, state_code = NULL) {
  seen <- character(0)
  for (coal in coalitions) {
    coalition_parties <- unlist(coal$parties, use.names = FALSE)
    lead_party <- coal$lead %||% NULL
    if (!is.null(lead_party)) lead_party <- as.character(lead_party)
    # Same party set in a different order is the same majority event,
    # unless a coalition lead party splits the scenario.
    key <- paste(
      c(sort(unique(coalition_parties)), if (nzchar(lead_party %||% "")) lead_party else ""),
      collapse = "+"
    )
    if (key %in% seen) next
    seen <- c(seen, key)
    scenario_defs[[length(scenario_defs) + 1]] <- list(
      id = coal$id,
      category = "coalition",
      label_de = localize_scenario_label(coal$label_de, state_code),
      evaluate = local({
        cp <- coalition_parties
        h <- hurdle
        lp <- lead_party
        function(shares) {
          if (!coalition_has_majority(shares, cp, hurdle = h)) return(FALSE)
          if (is.null(lp) || !nzchar(lp)) return(TRUE)
          if (!lp %in% names(shares)) return(FALSE)
          # "Führung" = strongest party within the coalition.
          shares[[lp]] >= max(shares[cp], na.rm = TRUE)
        }
      })
    )
  }
  scenario_defs
}

add_majority_excluding_scenarios <- function(scenario_defs, defs, hurdle, state_code = NULL) {
  seen <- character(0)
  for (def in defs) {
    exclude_parties <- unlist(def$exclude %||% list(), use.names = FALSE)
    if (length(exclude_parties) == 0) next
    key <- paste(c("ex", sort(unique(exclude_parties))), collapse = "+")
    if (key %in% seen) next
    seen <- c(seen, key)
    scenario_defs[[length(scenario_defs) + 1]] <- list(
      id = def$id,
      category = "majority_excluding",
      label_de = localize_scenario_label(def$label_de, state_code),
      evaluate = local({
        ex <- exclude_parties
        h <- hurdle
        function(shares) majority_excluding_parties(shares, ex, hurdle = h)
      })
    )
  }
  scenario_defs
}

resolve_above_hurdle_parties <- function(cfg, parties, state_code = NULL) {
  default_parties <- unlist(cfg[["above_hurdle_parties"]] %||% parties, use.names = FALSE)
  if (is.null(state_code) || !nzchar(as.character(state_code))) {
    return(default_parties)
  }
  by_state <- cfg[["above_hurdle_parties_by_state"]]
  if (is.null(by_state) || !is.list(by_state)) {
    return(default_parties)
  }
  key <- toupper(as.character(state_code))
  override <- by_state[[key]]
  if (is.null(override)) {
    return(default_parties)
  }
  unlist(override, use.names = FALSE)
}

resolve_excluded_scenario_ids <- function(cfg, state_code = NULL) {
  if (is.null(state_code) || !nzchar(as.character(state_code))) {
    return(character(0))
  }
  by_state <- cfg[["exclude_scenario_ids_by_state"]]
  if (is.null(by_state) || !is.list(by_state)) {
    return(character(0))
  }
  key <- toupper(as.character(state_code))
  unlist(by_state[[key]] %||% list(), use.names = FALSE)
}

resolve_coalitions <- function(cfg, state_code = NULL) {
  coalitions <- cfg[["coalitions"]] %||% list()
  if (is.null(state_code) || !nzchar(as.character(state_code))) {
    return(coalitions)
  }
  by_state <- cfg[["coalitions_by_state"]]
  if (is.null(by_state) || !is.list(by_state)) {
    return(coalitions)
  }
  key <- toupper(as.character(state_code))
  extra <- by_state[[key]] %||% list()
  if (length(extra) == 0) {
    return(coalitions)
  }
  c(coalitions, extra)
}

resolve_majority_excluding <- function(cfg, state_code = NULL) {
  # Use [["…"]] — `$majority_excluding` partial-matches majority_excluding_by_state.
  defs <- cfg[["majority_excluding"]] %||% list()
  if (is.null(state_code) || !nzchar(as.character(state_code))) {
    return(defs)
  }
  by_state <- cfg[["majority_excluding_by_state"]]
  if (is.null(by_state) || !is.list(by_state)) {
    return(defs)
  }
  key <- toupper(as.character(state_code))
  extra <- by_state[[key]] %||% list()
  if (length(extra) == 0) {
    return(defs)
  }
  c(defs, extra)
}

resolve_state_coalition_ids <- function(cfg, state_code = NULL) {
  if (is.null(state_code) || !nzchar(as.character(state_code))) {
    return(character(0))
  }
  key <- toupper(as.character(state_code))
  ids <- character(0)
  by_coal <- cfg[["coalitions_by_state"]]
  if (!is.null(by_coal) && is.list(by_coal)) {
    extra <- by_coal[[key]] %||% list()
    ids <- c(ids, vapply(extra, function(coal) as.character(coal$id %||% ""), character(1)))
  }
  by_ex <- cfg[["majority_excluding_by_state"]]
  if (!is.null(by_ex) && is.list(by_ex)) {
    extra <- by_ex[[key]] %||% list()
    ids <- c(ids, vapply(extra, function(def) as.character(def$id %||% ""), character(1)))
  }
  # Also always-include global majority_excluding defs when present.
  for (def in cfg[["majority_excluding"]] %||% list()) {
    ids <- c(ids, as.character(def$id %||% ""))
  }
  ids[nzchar(ids)]
}

compute_forecast_scenarios <- function(
    forecast_data,
    election_id,
    model,
    get_posterior_draws_fn,
    config_path,
    min_probability_pct = NULL,
    state_code = NULL) {
  cfg <- load_scenario_config(config_path)
  min_prob <- min_probability_pct %||% cfg$metadata$min_probability_pct %||% 1.0
  hurdle <- (cfg$metadata$hurdle_pct %||% 5.0) / 100

  draws_long <- get_posterior_draws_fn(
    data = forecast_data,
    election_id = election_id,
    model = model
  )

  parties_core <- FORECAST_SCENARIO_PARTIES
  # Keep Sonstige in the denominator when present so 5% is of all valid votes
  # (same definition as Sitzzuteilung / Listenplätze). Do not drop oth and
  # renormalize the remaining seven — that inflates small-party hurdle rates.
  parties_keep <- c(parties_core, FORECAST_OTH_PARTY)
  draws_wide <- draws_long %>%
    dplyr::filter(party %in% parties_keep) %>%
    dplyr::select(draw, party, posterior_draw) %>%
    tidyr::pivot_wider(names_from = party, values_from = posterior_draw)

  parties <- parties_core
  if (FORECAST_OTH_PARTY %in% names(draws_wide)) {
    parties <- c(parties_core, FORECAST_OTH_PARTY)
  }
  missing <- setdiff(parties_core, names(draws_wide))
  if (length(missing) > 0) {
    return(list(min_probability_pct = min_prob, items = list()))
  }

  mat <- as.matrix(draws_wide[, parties, drop = FALSE])
  mat_norm <- normalize_draw_matrix(mat)
  n_draws <- nrow(mat_norm)
  if (!is.finite(n_draws) || n_draws == 0) {
    return(list(min_probability_pct = min_prob, items = list()))
  }

  draw_shares <- lapply(seq_len(n_draws), function(i) {
    stats::setNames(mat_norm[i, ], parties)
  })

  scenario_defs <- list()
  scenario_defs <- add_largest_party_scenarios(
    scenario_defs,
    unlist(cfg$largest_party_parties %||% parties_core, use.names = FALSE),
    hurdle,
    state_code = state_code
  )
  scenario_defs <- add_above_hurdle_scenarios(
    scenario_defs,
    resolve_above_hurdle_parties(cfg, parties_core, state_code),
    hurdle,
    state_code = state_code
  )
  scenario_defs <- add_coalition_scenarios(
    scenario_defs,
    resolve_coalitions(cfg, state_code),
    hurdle,
    state_code = state_code
  )
  scenario_defs <- add_majority_excluding_scenarios(
    scenario_defs,
    resolve_majority_excluding(cfg, state_code),
    hurdle,
    state_code = state_code
  )

  excluded_ids <- resolve_excluded_scenario_ids(cfg, state_code)
  if (length(excluded_ids) > 0) {
    scenario_defs <- Filter(function(def) !(def$id %in% excluded_ids), scenario_defs)
  }

  always_include_ids <- resolve_state_coalition_ids(cfg, state_code)

  items <- lapply(scenario_defs, function(def) {
    hits <- vapply(draw_shares, def$evaluate, FUN.VALUE = logical(1))
    prob <- mean(hits) * 100
    rounded <- as.integer(round(prob))
    force_include <- def$id %in% always_include_ids
    list(
      id = def$id,
      category = def$category,
      label_de = def$label_de,
      # Whole percentages — tenths imply false precision.
      probability = rounded,
      # State-specific coalitions kept below the cutoff are shown as ~0 / ~pct.
      approximate = isTRUE(force_include && (!is.finite(rounded) || rounded < min_prob))
    )
  })

  items <- Filter(function(x) {
    if (!is.finite(x$probability)) return(FALSE)
    x$probability >= min_prob || isTRUE(x$approximate)
  }, items)
  items <- items[order(vapply(items, function(x) x$probability, numeric(1)), decreasing = TRUE)]

  # Drop the approximate flag when false so JSON stays compact.
  items <- lapply(items, function(x) {
    if (isTRUE(x$approximate)) return(x)
    x$approximate <- NULL
    x
  })

  list(
    min_probability_pct = min_prob,
    hurdle_pct = cfg$metadata$hurdle_pct %||% 5.0,
    items = items
  )
}
