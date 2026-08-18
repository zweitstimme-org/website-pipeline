#!/usr/bin/env Rscript
# Install R dependencies for the zweitstimme website pipeline.

required <- c(
  "jsonlite",
  "httr",
  "lubridate"
)

# Heavy Stan stack used by state-model / state-models estimation.
optional_state <- c(
  "dplyr",
  "tidyr",
  "rstanarm"
)

# Often needed before rstanarm can load; install explicitly so a flaky
# packagemanager download does not leave a half-working library.
stan_bootstrap <- c(
  "pkgbuild",
  "rstantools",
  "Rcpp",
  "RcppEigen",
  "StanHeaders",
  "BH",
  "RcppParallel"
)

cran_repos_list <- function() {
  rspm <- Sys.getenv("RSPM", unset = "")
  repos <- character()
  if (nzchar(rspm)) {
    repos <- c(repos, rspm)
  }
  repos <- c(repos, "https://cloud.r-project.org")
  unique(repos)
}

load_ok <- function(pkg) {
  requireNamespace(pkg, quietly = TRUE)
}

load_error <- function(pkg) {
  tryCatch(
    {
      loadNamespace(pkg)
      NULL
    },
    error = function(e) conditionMessage(e)
  )
}

install_packages_retry <- function(pkgs, repos, attempts = 3L) {
  options(timeout = max(600, getOption("timeout", 60)))
  ncpus <- max(1L, parallel::detectCores(logical = TRUE) - 1L)
  remaining <- unique(pkgs)

  for (attempt in seq_len(attempts)) {
    if (length(remaining) == 0) {
      break
    }
    repo <- repos[((attempt - 1L) %% length(repos)) + 1L]
    message(
      sprintf(
        "Installing (%d/%d) from %s: %s",
        attempt,
        attempts,
        repo,
        paste(remaining, collapse = ", ")
      )
    )
    for (pkg in remaining) {
      tryCatch(
        install.packages(
          pkg,
          repos = c(CRAN = repo),
          dependencies = TRUE,
          Ncpus = ncpus
        ),
        error = function(e) {
          message("install.packages(", pkg, ") error: ", conditionMessage(e))
        }
      )
    }
    remaining <- remaining[!vapply(remaining, load_ok, FUN.VALUE = logical(1))]
    if (length(remaining) > 0 && attempt < attempts) {
      Sys.sleep(5 * attempt)
    }
  }
  remaining
}

install_if_missing <- function(pkgs, attempts = 3L) {
  missing <- pkgs[!vapply(pkgs, load_ok, FUN.VALUE = logical(1))]
  if (length(missing) == 0) {
    return(invisible(NULL))
  }

  still_missing <- install_packages_retry(
    missing,
    repos = cran_repos_list(),
    attempts = attempts
  )

  if (length(still_missing) > 0) {
    details <- vapply(
      still_missing,
      function(pkg) {
        err <- load_error(pkg)
        if (is.null(err)) {
          paste0(pkg, " (present on disk but failed to load)")
        } else {
          paste0(pkg, ": ", err)
        }
      },
      FUN.VALUE = character(1)
    )
    stop(
      "Failed to install R packages:\n  - ",
      paste(details, collapse = "\n  - "),
      call. = FALSE
    )
  }
  invisible(NULL)
}

install_if_missing(required)

if (identical(tolower(Sys.getenv("INSTALL_STATE_MODEL_DEPS", "false")), "true")) {
  # Bootstrap fragile Stan deps first, then the packages we actually import.
  install_if_missing(stan_bootstrap)
  install_if_missing(optional_state)
}

cat("R dependencies ready.\n")
