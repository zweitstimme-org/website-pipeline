# Polling API scope issues (DAWUM → FastTrack)

**Status (2026-08-18): fixed upstream.** The Civey Berlin poll of 2026-08-05 is now on default `/v2/polls?scope=be` as `C00016724` (fieldwork 2026-07-20–08-03, n=3000, CDU not CDU_CSU). Bayern Civey rows with CSU+FW are under `scope=by`. Recent federal DAWUM rows use `CDU_CSU`. The old cleaned id `C00019957` 404s; it was re-ingested under the new id.

This note is kept as the investigation record. The pipeline still has a DAWUM-dump inject (`inject_dawum_state_polls`, `polls_supplement.json`) that can be removed once we are sure coverage is complete.

API base: `https://api.zweitstimme.org` (v2; formerly `api.fasttrack29.com`).

## Symptom (historical, 2026-08)

- Website / `scope=be` last poll: **INSA 2026-07-23**
- Newer poll exists on DAWUM / Tagesspiegel: **Civey, 2026-08-05**
  (fieldwork 2026-07-20–08-03, n≈3000; Linke 21, CDU 19, AfD 18, Grüne 17,
  SPD 12, FDP/BSW 3)

## What the API actually has

| Layer | Finding |
|-------|---------|
| Default `/v2/polls?scope=be` | No row after 2026-07-23 (`published_from=2026-07-24` → total 0) |
| `all-cleaned` | Poll **is** present as **`C00019957`** / raw **`R00020010`**, but **`scope=federal`**, `election_key=federal` |
| Default public dataset | Poll **absent** (404 on `/v2/polls/19957`); `valid: false` |
| BE since 2025 | Providers are **wahlrecht.de / html_scraper only** — no DAWUM state rows |

Raw row signals (worker `dawum`):

- `commissioner_raw`: Der Tagesspiegel
- `party_results_raw`: matches the AGH poll (CDU, not CDU_CSU; high Linke)
- `scope_raw` / `election_raw`: incorrectly **`federal` / Bundestagswahl**

## Why it is dropped from federal (default)

QC report for `C00019957` sets **`valid: false`**. Blocking **error**:

- **`qc_core_parties_present`**: federal context expects **`CDU_CSU`**; row only has **`CDU`**

Also jump **warnings** (vs previous *federal* Civey / other federal polls). Warnings
alone do not exclude (older default Civey can fail jump checks and still ship);
the core-party error does.

So: wrong federal label → federal party rules → invalid → excluded from
`public_dataset` / default `/v2/polls`. It is **not** shown as a federal poll on
the site; it is dropped from the public feed.

## Systemic pattern (not a one-off)

Recent DAWUM Civey rows in `all-cleaned` are almost all tagged `federal`, including
clear Landtag patterns, e.g.:

- **BE-like**: CDU only, high Linke, Tagesspiegel commissioner (incl. 2026-07-13 and 2026-08-05)
- **BY-like**: CSU + Freie Wähler

State scopes in the API currently rely on **wahlrecht.de**. DAWUM state Sonntagsfragen
are effectively missing from `scope=be` / `by` / … until scope ingest is fixed.

## Safe remediation (polling API — not this repo)

1. **One poll → one scope.** Do not also publish an AGH/Landtag poll as federal.
2. **Fix scope at DAWUM ingest** using hard signals first: DAWUM path/election
   (`/Berlin/…` → `be`, `/Bayern/…` → `by`), then commissioner when unambiguous.
3. **Party-set backstop** (review flag, not weak auto-guess): CSU+FW → `by`;
   CDU without `CDU_CSU`/`CSU` → not federal union; `CDU_CSU` → federal.
4. **Scope-aware QC**: core parties / jump checks must use the *assigned* scope
   (`CDU` for BE, `CDU_CSU` for federal, CSU rules for BY).
5. **Manual override table** (`raw_poll_id` → `scope`) for edge cases; re-validate
   into default after override.

Consumer-side heuristics in this pipeline (e.g. TH misscope drop in
`R/fetch_polls.R`) are a safety net only; they do not fix missing BE polls
upstream.

## Temporary consumer workaround (this repo)

Until FastTrack serves DAWUM Landtag rows under the correct scope, Stimmung /
state forecasts **scrape the official DAWUM dump** (`https://api.dawum.de/`)
and merge surveys whose `Parliament_ID` maps cleanly to a Land scope
(Berlin=`3`→`be`, Bayern=`2`→`by`, …). Bund (`0`) and EU (`17`) are skipped.

- R: `inject_dawum_state_polls()` in `R/fetch_polls.R`
- Python: `code/dawum_state_polls.py` via `PollingDataFetcher.fetch_all_polls`
- Dedup (API-like): exact institute+date; fuzzy ±7d with SPD/AFD deltas
  (`max_party_delta=1`, `max_total_delta=1.5`); same n + survey_end
- QC before inject (hard drop): percentage range, sum≈100 (±2), date
  consistency, respondents by method, core parties (scope-aware; FDP soft
  unless nearby API polls usually include it)
- QC warnings only: institute result jumps (>4pp vs previous same institute)
- No FastTrack `all-cleaned` re-scope (party heuristics alone are not used to
  guess unclear Länder)

Remove this inject once default `/v2/polls?scope=be|by|…` includes the DAWUM
rows correctly.

Example FastTrack ids for API follow-up: raw `R00020010`, cleaned `C00019957`
(2026-08-05); related Tagesspiegel Civey raw `R00020011` (2026-07-13).
