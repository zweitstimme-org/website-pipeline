# Fetch polls from the FastTrack polling API (v2 cleaned dataset).

# v2 renamed several fields vs the pipeline's historical names. Normalize so
# Kalman / state-model / website code can keep using publish_date etc.
normalize_v2_poll <- function(poll) {
  if (!is.list(poll)) return(poll)

  out <- poll
  if (is.null(out$publish_date) || !nzchar(as.character(out$publish_date %||% ""))) {
    if (!is.null(out$published_date)) out$publish_date <- out$published_date
  }
  if (is.null(out$survey_date_start) || !nzchar(as.character(out$survey_date_start %||% ""))) {
    if (!is.null(out$survey_start_date)) out$survey_date_start <- out$survey_start_date
  }
  if (is.null(out$survey_date_end) || !nzchar(as.character(out$survey_date_end %||% ""))) {
    if (!is.null(out$survey_end_date)) out$survey_date_end <- out$survey_end_date
  }
  if (is.null(out$method_key) || !nzchar(as.character(out$method_key %||% ""))) {
    if (!is.null(out$survey_method_key)) out$method_key <- out$survey_method_key
  }
  if (is.null(out$method_name) || !nzchar(as.character(out$method_name %||% ""))) {
    if (!is.null(out$survey_method_name)) out$method_name <- out$survey_method_name
  }
  if (is.null(out$raw_id) && !is.null(out$raw_poll_id)) out$raw_id <- out$raw_poll_id
  if (is.null(out$raw_public_id) && !is.null(out$raw_poll_public_id)) {
    out$raw_public_id <- out$raw_poll_public_id
  }
  if (is.null(out$date_downloaded) && !is.null(out$downloaded_at)) {
    out$date_downloaded <- out$downloaded_at
  }
  out
}

# Collapse API-flagged duplicate groups (matched pairs + multiple_matches).
# Leave no_match alone — those need fixing upstream.
prefer_matched_poll <- function(a, b) {
  a_api <- identical(a$source, "api")
  b_api <- identical(b$source, "api")
  if (a_api && !b_api) return(a)
  if (b_api && !a_api) return(b)

  a_dawum <- identical(a$provider_name, "DAWUM")
  b_dawum <- identical(b$provider_name, "DAWUM")
  if (a_dawum && !b_dawum) return(a)
  if (b_dawum && !a_dawum) return(b)

  a_id <- as.integer(a$id %||% 0L)
  b_id <- as.integer(b$id %||% 0L)
  if (a_id <= b_id) a else b
}

poll_institute_date_key <- function(poll) {
  paste0(poll$institute_name %||% poll$institute_key %||% "", "|", poll$publish_date %||% "")
}

drop_matched_duplicates <- function(polls) {
  if (length(polls) == 0) return(polls)

  by_id <- new.env(parent = emptyenv())
  for (p in polls) {
    id <- as.character(p$id %||% "")
    if (nzchar(id)) by_id[[id]] <- p
  }

  drop_ids <- character(0)

  # 1) Exact matched pairs linked by matching_poll_id.
  for (p in polls) {
    if (!identical(p$matching_status, "matched")) next
    id <- as.character(p$id %||% "")
    mid <- as.character(p$matching_poll_id %||% "")
    if (!nzchar(id) || !nzchar(mid)) next
    if (is.null(by_id[[mid]])) next
    if (id %in% drop_ids || mid %in% drop_ids) next

    keep <- prefer_matched_poll(p, by_id[[mid]])
    keep_id <- as.character(keep$id %||% "")
    drop_ids <- c(drop_ids, if (identical(keep_id, id)) mid else id)
  }

  # 2) multiple_matches: API saw ambiguity; collapse same institute/date group.
  multi_idx <- which(vapply(polls, function(p) identical(p$matching_status, "multiple_matches"), logical(1)))
  if (length(multi_idx) > 0) {
    keys <- vapply(polls[multi_idx], poll_institute_date_key, character(1))
    for (key in unique(keys)) {
      if (!nzchar(key) || grepl("^\\|", key) || grepl("\\|$", key)) next
      group <- polls[multi_idx[keys == key]]
      if (length(group) < 2) next
      keep <- Reduce(prefer_matched_poll, group)
      keep_id <- as.character(keep$id %||% "")
      for (p in group) {
        id <- as.character(p$id %||% "")
        if (nzchar(id) && !identical(id, keep_id)) drop_ids <- c(drop_ids, id)
      }
    }
  }

  drop_ids <- unique(drop_ids)
  if (length(drop_ids) == 0) return(polls)
  Filter(function(p) !(as.character(p$id %||% "") %in% drop_ids), polls)
}

