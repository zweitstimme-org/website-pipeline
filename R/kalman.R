# 1D Kalman filter + RTS smoother for latent vote support.

# Estimate process (q) and measurement (r) noise from the polls.
# Two-step method matching the filter's daily-mean observation model:
#   1) r from within-day dispersion of individual polls (same party, same day)
#   2) q from consecutive observation days after removing measurement variance:
#        E[(ȳ_j - ȳ_i)^2] = q * gap + r * (1/n_i + 1/n_j)
# Returns clamped values plus diagnostics; falls back to defaults if too sparse.
calibrate_kalman_qr <- function(polls,
                                parties = CORE_PARTIES,
                                q_default = 0.1,
                                r_default = 1.0,
                                min_pairs = 40L,
                                min_within_day = 20L,
                                max_gap_days = 180L,
                                q_range = c(0.01, 0.35),
                                r_range = c(0.5, 3.0)) {
  within_ss <- 0
  within_df <- 0
  gaps <- numeric(0)
  inv_n <- numeric(0)
  sqdiffs <- numeric(0)

  if (length(polls) >= 2 && length(parties) > 0) {
    poll_dates <- vapply(polls, function(p) p$publish_date %||% "", character(1))
    keep <- poll_dates != ""
    polls <- polls[keep]
    poll_dates <- poll_dates[keep]
    if (length(polls) >= 2) {
      maps <- lapply(polls, poll_to_party_map)
      days <- as.Date(poll_dates)

      for (party in parties) {
        vals <- vapply(maps, function(m) {
          v <- m[[party]]
          if (is.null(v) || !is.finite(v)) NA_real_ else as.numeric(v)
        }, numeric(1))
        ok <- is.finite(vals) & !is.na(days)
        if (!any(ok)) next
        split_idx <- split(which(ok), as.character(days[ok]))
        day_keys <- names(split_idx)
        day_ord <- order(as.Date(day_keys))
        day_keys <- day_keys[day_ord]
        day_means <- numeric(length(day_keys))
        day_ns <- numeric(length(day_keys))

        for (di in seq_along(day_keys)) {
          ix <- split_idx[[day_keys[[di]]]]
          v <- vals[ix]
          day_means[[di]] <- mean(v)
          day_ns[[di]] <- length(v)
          if (length(v) >= 2) {
            within_ss <- within_ss + sum((v - mean(v))^2)
            within_df <- within_df + (length(v) - 1)
          }
        }

        day_dates <- as.Date(day_keys)
        if (length(day_means) < 2) next
        for (k in seq_len(length(day_means) - 1)) {
          gap <- as.numeric(day_dates[[k + 1]] - day_dates[[k]])
          if (!is.finite(gap) || gap < 1 || gap > max_gap_days) next
          ni <- day_ns[[k]]
          nj <- day_ns[[k + 1]]
          if (!is.finite(ni) || !is.finite(nj) || ni < 1 || nj < 1) next
          gaps <- c(gaps, gap)
          inv_n <- c(inv_n, 1 / ni + 1 / nj)
          sqdiffs <- c(sqdiffs, (day_means[[k + 1]] - day_means[[k]])^2)
        }
      }
    }
  }

  n_pairs <- length(gaps)
  r_hat <- if (within_df >= min_within_day) within_ss / within_df else NA_real_
  q_hat <- NA_real_

  if (n_pairs >= min_pairs && is.finite(r_hat) && r_hat > 0) {
    resid <- sqdiffs - r_hat * inv_n
    # No-intercept regression of residual variance on gap; drop negative noise.
    fit <- stats::lm(resid ~ 0 + gaps)
    q_hat <- as.numeric(stats::coef(fit)[["gaps"]])
  } else if (n_pairs >= min_pairs && stats::sd(gaps) >= 1e-8) {
    # Sparse same-day replicates: joint classic regression.
    if (stats::sd(inv_n) >= 1e-12) {
      fit <- stats::lm(sqdiffs ~ 0 + gaps + inv_n)
      q_hat <- as.numeric(stats::coef(fit)[["gaps"]])
      r_hat <- as.numeric(stats::coef(fit)[["inv_n"]])
    } else {
      fit <- stats::lm(sqdiffs ~ gaps)
      q_hat <- as.numeric(stats::coef(fit)[["gaps"]])
      r_hat <- as.numeric(stats::coef(fit)[["(Intercept)"]]) / 2
    }
  } else {
    return(list(
      q = q_default,
      r = r_default,
      calibrated = FALSE,
      n_pairs = n_pairs,
      within_df = as.integer(within_df),
      fallback = TRUE
    ))
  }

  if (!is.finite(q_hat)) q_hat <- q_default
  if (!is.finite(r_hat)) r_hat <- r_default

  q <- min(max(q_hat, q_range[[1]]), q_range[[2]])
  r <- min(max(r_hat, r_range[[1]]), r_range[[2]])
  q_fell_back <- FALSE
  r_fell_back <- FALSE
  if (q_hat <= 0) {
    q <- q_default
    q_fell_back <- TRUE
  }
  if (r_hat <= 0) {
    r <- r_default
    r_fell_back <- TRUE
  }

  list(
    q = q,
    r = r,
    calibrated = TRUE,
    n_pairs = n_pairs,
    within_df = as.integer(within_df),
    fallback = q_fell_back || r_fell_back,
    q_raw = q_hat,
    r_raw = r_hat
  )
}

