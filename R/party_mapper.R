# Party name normalization and consolidation (mirrors polls-mapper-aggregator.js).

CORE_ORDER <- c(
  "CDU/CSU", "AfD", "SPD", "GRÜNE", "LINKE", "BSW", "FDP",
  "FW", "SSW", "PIRATEN", "REP", "Sonstige"
)

NORMALIZE <- c(
  "CDU" = "CDU/CSU",
  "CSU" = "CDU/CSU",
  "CDU_CSU" = "CDU/CSU",
  "cdu" = "CDU/CSU",
  "csu" = "CDU/CSU",
  "Grüne" = "GRÜNE",
  "gruene" = "GRÜNE",
  "grüne" = "GRÜNE",
  "GRUENE" = "GRÜNE",
  "Linke" = "LINKE",
  "PDS" = "LINKE",
  "Linke.PDS" = "LINKE",
  "AFD" = "AfD",
  "FW" = "FW",
  "Freie Wähler" = "FW",
  "FREIE_WAEHLER" = "FW",
  "BVB/FW" = "FW",
  "Piraten" = "PIRATEN",
  "SONSTIGE" = "Sonstige"
)

normalize_party_name <- function(name) {
  if (is.null(name) || length(name) == 0 || is.na(name)) return(NA_character_)
  trimmed <- trimws(as.character(name))
  if (trimmed %in% names(NORMALIZE)) return(unname(NORMALIZE[[trimmed]]))
  trimmed
}

results_array_to_party_map <- function(results) {
  out <- list()
  if (is.null(results) || length(results) == 0) return(out)

  if (is.data.frame(results)) {
    rows <- split(results, seq_len(nrow(results)))
  } else {
    rows <- results
  }

  for (row in rows) {
    if (is.null(row)) next
    party_raw <- row$party_key %||% row$party_short_name %||% row$party_name
    pct <- row$percentage
    if (is.null(party_raw) || is.null(pct)) next
    party <- normalize_party_name(party_raw)
    val <- suppressWarnings(as.numeric(pct))
    if (!is.finite(val)) next
    out[[party]] <- val
  }
  out
}

consolidate_party_map <- function(party_map) {
  out <- list()
  sum_main <- 0

  for (p in CORE_ORDER) {
    if (identical(p, "Sonstige")) next
    if (is.null(party_map[[p]])) next
    val <- suppressWarnings(as.numeric(party_map[[p]]))
    if (!is.finite(val)) next
    out[[p]] <- val
    sum_main <- sum_main + val
  }

  explicit <- party_map[["Sonstige"]]
  if (!is.null(explicit) && is.finite(suppressWarnings(as.numeric(explicit)))) {
    out[["Sonstige"]] <- as.numeric(explicit)
  } else if (sum_main > 0) {
    out[["Sonstige"]] <- round(max(0, 100 - sum_main), 1)
  }

  total <- sum(unlist(out))
  if (total > 0 && abs(total - 100) > 0.05) {
    factor <- 100 / total
    for (p in names(out)) {
      out[[p]] <- round(out[[p]] * factor, 1)
    }
  }

  out
}

poll_to_party_map <- function(poll) {
  consolidate_party_map(results_array_to_party_map(poll$results))
}

party_presence_in_poll <- function(poll, party) {
  mapped <- poll_to_party_map(poll)
  !is.null(mapped[[party]]) && is.finite(mapped[[party]])
}