# Raw party percentage from poll$results (before consolidation / Sonstige fill).
poll_raw_party_pct <- function(poll, party_keys) {
  results <- poll$results
  if (is.null(results) || length(results) == 0) return(NA_real_)
  keys <- toupper(as.character(party_keys))
  rows <- if (is.data.frame(results)) {
    split(results, seq_len(nrow(results)))
  } else {
    results
  }
  for (row in rows) {
    if (is.null(row)) next
    raw <- row$party_key %||% row$party_short_name %||% row$party_name
    if (is.null(raw)) next
    if (!(toupper(as.character(raw)) %in% keys)) next
    val <- suppressWarnings(as.numeric(row$percentage))
    if (is.finite(val)) return(val)
  }
  NA_real_
}

poll_has_raw_party <- function(poll, party_keys) {
  is.finite(poll_raw_party_pct(poll, party_keys))
}

# Federal Sonntagsfrage rows are scraped into Thüringen (BILD/INSA etc.).
# TH Landtag Grüne have been ≤5% since 2024; federal Grüne stay ~10–16%
# even when federal SPD is in the low teens. TH-only — western states
# legitimately have high Grüne.
is_misscoped_federal_th_poll <- function(poll) {
  if (is.null(poll) || is.null(poll$results) || length(poll$results) == 0) {
    return(FALSE)
  }
  date <- as.character(poll$publish_date %||% poll$published_date %||% "")
  if (!nzchar(date) || date < "2024-01-01") return(FALSE)

  gruene <- poll_raw_party_pct(poll, c("GRUENE", "GRÜNE", "Grüne", "gruene"))
  is.finite(gruene) && gruene >= 8
}

drop_misscoped_federal_polls <- function(polls, scope = NULL) {
  if (length(polls) == 0) return(polls)
  scope_l <- tolower(as.character(scope %||% ""))
  if (!scope_l %in% c("th", "thueringen", "thüringen")) {
    return(polls)
  }

  keep <- !vapply(polls, is_misscoped_federal_th_poll, logical(1))
  n_drop <- sum(!keep)
  if (n_drop > 0) {
    message(sprintf(
      "Dropped %d mis-scoped federal-looking poll(s) from scope=%s",
      n_drop, scope_l
    ))
  }
  polls[keep]
}

fetch_polls_page <- function(scope, date_from = NULL, date_to = NULL,
                             limit = POLLING_API_PAGE_SIZE, offset = 0) {
  query <- list(
    scope = scope,
    include_results = "true",
    limit = limit,
    offset = offset,
    sort = "-published_date"
  )
  if (!is.null(date_from)) query$published_from <- date_from
  if (!is.null(date_to)) query$published_to <- date_to

  url <- paste0(POLLING_API_BASE, "/v2/polls")
  resp <- httr::GET(url, query = query, httr::timeout(120))
  httr::stop_for_status(resp)
  parsed <- jsonlite::fromJSON(httr::content(resp, as = "text", encoding = "UTF-8"), simplifyVector = FALSE)
  items <- parsed$data %||% list()
  items <- lapply(items, normalize_v2_poll)
  list(
    items = items,
    total = parsed$pagination$total %||% length(items)
  )
}

# DAWUM Parliament_ID → FastTrack scope. Bundestag (0) and EU (17) omitted —
# only Landtage with an unambiguous catalog id are injected.
DAWUM_PARLIAMENT_TO_SCOPE <- c(
  "1" = "bw", "2" = "by", "3" = "be", "4" = "bb", "5" = "hb", "6" = "hh",
  "7" = "he", "8" = "mv", "9" = "ni", "10" = "nrw", "11" = "rp", "12" = "sl",
  "13" = "sn", "14" = "st", "15" = "sh", "16" = "th"
)