smooth_1d <- function(y, q = 0.1, r = 1.0, x0 = NULL, p0 = 1.0, n_obs = NULL) {
  n <- length(y)
  xf <- rep(NA_real_, n)
  pf <- rep(NA_real_, n)
  xp <- rep(NA_real_, n)
  pp <- rep(NA_real_, n)

  init <- x0
  if (is.null(init) || !is.finite(init)) {
    for (i in seq_len(n)) {
      if (is.finite(y[[i]])) {
        init <- y[[i]]
        break
      }
    }
  }

  if (is.null(init) || !is.finite(init)) {
    return(list(filtered = rep(NA_real_, n), smoothed = rep(NA_real_, n),
                filtered_var = rep(NA_real_, n), smoothed_var = rep(NA_real_, n)))
  }

  x <- init
  p <- p0

  for (t in seq_len(n)) {
    x_pred <- x
    p_pred <- p + q
    xp[[t]] <- x_pred
    pp[[t]] <- p_pred

    yt <- y[[t]]
    if (is.finite(yt)) {
      rt <- r
      if (!is.null(n_obs)) {
        nt <- n_obs[[t]]
        if (is.finite(nt) && nt > 0) rt <- r / nt
      }
      s <- p_pred + rt
      k <- if (s > 0) p_pred / s else 0
      x <- x_pred + k * (yt - x_pred)
      p <- (1 - k) * p_pred
    } else {
      x <- x_pred
      p <- p_pred
    }

    xf[[t]] <- x
    pf[[t]] <- p
  }

  xs <- xf
  ps <- pf
  xs[[n]] <- xf[[n]]
  ps[[n]] <- pf[[n]]

  if (n >= 2) {
    for (t in seq(n - 1, 1)) {
      p_pred_next <- pp[[t + 1]]
      c_val <- if (p_pred_next > 0) pf[[t]] / p_pred_next else 0
      xs[[t]] <- xf[[t]] + c_val * (xs[[t + 1]] - xp[[t + 1]])
      ps[[t]] <- pf[[t]] + c_val * c_val * (ps[[t + 1]] - p_pred_next)
    }
  }

  list(
    filtered = xf,
    smoothed = xs,
    filtered_var = pf,
    smoothed_var = ps
  )
}

build_daily_grid <- function(start_iso, end_iso) {
  start_date <- as.Date(start_iso)
  end_date <- as.Date(end_iso)
  seq(start_date, end_date, by = "day")
}

