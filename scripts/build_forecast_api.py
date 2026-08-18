#!/usr/bin/env python3
"""Build versioned static Forecast API JSON under static/api/ (or out/api/).

Writes:
  api/index.json
  api/openapi.json
  api/v1/federal/{index,forecast,pred_probabilities,forecast_districts?}.json
  api/v1/federal/archive/{index,YYYY-MM-DD}.json
  api/v2/federal/{index,forecast,districts,draws?}.json
  api/v2/federal/archive/{index,YYYY-MM-DD}.json
  api/v2/state/{index,st,be,…}.json
  api/v2/state/archive/{index,st_YYYY-MM-DD}.json
  api/v2/stimmung/federal.json
  api/v2/stimmung/federal/current.json
  api/v2/stimmung/state/index.json
  api/v2/stimmung/state/{st,…}.json
  api/v2/stimmung/state/{st,…}/current.json

v1 is the legacy federal-only contract. v2 is the current contract
(federal + state + Stimmung). Unversioned root files alias v1.

Also (unless --no-legacy-aliases):
  _redirects (301 root → /api/v1/federal/…)
  root forecast.json / pred_probabilities.json / forecast_districts.json
  as enveloped content aliases (GitHub Pages has no HTTP redirects).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

# Completed BTW still served from legacy root files while calendar points ahead.
_LEGACY_BTW_2025 = {
    "id": "bund_2025-02-23",
    "name": "Bundestagswahl",
    "date": "2025-02-23",
    "scope": "federal",
    "state_code": None,
    "date_is_estimated": False,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: Path) -> Any | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"warning: could not read {path}: {exc}", file=sys.stderr)
        return None


def _unwrap_api_payload(raw: Any) -> Any:
    """If file was already replaced with an enveloped alias, peel to inner data."""
    if (
        isinstance(raw, dict)
        and raw.get("api_version")
        and "data" in raw
        and "election" in raw
    ):
        return raw["data"]
    return raw


def _openapi_spec() -> dict[str, Any]:
    try:
        from forecast_api_openapi import openapi_spec
    except ImportError:
        import importlib.util

        spec_path = Path(__file__).with_name("forecast_api_openapi.py")
        spec = importlib.util.spec_from_file_location("forecast_api_openapi", spec_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"could not load {spec_path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.openapi_spec()
    return openapi_spec()


def _write_json(path: Path, payload: Any, *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if compact:
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    else:
        text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    path.write_text(text + "\n", encoding="utf-8")
    print(f"  wrote {path}")


def _find_first(name: str, dirs: list[Path]) -> Path | None:
    for d in dirs:
        p = d / name
        if p.is_file():
            return p
    return None


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    text = str(value).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _election_obj(
    *,
    election_id: str,
    name: str,
    election_date: str,
    scope: str,
    state_code: str | None = None,
    date_is_estimated: bool | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": election_id,
        "name": name,
        "date": election_date,
        "scope": scope,
        "state_code": state_code,
    }
    if date_is_estimated is not None:
        out["date_is_estimated"] = date_is_estimated
    return out


def _calendar_elections(calendar: dict | None) -> list[dict]:
    if not isinstance(calendar, dict):
        return []
    return list(calendar.get("elections") or [])


def _federal_from_calendar(calendar: dict | None) -> dict[str, Any] | None:
    for e in _calendar_elections(calendar):
        if e.get("scope") in ("bund", "federal") or (
            e.get("state_code") is None and "Bundestag" in str(e.get("election_name") or "")
        ):
            ed = e.get("election_date")
            if not ed:
                continue
            return _election_obj(
                election_id=f"bund_{ed}",
                name=str(e.get("election_name") or "Bundestagswahl"),
                election_date=str(ed),
                scope="federal",
                state_code=None,
                date_is_estimated=bool(e.get("date_is_estimated")),
            )
    return None


def _state_from_calendar(calendar: dict | None, state_code: str) -> dict[str, Any] | None:
    code = state_code.upper()
    for e in _calendar_elections(calendar):
        if str(e.get("state_code") or "").upper() == code:
            ed = e.get("election_date")
            if not ed:
                continue
            return _election_obj(
                election_id=f"{code.lower()}_{ed}",
                name=str(e.get("election_name") or f"Landtagswahl {code}"),
                election_date=str(ed),
                scope="state",
                state_code=code,
                date_is_estimated=bool(e.get("date_is_estimated")),
            )
    return None


def _next_state_election(calendar: dict | None, state_code: str) -> dict[str, Any] | None:
    """Upcoming (or soonest) Landtag election for Stimmung labeling."""
    code = state_code.upper()
    today = date.today()
    candidates: list[tuple[date, dict[str, Any]]] = []
    for e in _calendar_elections(calendar):
        if str(e.get("state_code") or "").upper() != code:
            continue
        ed = _parse_date(e.get("election_date"))
        if not ed:
            continue
        obj = _election_obj(
            election_id=f"{code.lower()}_{ed.isoformat()}",
            name=str(e.get("election_name") or f"Landtagswahl {code}"),
            election_date=ed.isoformat(),
            scope="state",
            state_code=code,
            date_is_estimated=bool(e.get("date_is_estimated")),
        )
        candidates.append((ed, obj))
    if not candidates:
        return None
    future = [c for c in candidates if c[0] >= today]
    pick = min(future or candidates, key=lambda x: x[0])
    return pick[1]


def _next_federal_election(calendar: dict | None) -> dict[str, Any] | None:
    fed = _federal_from_calendar(calendar)
    return fed


def _resolve_federal_election(
    calendar: dict | None,
    display_mode: dict | None,
    data_dirs: list[Path],
    legacy_dirs: list[Path],
) -> dict[str, Any]:
    """Prefer artifact metadata; fall back to BTW 2025 for legacy root files; else calendar."""
    ff = _find_first("forecast_federal.json", data_dirs)
    if ff:
        payload = _load_json(ff)
        if isinstance(payload, dict):
            meta = payload.get("metadata") or {}
            ed = meta.get("election_date") or meta.get("electionDate")
            if ed:
                return _election_obj(
                    election_id=str(meta.get("election_id") or f"bund_{ed}"),
                    name=str(meta.get("election_name") or "Bundestagswahl"),
                    election_date=str(ed),
                    scope="federal",
                    state_code=None,
                    date_is_estimated=meta.get("date_is_estimated"),
                )

    if isinstance(display_mode, dict):
        federal = display_mode.get("federal") or {}
        if federal.get("forecast_available") and federal.get("election_date"):
            ed = federal["election_date"]
            return _election_obj(
                election_id=f"bund_{ed}",
                name=str(federal.get("election_name") or "Bundestagswahl"),
                election_date=str(ed),
                scope="federal",
                state_code=None,
                date_is_estimated=federal.get("date_is_estimated"),
            )

    last_updated = _federal_last_updated_raw(data_dirs, legacy_dirs)

    cal_fed = _federal_from_calendar(calendar)
    lu_date = _parse_date(last_updated)
    if lu_date is not None:
        cal_date = _parse_date(cal_fed["date"]) if cal_fed else None
        # If the published federal forecast is clearly from the past cycle, tag BTW 2025.
        if cal_date and lu_date < cal_date and lu_date.year <= 2025:
            return dict(_LEGACY_BTW_2025)
        if lu_date.year == 2025 and lu_date <= date(2025, 3, 15):
            return dict(_LEGACY_BTW_2025)

    if cal_fed:
        return cal_fed
    return dict(_LEGACY_BTW_2025)


def _federal_last_updated_raw(
    data_dirs: list[Path], legacy_dirs: list[Path]
) -> str | None:
    for d in legacy_dirs + data_dirs:
        lu = _load_json(d / "last_updated.json")
        if isinstance(lu, dict) and lu.get("last_updated"):
            return str(lu["last_updated"])
        if d.name == "data":
            lu = _load_json(d.parent / "last_updated.json")
            if isinstance(lu, dict) and lu.get("last_updated"):
                return str(lu["last_updated"])
    return None


def _iso_datetime_loose(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "T" in text:
        return text
    try:
        dt = datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return text


def _envelope(
    api_version: str,
    election: dict[str, Any],
    data: Any,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "api_version": api_version,
        "generated_at": _now_iso(),
        "election": election,
        "data": data,
    }
    if extra:
        out.update(extra)
    return out


def _build_by_date(stimmung: dict) -> dict[str, Any]:
    """Date → party shares. Uncertainty stays in parallel series arrays to limit size."""
    dates = stimmung.get("dates") or []
    series = stimmung.get("series") or {}
    by_date: dict[str, Any] = {}
    for i, d in enumerate(dates):
        parties = {
            party: (vals[i] if isinstance(vals, list) and i < len(vals) else None)
            for party, vals in series.items()
        }
        by_date[str(d)] = {"parties": parties}
    return by_date


def _day_uncertainty(stimmung: dict, index: int) -> tuple[dict, dict]:
    unc_low = stimmung.get("uncertainty_low") or {}
    unc_high = stimmung.get("uncertainty_high") or {}
    low = {
        party: (vals[index] if isinstance(vals, list) and index < len(vals) else None)
        for party, vals in unc_low.items()
    }
    high = {
        party: (vals[index] if isinstance(vals, list) and index < len(vals) else None)
        for party, vals in unc_high.items()
    }
    return low, high


def _stimmung_series_payload(stimmung: dict) -> dict[str, Any]:
    """Public series shape: dates, series, by_date, current, trends, active_parties."""
    by_date = _build_by_date(stimmung)
    dates = [str(d) for d in (stimmung.get("dates") or [])]
    as_of = dates[-1] if dates else None
    return {
        "as_of": as_of,
        "dates": dates,
        "series": stimmung.get("series") or {},
        "by_date": by_date,
        "current": stimmung.get("current"),
        "trends": stimmung.get("trends"),
        "active_parties": stimmung.get("active_parties"),
        "uncertainty_low": stimmung.get("uncertainty_low"),
        "uncertainty_high": stimmung.get("uncertainty_high"),
        "metadata": stimmung.get("metadata"),
    }


def _stimmung_current_payload(stimmung: dict) -> dict[str, Any]:
    dates = [str(d) for d in (stimmung.get("dates") or [])]
    as_of = dates[-1] if dates else None
    parties = stimmung.get("current")
    low: dict = {}
    high: dict = {}
    if as_of and dates:
        idx = len(dates) - 1
        day = _build_by_date(stimmung).get(as_of) or {}
        parties = day.get("parties") or parties
        low, high = _day_uncertainty(stimmung, idx)
    return {
        "as_of": as_of,
        "parties": parties,
        "uncertainty_low": low or None,
        "uncertainty_high": high or None,
        "trends": stimmung.get("trends"),
        "active_parties": stimmung.get("active_parties"),
        "note": (
            "Kalman latent support for this calendar day (filled on days without a new poll)."
        ),
    }


# Root path → versioned path (canonical). Used for _redirects + content aliases.
LEGACY_FEDERAL_REDIRECTS = (
    ("/forecast.json", "/api/v1/federal/forecast.json"),
    ("/pred_probabilities.json", "/api/v1/federal/pred_probabilities.json"),
    ("/forecast_districts.json", "/api/v1/federal/forecast_districts.json"),
)


def _load_federal_forecast_data(
    data_dirs: list[Path], legacy_dirs: list[Path]
) -> Any | None:
    src = _find_first("forecast_federal.json", data_dirs)
    if src:
        loaded = _load_json(src)
        if isinstance(loaded, dict):
            if loaded.get("api_version") and "data" in loaded:
                return loaded.get("data")
            if "parties" in loaded:
                return loaded.get("parties")
        if loaded is not None:
            return loaded
    for d in legacy_dirs:
        loaded = _load_json(d / "forecast.json")
        raw = _unwrap_api_payload(loaded)
        if raw is not None:
            return raw
    return None


def build_v1_federal(
    api_root: Path,
    election: dict[str, Any],
    data_dirs: list[Path],
    legacy_dirs: list[Path],
) -> tuple[list[str], dict[str, Any]]:
    """Returns (endpoint paths, map of root filename → enveloped payload for aliases)."""
    endpoints: list[str] = []
    root_aliases: dict[str, Any] = {}
    fed_dir = api_root / "v1" / "federal"

    forecast_data = _load_federal_forecast_data(data_dirs, legacy_dirs)
    if forecast_data is not None:
        env = _envelope("v1", election, forecast_data)
        _write_json(fed_dir / "forecast.json", env)
        endpoints.append("/api/v1/federal/forecast.json")
        root_aliases["forecast.json"] = env

    pred = None
    src = _find_first("pred_probabilities.json", data_dirs + legacy_dirs)
    if src:
        pred = _unwrap_api_payload(_load_json(src))
    if pred is not None:
        env = _envelope("v1", election, pred)
        _write_json(fed_dir / "pred_probabilities.json", env)
        endpoints.append("/api/v1/federal/pred_probabilities.json")
        root_aliases["pred_probabilities.json"] = env

    districts = None
    src = _find_first("forecast_districts.json", data_dirs + legacy_dirs)
    if src:
        districts = _unwrap_api_payload(_load_json(src))
    if districts is not None:
        env = _envelope("v1", election, districts)
        _write_json(fed_dir / "forecast_districts.json", env)
        endpoints.append("/api/v1/federal/forecast_districts.json")
        root_aliases["forecast_districts.json"] = env

    # Federal archive (only files already archived by the pipeline — no backfill).
    archive_items = build_v1_federal_archive(api_root, data_dirs)

    _write_json(
        fed_dir / "index.json",
        _envelope(
            "v1",
            election,
            {
                "description": (
                    "Legacy federal-only contract from when the API published "
                    "Bundestag forecasts only. Prefer /api/v2/federal/."
                ),
                "status": "legacy",
                "successor": "/api/v2/federal/index.json",
                "endpoints": endpoints,
                "archive_index": "/api/v1/federal/archive/index.json",
                "archive_count": len(archive_items),
                "legacy_redirects": {
                    old: new for old, new in LEGACY_FEDERAL_REDIRECTS
                },
                "note": (
                    "Unchanged compatibility layer. Root /forecast.json etc. "
                    "still alias these files. New clients should use "
                    "/api/v2/federal/ (same data, improved contract, plus "
                    "state and Stimmung under /api/v2/)."
                ),
            },
        ),
    )
    return endpoints, root_aliases


def write_legacy_root_aliases(out_root: Path, root_aliases: dict[str, Any]) -> None:
    """Point legacy root URLs at v1: _redirects (CF/Netlify) + enveloped content aliases (GH Pages)."""
    if not root_aliases:
        return
    lines = [
        "# Forecast API — legacy root → /api/v1/federal (301)",
        "# Honored by Cloudflare Pages / Netlify; GitHub Pages uses content aliases below.",
    ]
    for old, new in LEGACY_FEDERAL_REDIRECTS:
        fname = old.lstrip("/")
        if fname in root_aliases:
            lines.append(f"{old} {new} 301")
    redirects_path = out_root / "_redirects"
    redirects_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  wrote {redirects_path}")

    for fname, payload in root_aliases.items():
        _write_json(out_root / fname, payload)


def _federal_source_metadata(data_dirs: list[Path]) -> dict[str, Any]:
    src = _find_first("forecast_federal.json", data_dirs)
    if not src:
        return {}
    loaded = _load_json(src)
    if isinstance(loaded, dict) and isinstance(loaded.get("metadata"), dict):
        return dict(loaded["metadata"])
    return {}


def _federal_parties_v2(rows: Any) -> list[dict[str, Any]]:
    if isinstance(rows, dict) and isinstance(rows.get("parties"), list):
        rows = rows["parties"]
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("party_code") is not None and row.get("fit") is not None:
            out.append(dict(row))
            continue
        fit = row.get("value")
        if fit is None:
            fit = row.get("y")
        party: dict[str, Any] = {
            "party": row.get("name") or row.get("party"),
            "party_code": row.get("_row") or row.get("party_code"),
            "fit": fit,
            "low": row.get("low"),
            "high": row.get("high"),
        }
        for key in ("name_eng", "low95", "high95", "color"):
            if row.get(key) is not None:
                party[key] = row[key]
        out.append(party)
    return out


def _federal_probabilities_v2(pred: Any) -> dict[str, Any] | None:
    if pred is None:
        return None
    if isinstance(pred, list):
        if pred and isinstance(pred[0], dict):
            return pred[0]
        return None
    if isinstance(pred, dict):
        return pred
    return None


def _federal_metadata(
    election: dict[str, Any],
    *,
    extra: dict[str, Any] | None = None,
    last_update: str | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = dict(extra or {})
    meta.setdefault("scope", "federal")
    meta.setdefault("election_id", election.get("id"))
    meta.setdefault("election_name", election.get("name"))
    meta.setdefault("election_date", election.get("date"))
    if last_update:
        meta.setdefault("last_update", last_update)
        meta.setdefault("asof_date", str(last_update)[:10])
    return {k: v for k, v in meta.items() if v is not None}


def _load_federal_draws_payload(
    data_dirs: list[Path], legacy_dirs: list[Path]
) -> dict[str, Any] | None:
    src = _find_first("forecast_federal_draws.json", data_dirs)
    if src:
        parsed = _state_draws_from_file(src)
        if parsed:
            return parsed
    for d in legacy_dirs:
        path = d / "draws.json"
        loaded = _load_json(path)
        raw = _unwrap_api_payload(loaded)
        if isinstance(raw, list) and raw and isinstance(raw[0], dict):
            parties = [k for k in raw[0].keys() if k != "draw"]
            return {
                "n_draws": len(raw),
                "unit": "share",
                "parties": parties,
                "draws": raw,
            }
        if isinstance(raw, dict) and isinstance(raw.get("draws"), list):
            parsed = _state_draws_from_file(path)
            if parsed:
                return parsed
    return None


def build_v2_federal_archive(
    api_root: Path,
    data_dirs: list[Path],
    *,
    last_update: str | None = None,
) -> list[dict[str, Any]]:
    archive_dir = api_root / "v2" / "federal" / "archive"
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    paths: list[Path] = []
    for d in data_dirs:
        paths.extend(sorted(d.glob("archive/forecast_federal_*.json")))
        if (d / "archive").is_dir():
            paths.extend(sorted((d / "archive").glob("forecast_federal_*.json")))

    for path in paths:
        m = re.match(r"forecast_federal_(\d{4}-\d{2}-\d{2})\.json$", path.name)
        if not m:
            continue
        ed = m.group(1)
        if ed in seen:
            continue
        seen.add(ed)
        raw = _unwrap_api_payload(_load_json(path))
        if raw is None:
            continue
        source_meta: dict[str, Any] = {}
        if isinstance(raw, dict) and "parties" in raw and "metadata" in raw:
            parties_raw = raw.get("parties")
            source_meta = dict(raw.get("metadata") or {})
            ed = str(source_meta.get("election_date") or ed)
            name = str(source_meta.get("election_name") or "Bundestagswahl")
        else:
            parties_raw = raw
            name = "Bundestagswahl"
        election = _election_obj(
            election_id=f"bund_{ed}",
            name=name,
            election_date=ed,
            scope="federal",
            state_code=None,
        )
        data = {
            "metadata": _federal_metadata(
                election, extra=source_meta, last_update=last_update
            ),
            "parties": _federal_parties_v2(parties_raw),
        }
        rel = f"{ed}.json"
        _write_json(
            archive_dir / rel,
            _envelope("v2", election, data, extra={"archived": True}),
        )
        items.append(
            {
                "election": election,
                "path": f"/api/v2/federal/archive/{rel}",
                "archived": True,
            }
        )

    _write_json(
        archive_dir / "index.json",
        {
            "api_version": "v2",
            "generated_at": _now_iso(),
            "description": (
                "Archived federal forecasts after election day. "
                "Only elections archived by the pipeline from now on (no backfill)."
            ),
            "forecasts": items,
        },
    )
    return items


def build_v2_federal(
    api_root: Path,
    election: dict[str, Any],
    data_dirs: list[Path],
    legacy_dirs: list[Path],
) -> list[str]:
    """Current federal contract: metadata + parties (fit/low/high), plus districts/draws."""
    endpoints: list[str] = []
    fed_dir = api_root / "v2" / "federal"
    last_update = _iso_datetime_loose(
        _federal_last_updated_raw(data_dirs, legacy_dirs)
    )
    source_meta = _federal_source_metadata(data_dirs)
    parties = _federal_parties_v2(
        _load_federal_forecast_data(data_dirs, legacy_dirs)
    )

    pred = None
    src = _find_first("pred_probabilities.json", data_dirs + legacy_dirs)
    if src:
        pred = _federal_probabilities_v2(_unwrap_api_payload(_load_json(src)))

    districts = None
    src = _find_first("forecast_districts.json", data_dirs + legacy_dirs)
    if src:
        districts = _unwrap_api_payload(_load_json(src))

    draws_payload = _load_federal_draws_payload(data_dirs, legacy_dirs)
    draws_url = "/api/v2/federal/draws.json" if draws_payload else None
    meta = _federal_metadata(
        election, extra=source_meta, last_update=last_update
    )
    if draws_payload:
        meta["draws_path"] = draws_url
        meta["n_draws"] = draws_payload.get("n_draws") or len(
            draws_payload.get("draws") or []
        )

    forecast_data: dict[str, Any] = {
        "metadata": meta,
        "parties": parties,
    }
    if pred is not None:
        forecast_data["probabilities"] = pred
    if parties or pred is not None:
        _write_json(fed_dir / "forecast.json", _envelope("v2", election, forecast_data))
        endpoints.append("/api/v2/federal/forecast.json")

    if isinstance(districts, list):
        _write_json(
            fed_dir / "districts.json",
            _envelope(
                "v2",
                election,
                {"metadata": dict(meta), "districts": districts},
            ),
            compact=True,
        )
        endpoints.append("/api/v2/federal/districts.json")

    if draws_payload:
        enriched = _enrich_state_draws(
            draws_payload,
            forecast_data=forecast_data,
            forecast_path="/api/v2/federal/forecast.json",
        )
        _write_json(
            fed_dir / "draws.json",
            _envelope("v2", election, enriched),
            compact=True,
        )
        endpoints.append(draws_url)

    archive_items = build_v2_federal_archive(
        api_root, data_dirs, last_update=last_update
    )

    catalog: dict[str, Any] = {
        "description": (
            "Federal (Bundestag) election-day forecasts, current (v2) contract."
        ),
        "status": "current",
        "forecast": "/api/v2/federal/forecast.json",
        "archive_index": "/api/v2/federal/archive/index.json",
        "archive_count": len(archive_items),
        "legacy": "/api/v1/federal/index.json",
        "endpoints": endpoints,
        "note": (
            "Same underlying federal forecast as v1, with the improved envelope: "
            "metadata plus parties as fit/low/high (percentage points). "
            "Probabilities stay 0–1. Prefer this over /api/v1/federal/."
        ),
    }
    if "/api/v2/federal/districts.json" in endpoints:
        catalog["districts"] = "/api/v2/federal/districts.json"
    if draws_url:
        catalog["draws"] = draws_url
    _write_json(fed_dir / "index.json", _envelope("v2", election, catalog))
    return endpoints


def _state_payload_from_file(
    path: Path, calendar: dict | None
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return None
    # archived or active may already be enveloped
    if payload.get("api_version") and "data" in payload:
        inner = payload["data"]
        election = payload.get("election") or {}
        if isinstance(inner, dict):
            return election if isinstance(election, dict) else {}, inner
        return None
    meta = dict(payload.get("metadata") or {})
    m = re.search(r"forecast_state_([a-z]{2})(?:_(\d{4}-\d{2}-\d{2}))?\.json$", path.name)
    code_lower = (m.group(1) if m else str(meta.get("state_code") or "xx")).lower()
    state_code = str(meta.get("state_code") or code_lower.upper()).upper()
    cal = _state_from_calendar(calendar, state_code)
    election_date = str(
        meta.get("election_date")
        or (m.group(2) if m and m.group(2) else None)
        or (cal or {}).get("date")
        or ""
    )
    election_name = str(
        meta.get("election_name")
        or (cal or {}).get("name")
        or f"Landtagswahl {state_code}"
    )
    election_id = str(
        meta.get("election_id")
        or (cal or {}).get("id")
        or f"{code_lower}_{election_date}"
    )
    meta["election_name"] = election_name
    meta["election_date"] = election_date
    meta["election_id"] = election_id
    election = _election_obj(
        election_id=election_id,
        name=election_name,
        election_date=election_date,
        scope="state",
        state_code=state_code,
        date_is_estimated=(cal or {}).get("date_is_estimated"),
    )
    data = {
        "metadata": meta,
        "parties": payload.get("parties") or [],
        "scenarios": payload.get("scenarios"),
    }
    return election, data


_DRAWS_NOTES = (
    "Each draw is a posterior predictive vote-share vector (0–1), "
    "normalized so party shares sum to 1. summary.parties repeats the "
    "published point estimates and ~83% interval in percentage points, "
    "computed from these draws."
)


_DRAWS_TIMING_KEYS = ("last_update", "asof_date", "last_poll_date")
# Former metadata fields, minus ones that already live elsewhere on this payload.
_DRAWS_FLAT_META_KEYS = (
    "state_code",
    "election_id",
    "election_name",
    "election_date",
    "model",
    "lead",
    "lead_model",
    "lead_horizon_days",
    "poll_window_days",
    "scenario_config_md5",
    "predictor_encoding",
    "shares_normalized_to_100",
    "source_repo",
)
_DRAWS_TAIL_KEYS = (
    "summary",
    "forecast_path",
    "normalization",
    "notes",
    "n_draws",
    "unit",
    "parties",
    "draws",
)
# Do not copy these out of nested metadata: they duplicate header/tail fields,
# or (draws_path) just point at this file.
_DRAWS_SKIP_FROM_META = frozenset(
    {
        "metadata",
        "n_draws",
        "draws_path",
        "parties",
        "draws",
        "summary",
        "unit",
        "forecast_path",
        "normalization",
        "notes",
        *_DRAWS_TIMING_KEYS,
    }
)


def _flatten_draws_meta(data: dict[str, Any], meta: dict[str, Any] | None) -> None:
    """Lift forecast fields onto data; keep last_update / dates only at the top."""
    if not isinstance(meta, dict):
        return
    for key in _DRAWS_TIMING_KEYS:
        if data.get(key) is None and meta.get(key) is not None:
            data[key] = meta[key]
    for key, value in meta.items():
        if key in _DRAWS_SKIP_FROM_META:
            continue
        if data.get(key) is None and value is not None:
            data[key] = value
    data.pop("metadata", None)


def _state_draws_from_file(path: Path) -> dict[str, Any] | None:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return None
    inner = payload.get("data") if payload.get("api_version") and "data" in payload else payload
    if not isinstance(inner, dict):
        return None
    draws = inner.get("draws")
    if not isinstance(draws, list) or not draws:
        return None
    parties = inner.get("parties")
    if not parties and isinstance(draws[0], dict):
        parties = [k for k in draws[0].keys() if k != "draw"]
    out: dict[str, Any] = {}
    for key in _DRAWS_TIMING_KEYS:
        if inner.get(key):
            out[key] = inner[key]
    _flatten_draws_meta(
        out, inner.get("metadata") if isinstance(inner.get("metadata"), dict) else None
    )
    for key, value in inner.items():
        if key in ("metadata", "draws", "n_draws", "unit", "parties", "summary") or key in out:
            continue
        if value is not None:
            out[key] = value
    summary = inner.get("summary")
    if isinstance(summary, dict) and summary:
        out["summary"] = summary
    for key in ("forecast_path", "normalization", "notes"):
        if inner.get(key):
            out[key] = inner[key]
    out["n_draws"] = int(inner.get("n_draws") or len(draws))
    out["unit"] = inner.get("unit") or "share"
    out["parties"] = parties or []
    out["draws"] = draws
    return out


def _enrich_state_draws(
    data: dict[str, Any],
    *,
    forecast_data: dict[str, Any] | None = None,
    forecast_path: str | None = None,
) -> dict[str, Any]:
    """Make draws self-contained: timing, model, last poll, and summary + CIs."""
    forecast_meta = None
    forecast_parties = None
    if isinstance(forecast_data, dict):
        if isinstance(forecast_data.get("metadata"), dict):
            forecast_meta = forecast_data["metadata"]
        if isinstance(forecast_data.get("parties"), list):
            forecast_parties = forecast_data["parties"]

    nested = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    merged: dict[str, Any] = dict(forecast_meta or {})
    merged.update({k: v for k, v in nested.items() if v is not None})
    _flatten_draws_meta(data, merged)

    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    if forecast_parties:
        summary["parties"] = forecast_parties
    if summary:
        data["summary"] = summary

    if forecast_path:
        data["forecast_path"] = forecast_path
    data.setdefault("normalization", "shares_sum_to_1")
    data.setdefault("notes", _DRAWS_NOTES)
    return _order_state_draws_payload(data)


_DRAWS_KEY_ORDER = _DRAWS_TIMING_KEYS + _DRAWS_FLAT_META_KEYS + _DRAWS_TAIL_KEYS


def _order_state_draws_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Timing + model fields first, raw simulations last — prefix is readable."""
    ordered: dict[str, Any] = {}
    tail = set(_DRAWS_TAIL_KEYS)
    for key in _DRAWS_KEY_ORDER:
        if key in data and key not in tail:
            ordered[key] = data[key]
    for key, value in data.items():
        if key not in ordered and key not in tail:
            ordered[key] = value
    for key in _DRAWS_TAIL_KEYS:
        if key in data:
            ordered[key] = data[key]
    return ordered