# DAWUM party Shortcut → API party_key (matches FastTrack / party_mapper.R).
DAWUM_PARTY_SHORTCUT_TO_KEY <- c(
  "AfD" = "AFD",
  "Grüne" = "GRUENE",
  "BSW" = "BSW",
  "CDU/CSU" = "CDU_CSU",
  "CDU" = "CDU",
  "CSU" = "CSU",
  "Linke" = "LINKE",
  "FDP" = "FDP",
  "SPD" = "SPD",
  "Freie Wähler" = "FREIE_WAEHLER",
  "BVB/FW" = "FREIE_WAEHLER",
  "SSW" = "SSW",
  "Piraten" = "PIRATEN",
  "Sonstige" = "SONSTIGE"
)

.dawum_dump_cache <- new.env(parent = emptyenv())

fetch_dawum_dump <- function(url = DAWUM_API_URL) {
  if (exists("dump", envir = .dawum_dump_cache, inherits = FALSE)) {
    return(.dawum_dump_cache$dump)
  }
  resp <- httr::GET(
    url,
    httr::add_headers("User-Agent" = "zweitstimme-website-pipeline/1.0"),
    httr::timeout(120)
  )
  httr::stop_for_status(resp)
  dump <- jsonlite::fromJSON(
    httr::content(resp, as = "text", encoding = "UTF-8"),
    simplifyVector = FALSE
  )
  .dawum_dump_cache$dump <- dump
  dump
}

# Align DAWUM institute labels with FastTrack institute_key where known.
DAWUM_INSTITUTE_NAME_TO_KEY <- c(
  "Infratest dimap" = "INFRATEST",
  "Infratest Dimap" = "INFRATEST",
  "INSA" = "INSA",
  "Civey" = "CIVEY",
  "Forsa" = "FORSA",
  "Forschungsgruppe Wahlen" = "FORSCHUNGSGRUPPE_WAHLEN",
  "Allensbach" = "ALLENSBACH",
  "GMS" = "GMS",
  "Verian" = "VERIAN",
  "YouGov" = "YOUGOV"
)

# Named character vectors error on unknown [[key]]; lists would return NULL.
named_get <- function(vec, key) {
  key <- as.character(key %||% "")
  if (!nzchar(key) || !(key %in% names(vec))) return(NULL)
  unname(vec[[key]])
}

institute_name_to_key <- function(name) {
  trimmed <- trimws(as.character(name %||% ""))
  mapped <- named_get(DAWUM_INSTITUTE_NAME_TO_KEY, trimmed)
  if (!is.null(mapped)) return(mapped)
  raw <- toupper(gsub("[^A-Za-z0-9]+", "_", trimmed))
  raw <- gsub("^_|_$", "", raw)
  if (grepl("^INFRATEST", raw)) return("INFRATEST")
  if (!nzchar(raw)) return("UNKNOWN")
  raw
}

canonicalize_institute_key <- function(key_or_name) {
  raw <- trimws(as.character(key_or_name %||% ""))
  if (!nzchar(raw)) return("")
  mapped <- named_get(DAWUM_INSTITUTE_NAME_TO_KEY, raw)
  if (!is.null(mapped)) return(mapped)
  key <- toupper(gsub("[^A-Za-z0-9]+", "_", raw))
  key <- gsub("^_|_$", "", key)
  if (grepl("^INFRATEST", key)) return("INFRATEST")
  key
}

poll_institute_date_dedupe_key <- function(poll) {
  inst <- canonicalize_institute_key(
    poll$institute_key %||% poll$institute_name %||% ""
  )
  date <- as.character(poll$publish_date %||% poll$published_date %||% "")
  paste0(inst, "|", date)
}