latent_support_from_polls <- function(polls, start_iso, end_iso, parties,
                                      q = 0.1, r = 1.0, use_smoother = TRUE,
                                      impute_parties = character(0),
                                      impute_pct = STIMMUNG_IMPUTE_PCT,
                                      impute_hold_days = STIMMUNG_IMPUTE_HOLD_DAYS) {
  dates <- build_daily_grid(start_iso, end_iso)
  date_strings <- format(dates, "%Y-%m-%d")

  by_date <- split(polls, vapply(polls, function(p) p$publish_date %||% "", character(1)))
  by_date[[""]] <- NULL
  maps_by_date <- lapply(by_date, function(day_polls) lapply(day_polls, poll_to_party_map))
  n_obs_by_date <- vapply(date_strings, function(d) {
    day_polls <- by_date[[d]]
    if (is.null(day_polls)) return(NA_real_)
    length(day_polls)
  }, numeric(1))

  # Last date each imputable party was actually reported (institutes often omit
  # parties below ~3%). Mirrors state-models impute_unreported_parties():
  # unreported parties are held at impute_pct for impute_hold_days after their
  # last report, then drop out (NA) so a vanished party can fall away.
  last_seen <- list()
  if (length(impute_parties) > 0) {
    for (party in impute_parties) {
      seen <- as.Date(character(0))
      for (d in names(maps_by_date)) {
        for (mapped in maps_by_date[[d]]) {
          val <- mapped[[party]]
          if (!is.null(val) && is.finite(val)) {
            seen <- c(seen, as.Date(d))
            break
          }
        }
      }
      if (length(seen) > 0) last_seen[[party]] <- sort(seen)
    }
  }

  series_filtered <- list()
  series_smoothed <- list()
  var_filtered <- list()
  var_smoothed <- list()
  current <- list()

  for (party in parties) {
    seen_dates <- last_seen[[party]]
    y <- vapply(date_strings, function(d) {
      day_maps <- maps_by_date[[d]]
      if (is.null(day_maps)) return(NA_real_)
      day_date <- as.Date(d)
      eligible <- FALSE
      if (!is.null(seen_dates)) {
        prev <- seen_dates[seen_dates <= day_date]
        if (length(prev) > 0 &&
            as.numeric(day_date - max(prev)) <= impute_hold_days) {
          eligible <- TRUE
        }
      }
      vals <- numeric(0)
      for (mapped in day_maps) {
        val <- mapped[[party]]
        if (!is.null(val) && is.finite(val)) {
          vals <- c(vals, val)
        } else if (eligible) {
          vals <- c(vals, impute_pct)
        }
      }
      if (length(vals) == 0) return(NA_real_)
      mean(vals)
    }, numeric(1))

    kf <- smooth_1d(as.list(y), q = q, r = r, n_obs = as.list(n_obs_by_date))
    filtered <- vapply(kf$filtered, function(v) if (is.finite(v)) round(v, 1) else NA_real_, numeric(1))
    smoothed <- vapply(kf$smoothed, function(v) if (is.finite(v)) round(v, 1) else NA_real_, numeric(1))

    series_filtered[[party]] <- filtered
    series_smoothed[[party]] <- smoothed
    var_filtered[[party]] <- kf$filtered_var
    var_smoothed[[party]] <- kf$smoothed_var

    display <- if (use_smoother) smoothed else filtered
    last <- tail(display, 1)
    current[[party]] <- if (is.finite(last)) last else NA_real_
  }

  list(
    dates = date_strings,
    series = list(filtered = series_filtered, smoothed = series_smoothed),
    uncertainty = list(filtered = var_filtered, smoothed = var_smoothed),
    current = current
  )
}

