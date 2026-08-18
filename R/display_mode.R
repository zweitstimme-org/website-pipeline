# Build election calendar and display mode JSON artifacts.

build_election_calendar <- function(election_dates_path = ELECTION_DATES_FILE,
                                    output_path = ELECTION_CALENDAR_FILE) {
  elections <- list()

  # Federal Bundestagswahl placeholder — update manually when date is known.
  federal <- list(
    scope = "bund",
    state_code = NULL,
    state_name = "Deutschland",
    election_name = "Bundestagswahl",
    election_date = Sys.getenv("FEDERAL_ELECTION_DATE", "2029-02-25"),
    date_is_estimated = TRUE
  )
  elections <- c(list(federal), elections)

  if (file.exists(election_dates_path)) {
    scraped <- jsonlite::fromJSON(election_dates_path, simplifyVector = FALSE)
    for (row in scraped$elections %||% list()) {
      elections[[length(elections) + 1]] <- list(
        scope = tolower(STATE_CODE_TO_SCOPE[[row$state_code]]),
        state_code = row$state_code,
        state_name = row$state_name,
        election_name = paste("Landtagswahl", row$state_name),
        election_date = row$estimated_date,
        date_is_estimated = isTRUE(row$date_is_estimated)
      )
    }
  }

  payload <- list(
    metadata = list(
      last_updated = format(Sys.time(), "%Y-%m-%dT%H:%M:%OS"),
      source = "website-pipeline/data/election_calendar.json",
      forecast_window_days = FORECAST_WINDOW_DAYS
    ),
    elections = elections
  )

  dir.create(dirname(output_path), recursive = TRUE, showWarnings = FALSE)
  jsonlite::write_json(payload, output_path, auto_unbox = TRUE, pretty = TRUE, null = "null")
  payload
}

days_until <- function(target_date, from_date = Sys.Date()) {
  as.integer(as.Date(target_date) - from_date)
}

forecast_archive_dir <- function(output_dir = OUTPUT_DIR) {
  file.path(output_dir, "archive")
}

active_forecast_path <- function(scope, state_code = NULL, output_dir = OUTPUT_DIR) {
  if (identical(scope, "bund")) {
    return(file.path(output_dir, "forecast_federal.json"))
  }
  if (!is.null(state_code)) {
    return(file.path(output_dir, paste0("forecast_state_", tolower(state_code), ".json")))
  }
  NULL
}

archived_forecast_path <- function(scope, state_code = NULL, election_date,
                                   output_dir = OUTPUT_DIR) {
  archive_dir <- forecast_archive_dir(output_dir)
  if (identical(scope, "bund")) {
    return(file.path(archive_dir, paste0("forecast_federal_", election_date, ".json")))
  }
  if (!is.null(state_code)) {
    return(file.path(archive_dir, paste0("forecast_state_", tolower(state_code), "_", election_date, ".json")))
  }
  NULL
}

forecast_file_exists <- function(scope, state_code = NULL, output_dir = OUTPUT_DIR) {
  path <- active_forecast_path(scope, state_code, output_dir)
  !is.null(path) && file.exists(path)
}

archive_forecast_key <- function(scope, state_code = NULL, election_date) {
  if (identical(scope, "bund")) {
    return(paste0("federal_", election_date))
  }
  paste0(tolower(state_code), "_", election_date)
}

archive_forecast_file_field <- function(scope, state_code = NULL, election_date) {
  if (identical(scope, "bund")) {
    return(paste0("archive/forecast_federal_", election_date, ".json"))
  }
  paste0("archive/forecast_state_", tolower(state_code), "_", election_date, ".json")
}

