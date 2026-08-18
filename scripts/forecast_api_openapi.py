"""OpenAPI 3.1 spec for the static Zweitstimme Forecast API."""

from __future__ import annotations

from typing import Any

STATE_CODES = [
    "bb",
    "be",
    "bw",
    "by",
    "hb",
    "he",
    "hh",
    "mv",
    "ni",
    "nw",
    "rp",
    "sh",
    "sl",
    "sn",
    "st",
    "th",
]

INFO_DESCRIPTION = """
Public JSON API for **election-day forecasts**, **posterior draws**, and **Aktuelle Stimmung**.

Static files, CORS-open (`Access-Control-Allow-Origin: *`), **GET only**. No authentication.

This is **not** the polling API for individual surveys. That lives at [api.zweitstimme.org/docs](https://api.zweitstimme.org/docs).

## Concepts

- **Forecast** — model output for election day: point estimates, uncertainty intervals, scenario probabilities, and optionally posterior draws.
- **Stimmung** — Kalman-smoothed latent support by calendar day. Days without a new poll are still present. No seat scenarios.
- **`election`** — names the next relevant election for that scope. It is not the forecast timestamp. The same path can refer to a later cycle.

## Versioning

| Version | Meaning |
|---|---|
| `v1` | Legacy contract from when only federal forecasts existed. Kept for compatibility. |
| `v2` | Current contract: federal and state election-day forecasts, posterior draws, and Stimmung. |
| unversioned `/forecast.json` etc. | Aliases of the `v1` federal files. |

Start at `GET /api/index.json`. Prefer `v2` for new integrations. Federal data exists under both `/api/v1/federal/` (old row shape) and `/api/v2/federal/` (metadata + `fit`/`low`/`high`, same as state).

## Envelope

Versioned endpoints wrap payloads as:

```json
{
  "api_version": "v2",
  "generated_at": "2026-08-18T08:06:53Z",
  "election": { "id": "st_2026-09-06", "name": "Landtagswahl Sachsen-Anhalt", "date": "2026-09-06", "scope": "state", "state_code": "ST" },
  "data": {}
}
```

## Availability

- State forecasts exist only inside the **~90-day window** before election day. Outside that window the path returns **404**.
- After election day the last forecast moves to `/api/v2/federal/archive/` or `/api/v2/state/archive/`.
- Archives start when this API began publishing them; there is no historical backfill.
- `/data/*.json` files used by the website UI are **not** a public contract.

## Units

Watch the unit. Party vote shares in summary forecasts are usually **percentage points**. Posterior draws use **shares from 0 to 1**. Federal `probabilities` / `pred_probabilities` are also 0–1. State scenario `probability` values are **percent 0–100**.

## License

Texts, explanations, and visualizations: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), attribution **zweitstimme.org**. Polling inputs may come from [dawum.de](https://dawum.de) ([ODbL](https://opendatacommons.org/licenses/odbl/)) and [wahlrecht.de](https://www.wahlrecht.de) / the named institutes. No guarantee of availability, completeness, or correctness. Forecasts and Stimmung are model outputs, not official results.
""".strip()


def _ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def _json_content(schema: dict[str, Any], example: Any | None = None) -> dict[str, Any]:
    media: dict[str, Any] = {"schema": schema}
    if example is not None:
        media["example"] = example
    return {"application/json": media}


def _ok(schema: dict[str, Any], description: str = "Successful response", example: Any | None = None) -> dict[str, Any]:
    return {
        "200": {
            "description": description,
            "content": _json_content(schema, example),
        }
    }


def _ok_or_404(schema: dict[str, Any], missing: str) -> dict[str, Any]:
    out = _ok(schema)
    out["404"] = {"description": missing}
    return out


def _get(
    *,
    operation_id: str,
    summary: str,
    description: str,
    tags: list[str],
    schema: dict[str, Any],
    params: list[dict[str, Any]] | None = None,
    example: Any | None = None,
    missing: str | None = None,
    deprecated: bool = False,
) -> dict[str, Any]:
    responses = _ok_or_404(schema, missing) if missing else _ok(schema, example=example)
    if example is not None and "200" in responses:
        responses["200"]["content"]["application/json"]["example"] = example
    op: dict[str, Any] = {
        "operationId": operation_id,
        "summary": summary,
        "description": description,
        "tags": tags,
        "responses": responses,
    }
    if params:
        op["parameters"] = params
    if deprecated:
        op["deprecated"] = True
    return {"get": op}