# Mirror polling-api validation.toml / public_policy.yaml (consumer-side).
DAWUM_QC_SUM_TOLERANCE <- 2.0
DAWUM_QC_JUMP_THRESHOLD <- 4.0
DAWUM_QC_RESPONDENTS_DEFAULT <- c(500L, 6000L)
DAWUM_MATCH_DATE_WINDOW_DAYS <- 7L
DAWUM_MATCH_MAX_PARTY_DELTA <- 1.0
DAWUM_MATCH_MAX_TOTAL_DELTA <- 1.5
DAWUM_MATCH_PARTIES <- c("SPD", "AFD")

DAWUM_METHOD_NAME_TO_KEY <- c(
  "Online" = "ONLINE",
  "Telefonisch" = "TELEFONISCH",
  "Telefon & Online" = "TELEFON_ONLINE",
  "Persönlich" = "PERSOENLICH",
  "Persönlich & Online" = "PERSOENLICH_ONLINE",
  "Unbekannt" = "UNBEKANNT"
)

DAWUM_RESPONDENT_LIMITS <- list(
  ONLINE = c(500L, 6000L),
  TELEFONISCH = c(700L, 4000L),
  TELEFON_ONLINE = c(700L, 4000L),
  PERSOENLICH = c(500L, 3000L),
  PERSOENLICH_ONLINE = c(500L, 6000L),
  UNBEKANNT = c(500L, 6000L)
)

poll_result_map <- function(poll) {
  out <- list()
  for (row in poll$results %||% list()) {
    if (is.null(row)) next
    key <- toupper(as.character(row$party_key %||% ""))
    pct <- suppressWarnings(as.numeric(row$percentage))
    if (!nzchar(key) || !is.finite(pct)) next
    out[[key]] <- pct
  }
  out
}

poll_publish_date <- function(poll) {
  as.character(poll$publish_date %||% poll$published_date %||% "")
}

expected_core_parties_for_scope <- function(scope, year) {
  scope_l <- tolower(as.character(scope %||% ""))
  parties <- if (identical(scope_l, "by")) {
    c("CSU", "SPD", "FDP")
  } else {
    c("CDU", "SPD", "FDP")
  }
  if (is.finite(year) && year >= 1990) parties <- c(parties, "GRUENE")
  if (is.finite(year) && year >= 2014) parties <- c(parties, "AFD")
  unique(parties)
}