maybe_archive_forecast <- function(entry, today, output_dir = OUTPUT_DIR) {
  election_date <- entry$election_date
  if (is.null(election_date) || !nzchar(election_date)) {
    return(NULL)
  }

  days <- days_until(election_date, today)
  if (days >= 0) {
    return(NULL)
  }

  scope <- entry$scope
  state_code <- entry$state_code
  archive_path <- archived_forecast_path(scope, state_code, election_date, output_dir)
  active_path <- active_forecast_path(scope, state_code, output_dir)

  if (is.null(archive_path)) {
    return(NULL)
  }

  dir.create(dirname(archive_path), recursive = TRUE, showWarnings = FALSE)

  if (!is.null(active_path) && file.exists(active_path)) {
    file.copy(active_path, archive_path, overwrite = TRUE)
    file.remove(active_path)
  }

  if (!identical(scope, "bund") && !is.null(state_code)) {
    active_draws <- file.path(
      output_dir, paste0("forecast_state_", tolower(state_code), "_draws.json")
    )
    archive_draws <- file.path(
      forecast_archive_dir(output_dir),
      paste0("forecast_state_", tolower(state_code), "_", election_date, "_draws.json")
    )
    if (file.exists(active_draws)) {
      file.copy(active_draws, archive_draws, overwrite = TRUE)
      file.remove(active_draws)
    }
  }

  if (!file.exists(archive_path)) {
    return(NULL)
  }

  list(
    key = archive_forecast_key(scope, state_code, election_date),
    scope = if (identical(scope, "bund")) "federal" else "state",
    state_code = state_code,
    election_date = election_date,
    election_name = entry$election_name,
    date_is_estimated = isTRUE(entry$date_is_estimated),
    forecast_file = archive_forecast_file_field(scope, state_code, election_date),
    archived_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%OS")
  )
}

build_display_mode <- function(calendar = NULL, output_dir = OUTPUT_DIR,
                               output_path = file.path(output_dir, "display_mode.json")) {
  if (is.null(calendar)) {
    calendar <- build_election_calendar()
  }

  today <- Sys.Date()
  federal_mode <- list(
    mode = "stimmung",
    election_date = NULL,
    days_to_election = NULL,
    forecast_available = FALSE
  )

  state_modes <- list()
  archive_forecasts <- list()

  for (entry in calendar$elections) {
    election_date <- entry$election_date
    if (is.null(election_date) || !nzchar(election_date)) next

    days <- days_until(election_date, today)
    scope <- entry$scope
    state_code <- entry$state_code

    if (days < 0) {
      archived <- maybe_archive_forecast(entry, today, output_dir)
      if (!is.null(archived)) {
        archive_forecasts[[length(archive_forecasts) + 1]] <- archived
      }
      next
    }

    within_window <- days <= FORECAST_WINDOW_DAYS
    has_forecast <- forecast_file_exists(scope, state_code, output_dir)

    mode_info <- list(
      mode = if (within_window && has_forecast) "forecast" else "stimmung",
      election_date = election_date,
      days_to_election = days,
      election_name = entry$election_name,
      date_is_estimated = isTRUE(entry$date_is_estimated),
      forecast_available = has_forecast && within_window
    )

    if (identical(scope, "bund")) {
      federal_mode <- mode_info
    } else if (!is.null(state_code)) {
      state_modes[[state_code]] <- mode_info
    }
  }

  if (length(archive_forecasts) > 0) {
    archive_dates <- vapply(archive_forecasts, function(x) x$election_date, character(1))
    archive_forecasts <- archive_forecasts[order(archive_dates, decreasing = TRUE)]
  }

  payload <- list(
    last_update = format(Sys.time(), "%Y-%m-%dT%H:%M:%OS"),
    forecast_window_days = FORECAST_WINDOW_DAYS,
    federal = federal_mode,
    states = state_modes,
    archive = list(forecasts = archive_forecasts)
  )

  dir.create(dirname(output_path), recursive = TRUE, showWarnings = FALSE)
  jsonlite::write_json(payload, output_path, auto_unbox = TRUE, pretty = TRUE, null = "null")
  payload
}