def _write_state_draws(
    api_root: Path,
    election: dict[str, Any],
    draws_file: Path | None,
    dest_rel: Path,
    extra: dict[str, Any] | None = None,
    *,
    forecast_data: dict[str, Any] | None = None,
    forecast_path: str | None = None,
) -> str | None:
    if draws_file is None or not draws_file.is_file():
        return None
    data = _state_draws_from_file(draws_file)
    if not data:
        return None
    data = _enrich_state_draws(
        data, forecast_data=forecast_data, forecast_path=forecast_path
    )
    env = _envelope("v2", election, data, extra=extra)
    _write_json(api_root / dest_rel, env, compact=True)
    return "/api/" + dest_rel.as_posix()


def build_v1_federal_archive(
    api_root: Path, data_dirs: list[Path]
) -> list[dict[str, Any]]:
    """Expose pipeline archive/forecast_federal_*.json — no historical backfill."""
    archive_dir = api_root / "v1" / "federal" / "archive"
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    paths: list[Path] = []
    for d in data_dirs:
        paths.extend(sorted(d.glob("archive/forecast_federal_*.json")))
        paths.extend(sorted((d / "archive").glob("forecast_federal_*.json")) if (d / "archive").is_dir() else [])

    for path in paths:
        m = re.match(r"forecast_federal_(\d{4}-\d{2}-\d{2})\.json$", path.name)
        if not m:
            continue
        ed = m.group(1)
        if ed in seen:
            continue
        seen.add(ed)
        raw = _unwrap_api_payload(_load_json(path))
        if raw is None:
            continue
        if isinstance(raw, dict) and "parties" in raw and "metadata" in raw:
            data = raw.get("parties")
            meta = raw.get("metadata") or {}
            ed = str(meta.get("election_date") or ed)
            name = str(meta.get("election_name") or "Bundestagswahl")
        else:
            data = raw
            name = "Bundestagswahl"
        election = _election_obj(
            election_id=f"bund_{ed}",
            name=name,
            election_date=ed,
            scope="federal",
            state_code=None,
        )
        rel = f"{ed}.json"
        _write_json(archive_dir / rel, _envelope("v1", election, data))
        items.append(
            {
                "election": election,
                "path": f"/api/v1/federal/archive/{rel}",
                "archived": True,
            }
        )

    _write_json(
        archive_dir / "index.json",
        {
            "api_version": "v1",
            "generated_at": _now_iso(),
            "description": (
                "Archived federal forecasts after election day. "
                "Only elections archived by the pipeline from now on (no backfill)."
            ),
            "forecasts": items,
        },
    )
    return items