def _path_param(name: str, description: str, **schema_extra: Any) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string", **schema_extra}
    return {
        "name": name,
        "in": "path",
        "required": True,
        "description": description,
        "schema": schema,
    }


def _code_param() -> dict[str, Any]:
    return _path_param(
        "code",
        "Lowercase German state code, for example `st`, `be`, `mv`.",
        enum=STATE_CODES,
        example="st",
    )


def schemas() -> dict[str, Any]:
    party_map = {
        "type": "object",
        "additionalProperties": {"type": ["number", "null"]},
        "description": "Map of party label → numeric value. Inactive parties may be null.",
        "example": {"CDU/CSU": 20.3, "AfD": 28.0, "SPD": 12.1},
    }
    return {
        "Election": {
            "type": "object",
            "description": "Which election this payload refers to. Re-read it; the same path can name a later cycle.",
            "required": ["id", "name", "date", "scope"],
            "properties": {
                "id": {"type": "string", "example": "st_2026-09-06"},
                "name": {"type": "string", "example": "Landtagswahl Sachsen-Anhalt"},
                "date": {"type": "string", "format": "date", "example": "2026-09-06"},
                "scope": {"type": "string", "enum": ["federal", "state"]},
                "state_code": {
                    "type": ["string", "null"],
                    "description": "Uppercase state code, or null for federal payloads.",
                    "example": "ST",
                },
                "date_is_estimated": {
                    "type": "boolean",
                    "description": "True when the election date is a placeholder, not a scheduled date.",
                },
            },
        },
        "Envelope": {
            "type": "object",
            "description": "Common wrapper for versioned endpoints.",
            "required": ["api_version", "generated_at", "election", "data"],
            "properties": {
                "api_version": {"type": "string", "enum": ["v1", "v2"]},
                "generated_at": {
                    "type": "string",
                    "format": "date-time",
                    "description": "API publish time (UTC). Distinct from the model-run timestamp inside `data`.",
                },
                "election": _ref("Election"),
                "data": {"description": "Endpoint-specific payload."},
                "as_of": {
                    "type": "string",
                    "format": "date",
                    "description": "Present on Stimmung responses: calendar day represented by the payload.",
                },
                "archived": {
                    "type": "boolean",
                    "description": "Present on archive responses.",
                },
            },
        },
        "ApiIndex": {
            "type": "object",
            "description": "Machine-readable catalog of the Forecast API.",
            "properties": {
                "name": {"type": "string"},
                "generated_at": {"type": "string", "format": "date-time"},
                "docs": {"type": "string", "format": "uri"},
                "openapi": {"type": "string"},
                "versions": {"type": "object"},
                "election_envelope": {"type": "object"},
                "legacy_root": {"type": "object"},
                "policy": {"type": "object"},
                "counts": {"type": "object"},
            },
        },
        "FederalIndexData": {
            "type": "object",
            "properties": {
                "description": {"type": "string"},
                "status": {"type": "string", "example": "current"},
                "successor": {"type": "string"},
                "legacy": {"type": "string"},
                "forecast": {"type": "string"},
                "districts": {"type": "string"},
                "draws": {"type": "string"},
                "endpoints": {"type": "array", "items": {"type": "string"}},
                "archive_index": {"type": "string"},
                "archive_count": {"type": "integer"},
                "legacy_redirects": {"type": "object", "additionalProperties": {"type": "string"}},
                "note": {"type": "string"},
            },
        },
        "FederalPartyRow": {
            "type": "object",
            "description": "Legacy `v1` party row. `value`/`y` and interval fields are percentage points. `low`/`high` ≈ 83% interval; `low95`/`high95` ≈ 95%. Prefer `FederalPartyRowV2` on `/api/v2/federal/forecast.json`.",
            "properties": {
                "name": {"type": "string", "example": "CDU/CSU"},
                "name_eng": {"type": "string"},
                "_row": {"type": "string", "description": "Party code such as `cdu` or `afd`.", "example": "cdu"},
                "value": {"type": "number", "description": "Point estimate in percentage points."},
                "y": {"type": "number", "description": "Same as `value` (chart helper)."},
                "x": {"type": "integer"},
                "low": {"type": "number"},
                "high": {"type": "number"},
                "low95": {"type": "number"},
                "high95": {"type": "number"},
                "color": {"type": "string"},
            },
        },
        "FederalPartyRowV2": {
            "type": "object",
            "description": "Current federal party row. Same fields as state forecasts (`party`, `party_code`, `fit`, `low`, `high` in percentage points). `low`/`high` ≈ 83%; `low95`/`high95` ≈ 95% when present.",
            "required": ["party", "party_code", "fit"],
            "properties": {
                "party": {"type": "string", "example": "CDU/CSU"},
                "party_code": {"type": "string", "example": "cdu"},
                "fit": {"type": "number", "example": 29.3},
                "low": {"type": "number", "example": 24.2},
                "high": {"type": "number", "example": 34.5},
                "low95": {"type": "number"},
                "high95": {"type": "number"},
                "name_eng": {"type": "string"},
                "color": {"type": "string"},
            },
        },
        "FederalForecastMetadata": {
            "type": "object",
            "properties": {
                "scope": {"type": "string", "example": "federal"},
                "election_id": {"type": "string"},
                "election_name": {"type": "string"},
                "election_date": {"type": "string", "format": "date"},
                "last_update": {
                    "type": "string",
                    "description": "When this forecast was computed / exported.",
                },
                "asof_date": {
                    "type": "string",
                    "format": "date",
                    "description": "Forecast input-date anchor.",
                },
                "n_draws": {"type": "integer"},
                "draws_path": {
                    "type": "string",
                    "example": "/api/v2/federal/draws.json",
                },
            },
        },
        "FederalForecastData": {
            "type": "object",
            "properties": {
                "metadata": _ref("FederalForecastMetadata"),
                "parties": {"type": "array", "items": _ref("FederalPartyRowV2")},
                "probabilities": _ref("FederalProbabilities"),
            },
        },
        "FederalDistrictsData": {
            "type": "object",
            "properties": {
                "metadata": _ref("FederalForecastMetadata"),
                "districts": {
                    "type": "array",
                    "items": _ref("FederalDistrictRow"),
                },
            },
        },
        "FederalProbabilities": {
            "type": "object",
            "description": "Probabilities as shares from **0 to 1**, not percentages. Keys: `hurdle_*` (clears 5%), `maj_*` (coalition seat majority), `prob_*_largest`, `grundmandat_*`.",
            "additionalProperties": {"type": "number"},
            "example": {
                "hurdle_fdp": 0.144,
                "maj_cdu_csu_spd": 0.609,
                "prob_cdu_csu_largest": 0.921,
            },
        },
        "FederalDistrictRow": {
            "type": "object",
            "description": "District-level first/second-vote forecast row. Large file.",
            "properties": {
                "wkr": {"type": "integer", "description": "Wahlkreis number."},
                "wkr_name": {"type": "string"},
                "land": {"type": "string"},
                "party": {"type": "string"},
                "partei": {"type": "string"},
                "value": {"type": "number", "description": "First-vote point estimate, percentage points."},
                "low": {"type": "number"},
                "high": {"type": "number"},
                "probability": {"type": "number", "description": "Win probability, 0–1."},
                "winner": {"type": ["boolean", "integer", "string", "null"]},
                "zs_value": {"type": "number", "description": "Second-vote (Zweitstimme) estimate."},
                "zs_low": {"type": "number"},
                "zs_high": {"type": "number"},
                "Nachname": {"type": ["string", "null"]},
                "Vornamen": {"type": ["string", "null"]},
            },
        },
        "StateCatalogItem": {
            "type": "object",
            "properties": {
                "state_code": {"type": "string", "example": "ST"},
                "path": {"type": "string", "example": "/api/v2/state/st.json"},
                "draws": {
                    "type": "string",
                    "description": "Present when posterior draws are published.",
                    "example": "/api/v2/state/st/draws.json",
                },
                "active": {"type": "boolean"},
                "election": _ref("Election"),
            },
        },
        "StateIndex": {
            "type": "object",
            "properties": {
                "api_version": {"type": "string", "example": "v2"},
                "generated_at": {"type": "string", "format": "date-time"},
                "description": {"type": "string"},
                "forecast_window_days": {"type": "integer", "example": 90},
                "states": {"type": "array", "items": _ref("StateCatalogItem")},
                "archive_index": {"type": "string"},
                "archive_count": {"type": "integer"},
            },
        },
        "StatePartyRow": {
            "type": "object",
            "description": "`fit`/`low`/`high` are percentage points. `low`/`high` ≈ 83% interval.",
            "required": ["party", "party_code", "fit"],
            "properties": {
                "party": {"type": "string", "example": "CDU"},
                "party_code": {"type": "string", "example": "cdu"},
                "fit": {"type": "number", "example": 23},
                "low": {"type": "number", "example": 17},
                "high": {"type": "number", "example": 29},
            },
        },
        "StateScenarioItem": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "example": "largest_party_afd"},
                "category": {"type": "string", "example": "largest_party"},
                "label_de": {"type": "string", "example": "AfD stärkste Kraft"},
                "probability": {
                    "type": "number",
                    "description": "Percent from 0 to 100, not a 0–1 share.",
                    "example": 98,
                },
            },
        },
        "StateForecastMetadata": {
            "type": "object",
            "properties": {
                "state_code": {"type": "string"},
                "election_id": {"type": "string"},
                "election_name": {"type": "string"},
                "election_date": {"type": "string", "format": "date"},
                "last_poll_date": {
                    "type": "string",
                    "format": "date",
                    "description": "Newest poll included in this forecast.",
                },
                "asof_date": {
                    "type": "string",
                    "format": "date",
                    "description": "Forecast input-date anchor.",
                },
                "last_update": {
                    "type": "string",
                    "description": "When this forecast was computed / exported (UTC).",
                },
                "lead_horizon_days": {
                    "type": "integer",
                    "description": "Days until election used in the model.",
                },
                "n_draws": {"type": "integer", "example": 4000},
                "draws_path": {"type": "string", "example": "/api/v2/state/st/draws.json"},
                "model": {"type": "string"},
                "source_repo": {"type": "string"},
            },
        },
        "StateForecastData": {
            "type": "object",
            "properties": {
                "metadata": _ref("StateForecastMetadata"),
                "parties": {"type": "array", "items": _ref("StatePartyRow")},
                "scenarios": {
                    "type": "object",
                    "properties": {
                        "min_probability_pct": {"type": "number"},
                        "hurdle_pct": {"type": "number"},
                        "items": {"type": "array", "items": _ref("StateScenarioItem")},
                    },
                },
            },
        },
        "StateDraw": {
            "type": "object",
            "description": "One posterior simulation. Values are vote **shares from 0 to 1**, normalized to 1.",
            "additionalProperties": {"type": "number"},
            "example": {"cdu": 0.23, "spd": 0.07, "gru": 0.05, "afd": 0.41, "oth": 0.04},
        },
        "StateDrawsData": {
            "type": "object",
            "description": (
                "Self-contained posterior draws. Timing and model fields sit at "
                "`data` (no nested `metadata` object). `n_draws` / `unit` / "
                "`parties` come once, just above the raw `draws` array. "
                "Regenerated whenever the state forecast is rerun."
            ),
            "properties": {
                "last_update": {
                    "type": "string",
                    "description": "Forecast-run timestamp (UTC). Distinct from envelope `generated_at`.",
                },
                "asof_date": {
                    "type": "string",
                    "format": "date",
                    "description": "Forecast input-date anchor.",
                },
                "last_poll_date": {
                    "type": "string",
                    "format": "date",
                    "description": "Newest poll included in this forecast.",
                },
                "state_code": {"type": "string"},
                "election_id": {"type": "string"},
                "election_name": {"type": "string"},
                "election_date": {"type": "string", "format": "date"},
                "model": {"type": "string"},
                "lead": {"type": "string"},
                "lead_model": {"type": "string"},
                "lead_horizon_days": {"type": "integer"},
                "poll_window_days": {"type": ["integer", "null"]},
                "scenario_config_md5": {"type": "string"},
                "predictor_encoding": {"type": "string"},
                "shares_normalized_to_100": {"type": "boolean"},
                "source_repo": {"type": "string"},
                "summary": {
                    "type": "object",
                    "description": "Published point estimates and ~83% intervals in percentage points, computed from these draws.",
                    "properties": {
                        "parties": {"type": "array", "items": _ref("StatePartyRow")},
                    },
                },
                "forecast_path": {
                    "type": "string",
                    "example": "/api/v2/state/st.json",
                    "description": "Companion summary endpoint for this same run.",
                },
                "normalization": {
                    "type": "string",
                    "example": "shares_sum_to_1",
                    "description": "Each draw's party shares sum to 1.",
                },
                "notes": {"type": "string"},
                "n_draws": {"type": "integer", "example": 4000},
                "unit": {
                    "type": "string",
                    "enum": ["share"],
                    "description": "`share` means 0–1 vote shares, not percentage points.",
                },
                "parties": {
                    "type": "array",
                    "items": {"type": "string"},
                    "example": ["cdu", "spd", "gru", "fdp", "lin", "afd", "bsw", "oth"],
                },
                "draws": {"type": "array", "items": _ref("StateDraw")},
            },
        },
        "StimmungCurrentData": {
            "type": "object",
            "properties": {
                "as_of": {"type": "string", "format": "date"},
                "parties": party_map,
                "uncertainty_low": party_map,
                "uncertainty_high": party_map,
                "trends": {
                    **party_map,
                    "description": "Short-run movement in percentage points.",
                },
                "active_parties": {"type": "array", "items": {"type": "string"}},
                "note": {"type": "string"},
            },
        },
        "StimmungSeriesData": {
            "type": "object",
            "description": "Full daily series. There is no `?date=` query because the API is statically hosted. Index `by_date[YYYY-MM-DD]` locally.",
            "properties": {
                "as_of": {"type": "string", "format": "date"},
                "dates": {"type": "array", "items": {"type": "string", "format": "date"}},
                "series": {
                    "type": "object",
                    "additionalProperties": {"type": "array", "items": {"type": ["number", "null"]}},
                    "description": "Party label → array aligned with `dates`.",
                },
                "by_date": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "object",
                        "properties": {"parties": party_map},
                    },
                    "description": "Calendar date → `{ parties: { … } }`.",
                },
                "current": party_map,
                "trends": party_map,
                "active_parties": {"type": "array", "items": {"type": "string"}},
                "uncertainty_low": party_map,
                "uncertainty_high": party_map,
                "metadata": {"type": "object"},
            },
        },
        "StimmungStateCatalogItem": {
            "type": "object",
            "properties": {
                "state_code": {"type": "string", "example": "ST"},
                "path": {"type": "string", "example": "/api/v2/stimmung/state/st.json"},
                "current": {"type": "string", "example": "/api/v2/stimmung/state/st/current.json"},
                "election": _ref("Election"),
                "as_of": {"type": "string", "format": "date"},
            },
        },
    }


