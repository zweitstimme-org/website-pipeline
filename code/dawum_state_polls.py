"""Scrape Landtag polls from the official DAWUM dump (api.dawum.de).

Parliament_ID maps unambiguously to FastTrack scopes. Used while the polling
API mis-tags / drops DAWUM state rows (see docs/POLLING_API_SCOPE.md).
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any

import requests

logger = logging.getLogger(__name__)

DAWUM_API_URL = "https://api.dawum.de/"

# Bundestag (0) and EU (17) omitted — only Landtage with a clear catalog id.
DAWUM_PARLIAMENT_TO_SCOPE: dict[str, str] = {
    "1": "bw",
    "2": "by",
    "3": "be",
    "4": "bb",
    "5": "hb",
    "6": "hh",
    "7": "he",
    "8": "mv",
    "9": "ni",
    "10": "nrw",
    "11": "rp",
    "12": "sl",
    "13": "sn",
    "14": "st",
    "15": "sh",
    "16": "th",
}

DAWUM_PARTY_SHORTCUT_TO_KEY: dict[str, str] = {
    "AfD": "AFD",
    "Grüne": "GRUENE",
    "BSW": "BSW",
    "CDU/CSU": "CDU_CSU",
    "CDU": "CDU",
    "CSU": "CSU",
    "Linke": "LINKE",
    "FDP": "FDP",
    "SPD": "SPD",
    "Freie Wähler": "FREIE_WAEHLER",
    "BVB/FW": "FREIE_WAEHLER",
    "SSW": "SSW",
    "Piraten": "PIRATEN",
    "Sonstige": "SONSTIGE",
}

DAWUM_INSTITUTE_NAME_TO_KEY: dict[str, str] = {
    "Infratest dimap": "INFRATEST",
    "Infratest Dimap": "INFRATEST",
    "INSA": "INSA",
    "Civey": "CIVEY",
    "Forsa": "FORSA",
    "Forschungsgruppe Wahlen": "FORSCHUNGSGRUPPE_WAHLEN",
    "Allensbach": "ALLENSBACH",
    "GMS": "GMS",
    "Verian": "VERIAN",
    "YouGov": "YOUGOV",
}


@lru_cache(maxsize=1)
def fetch_dawum_dump(url: str = DAWUM_API_URL) -> dict[str, Any]:
    response = requests.get(
        url,
        timeout=120,
        headers={"User-Agent": "zweitstimme-website-pipeline/1.0"},
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Unexpected DAWUM API payload")
    return payload


def institute_name_to_key(name: str | None) -> str:
    trimmed = (name or "").strip()
    if trimmed in DAWUM_INSTITUTE_NAME_TO_KEY:
        return DAWUM_INSTITUTE_NAME_TO_KEY[trimmed]
    raw = re.sub(r"[^A-Za-z0-9]+", "_", trimmed).strip("_").upper()
    if raw.startswith("INFRATEST"):
        return "INFRATEST"
    return raw or "UNKNOWN"


def canonicalize_institute_key(key_or_name: str | None) -> str:
    raw = (key_or_name or "").strip()
    if not raw:
        return ""
    if raw in DAWUM_INSTITUTE_NAME_TO_KEY:
        return DAWUM_INSTITUTE_NAME_TO_KEY[raw]
    key = re.sub(r"[^A-Za-z0-9]+", "_", raw).strip("_").upper()
    if key.startswith("INFRATEST"):
        return "INFRATEST"
    return key


# Mirror polling-api validation.toml / public_policy.yaml (consumer-side).
QC_SUM_TOLERANCE = 2.0
QC_JUMP_THRESHOLD = 4.0
QC_RESPONDENTS_DEFAULT = (500, 6000)
MATCH_DATE_WINDOW_DAYS = 7
MATCH_MAX_PARTY_DELTA = 1.0
MATCH_MAX_TOTAL_DELTA = 1.5
MATCH_PARTIES = ("SPD", "AFD")

METHOD_NAME_TO_KEY = {
    "Online": "ONLINE",
    "Telefonisch": "TELEFONISCH",
    "Telefon & Online": "TELEFON_ONLINE",
    "Persönlich": "PERSOENLICH",
    "Persönlich & Online": "PERSOENLICH_ONLINE",
    "Unbekannt": "UNBEKANNT",
}

RESPONDENT_LIMITS = {
    "ONLINE": (500, 6000),
    "TELEFONISCH": (700, 4000),
    "TELEFON_ONLINE": (700, 4000),
    "PERSOENLICH": (500, 3000),
    "PERSOENLICH_ONLINE": (500, 6000),
    "UNBEKANNT": (500, 6000),
}


def poll_institute_date_key(poll: dict[str, Any]) -> str:
    institute = (
        poll.get("institute_key") or poll.get("institute_name") or poll.get("institute") or ""
    )
    date = poll.get("publish_date") or poll.get("published_date") or poll.get("date") or ""
    return f"{canonicalize_institute_key(str(institute))}|{date}"


def _publish_date(poll: dict[str, Any]) -> str:
    return str(poll.get("publish_date") or poll.get("published_date") or poll.get("date") or "")


def _result_map(poll: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    results = poll.get("results") or []
    if isinstance(results, dict):
        # Normalized pipeline shape: {party_name: pct}
        for key, pct in results.items():
            try:
                out[str(key).upper()] = float(pct)
            except (TypeError, ValueError):
                continue
        return out
    for row in results:
        if not isinstance(row, dict):
            continue
        key = str(row.get("party_key") or "").upper()
        try:
            pct = float(row.get("percentage"))
        except (TypeError, ValueError):
            continue
        if key:
            out[key] = pct
    # Also accept PollingDataFetcher.normalize_poll parties dict.
    parties = poll.get("parties")
    if isinstance(parties, dict):
        for key, pct in parties.items():
            try:
                out[str(key).upper()] = float(pct)
            except (TypeError, ValueError):
                continue
    return out


def _expected_core_parties(scope: str, year: int | None) -> set[str]:
    parties = {"CSU", "SPD", "FDP"} if scope == "by" else {"CDU", "SPD", "FDP"}
    if year is not None and year >= 1990:
        parties.add("GRUENE")
    if year is not None and year >= 2014:
        parties.add("AFD")
    return parties


def qc_dawum_poll(
    poll: dict[str, Any],
    comparison_polls: list[dict[str, Any]] | None = None,
) -> tuple[bool, list[str], list[str]]:
    """Return (ok, errors, warnings) using API-like checks."""
    comparison_polls = comparison_polls or []
    errors: list[str] = []
    warnings: list[str] = []
    res = _result_map(poll)

    if not res:
        errors.append("no_results")
    else:
        pcts = list(res.values())
        if any((not (0 <= p <= 100)) for p in pcts):
            errors.append("percentage_range")
        total = sum(pcts)
        if not (100 - QC_SUM_TOLERANCE <= total <= 100 + QC_SUM_TOLERANCE):
            errors.append(f"result_sum={total:.1f}")

    start = str(poll.get("survey_start_date") or poll.get("survey_date_start") or "")
    end = str(poll.get("survey_end_date") or poll.get("survey_date_end") or "")
    publish = _publish_date(poll)
    today = __import__("datetime").date.today().isoformat()
    if not start or not end or not publish:
        errors.append("missing_dates")
    elif not (start <= end <= publish <= today):
        errors.append("date_consistency")

    method_key = str(poll.get("method_key") or poll.get("survey_method_key") or "UNBEKANNT").upper()
    lo, hi = RESPONDENT_LIMITS.get(method_key, QC_RESPONDENTS_DEFAULT)
    try:
        n = int(poll["respondents"]) if poll.get("respondents") is not None else None
    except (TypeError, ValueError):
        n = None
    if n is None or not (lo <= n <= hi):
        errors.append("respondents")

    year = int(publish[:4]) if len(publish) >= 4 and publish[:4].isdigit() else None
    expected = _expected_core_parties(str(poll.get("scope") or ""), year)
    missing = expected - set(res)
    hard_missing = missing - {"FDP"}
    if "FDP" in missing:
        fdp_flags = ["FDP" in _result_map(p) for p in comparison_polls]
        if len(fdp_flags) >= 5 and (sum(fdp_flags) / len(fdp_flags)) >= 0.8:
            hard_missing.add("FDP")
        elif missing:
            warnings.append("core_parties_soft:FDP")
    if hard_missing:
        errors.append("core_parties:" + ",".join(sorted(hard_missing)))

    inst = canonicalize_institute_key(
        str(poll.get("institute_key") or poll.get("institute_name") or "")
    )
    prev = None
    prev_date = ""
    for other in comparison_polls:
        other_inst = canonicalize_institute_key(
            str(other.get("institute_key") or other.get("institute_name") or "")
        )
        if other_inst != inst:
            continue
        other_date = _publish_date(other)
        if other_date and other_date < publish and other_date > prev_date:
            prev = other
            prev_date = other_date
    if prev is not None:
        prev_res = _result_map(prev)
        jumped = [
            party
            for party in set(res) & set(prev_res)
            if abs(res[party] - prev_res[party]) > QC_JUMP_THRESHOLD
        ]
        if jumped:
            warnings.append("institute_jump:" + ",".join(sorted(jumped)))

    return (not errors, errors, warnings)


def dawum_matches_existing_poll(candidate: dict[str, Any], existing: list[dict[str, Any]]) -> bool:
    cand_key = poll_institute_date_key(candidate)
    if cand_key and not cand_key.startswith("|"):
        if any(poll_institute_date_key(p) == cand_key for p in existing):
            return True

    from datetime import date

    try:
        cand_date = date.fromisoformat(_publish_date(candidate))
    except ValueError:
        return False

    cand_res = _result_map(candidate)
    cand_inst = canonicalize_institute_key(
        str(candidate.get("institute_key") or candidate.get("institute_name") or "")
    )
    for poll in existing:
        try:
            other_date = date.fromisoformat(_publish_date(poll))
        except ValueError:
            continue
        if abs((cand_date - other_date).days) > MATCH_DATE_WINDOW_DAYS:
            continue
        same_inst = cand_inst == canonicalize_institute_key(
            str(poll.get("institute_key") or poll.get("institute_name") or "")
        )
        other_res = _result_map(poll)
        deltas: list[float] = []
        ok_parties = True
        for party in MATCH_PARTIES:
            if party not in cand_res or party not in other_res:
                ok_parties = False
                break
            deltas.append(abs(cand_res[party] - other_res[party]))
        if (
            ok_parties
            and same_inst
            and max(deltas) <= MATCH_MAX_PARTY_DELTA
            and sum(deltas) <= MATCH_MAX_TOTAL_DELTA
        ):
            return True

        try:
            n_a = int(candidate["respondents"]) if candidate.get("respondents") is not None else None
            n_b = int(poll["respondents"]) if poll.get("respondents") is not None else None
        except (TypeError, ValueError):
            n_a = n_b = None
        end_a = str(candidate.get("survey_end_date") or candidate.get("survey_date_end") or "")
        end_b = str(poll.get("survey_end_date") or poll.get("survey_date_end") or "")
        if same_inst and n_a is not None and n_a == n_b and end_a and end_a == end_b:
            return True

    return False


def _results_to_api(results: dict[str, Any] | None, parties: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(results, dict):
        return out
    for party_id, percentage in results.items():
        party = parties.get(str(party_id)) or {}
        shortcut = str(party.get("Shortcut") or "")
        key = DAWUM_PARTY_SHORTCUT_TO_KEY.get(shortcut)
        if not key:
            key = re.sub(r"[^A-Za-z0-9]+", "_", shortcut).strip("_").upper()
        if not key:
            continue
        try:
            pct = float(percentage)
        except (TypeError, ValueError):
            continue
        out.append(
            {
                "party_key": key,
                "party_short_name": shortcut,
                "party_name": party.get("Name") or shortcut,
                "percentage": pct,
            }
        )
    return out


def _survey_to_poll(
    survey_id: str,
    survey: dict[str, Any],
    *,
    scope: str,
    institute_name: str,
    commissioner_name: str | None,
    method_name: str | None,
    parties: dict[str, Any],
) -> dict[str, Any]:
    period = survey.get("Survey_Period") or {}
    publish = str(survey.get("Date") or "")
    start = str(period.get("Date_Start") or publish)
    end = str(period.get("Date_End") or publish)
    respondents_raw = survey.get("Surveyed_Persons")
    try:
        respondents = int(respondents_raw) if respondents_raw is not None else None
    except (TypeError, ValueError):
        respondents = None
    method_key = METHOD_NAME_TO_KEY.get(method_name or "", "UNBEKANNT")

    return {
        "id": None,
        "public_id": f"DAWUM-{survey_id}",
        "published_date": publish,
        "publish_date": publish,
        "survey_start_date": start,
        "survey_end_date": end,
        "respondents": respondents,
        "institute_name": institute_name,
        "institute_key": institute_name_to_key(institute_name),
        "provider_name": "DAWUM",
        "source": "dawum_scrape",
        "commissioner_name": commissioner_name,
        "survey_method_name": method_name,
        "method_key": method_key,
        "survey_method_key": method_key,
        "scope": scope,
        "election_key": scope,
        "election_type": "State election",
        "matching_status": "no_match",
        "results": _results_to_api(survey.get("Results"), parties),
        "pipeline_dawum_scrape": True,
    }


def fetch_dawum_state_polls(
    scope: str,
    *,
    published_from: str | None = None,
    published_to: str | None = None,
) -> list[dict[str, Any]]:
    scope_l = (scope or "").strip().lower()
    parliament_ids = {pid for pid, sc in DAWUM_PARLIAMENT_TO_SCOPE.items() if sc == scope_l}
    if not parliament_ids:
        return []

    dump = fetch_dawum_dump()
    surveys = dump.get("Surveys") or {}
    institutes = dump.get("Institutes") or {}
    taskers = dump.get("Taskers") or {}
    methods = dump.get("Methods") or {}
    parties = dump.get("Parties") or {}

    out: list[dict[str, Any]] = []
    for survey_id, survey in surveys.items():
        if not isinstance(survey, dict):
            continue
        if str(survey.get("Parliament_ID") or "") not in parliament_ids:
            continue
        publish = str(survey.get("Date") or "")
        if not publish:
            continue
        if published_from and publish < published_from:
            continue
        if published_to and publish > published_to:
            continue

        institute = institutes.get(str(survey.get("Institute_ID") or "")) or {}
        tasker = taskers.get(str(survey.get("Tasker_ID") or "")) or {}
        method = methods.get(str(survey.get("Method_ID") or "")) or {}
        out.append(
            _survey_to_poll(
                str(survey_id),
                survey,
                scope=scope_l,
                institute_name=str(institute.get("Name") or "Unknown"),
                commissioner_name=tasker.get("Name"),
                method_name=method.get("Name"),
                parties=parties,
            )
        )
    out.sort(key=_publish_date)
    return out


def inject_dawum_state_polls(
    polls: list[dict[str, Any]],
    scope: str,
    *,
    published_from: str | None = None,
    published_to: str | None = None,
) -> list[dict[str, Any]]:
    scope_l = (scope or "").strip().lower()
    if scope_l not in DAWUM_PARLIAMENT_TO_SCOPE.values():
        return polls

    try:
        scraped = fetch_dawum_state_polls(
            scope_l,
            published_from=published_from,
            published_to=published_to,
        )
    except Exception as exc:  # noqa: BLE001 — consumer safety net, keep API polls
        logger.warning("DAWUM scrape failed for scope=%s: %s", scope_l, exc)
        return polls

    if not scraped:
        return polls

    n_dup = 0
    n_qc_fail = 0
    n_warn = 0
    extras: list[dict[str, Any]] = []
    comparison = list(polls)

    for poll in scraped:
        if dawum_matches_existing_poll(poll, comparison):
            n_dup += 1
            continue
        ok, errors, warnings = qc_dawum_poll(poll, comparison_polls=comparison)
        if warnings:
            n_warn += 1
            logger.info("DAWUM QC warning %s: %s", poll.get("public_id"), "; ".join(warnings))
        if not ok:
            n_qc_fail += 1
            logger.info("DAWUM QC drop %s: %s", poll.get("public_id"), "; ".join(errors))
            continue
        extras.append(poll)
        comparison.append(poll)

    if not extras:
        if n_dup or n_qc_fail:
            logger.info(
                "DAWUM scrape scope=%s: 0 injected (dup=%s, qc_fail=%s)",
                scope_l,
                n_dup,
                n_qc_fail,
            )
        return polls

    logger.info(
        "Injected %s DAWUM-scraped poll(s) into scope=%s (dup=%s, qc_fail=%s, warnings=%s)",
        len(extras),
        scope_l,
        n_dup,
        n_qc_fail,
        n_warn,
    )
    return polls + extras
