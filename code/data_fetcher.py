"""Fetch and normalize polling data from the Fasttrack API (v2)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import requests

from config import (
    PARTY_KEY_TO_NAME,
    POLLING_API_PAGE_SIZE,
    POLLING_API_POLLS_ENDPOINT,
    SCOPE_TO_STATE_CODE,
)
from dawum_state_polls import inject_dawum_state_polls

logger = logging.getLogger(__name__)

# Accept legacy filter names used by callers and map them to v2 query params.
_FILTER_ALIASES = {
    "date_from": "published_from",
    "date_to": "published_to",
}


class PollingDataFetcher:
    """Fetch polls from api.zweitstimme.org and normalize to pipeline format."""

    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "zweitstimme-website-pipeline/1.0")

    def _get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.get(url, params=params, timeout=120)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _normalize_filters(filters: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in filters.items():
            if value is None:
                continue
            normalized[_FILTER_ALIASES.get(key, key)] = value
        return normalized

    def fetch_poll_page(
        self,
        *,
        limit: int = POLLING_API_PAGE_SIZE,
        offset: int = 0,
        **filters: Any,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "limit": limit,
            "offset": offset,
            "include_results": True,
            "sort": "-published_date",
        }
        params.update(self._normalize_filters(filters))
        return self._get_json(POLLING_API_POLLS_ENDPOINT, params=params)

    @staticmethod
    def _prefer_matched_poll(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
        if a.get("source") == "api" and b.get("source") != "api":
            return a
        if b.get("source") == "api" and a.get("source") != "api":
            return b
        if a.get("provider_name") == "DAWUM" and b.get("provider_name") != "DAWUM":
            return a
        if b.get("provider_name") == "DAWUM" and a.get("provider_name") != "DAWUM":
            return b
        a_id = int(a.get("id") or 0)
        b_id = int(b.get("id") or 0)
        return a if a_id <= b_id else b

    @classmethod
    def drop_matched_duplicates(cls, polls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Collapse matched pairs and multiple_matches groups; leave no_match alone."""
        by_id = {int(p["id"]): p for p in polls if p.get("id") is not None}
        drop_ids: set[int] = set()

        # 1) Exact matched pairs linked by matching_poll_id.
        for poll in polls:
            if poll.get("matching_status") != "matched":
                continue
            try:
                poll_id = int(poll["id"])
                match_id = int(poll["matching_poll_id"])
            except (KeyError, TypeError, ValueError):
                continue
            if match_id not in by_id or poll_id in drop_ids or match_id in drop_ids:
                continue
            keep = cls._prefer_matched_poll(poll, by_id[match_id])
            drop_ids.add(match_id if int(keep.get("id") or 0) == poll_id else poll_id)

        # 2) multiple_matches: collapse same institute/date group.
        multi_groups: dict[str, list[dict[str, Any]]] = {}
        for poll in polls:
            if poll.get("matching_status") != "multiple_matches":
                continue
            date = poll.get("publish_date") or poll.get("published_date") or ""
            institute = poll.get("institute_name") or poll.get("institute_key") or ""
            if not date or not institute:
                continue
            key = f"{institute}|{date}"
            multi_groups.setdefault(key, []).append(poll)

        for group in multi_groups.values():
            if len(group) < 2:
                continue
            keep = group[0]
            for poll in group[1:]:
                keep = cls._prefer_matched_poll(keep, poll)
            keep_id = int(keep.get("id") or 0)
            for poll in group:
                poll_id = int(poll.get("id") or 0)
                if poll_id and poll_id != keep_id:
                    drop_ids.add(poll_id)

        if not drop_ids:
            return polls
        return [p for p in polls if int(p.get("id") or 0) not in drop_ids]

    def fetch_all_polls(self, **filters: Any) -> list[dict[str, Any]]:
        """Fetch all polls, paginating through the Fasttrack v2 API."""
        raw_polls: list[dict[str, Any]] = []
        offset = 0

        while True:
            payload = self.fetch_poll_page(limit=POLLING_API_PAGE_SIZE, offset=offset, **filters)
            items = payload.get("data", [])
            if not items:
                break

            raw_polls.extend(items)
            total = payload.get("pagination", {}).get("total", len(raw_polls))
            offset += len(items)
            logger.info("Fetched %s/%s polls", offset, total)

            if offset >= total:
                break

        polls = self.drop_matched_duplicates(raw_polls)
        scope = filters.get("scope")
        if scope:
            polls = inject_dawum_state_polls(
                polls,
                str(scope),
                published_from=filters.get("published_from") or filters.get("date_from"),
                published_to=filters.get("published_to") or filters.get("date_to"),
            )
        return [self.normalize_poll(poll) for poll in polls]

    def fetch_recent_polls(self, days: int = 30, **filters: Any) -> list[dict[str, Any]]:
        cutoff = datetime.now().date() - timedelta(days=days)
        published_from = filters.pop("published_from", filters.pop("date_from", cutoff.isoformat()))
        return self.fetch_all_polls(published_from=published_from, **filters)

    def fetch_polls_by_election(self, election_key: str, **filters: Any) -> list[dict[str, Any]]:
        return self.fetch_all_polls(election_key=election_key, **filters)

    def fetch_polls_by_scope(self, scope: str, **filters: Any) -> list[dict[str, Any]]:
        return self.fetch_all_polls(scope=scope, **filters)

    @staticmethod
    def _field(poll: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            value = poll.get(key)
            if value is not None and value != "":
                return value
        return None

    @staticmethod
    def normalize_poll(poll: dict[str, Any]) -> dict[str, Any]:
        scope = poll.get("scope") or "federal"
        state_code = None
        normalized_scope = scope

        if scope == "federal":
            normalized_scope = "federal"
        elif scope in {"ost", "west"}:
            normalized_scope = scope
        else:
            normalized_scope = "state"
            state_code = SCOPE_TO_STATE_CODE.get(scope, scope.upper())

        publish_date = PollingDataFetcher._field(poll, "publish_date", "published_date")
        survey_start = PollingDataFetcher._field(poll, "survey_date_start", "survey_start_date")
        survey_end = PollingDataFetcher._field(poll, "survey_date_end", "survey_end_date")

        return {
            "id": poll.get("id"),
            "public_id": poll.get("public_id"),
            "date": publish_date,
            "publish_date": publish_date,
            "fieldwork_start": survey_start,
            "fieldwork_end": survey_end,
            "survey_date_start": survey_start,
            "survey_date_end": survey_end,
            "respondents": poll.get("respondents"),
            "institute": poll.get("institute_name"),
            "institute_key": poll.get("institute_key"),
            "provider": poll.get("provider_name"),
            "source": poll.get("source"),
            "scope": normalized_scope,
            "api_scope": scope,
            "state": state_code,
            "election_key": poll.get("election_key"),
            "election_type": poll.get("election_type"),
            "method": PollingDataFetcher._field(poll, "method_name", "survey_method_name"),
            "method_key": PollingDataFetcher._field(poll, "method_key", "survey_method_key"),
            "parties": PollingDataFetcher.extract_parties(poll),
        }

    @staticmethod
    def extract_parties(poll: dict[str, Any]) -> dict[str, float]:
        results = poll.get("results")
        parties: dict[str, float] = {}

        if isinstance(results, dict):
            for party_key, percentage in results.items():
                if percentage is None:
                    continue
                name = PARTY_KEY_TO_NAME.get(party_key, party_key)
                parties[name] = float(percentage)
            return parties

        if isinstance(results, list):
            for row in results:
                percentage = row.get("percentage")
                if percentage is None:
                    continue
                name = (
                    row.get("party_short_name")
                    or PARTY_KEY_TO_NAME.get(row.get("party_key", ""), row.get("party_key"))
                    or row.get("party_name")
                )
                if name:
                    parties[name] = float(percentage)

        return parties