qc_dawum_poll <- function(poll, comparison_polls = list()) {
  errors <- character(0)
  warnings <- character(0)
  res <- poll_result_map(poll)

  if (length(res) == 0) {
    errors <- c(errors, "no_results")
  } else {
    pcts <- unlist(res, use.names = FALSE)
    if (any(!is.finite(pcts) | pcts < 0 | pcts > 100)) {
      errors <- c(errors, "percentage_range")
    }
    total <- sum(pcts)
    if (!(total >= 100 - DAWUM_QC_SUM_TOLERANCE && total <= 100 + DAWUM_QC_SUM_TOLERANCE)) {
      errors <- c(errors, sprintf("result_sum=%.1f", total))
    }
  }

  start <- as.character(poll$survey_date_start %||% poll$survey_start_date %||% "")
  end <- as.character(poll$survey_date_end %||% poll$survey_end_date %||% "")
  publish <- poll_publish_date(poll)
  today <- format(Sys.Date(), "%Y-%m-%d")
  if (!nzchar(start) || !nzchar(end) || !nzchar(publish)) {
    errors <- c(errors, "missing_dates")
  } else if (!(start <= end && end <= publish && publish <= today)) {
    errors <- c(errors, "date_consistency")
  }

  method_key <- toupper(as.character(
    poll$method_key %||% poll$survey_method_key %||% "UNBEKANNT"
  ))
  limits <- DAWUM_RESPONDENT_LIMITS[[method_key]]
  if (is.null(limits)) limits <- DAWUM_QC_RESPONDENTS_DEFAULT
  n <- suppressWarnings(as.integer(poll$respondents))
  if (!is.finite(n) || n < limits[1] || n > limits[2]) {
    errors <- c(errors, "respondents")
  }

  year <- suppressWarnings(as.integer(substr(publish, 1, 4)))
  expected <- expected_core_parties_for_scope(poll$scope, year)
  present <- names(res)
  missing <- setdiff(expected, present)
  # Soft: FDP often omitted when below ~3%. Block only if nearby API polls
  # usually report it (presence share >= 0.8 over up to 5 comparisons).
  hard_missing <- setdiff(missing, "FDP")
  if ("FDP" %in% missing) {
    fdp_presence <- vapply(comparison_polls, function(p) {
      "FDP" %in% names(poll_result_map(p))
    }, logical(1))
    if (length(fdp_presence) >= 5 && mean(fdp_presence) >= 0.8) {
      hard_missing <- c(hard_missing, "FDP")
    } else if (length(missing)) {
      warnings <- c(warnings, "core_parties_soft:FDP")
    }
  }
  if (length(hard_missing) > 0) {
    errors <- c(errors, paste0("core_parties:", paste(hard_missing, collapse = ",")))
  }

  # Jump vs previous same-institute poll among comparison set (warning only).
  inst <- canonicalize_institute_key(poll$institute_key %||% poll$institute_name)
  pub <- poll_publish_date(poll)
  prev <- NULL
  prev_date <- ""
  for (p in comparison_polls) {
    if (!identical(
      canonicalize_institute_key(p$institute_key %||% p$institute_name),
      inst
    )) next
    d <- poll_publish_date(p)
    if (!nzchar(d) || d >= pub) next
    if (d > prev_date) {
      prev <- p
      prev_date <- d
    }
  }
  if (!is.null(prev)) {
    prev_res <- poll_result_map(prev)
    jumped <- character(0)
    for (party in intersect(names(res), names(prev_res))) {
      if (abs(res[[party]] - prev_res[[party]]) > DAWUM_QC_JUMP_THRESHOLD) {
        jumped <- c(jumped, party)
      }
    }
    if (length(jumped) > 0) {
      warnings <- c(warnings, paste0("institute_jump:", paste(jumped, collapse = ",")))
    }
  }

  list(ok = length(errors) == 0, errors = errors, warnings = warnings)
}

dawum_matches_existing_poll <- function(candidate, existing) {
  # Exact institute + publish date.
  cand_key <- poll_institute_date_dedupe_key(candidate)
  if (nzchar(cand_key) && !grepl("^\\|", cand_key)) {
    for (p in existing) {
      if (identical(poll_institute_date_dedupe_key(p), cand_key)) return(TRUE)
    }
  }

  # Fuzzy match (polling-api poll_matching): ±7 days, SPD/AFD deltas.
  cand_date <- suppressWarnings(as.Date(poll_publish_date(candidate)))
  if (is.na(cand_date)) return(FALSE)
  cand_res <- poll_result_map(candidate)
  for (p in existing) {
    d <- suppressWarnings(as.Date(poll_publish_date(p)))
    if (is.na(d)) next
    if (abs(as.integer(cand_date - d)) > DAWUM_MATCH_DATE_WINDOW_DAYS) next

    # Same institute preferred; also allow cross-provider same fieldwork clone.
    same_inst <- identical(
      canonicalize_institute_key(candidate$institute_key %||% candidate$institute_name),
      canonicalize_institute_key(p$institute_key %||% p$institute_name)
    )

    deltas <- c()
    for (party in DAWUM_MATCH_PARTIES) {
      a <- cand_res[[party]]
      b <- poll_result_map(p)[[party]]
      if (is.null(a) || is.null(b)) {
        deltas <- NULL
        break
      }
      deltas <- c(deltas, abs(a - b))
    }
    if (is.null(deltas)) next
    if (max(deltas) <= DAWUM_MATCH_MAX_PARTY_DELTA &&
        sum(deltas) <= DAWUM_MATCH_MAX_TOTAL_DELTA &&
        same_inst) {
      return(TRUE)
    }

    # Respondent + survey-end exact match (same fieldwork published under
    # slightly different labels).
    n_a <- suppressWarnings(as.integer(candidate$respondents))
    n_b <- suppressWarnings(as.integer(p$respondents))
    end_a <- as.character(candidate$survey_date_end %||% candidate$survey_end_date %||% "")
    end_b <- as.character(p$survey_date_end %||% p$survey_end_date %||% "")
    if (is.finite(n_a) && is.finite(n_b) && n_a == n_b &&
        nzchar(end_a) && identical(end_a, end_b) && same_inst) {
      return(TRUE)
    }
  }
  FALSE
}