def _envelope_schema(data_name: str) -> dict[str, Any]:
    return {
        "allOf": [
            _ref("Envelope"),
            {
                "type": "object",
                "properties": {"data": _ref(data_name)},
            },
        ]
    }


def paths() -> dict[str, Any]:
    code = _code_param()
    archive_id = _path_param(
        "id",
        "Archive id `{code}_{YYYY-MM-DD}`, for example `st_2021-06-06`.",
        example="st_2021-06-06",
        pattern=r"^[a-z]{2}_\d{4}-\d{2}-\d{2}$",
    )
    federal_date = _path_param(
        "date",
        "Archive date `YYYY-MM-DD`.",
        example="2025-02-23",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )

    return {
        "/api/index.json": _get(
            operation_id="get_api_index_json",
            summary="API discovery",
            description="Catalog of versions, endpoints, archive policy, and OpenAPI URL. Start here.",
            tags=["discovery"],
            schema=_ref("ApiIndex"),
        ),
        "/api/openapi.json": _get(
            operation_id="get_api_openapi_json",
            summary="OpenAPI document",
            description="This specification as JSON.",
            tags=["discovery"],
            schema={"type": "object"},
        ),
        "/api/v2/federal/index.json": _get(
            operation_id="get_v2_federal_index",
            summary="Federal forecast catalog",
            description="Entry point for the current federal (`v2`) contract: forecast, districts, draws, archive. Successor of `/api/v1/federal/`.",
            tags=["federal"],
            schema=_envelope_schema("FederalIndexData"),
        ),
        "/api/v2/federal/forecast.json": _get(
            operation_id="get_v2_federal_forecast",
            summary="Federal party forecast",
            description="Current federal summary: `data.metadata`, `data.parties` (`fit`/`low`/`high` in **percentage points**), and `data.probabilities` (shares **0–1**). Same underlying forecast as `v1`, improved shape.",
            tags=["federal"],
            schema=_envelope_schema("FederalForecastData"),
        ),
        "/api/v2/federal/districts.json": _get(
            operation_id="get_v2_federal_districts",
            summary="Federal district forecast",
            description="Wahlkreis-level first- and second-vote forecast with `metadata`. Large file.",
            tags=["federal"],
            schema=_envelope_schema("FederalDistrictsData"),
            missing="No district forecast published.",
        ),
        "/api/v2/federal/draws.json": _get(
            operation_id="get_v2_federal_draws",
            summary="Federal posterior draws",
            description="Raw posterior simulations (`unit: share`, 0–1) behind the federal summary. Header (`metadata`, `summary` with CIs) comes first; the `draws` array follows. Large file.",
            tags=["federal"],
            schema=_envelope_schema("StateDrawsData"),
            missing="No federal draws published.",
        ),
        "/api/v2/federal/archive/index.json": _get(
            operation_id="get_v2_federal_archive_index",
            summary="Federal archive catalog",
            description="Archived federal forecast runs in the v2 contract. Empty until the pipeline has frozen a cycle.",
            tags=["federal"],
            schema=_ref("Envelope"),
        ),
        "/api/v2/federal/archive/{date}.json": _get(
            operation_id="get_v2_federal_archive_run",
            summary="One archived federal forecast",
            description="Frozen federal forecast for one run date, v2 shape.",
            tags=["federal"],
            schema=_envelope_schema("FederalForecastData"),
            params=[federal_date],
            missing="No archived federal forecast for that date.",
        ),
        "/api/v1/federal/index.json": _get(
            operation_id="get_v1_federal_index",
            summary="Legacy federal catalog",
            description="Entry point for the **legacy** federal-only contract. Prefer `/api/v2/federal/index.json`.",
            tags=["v1"],
            schema=_envelope_schema("FederalIndexData"),
            deprecated=True,
        ),
        "/api/v1/federal/forecast.json": _get(
            operation_id="get_v1_federal_forecast",
            summary="Legacy federal party forecast",
            description="Legacy `data` array of `{value, _row, …}` rows. Prefer `/api/v2/federal/forecast.json` (`fit`/`party_code`). Point estimates are **percentage points**.",
            tags=["v1"],
            schema={
                "allOf": [
                    _ref("Envelope"),
                    {
                        "type": "object",
                        "properties": {
                            "data": {"type": "array", "items": _ref("FederalPartyRow")}
                        },
                    },
                ]
            },
            deprecated=True,
        ),
        "/api/v1/federal/pred_probabilities.json": _get(
            operation_id="get_v1_federal_pred_probabilities",
            summary="Legacy federal scenario probabilities",
            description="`data` is a one-element array of probability maps. Values are **shares from 0 to 1**. Prefer `data.probabilities` on `/api/v2/federal/forecast.json`.",
            tags=["v1"],
            schema={
                "allOf": [
                    _ref("Envelope"),
                    {
                        "type": "object",
                        "properties": {
                            "data": {
                                "type": "array",
                                "items": _ref("FederalProbabilities"),
                            }
                        },
                    },
                ]
            },
            deprecated=True,
        ),
        "/api/v1/federal/forecast_districts.json": _get(
            operation_id="get_v1_federal_forecast_districts",
            summary="Legacy federal district forecast",
            description="Wahlkreis-level first- and second-vote forecast. Prefer `/api/v2/federal/districts.json`. Large file.",
            tags=["v1"],
            schema={
                "allOf": [
                    _ref("Envelope"),
                    {
                        "type": "object",
                        "properties": {
                            "data": {
                                "type": "array",
                                "items": _ref("FederalDistrictRow"),
                            }
                        },
                    },
                ]
            },
            deprecated=True,
        ),
        "/api/v1/federal/archive/index.json": _get(
            operation_id="get_v1_federal_archive_index",
            summary="Legacy federal archive catalog",
            description="Archived federal forecast runs in the v1 contract. Prefer `/api/v2/federal/archive/`.",
            tags=["v1"],
            schema=_ref("Envelope"),
            deprecated=True,
        ),
        "/api/v1/federal/archive/{date}.json": _get(
            operation_id="get_v1_federal_archive_run",
            summary="One archived federal forecast (v1)",
            description="Frozen federal forecast for one run date, legacy row shape.",
            tags=["v1"],
            schema=_ref("Envelope"),
            params=[federal_date],
            missing="No archived federal forecast for that date.",
            deprecated=True,
        ),
        "/api/v2/state/index.json": _get(
            operation_id="get_v2_state_index",
            summary="Active state forecasts",
            description="States currently inside the ~90-day forecast window. Prefer this over hardcoding state codes. Each item includes `path` and, when published, `draws`.",
            tags=["state"],
            schema=_ref("StateIndex"),
        ),
        "/api/v2/state/{code}.json": _get(
            operation_id="get_v2_state_forecast",
            summary="One state forecast",
            description="Summary forecast for one Landtag election: party estimates, intervals, and scenario probabilities. **404** when the state is outside the forecast window.",
            tags=["state"],
            schema=_envelope_schema("StateForecastData"),
            params=[code],
            missing="No active forecast for that state (outside the window, unknown code, or not yet published).",
        ),
        "/api/v2/state/{code}/draws.json": _get(
            operation_id="get_v2_state_draws",
            summary="State posterior draws",
            description="Raw posterior simulations (`unit: share`, 0–1) behind the summary and scenarios. Timing, model, last poll, and published `summary` (with CIs) sit directly on `data`; `n_draws` / `unit` / `parties` come once, then the `draws` array. Regenerated on every state-forecast run. Large file (~4000 draws).",
            tags=["state"],
            schema=_envelope_schema("StateDrawsData"),
            params=[code],
            missing="No draws published for that state.",
        ),
        "/api/v2/state/archive/index.json": _get(
            operation_id="get_v2_state_archive_index",
            summary="State archive catalog",
            description="Frozen Landtag forecasts after election day. Not backfilled for older cycles.",
            tags=["state"],
            schema=_ref("Envelope"),
        ),
        "/api/v2/state/archive/{id}.json": _get(
            operation_id="get_v2_state_archive_forecast",
            summary="One archived state forecast",
            description="Frozen state forecast. May include `archived: true`.",
            tags=["state"],
            schema=_envelope_schema("StateForecastData"),
            params=[archive_id],
            missing="No archived forecast for that id.",
        ),
        "/api/v2/state/archive/{id}/draws.json": _get(
            operation_id="get_v2_state_archive_draws",
            summary="Archived state draws",
            description="Posterior draws that belong to one archived state forecast.",
            tags=["state"],
            schema=_envelope_schema("StateDrawsData"),
            params=[archive_id],
            missing="No archived draws for that id.",
        ),
        "/api/v2/stimmung/federal/current.json": _get(
            operation_id="get_v2_stimmung_federal_current",
            summary="Federal Stimmung, current day",
            description="Kalman latent support for today. Values are **percentage points**. `election` names the next Bundestag election, which may have an estimated date.",
            tags=["stimmung"],
            schema=_envelope_schema("StimmungCurrentData"),
        ),
        "/api/v2/stimmung/federal.json": _get(
            operation_id="get_v2_stimmung_federal_series",
            summary="Federal Stimmung, full series",
            description="Daily federal series. Pick a day with `data.by_date[\"YYYY-MM-DD\"]`. No `?date=` parameter.",
            tags=["stimmung"],
            schema=_envelope_schema("StimmungSeriesData"),
        ),
        "/api/v2/stimmung/state/index.json": _get(
            operation_id="get_v2_stimmung_state_index",
            summary="State Stimmung catalog",
            description="All Länder, including those without an active election-day forecast. Use `path` for the full series and `current` for today.",
            tags=["stimmung"],
            schema=_ref("Envelope"),
        ),
        "/api/v2/stimmung/state/{code}/current.json": _get(
            operation_id="get_v2_stimmung_state_current",
            summary="State Stimmung, current day",
            description="Kalman latent support for one Land, current day.",
            tags=["stimmung"],
            schema=_envelope_schema("StimmungCurrentData"),
            params=[code],
            missing="Unknown state code.",
        ),
        "/api/v2/stimmung/state/{code}.json": _get(
            operation_id="get_v2_stimmung_state_series",
            summary="State Stimmung, full series",
            description="Daily series for one Land. Index `data.by_date[YYYY-MM-DD]` locally.",
            tags=["stimmung"],
            schema=_envelope_schema("StimmungSeriesData"),
            params=[code],
            missing="Unknown state code.",
        ),
        "/forecast.json": _get(
            operation_id="get_legacy_forecast",
            summary="Legacy federal forecast alias",
            description="Alias of `/api/v1/federal/forecast.json`. Enveloped payload, not a bare array.",
            tags=["legacy"],
            schema=_ref("Envelope"),
            deprecated=True,
        ),
        "/pred_probabilities.json": _get(
            operation_id="get_legacy_pred_probabilities",
            summary="Legacy federal probabilities alias",
            description="Alias of `/api/v1/federal/pred_probabilities.json`.",
            tags=["legacy"],
            schema=_ref("Envelope"),
            deprecated=True,
        ),
        "/forecast_districts.json": _get(
            operation_id="get_legacy_forecast_districts",
            summary="Legacy federal districts alias",
            description="Alias of `/api/v1/federal/forecast_districts.json`.",
            tags=["legacy"],
            schema=_ref("Envelope"),
            deprecated=True,
        ),
    }


