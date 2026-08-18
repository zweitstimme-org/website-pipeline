#!/usr/bin/env python3
import argparse
import json
import os
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = REPO_ROOT / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))
try:
    from dawum_state_polls import fetch_dawum_state_polls
except Exception:
    fetch_dawum_state_polls = None

POLLING_API_BASE = os.environ.get("POLLING_API_BASE", "https://api.zweitstimme.org").rstrip("/")
SITE_BASE = os.environ.get("SITE_BASE", "https://zweitstimme.org").rstrip("/")


def load_json_url(url: str):
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.load(resp)


def parse_day(value):
    if not value:
        return None
    s = str(value)[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def latest_poll_date(scope: str):
    url = f"{POLLING_API_BASE}/v2/polls?scope={scope}&limit=1&sort=-published_date&include_results=true"
    data = load_json_url(url)
    items = data.get("data") or []
    if not items:
        return None
    return parse_day(items[0].get("published_date") or items[0].get("publish_date"))


def latest_state_poll_date(state_code: str):
    state_code = state_code.lower()
    scope = {"nw": "nrw"}.get(state_code, state_code)
    best = latest_poll_date(scope)
    if fetch_dawum_state_polls is not None:
        try:
            for p in fetch_dawum_state_polls(scope):
                d = parse_day(p.get("publish_date") or p.get("published_date") or p.get("date"))
                if d and (best is None or d > best):
                    best = d
        except Exception:
            pass
    return best


def published_state_poll_date(state_code: str):
    url = f"{SITE_BASE}/data/forecast_state_{state_code.lower()}.json"
    try:
        data = load_json_url(url)
    except Exception:
        return None
    return parse_day((data.get("metadata") or {}).get("last_poll_date"))


def published_stimmung_poll_date(scope: str):
    if scope == "federal":
        url = f"{SITE_BASE}/data/stimmung_federal.json"
        getter = lambda d: (d.get("metadata") or {}).get("date_range", {}).get("end")
    else:
        url = f"{SITE_BASE}/data/stimmung_states.json"
        state = scope.upper()
        getter = lambda d: (((d.get("states") or {}).get(state) or {}).get("metadata") or {}).get("date_range", {}).get("end")
    try:
        data = load_json_url(url)
    except Exception:
        return None
    return parse_day(getter(data))


def due_state_codes():
    cal = json.loads((REPO_ROOT / "data" / "election_calendar.json").read_text())
    today = date.today()
    window = int(cal.get("metadata", {}).get("forecast_window_days", 90))
    due = []
    for e in cal.get("elections", []):
        if e.get("scope") == "bund":
            continue
        code = e.get("state_code")
        d = parse_day(e.get("election_date"))
        if not code or not d:
            continue
        days = (d - today).days
        if 0 < days <= window:
            due.append(code.upper())
    return sorted(set(due))


def federal_due():
    cal = json.loads((REPO_ROOT / "data" / "election_calendar.json").read_text())
    today = date.today()
    window = int(cal.get("metadata", {}).get("forecast_window_days", 90))
    for e in cal.get("elections", []):
        if e.get("scope") != "bund":
            continue
        d = parse_day(e.get("election_date"))
        if not d:
            continue
        days = (d - today).days
        if 0 <= days <= window:
            return True
    return False


def decide_state():
    details = []
    run = False
    due = due_state_codes()
    for code in due:
        latest = latest_state_poll_date(code)
        published = published_state_poll_date(code)
        changed = published is None or (latest is not None and latest > published)
        details.append({
            "state_code": code,
            "latest_poll_date": latest.isoformat() if latest else None,
            "published_last_poll_date": published.isoformat() if published else None,
            "changed": changed,
        })
        run = run or changed
    return {
        "run": run,
        "reason": "new_state_poll" if run else ("no_due_state_forecasts" if not due else "no_new_state_polls"),
        "details": details,
    }


def decide_stimmung():
    details = []
    run = False
    fed_latest = latest_poll_date("federal")
    fed_published = published_stimmung_poll_date("federal")
    fed_changed = fed_published is None or (fed_latest is not None and fed_latest > fed_published)
    details.append({
        "scope": "federal",
        "latest_poll_date": fed_latest.isoformat() if fed_latest else None,
        "published_last_poll_date": fed_published.isoformat() if fed_published else None,
        "changed": fed_changed,
    })
    run = run or fed_changed
    for code in ["BW","BY","BE","BB","HB","HH","HE","MV","NI","NW","RP","SL","SN","ST","SH","TH"]:
        scope = code.lower()
        latest = latest_state_poll_date(code)
        published = published_stimmung_poll_date(code)
        changed = published is None or (latest is not None and latest > published)
        details.append({
            "scope": scope,
            "latest_poll_date": latest.isoformat() if latest else None,
            "published_last_poll_date": published.isoformat() if published else None,
            "changed": changed,
        })
        run = run or changed
    return {"run": run, "reason": "new_poll" if run else "no_new_polls", "details": details}


def published_federal_forecast_poll_date():
    try:
        data = load_json_url(f"{SITE_BASE}/data/forecast_federal.json")
    except Exception:
        return None
    return parse_day((data.get("metadata") or {}).get("last_poll_date"))


def decide_federal():
    due = federal_due()
    latest = latest_poll_date("federal")
    published = published_federal_forecast_poll_date()
    changed = published is None or (latest is not None and latest > published)
    return {
        "run": due and changed,
        "reason": "new_federal_poll" if due and changed else ("outside_forecast_window" if not due else "no_new_federal_polls"),
        "details": [{
            "scope": "federal",
            "latest_poll_date": latest.isoformat() if latest else None,
            "published_last_poll_date": published.isoformat() if published else None,
            "forecast_due": due,
            "changed": changed,
        }],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["state", "stimmung", "federal"], required=True)
    ap.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    args = ap.parse_args()

    if args.mode == "state":
        out = decide_state()
    elif args.mode == "stimmung":
        out = decide_stimmung()
    else:
        out = decide_federal()

    print(json.dumps(out, indent=2))
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as f:
            f.write(f"run={'true' if out['run'] else 'false'}\n")
            f.write(f"reason={out['reason']}\n")
            f.write("details<<EOF\n")
            f.write(json.dumps(out["details"], ensure_ascii=False))
            f.write("\nEOF\n")

if __name__ == "__main__":
    main()