# Time-varying party inclusion ("activity"): for each party and grid day,
# decide whether the party is currently part of the published poll universe.
# The reference window contains all polls of the trailing `window_days`,
# extended backwards to at least the last `min_k` polls (sparse state polling):
#   - a party becomes active once it appears in >= enter_frac of the window,
#   - it exits once its share of the window drops below exit_frac; if the
#     window had to be extended beyond `window_days` (sparse polling), the
#     exit additionally requires that no poll listed the party for
#     `exit_grace_days` (avoids flapping on isolated poll bursts),
#   - between exit_frac and enter_frac the previous state is kept (hysteresis),
#   - before its first appearance it is inactive (no backfill into the past).
# Outside its active window a party is hidden and its share flows into Sonstige.
party_activity_masks <- function(polls, parties, date_strings,
                                 window_days = PARTY_ACTIVITY_WINDOW_DAYS,
                                 min_k = PARTY_ACTIVITY_MIN_K,
                                 enter_frac = PARTY_ACTIVITY_ENTER_FRAC,
                                 exit_frac = PARTY_ACTIVITY_EXIT_FRAC,
                                 exit_grace_days = PARTY_ACTIVITY_EXIT_GRACE_DAYS) {
  n_days <- length(date_strings)
  masks <- lapply(parties, function(p) rep(FALSE, n_days))
  names(masks) <- parties
  if (length(polls) == 0 || n_days == 0) return(masks)

  poll_dates <- vapply(polls, function(p) p$publish_date %||% "", character(1))
  keep <- poll_dates != ""
  polls <- polls[keep]
  poll_dates <- poll_dates[keep]
  if (length(polls) == 0) return(masks)
  ord <- order(poll_dates)
  polls <- polls[ord]
  poll_dates <- poll_dates[ord]

  poll_maps <- lapply(polls, poll_to_party_map)
  presence <- lapply(parties, function(party) {
    vapply(poll_maps, function(m) {
      val <- m[[party]]
      !is.null(val) && is.finite(val)
    }, logical(1))
  })
  names(presence) <- parties

  n_polls <- length(polls)
  grid_days <- as.Date(date_strings)
  poll_days <- as.Date(poll_dates)

  # Window bounds per grid day (party-independent): polls lo..j are considered.
  j_for_day <- integer(n_days)
  lo_for_day <- integer(n_days)
  sparse_day <- logical(n_days)
  j <- 0
  lo <- 1
  for (i in seq_len(n_days)) {
    while (j < n_polls && poll_days[[j + 1]] <= grid_days[[i]]) j <- j + 1
    while (lo <= j && as.numeric(grid_days[[i]] - poll_days[[lo]]) > window_days) lo <- lo + 1
    j_for_day[[i]] <- j
    if (j > 0) {
      lo_ext <- min(lo, max(1, j - min_k + 1))
      lo_for_day[[i]] <- lo_ext
      # Sparse: the trailing-days window alone held fewer than min_k polls,
      # so the window reaches further back than window_days.
      sparse_day[[i]] <- lo_ext < lo
    } else {
      lo_for_day[[i]] <- 0
    }
  }

  for (party in parties) {
    pres <- presence[[party]]
    cum <- cumsum(pres)
    seen_day_idx <- which(pres)
    last_seen_before <- function(j) {
      hits <- seen_day_idx[seen_day_idx <= j]
      if (length(hits) == 0) return(as.Date(NA))
      poll_days[[max(hits)]]
    }
    active <- FALSE
    for (i in seq_len(n_days)) {
      j <- j_for_day[[i]]
      if (j > 0) {
        lo_i <- lo_for_day[[i]]
        n_win <- j - lo_i + 1
        n_present <- cum[[j]] - if (lo_i > 1) cum[[lo_i - 1]] else 0
        frac <- n_present / n_win
        if (frac >= enter_frac) {
          active <- TRUE
        } else if (frac < exit_frac) {
          if (!sparse_day[[i]]) {
            active <- FALSE
          } else {
            last_seen <- last_seen_before(j)
            days_since_seen <- if (is.na(last_seen)) Inf else as.numeric(grid_days[[i]] - last_seen)
            if (days_since_seen > exit_grace_days) active <- FALSE
          }
        }
        # exit_frac <= frac < enter_frac: keep previous state (hysteresis)
      }
      masks[[party]][[i]] <- active
    }
  }

  masks
}

