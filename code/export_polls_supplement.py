#!/usr/bin/env python3
"""Export DAWUM Landtag polls as a website supplement for poll tables / charts.

FastTrack often mis-scopes these rows (esp. Civey) as federal and drops them
from default /v2/polls. The browser merges this file after the API fetch.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from dawum_state_polls import (
    DAWUM_PARLIAMENT_TO_SCOPE,
    fetch_dawum_dump,
    inject_dawum_state_polls,
)

logger = logging.getLogger(__name__)


def _public_poll(poll: dict) -> dict:
    """Keep API-shaped fields the website mapper expects."""
    keep = {
        "id",
        "public_id",
        "published_date",
        "publish_date",
        "survey_start_date",
        "survey_end_date",
        "survey_date_start",
        "survey_date_end",
        "respondents",
        "institute_name",
        "institute_key",
        "provider_name",
        "source",
        "commissioner_name",
        "survey_method_name",
        "method_name",
        "method_key",
        "survey_method_key",
        "scope",
        "election_key",
        "election_type",
        "matching_status",
        "results",
        "pipeline_dawum_scrape",
    }
    return {k: poll[k] for k in keep if k in poll}


def export_supplement(output: Path) -> dict:
    fetch_dawum_dump.cache_clear()
    by_scope: dict[str, list[dict]] = {}
    scopes = sorted(set(DAWUM_PARLIAMENT_TO_SCOPE.values()))
    for scope in scopes:
        # Empty API list → all QC-passed DAWUM rows for this parliament.
        polls = inject_dawum_state_polls([], scope)
        by_scope[scope] = [_public_poll(p) for p in polls]
        logger.info("scope=%s: %s supplement poll(s)", scope, len(by_scope[scope]))

    payload = {
        "metadata": {
            "source": "api.dawum.de",
            "purpose": "Fill Landtag polls missing from FastTrack default /v2/polls",
            "last_update": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "scopes": scopes,
            "total_polls": sum(len(v) for v in by_scope.values()),
        },
        "by_scope": by_scope,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.info("Wrote %s (%s polls)", output, payload["metadata"]["total_polls"])
    return payload


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "output" / "polls_supplement.json",
    )
    args = parser.parse_args()
    export_supplement(args.output)


if __name__ == "__main__":
    main()