dawum_results_to_api <- function(results, parties_lookup) {
  out <- list()
  if (is.null(results) || length(results) == 0) return(out)
  for (pid in names(results)) {
    party <- parties_lookup[[as.character(pid)]]
    shortcut <- if (is.list(party)) as.character(party$Shortcut %||% "") else ""
    key <- named_get(DAWUM_PARTY_SHORTCUT_TO_KEY, shortcut)
    if (is.null(key) || !nzchar(key)) {
      # Keep unknown parties under a stable key so Sonstige fill still works.
      key <- toupper(gsub("[^A-Za-z0-9]+", "_", shortcut))
      if (!nzchar(key)) next
    }
    pct <- suppressWarnings(as.numeric(results[[pid]]))
    if (!is.finite(pct)) next
    out <- c(out, list(list(
      party_key = key,
      party_short_name = shortcut,
      party_name = if (is.list(party)) party$Name %||% shortcut else shortcut,
      percentage = pct
    )))
  }
  out
}

dawum_survey_to_poll <- function(survey_id, survey, scope, institute_name,
                                 commissioner_name, method_name, parties_lookup) {
  period <- survey$Survey_Period %||% list()
  publish <- as.character(survey$Date %||% "")
  start <- as.character(period$Date_Start %||% publish)
  end <- as.character(period$Date_End %||% publish)
  respondents <- suppressWarnings(as.integer(survey$Surveyed_Persons))
  if (!is.finite(respondents)) respondents <- NULL
  method_key <- named_get(DAWUM_METHOD_NAME_TO_KEY, method_name %||% "")
  if (is.null(method_key)) method_key <- "UNBEKANNT"

  list(
    id = NULL,
    public_id = paste0("DAWUM-", survey_id),
    published_date = publish,
    publish_date = publish,
    survey_start_date = start,
    survey_end_date = end,
    survey_date_start = start,
    survey_date_end = end,
    respondents = respondents,
    institute_name = institute_name,
    institute_key = institute_name_to_key(institute_name),
    provider_name = "DAWUM",
    source = "dawum_scrape",
    commissioner_name = commissioner_name,
    survey_method_name = method_name,
    method_name = method_name,
    survey_method_key = method_key,
    method_key = method_key,
    scope = scope,
    election_key = scope,
    election_type = "State election",
    matching_status = "no_match",
    results = dawum_results_to_api(survey$Results, parties_lookup),
    pipeline_dawum_scrape = TRUE
  )
}

# Scrape Landtag surveys from api.dawum.de for one scope (clear Parliament_ID).
fetch_dawum_state_polls <- function(scope, date_from = NULL, date_to = NULL) {
  scope_l <- tolower(as.character(scope %||% ""))
  if (!scope_l %in% unname(DAWUM_PARLIAMENT_TO_SCOPE)) return(list())

  parliament_ids <- names(DAWUM_PARLIAMENT_TO_SCOPE)[
    DAWUM_PARLIAMENT_TO_SCOPE == scope_l
  ]
  dump <- fetch_dawum_dump()
  surveys <- dump$Surveys %||% list()
  institutes <- dump$Institutes %||% list()
  taskers <- dump$Taskers %||% list()
  methods <- dump$Methods %||% list()
  parties <- dump$Parties %||% list()

  out <- list()
  for (sid in names(surveys)) {
    survey <- surveys[[sid]]
    if (is.null(survey)) next
    if (!(as.character(survey$Parliament_ID %||% "") %in% parliament_ids)) next

    publish <- as.character(survey$Date %||% "")
    if (!nzchar(publish)) next
    if (!is.null(date_from) && publish < date_from) next
    if (!is.null(date_to) && publish > date_to) next

    inst <- institutes[[as.character(survey$Institute_ID %||% "")]]
    institute_name <- if (is.list(inst)) inst$Name %||% "Unknown" else "Unknown"
    tasker <- taskers[[as.character(survey$Tasker_ID %||% "")]]
    commissioner <- if (is.list(tasker)) tasker$Name %||% NULL else NULL
    method <- methods[[as.character(survey$Method_ID %||% "")]]
    method_name <- if (is.list(method)) method$Name %||% NULL else NULL

    out <- c(out, list(dawum_survey_to_poll(
      sid, survey,
      scope = scope_l,
      institute_name = institute_name,
      commissioner_name = commissioner,
      method_name = method_name,
      parties_lookup = parties
    )))
  }
  out
}

