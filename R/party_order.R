# Build party_order.json from last completed election results.
# Display order = vote share descending; Sonstige is never ranked here and is
# always appended on the far right by the website (when shown/forecast).

FALLBACK_PARTY_ORDER <- c(
  "CDU/CSU", "AfD", "SPD", "GRÜNE", "LINKE", "BSW", "FDP",
  "FW", "SSW", "PIRATEN", "REP"
)

CSV_PARTY_TO_LABEL <- c(
  afd = "AfD", bsw = "BSW", cdu = "CDU/CSU", fdp = "FDP",
  gru = "GRÜNE", lin = "LINKE", spd = "SPD", fw = "FW",
  oth = "Sonstige", pir = "PIRATEN", ssw = "SSW", npd = "Sonstige"
)

order_from_shares <- function(shares) {
  if (length(shares) == 0) return(FALLBACK_PARTY_ORDER)
  keep <- names(shares)[!names(shares) %in% c("Sonstige", "oth")]
  shares <- shares[keep]
  shares <- shares[is.finite(unlist(shares))]
  if (length(shares) == 0) return(FALLBACK_PARTY_ORDER)
  names(sort(unlist(shares), decreasing = TRUE))
}

shares_from_json_entry <- function(entry) {
  if (is.null(entry) || is.null(entry$shares)) return(list())
  entry$shares
}

shares_from_state_csv <- function(state_code, results_file = STATE_ELECTION_RESULTS_FILE) {
  if (!file.exists(results_file)) return(list())
  df <- utils::read.csv(results_file, stringsAsFactors = FALSE)
  land <- tolower(state_code)
  df <- df[tolower(df$land) == land, ]
  if (nrow(df) == 0) return(list())
  latest_date <- max(as.Date(df$electiondate))
  latest <- df[as.Date(df$electiondate) == latest_date, ]
  shares <- list()
  for (i in seq_len(nrow(latest))) {
    code <- tolower(as.character(latest$party[[i]]))
    label <- CSV_PARTY_TO_LABEL[[code]] %||% NA_character_
    val <- suppressWarnings(as.numeric(latest$vote_share[[i]]))
    if (is.na(label) || identical(label, "Sonstige") || !is.finite(val)) next
    shares[[label]] <- val
  }
  list(election_date = as.character(latest_date), shares = shares)
}

build_party_order <- function(results_path = file.path(DATA_DIR, "last_election_results.json"),
                              output_path = file.path(OUTPUT_DIR, "party_order.json")) {
  curated <- if (file.exists(results_path)) {
    jsonlite::fromJSON(results_path, simplifyVector = FALSE)
  } else {
    list()
  }

  federal_entry <- curated$federal %||% list()
  federal_shares <- shares_from_json_entry(federal_entry)
  federal_order <- order_from_shares(federal_shares)

  states_out <- list()
  state_codes <- unique(c(names(STATE_CODE_TO_SCOPE), names(curated$states %||% list())))
  for (code in sort(state_codes)) {
    curated_state <- (curated$states %||% list())[[code]]
    if (!is.null(curated_state) && !is.null(curated_state$shares)) {
      shares <- shares_from_json_entry(curated_state)
      election_date <- curated_state$election_date %||% NA_character_
    } else {
      csv_entry <- shares_from_state_csv(code)
      shares <- csv_entry$shares %||% list()
      election_date <- csv_entry$election_date %||% NA_character_
    }
    states_out[[code]] <- list(
      election_date = election_date,
      shares = shares,
      order = order_from_shares(shares)
    )
  }

  payload <- list(
    metadata = list(
      last_update = format(Sys.time(), "%Y-%m-%dT%H:%M:%OS"),
      source = "data/last_election_results.json (+ state-election-results.csv fallback)",
      note = "Bars/tables/forecasts: parties ordered by last-election vote share; Sonstige always far right when shown."
    ),
    fallback_order = FALLBACK_PARTY_ORDER,
    federal = list(
      election_date = federal_entry$election_date %||% NA_character_,
      election_name = federal_entry$election_name %||% "Bundestagswahl",
      shares = federal_shares,
      order = federal_order
    ),
    states = states_out
  )

  dir.create(dirname(output_path), recursive = TRUE, showWarnings = FALSE)
  jsonlite::write_json(payload, output_path, auto_unbox = TRUE, pretty = TRUE, null = "null")
  payload
}