def build_v2_state(
    api_root: Path,
    calendar: dict | None,
    data_dirs: list[Path],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    state_dir = api_root / "v2" / "state"
    index_items: list[dict[str, Any]] = []
    seen: set[str] = set()

    paths: list[Path] = []
    for d in data_dirs:
        paths.extend(sorted(d.glob("forecast_state_*.json")))

    for path in paths:
        m = re.match(r"forecast_state_([a-z]{2})\.json$", path.name)
        if not m:
            continue
        code_lower = m.group(1)
        if code_lower in seen:
            continue
        seen.add(code_lower)
        parsed = _state_payload_from_file(path, calendar)
        if not parsed:
            continue
        election, data = parsed
        draws_file = _find_first(f"forecast_state_{code_lower}_draws.json", data_dirs)
        draws_url = _write_state_draws(
            api_root,
            election,
            draws_file,
            Path("v2") / "state" / code_lower / "draws.json",
            forecast_data=data,
            forecast_path=f"/api/v2/state/{code_lower}.json",
        )
        if draws_url:
            meta = data.get("metadata")
            if isinstance(meta, dict):
                meta["draws_path"] = draws_url
                meta["n_draws"] = meta.get("n_draws")
        _write_json(state_dir / f"{code_lower}.json", _envelope("v2", election, data))
        item = {
            "state_code": election.get("state_code"),
            "path": f"/api/v2/state/{code_lower}.json",
            "election": election,
            "active": True,
        }
        if draws_url:
            item["draws"] = draws_url
        index_items.append(item)

    archive_items = build_v2_state_archive(api_root, calendar, data_dirs)

    _write_json(
        state_dir / "index.json",
        {
            "api_version": "v2",
            "generated_at": _now_iso(),
            "description": (
                "Active state (Landtag) forecasts within the ~90-day window before election day. "
                "Past elections (once archived by the pipeline) are under /api/v2/state/archive/."
            ),
            "forecast_window_days": 90,
            "states": index_items,
            "archive_index": "/api/v2/state/archive/index.json",
            "archive_count": len(archive_items),
        },
    )
    return index_items, archive_items


def build_v2_state_archive(
    api_root: Path,
    calendar: dict | None,
    data_dirs: list[Path],
) -> list[dict[str, Any]]:
    """Query archived state forecasts going forward — no backfill of past elections."""
    archive_dir = api_root / "v2" / "state" / "archive"
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Prefer display_mode.archive.forecasts catalog when present
    dm = None
    dm_path = _find_first("display_mode.json", data_dirs)
    if dm_path:
        dm = _load_json(dm_path)
    catalog = []
    if isinstance(dm, dict):
        catalog = list((dm.get("archive") or {}).get("forecasts") or [])

    paths: list[Path] = []
    for d in data_dirs:
        arch = d / "archive"
        if arch.is_dir():
            paths.extend(sorted(arch.glob("forecast_state_*.json")))

    # Map path by basename for catalog lookup
    by_name = {p.name: p for p in paths}

    def add_from_path(path: Path, archived_at: str | None = None) -> None:
        m = re.match(
            r"forecast_state_([a-z]{2})_(\d{4}-\d{2}-\d{2})\.json$", path.name
        )
        if not m:
            return
        key = f"{m.group(1)}_{m.group(2)}"
        if key in seen:
            return
        parsed = _state_payload_from_file(path, calendar)
        if not parsed:
            return
        seen.add(key)
        election, data = parsed
        rel = f"{key}.json"
        draws_file = path.with_name(f"forecast_state_{key}_draws.json")
        if not draws_file.is_file():
            draws_file = _find_first(f"forecast_state_{key}_draws.json", data_dirs)
        draws_url = _write_state_draws(
            api_root,
            election,
            draws_file,
            Path("v2") / "state" / "archive" / key / "draws.json",
            extra={"archived": True},
            forecast_data=data,
            forecast_path=f"/api/v2/state/archive/{rel}",
        )
        if draws_url:
            meta = data.get("metadata")
            if isinstance(meta, dict):
                meta["draws_path"] = draws_url
        env = _envelope("v2", election, data, extra={"archived": True})
        if archived_at:
            env["archived_at"] = archived_at
        _write_json(archive_dir / rel, env)
        item = {
            "state_code": election.get("state_code"),
            "path": f"/api/v2/state/archive/{rel}",
            "election": election,
            "archived": True,
            "archived_at": archived_at,
        }
        if draws_url:
            item["draws"] = draws_url
        items.append(item)

    for entry in catalog:
        if not isinstance(entry, dict):
            continue
        if entry.get("scope") not in ("state", None) and entry.get("state_code") is None:
            continue
        ff = str(entry.get("forecast_file") or "")
        name = Path(ff).name
        path = by_name.get(name)
        if path is None:
            # try resolve relative to data dirs
            for d in data_dirs:
                cand = d / ff
                if cand.is_file():
                    path = cand
                    break
        if path is None:
            continue
        add_from_path(path, archived_at=entry.get("archived_at"))

    # Any archive files not listed in display_mode
    for path in paths:
        add_from_path(path)

    _write_json(
        archive_dir / "index.json",
        {
            "api_version": "v2",
            "generated_at": _now_iso(),
            "description": (
                "Archived Landtag forecasts (frozen after election day). "
                "Populated going forward by the pipeline; past elections are not backfilled."
            ),
            "forecasts": items,
        },
    )
    return items


def build_v2_stimmung(
    api_root: Path,
    calendar: dict | None,
    data_dirs: list[Path],
) -> dict[str, Any]:
    stim_root = api_root / "v2" / "stimmung"
    summary: dict[str, Any] = {"federal": None, "states": []}

    federal_raw = None
    src = _find_first("stimmung_federal.json", data_dirs)
    if src:
        federal_raw = _load_json(src)

    fed_election = _next_federal_election(calendar) or dict(_LEGACY_BTW_2025)
    if isinstance(federal_raw, dict) and federal_raw.get("dates"):
        series = _stimmung_series_payload(federal_raw)
        current = _stimmung_current_payload(federal_raw)
        _write_json(
            stim_root / "federal.json",
            _envelope("v2", fed_election, series, extra={"as_of": series.get("as_of")}),
            compact=True,
        )
        _write_json(
            stim_root / "federal" / "current.json",
            _envelope("v2", fed_election, current, extra={"as_of": current.get("as_of")}),
        )
        summary["federal"] = {
            "path": "/api/v2/stimmung/federal.json",
            "current": "/api/v2/stimmung/federal/current.json",
            "election": fed_election,
            "as_of": series.get("as_of"),
        }

    states_raw = None
    src = _find_first("stimmung_states.json", data_dirs)
    if src:
        states_raw = _load_json(src)

    state_items: list[dict[str, Any]] = []
    states_map = {}
    if isinstance(states_raw, dict):
        states_map = states_raw.get("states") or {}

    for state_code, stimmung in sorted(states_map.items()):
        if not isinstance(stimmung, dict) or not stimmung.get("dates"):
            continue
        code = str(state_code).upper()
        code_lower = code.lower()
        election = _next_state_election(calendar, code) or _election_obj(
            election_id=f"{code_lower}_unknown",
            name=f"Landtagswahl {code}",
            election_date="",
            scope="state",
            state_code=code,
        )
        series = _stimmung_series_payload(stimmung)
        current = _stimmung_current_payload(stimmung)
        _write_json(
            stim_root / "state" / f"{code_lower}.json",
            _envelope("v2", election, series, extra={"as_of": series.get("as_of")}),
            compact=True,
        )
        _write_json(
            stim_root / "state" / code_lower / "current.json",
            _envelope("v2", election, current, extra={"as_of": current.get("as_of")}),
        )
        state_items.append(
            {
                "state_code": code,
                "path": f"/api/v2/stimmung/state/{code_lower}.json",
                "current": f"/api/v2/stimmung/state/{code_lower}/current.json",
                "election": election,
                "as_of": series.get("as_of"),
            }
        )

    _write_json(
        stim_root / "state" / "index.json",
        {
            "api_version": "v2",
            "generated_at": _now_iso(),
            "description": (
                "Aktuelle Stimmung (Kalman) per Land. Daily series includes days "
                "without a new poll. Use data.by_date[YYYY-MM-DD] for a single day."
            ),
            "states": state_items,
        },
    )
    summary["states"] = state_items
    return summary


def build(
    api_root: Path,
    data_dirs: list[Path],
    legacy_dirs: list[Path],
    *,
    out_root: Path | None = None,
    write_legacy_aliases: bool = True,
) -> None:
    data_dirs = [d for d in data_dirs if d.is_dir()]
    legacy_dirs = [d for d in legacy_dirs if d.is_dir()]

    calendar = None
    cal_path = _find_first("election_calendar.json", data_dirs)
    if cal_path:
        calendar = _load_json(cal_path)

    display_mode = None
    dm_path = _find_first("display_mode.json", data_dirs)
    if dm_path:
        display_mode = _load_json(dm_path)

    print(f"Building Forecast API → {api_root}")
    if api_root.exists():
        import shutil

        shutil.rmtree(api_root)
    api_root.mkdir(parents=True, exist_ok=True)

    federal_election = _resolve_federal_election(
        calendar, display_mode, data_dirs, legacy_dirs
    )
    v1_eps, root_aliases = build_v1_federal(
        api_root, federal_election, data_dirs, legacy_dirs
    )
    v2_fed_eps = build_v2_federal(
        api_root, federal_election, data_dirs, legacy_dirs
    )
    state_items, archive_items = build_v2_state(api_root, calendar, data_dirs)
    stim_summary = build_v2_stimmung(api_root, calendar, data_dirs)

    if write_legacy_aliases and out_root is not None:
        write_legacy_root_aliases(out_root, root_aliases)

    _write_json(api_root / "openapi.json", _openapi_spec())

    _write_json(
        api_root / "index.json",
        {
            "name": "Zweitstimme Forecast API",
            "generated_at": _now_iso(),
            "docs": "https://zweitstimme.org/docs/api/",
            "openapi": "/api/openapi.json",
            "versions": {
                "v1": {
                    "status": "legacy",
                    "description": (
                        "Legacy contract from when only federal forecasts existed. "
                        "Unchanged for compatibility. Prefer v2."
                    ),
                    "index": "/api/v1/federal/index.json",
                    "archive_index": "/api/v1/federal/archive/index.json",
                    "successor": "/api/v2/federal/index.json",
                    "endpoints": v1_eps,
                },
                "v2": {
                    "status": "current",
                    "description": (
                        "Current contract: federal and state election-day forecasts, "
                        "posterior draws, and Aktuelle Stimmung."
                    ),
                    "federal_index": "/api/v2/federal/index.json",
                    "federal_archive_index": "/api/v2/federal/archive/index.json",
                    "state_index": "/api/v2/state/index.json",
                    "state_archive_index": "/api/v2/state/archive/index.json",
                    "stimmung_federal": "/api/v2/stimmung/federal.json",
                    "stimmung_state_index": "/api/v2/stimmung/state/index.json",
                    "forecast_window_days": 90,
                },
            },
            "election_envelope": {
                "fields": ["id", "name", "date", "scope", "state_code"],
                "note": "Every versioned response includes an election object naming the vote.",
            },
            "legacy_root": {
                "note": (
                    "Root /forecast.json etc. redirect to /api/v1/federal/* "
                    "(HTTP 301 via _redirects where supported; otherwise same enveloped JSON)."
                ),
                "redirects": {old: new for old, new in LEGACY_FEDERAL_REDIRECTS},
            },
            "policy": {
                "active_forecast_window_days": 90,
                "archive": (
                    "After election day, forecasts move to /api/v2/federal/archive/ "
                    "and /api/v2/state/archive/ (v1 federal archive remains for the "
                    "legacy contract). No backfill of earlier elections."
                ),
            },
            "counts": {
                "v1_federal_endpoints": len(v1_eps),
                "v2_federal_endpoints": len(v2_fed_eps),
                "v2_state_forecasts": len(state_items),
                "v2_state_archive": len(archive_items),
                "v2_stimmung_states": len(stim_summary.get("states") or []),
            },
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Directory that will contain api/ (usually …/static or gh-pages root)",
    )
    parser.add_argument(
        "--data",
        type=Path,
        action="append",
        default=[],
        help="Directory with pipeline JSON (output/, static/data/, …). Repeatable.",
    )
    parser.add_argument(
        "--legacy-static",
        type=Path,
        action="append",
        default=[],
        help="Hugo static/ root with legacy /forecast.json etc. Repeatable.",
    )
    parser.add_argument(
        "--no-legacy-aliases",
        action="store_true",
        help="Do not write root /forecast.json aliases or _redirects",
    )
    args = parser.parse_args()

    data_dirs = list(args.data) if args.data else []
    legacy_dirs = list(args.legacy_static) if args.legacy_static else []
    if not data_dirs:
        print("error: pass at least one --data directory", file=sys.stderr)
        return 2

    api_root = args.out / "api"
    build(
        api_root,
        data_dirs,
        legacy_dirs,
        out_root=args.out,
        write_legacy_aliases=not args.no_legacy_aliases,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