def openapi_spec() -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Zweitstimme Forecast API",
            "version": "2.0.0",
            "description": INFO_DESCRIPTION,
            "contact": {
                "name": "zweitstimme.org",
                "url": "https://zweitstimme.org",
            },
            "license": {
                "name": "CC BY 4.0",
                "url": "https://creativecommons.org/licenses/by/4.0/",
            },
        },
        "externalDocs": {
            "description": "Polling API (individual surveys)",
            "url": "https://api.zweitstimme.org/docs",
        },
        "servers": [
            {
                "url": "https://zweitstimme.org",
                "description": "Production",
            }
        ],
        "tags": [
            {
                "name": "discovery",
                "description": "Catalog and OpenAPI document",
            },
            {
                "name": "federal",
                "description": "Bundestag election-day forecasts (current `v2` contract)",
            },
            {
                "name": "state",
                "description": "Landtag election-day forecasts and posterior draws (`v2`)",
            },
            {
                "name": "stimmung",
                "description": "Kalman-smoothed daily latent support (federal and Länder)",
            },
            {
                "name": "v1",
                "description": "Legacy federal-only contract. Prefer `/api/v2/federal/`.",
            },
            {
                "name": "legacy",
                "description": "Unversioned root aliases of the federal `v1` contract",
            },
        ],
        "paths": paths(),
        "components": {"schemas": schemas()},
    }
