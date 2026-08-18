#!/usr/bin/env python3
"""Estimate Landtag/AGH district Erst model (pre-election information only).

Formula (lean federal-style OLS):
  resp_E ~ resp_Z_hat + res_l1_E + no_cand_l1

Important: resp_Z_hat is the *projected* district Zweitstimme from the previous
election via proportional swing to the statewide outcome — the same inputs the
live forecast has before election day (lagged district structure + land target).
We do **not** put observed district Zweit of the outcome election on the RHS.

Trains on data/district_train_panel.csv (pooled MV/ST/BE transitions).
Writes data/district_model_coefs.json for district_forecast.py.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from district_forecast import proportional_swing

REPO = Path(__file__).resolve().parents[1]
PANEL = REPO / "data" / "district_train_panel.csv"
OUT = REPO / "data" / "district_model_coefs.json"

TRAIN_PARTIES = ("spd", "afd", "cdu", "linke", "gruene", "fdp")
ALL_PARTIES = TRAIN_PARTIES + ("others",)


def load_panel(path: Path) -> list[dict]:
    rows = []
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(
                {
                    "state": r["state"],
                    "election": int(r["election"]),
                    "wkr": int(r["wkr"]),
                    "party": r["party"],
                    "resp_E": float(r["resp_E"]),
                    "resp_Z": float(r["resp_Z"]),
                    "res_l1_E": float(r["res_l1_E"]),
                    "res_l1_Z": float(r["res_l1_Z"]),
                    "no_cand_l1": int(r["no_cand_l1"]),
                }
            )
    return rows


def _statewide(by_party: dict[str, list[float]]) -> np.ndarray:
    """Unweighted mean across districts (shares already sum to 1 per district)."""
    return np.array(
        [float(np.mean(by_party[p])) if by_party[p] else 0.0 for p in ALL_PARTIES],
        dtype=float,
    )


def add_projected_zweit(rows: list[dict]) -> list[dict]:
    """Replace training Zweit with swing projection from L1 (pre-election info)."""
    # Group full party vectors per district
    districts: dict[tuple[str, int, int], dict[str, dict[str, float]]] = defaultdict(
        lambda: {"resp_Z": {}, "res_l1_Z": {}, "rows": []}
    )
    for r in rows:
        key = (r["state"], r["election"], r["wkr"])
        districts[key]["resp_Z"][r["party"]] = r["resp_Z"]
        districts[key]["res_l1_Z"][r["party"]] = r["res_l1_Z"]
        districts[key]["rows"].append(r)

    # Statewide land target = actual statewide Zweit of outcome election
    # (plays the role of today's land forecast; district Zweit stays projected).
    land_z: dict[tuple[str, int], np.ndarray] = {}
    land_l1: dict[tuple[str, int], np.ndarray] = {}
    by_elec: dict[tuple[str, int], list] = defaultdict(list)
    for key, d in districts.items():
        by_elec[(key[0], key[1])].append(d)
    for elec_key, dist_list in by_elec.items():
        z_lists = {p: [] for p in ALL_PARTIES}
        l1_lists = {p: [] for p in ALL_PARTIES}
        for d in dist_list:
            for p in ALL_PARTIES:
                z_lists[p].append(d["resp_Z"].get(p, 0.0))
                l1_lists[p].append(d["res_l1_Z"].get(p, 0.0))
        land_z[elec_key] = _statewide(z_lists)
        land_l1[elec_key] = _statewide(l1_lists)

    out = []
    for key, d in districts.items():
        elec_key = (key[0], key[1])
        z_l1 = np.array([d["res_l1_Z"].get(p, 0.0) for p in ALL_PARTIES], dtype=float)
        z_hat = proportional_swing(z_l1, land_l1[elec_key], land_z[elec_key])
        for r in d["rows"]:
            if r["party"] not in TRAIN_PARTIES:
                continue
            pi = ALL_PARTIES.index(r["party"])
            rr = dict(r)
            rr["resp_Z_obs"] = r["resp_Z"]
            rr["resp_Z"] = float(z_hat[pi])  # projected — used in regression
            out.append(rr)
    return out


def ols(y: np.ndarray, X: np.ndarray) -> tuple[np.ndarray, np.ndarray, float, np.ndarray]:
    n, k = X.shape
    xtx = X.T @ X
    beta = np.linalg.solve(xtx, X.T @ y)
    fitted = X @ beta
    resid = y - fitted
    dof = max(n - k, 1)
    sigma2 = float(resid @ resid / dof)
    cov = sigma2 * np.linalg.inv(xtx)
    return beta, cov, float(np.sqrt(sigma2)), fitted


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--panel", type=Path, default=PANEL)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    raw = load_panel(args.panel)
    rows = add_projected_zweit(raw)
    if len(rows) < 50:
        raise SystemExit(f"Too few training rows: {len(rows)}")

    y = np.array([r["resp_E"] for r in rows], dtype=float)
    X = np.column_stack(
        [
            np.ones(len(rows)),
            np.array([r["resp_Z"] for r in rows], dtype=float),
            np.array([r["res_l1_E"] for r in rows], dtype=float),
            np.array([r["no_cand_l1"] for r in rows], dtype=float),
        ]
    )
    names = ["intercept", "resp_Z_hat", "res_l1_E", "no_cand_l1"]
    beta, cov, sigma, fitted = ols(y, X)
    mae = float(np.mean(np.abs(y - fitted)))
    rmse = float(np.sqrt(np.mean((y - fitted) ** 2)))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - float(np.sum((y - fitted) ** 2)) / ss_tot if ss_tot > 0 else 0.0

    # How far projected Zweit is from observed (sanity)
    z_err = float(
        np.mean([abs(r["resp_Z"] - r["resp_Z_obs"]) for r in rows])
    )

    groups: dict[tuple[str, int], list[int]] = {}
    for i, r in enumerate(rows):
        groups.setdefault((r["state"], r["election"]), []).append(i)
    loo_abs = []
    for _key, idx in groups.items():
        mask = np.ones(len(rows), dtype=bool)
        mask[idx] = False
        if mask.sum() < 20:
            continue
        b, _, _, _ = ols(y[mask], X[mask])
        pred = X[idx] @ b
        loo_abs.extend(list(np.abs(y[idx] - pred)))
    loo_mae = float(np.mean(loo_abs)) if loo_abs else None

    payload = {
        "formula": "resp_E ~ resp_Z_hat + res_l1_E + no_cand_l1",
        "resp_Z_definition": (
            "proportional swing from res_l1_Z toward actual statewide Zweit "
            "of the outcome election (land target = role of today's forecast; "
            "district Zweit never uses observed outcome-election district results)"
        ),
        "swing": "proportional Zweit (federal-style)",
        "parties_modeled": list(TRAIN_PARTIES),
        "coef_names": ["intercept", "resp_Z", "res_l1_E", "no_cand_l1"],
        "coef": [float(x) for x in beta],
        "vcov": [[float(x) for x in row] for row in cov],
        "sigma": sigma,
        "n": len(rows),
        "n_elections": len(groups),
        "elections": [
            {"state": s, "election": e, "n": len(idx)}
            for (s, e), idx in sorted(groups.items())
        ],
        "fit": {
            "r2": round(r2, 4),
            "mae": round(mae, 4),
            "rmse": round(rmse, 4),
            "mae_z_hat_vs_obs": round(z_err, 4),
        },
        "loo_mae": None if loo_mae is None else round(loo_mae, 4),
        "trained_at": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S"),
        "panel": str(args.panel.relative_to(REPO)),
        "notes": (
            "Pre-election information set: lagged district Erst/Zweit + statewide "
            "land target. RHS Zweit is projected, not observed. "
            "No candidate covariates. ST lags are StaLA comparable %-shares."
        ),
    }
    # Keep coef_names aligned with district_forecast (expects resp_Z slot).
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.out}")
    print("  coef:", {n: round(c, 3) for n, c in zip(names, beta)})
    print(f"  R²={r2:.3f} MAE={mae:.3f} LOO-MAE={loo_mae}  |Zhat−Zobs|={z_err:.3f}")
    for e in payload["elections"]:
        print(f"  train {e['state']} {e['election']}: {e['n']} rows")


if __name__ == "__main__":
    main()