normalize_series_day <- function(day_values, active_parties) {
  out <- list()
  sum_main <- 0

  for (p in active_parties) {
    val <- day_values[[p]]
    if (!is.null(val) && is.finite(val)) {
      out[[p]] <- val
      sum_main <- sum_main + val
    }
  }

  if (sum_main <= 0) {
    out[["Sonstige"]] <- 0
    return(out)
  }
  if (sum_main > 100) {
    factor <- 100 / sum_main
    for (p in names(out)) {
      out[[p]] <- round(out[[p]] * factor, 1)
    }
    out[["Sonstige"]] <- 0
  } else {
    out[["Sonstige"]] <- round(100 - sum_main, 1)
  }
  out
}

apply_inclusion_and_normalize <- function(kalman_result, polls, core_parties, optional_parties,
                                            uncertainty_sigma = 1.0) {
  dates <- kalman_result$dates
  n <- length(dates)
  use_key <- if (USE_SMOOTHER) "smoothed" else "filtered"
  raw_series <- kalman_result$series[[use_key]]
  var_key <- if (USE_SMOOTHER) "smoothed" else "filtered"
  var_series <- kalman_result$uncertainty[[var_key]]

  parties_no_sonstige <- unique(c(core_parties, optional_parties))
  masks <- party_activity_masks(polls, parties_no_sonstige, dates)

  active_on_day <- function(i) {
    parties_no_sonstige[vapply(parties_no_sonstige, function(p) isTRUE(masks[[p]][[i]]), logical(1))]
  }

  # Parties considered part of the current poll universe (active on last day).
  active_current <- if (n > 0) active_on_day(n) else character(0)
  include_optional <- optional_parties[optional_parties %in% active_current]

  normalized <- lapply(seq_len(n), function(i) {
    day_vals <- lapply(names(raw_series), function(p) raw_series[[p]][[i]])
    names(day_vals) <- names(raw_series)
    normalize_series_day(day_vals, active_on_day(i))
  })

  parties_out <- unique(c(core_parties, optional_parties, "Sonstige"))
  series_out <- lapply(parties_out, function(p) {
    vapply(normalized, function(day) day[[p]] %||% NA_real_, numeric(1))
  })
  names(series_out) <- parties_out

  uncertainty_low <- lapply(parties_out, function(p) rep(NA_real_, n))
  names(uncertainty_low) <- parties_out
  uncertainty_high <- lapply(parties_out, function(p) rep(NA_real_, n))
  names(uncertainty_high) <- parties_out

  for (i in seq_len(n)) {
    day_active <- active_on_day(i)
    day_norm <- normalized[[i]]

    sum_raw <- 0
    for (p in day_active) {
      val <- raw_series[[p]][[i]]
      if (is.finite(val)) sum_raw <- sum_raw + val
    }
    scale <- if (sum_raw > 0) 100 / sum_raw else NA_real_

    for (p in day_active) {
      pt <- day_norm[[p]]
      if (is.null(pt) || !is.finite(pt)) next
      vr <- var_series[[p]][[i]]
      if (is.null(vr) || !is.finite(vr) || !is.finite(scale)) next
      half_width <- uncertainty_sigma * sqrt(vr) * scale
      uncertainty_low[[p]][[i]] <- round(max(0, pt - half_width), 1)
      uncertainty_high[[p]][[i]] <- round(min(100, pt + half_width), 1)
    }
  }

  current_day <- if (n > 0) normalized[[n]] else list()
  current <- lapply(parties_out, function(p) current_day[[p]] %||% NA_real_)
  names(current) <- parties_out

  trends <- lapply(parties_out, function(p) {
    if (!identical(p, "Sonstige") && !is.finite(current[[p]])) return(NA_real_)
    vals <- series_out[[p]]
    vals <- vals[is.finite(vals)]
    if (length(vals) < 14) return(NA_real_)
    round(tail(vals, 1) - vals[[length(vals) - 13]], 1)
  })
  names(trends) <- parties_out

  list(
    dates = dates,
    series = series_out,
    current = current,
    trends = trends,
    include_optional = include_optional,
    active_parties = active_current,
    uncertainty_low = uncertainty_low,
    uncertainty_high = uncertainty_high
  )
}