inject_dawum_state_polls <- function(polls, scope, date_from = NULL, date_to = NULL) {
  scope_l <- tolower(as.character(scope %||% ""))
  if (!scope_l %in% unname(DAWUM_PARLIAMENT_TO_SCOPE)) return(polls)

  scraped <- tryCatch(
    fetch_dawum_state_polls(scope_l, date_from = date_from, date_to = date_to),
    error = function(e) {
      warning(sprintf("DAWUM scrape failed for scope=%s: %s", scope_l, e$message))
      list()
    }
  )
  if (length(scraped) == 0) return(polls)

  # Newest last so jump checks see earlier institute polls first when we append.
  scraped <- scraped[order(vapply(scraped, poll_publish_date, character(1)))]

  n_dup <- 0L
  n_qc_fail <- 0L
  n_warn <- 0L
  extras <- list()
  comparison <- polls

  for (p in scraped) {
    if (dawum_matches_existing_poll(p, comparison)) {
      n_dup <- n_dup + 1L
      next
    }
    qc <- qc_dawum_poll(p, comparison_polls = comparison)
    if (length(qc$warnings) > 0) {
      n_warn <- n_warn + 1L
      message(sprintf(
        "DAWUM QC warning %s: %s",
        p$public_id %||% "?",
        paste(qc$warnings, collapse = "; ")
      ))
    }
    if (!qc$ok) {
      n_qc_fail <- n_qc_fail + 1L
      message(sprintf(
        "DAWUM QC drop %s: %s",
        p$public_id %||% "?",
        paste(qc$errors, collapse = "; ")
      ))
      next
    }
    extras <- c(extras, list(p))
    comparison <- c(comparison, list(p))
  }

  if (length(extras) == 0) {
    if (n_dup > 0 || n_qc_fail > 0) {
      message(sprintf(
        "DAWUM scrape scope=%s: 0 injected (dup=%d, qc_fail=%d)",
        scope_l, n_dup, n_qc_fail
      ))
    }
    return(polls)
  }

  message(sprintf(
    "Injected %d DAWUM-scraped poll(s) into scope=%s (dup=%d, qc_fail=%d, warnings=%d)",
    length(extras), scope_l, n_dup, n_qc_fail, n_warn
  ))
  c(polls, extras)
}

fetch_polls_all <- function(scope, date_from = NULL, date_to = NULL, max_total = 20000) {
  all_items <- list()
  offset <- 0L
  total <- Inf

  repeat {
    page <- fetch_polls_page(scope, date_from, date_to, offset = offset)
    items <- page$items
    if (length(items) == 0) break
    all_items <- c(all_items, items)
    total <- page$total
    offset <- offset + length(items)
    if (offset >= total || length(all_items) >= max_total) break
  }

  if (length(all_items) > max_total) {
    all_items <- all_items[seq_len(max_total)]
  }

  polls <- drop_matched_duplicates(all_items)
  polls <- inject_dawum_state_polls(polls, scope, date_from = date_from, date_to = date_to)
  drop_misscoped_federal_polls(polls, scope = scope)
}

polls_date_range <- function(polls) {
  dates <- vapply(polls, function(p) p$publish_date %||% NA_character_, character(1))
  dates <- dates[!is.na(dates) & nzchar(dates)]
  if (length(dates) == 0) {
    return(list(start = NA_character_, end = NA_character_))
  }
  list(start = min(dates), end = max(dates))
}
