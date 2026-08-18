#!/usr/bin/env Rscript
# Skeleton runner for the Zweitstimme federal forecast model.

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

FEDERAL_MODEL_DIR <- Sys.getenv(
  "FEDERAL_MODEL_DIR",
  "/mnt/cerfort/forecasts/prediction-2025"
)
ELECTION_DATE <- Sys.getenv("ELECTION_DATE", "2029-02-25")
POLL_SOURCE <- Sys.getenv("POLL_SOURCE", "api")

cat("Federal forecast skeleton\n")
cat("  Model dir:", FEDERAL_MODEL_DIR, "\n")
cat("  Election:", ELECTION_DATE, "\n")
cat("  Poll source:", POLL_SOURCE, "\n")

run_script <- file.path(FEDERAL_MODEL_DIR, "code", "00_run-model.R")
if (!file.exists(run_script)) {
  stop(
    "Federal model entry script not found: ", run_script,
    "\nSet FEDERAL_MODEL_DIR to a checkout of zweitstimme-org/prediction-2025."
  )
}

# TODO: parameterize prediction-2025 (paths, poll source, election date) before enabling full automation.
# For now, document the expected handoff and emit a placeholder manifest.

manifest <- list(
  status = "skeleton",
  message = paste(
    "Wire this runner to parameterized prediction-2025 once the next Bundestagswahl cycle begins.",
    "District forecast inputs (candidate CSV, GeoJSON, remapping tables) belong in federal-model/inputs/."
  ),
  election_date = ELECTION_DATE,
  poll_source = POLL_SOURCE,
  model_dir = FEDERAL_MODEL_DIR,
  expected_outputs = c(
    "forecast_federal.json",
    "pred_probabilities.json",
    "forecast_districts.json"
  ),
  district_inputs = list(
    candidates = "federal-model/inputs/btw_candidates.csv",
    geojson = "federal-model/inputs/wahlkreise.geojson",
    remapping = "federal-model/inputs/district_remapping.csv"
  ),
  last_update = format(Sys.time(), "%Y-%m-%dT%H:%M:%OS")
)

dir.create(OUTPUT_DIR, recursive = TRUE, showWarnings = FALSE)
dir.create(file.path(REPO_ROOT, "federal-model", "inputs"), recursive = TRUE, showWarnings = FALSE)

jsonlite::write_json(
  manifest,
  file.path(OUTPUT_DIR, "federal_forecast_manifest.json"),
  auto_unbox = TRUE,
  pretty = TRUE
)

cat("Wrote federal_forecast_manifest.json (skeleton). Full model run not yet wired.\n")
