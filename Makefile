# Makefile for Zweitstimme website data pipeline

REPO_ROOT := $(shell pwd)
R ?= Rscript
PY ?= python3
OUTPUT_DIR := $(REPO_ROOT)/output
VENV_DIR ?= .venv

.PHONY: all deps stimmung election-dates display-mode state-forecast district-forecast mv-district-forecast federal-forecast wahlabend-fetch wahlabend-nowcast wahlabend-ltw wahlabend-st-live publish sync-mock status clean help

all: stimmung display-mode

deps:
	$(R) R/install.R
	$(PY) -m pip install -r requirements.txt

election-dates:
	$(PY) code/scrape_election_dates.py --output data/json_output/election_dates.json
	$(R) -e 'source("R/config.R"); source("R/display_mode.R"); build_election_calendar()'

stimmung: election-dates
	$(R) R/run_stimmung.R
	$(PY) code/export_polls_supplement.py --output $(OUTPUT_DIR)/polls_supplement.json

display-mode:
	$(R) -e 'source("R/config.R"); source("R/display_mode.R"); build_election_calendar(); build_display_mode()'

# Exact-lead forecasts via sibling repo zweitstimme-org/state-models.
# Optional: STATE=ST DATE=2026-09-06 for a single election; else all within 90 days.
# STATE_MODELS_DIR=../state-models SKIP_ESTIMATE=1 to reuse cached Stan fits.
state-forecast:
	@if [ -n "$(STATE)" ] && [ -n "$(DATE)" ]; then \
	  ELECTIONS_TO_FORECAST="$$(echo $(STATE) | tr '[:upper:]' '[:lower:]')_$(DATE)" \
	    bash scripts/run_state_models_forecast.sh; \
	else \
	  bash scripts/run_state_models_forecast.sh; \
	fi

district-train:
	$(PY) code/build_district_train_panel.py --states MV ST BE
	$(PY) code/estimate_district_model.py

wahlabend-fetch:
	bash scripts/fetch_wahlabend_data.sh

wahlabend-priors:
	$(PY) code/wahlabend_prior_forecast.py --years 2016 2023

wahlabend-nowcast: wahlabend-fetch wahlabend-priors
	$(PY) code/wahlabend_nowcast.py

# ST + MV Landtagswahl nowcast (Replay LTW 2021 ← 2016 WB)
wahlabend-ltw-fetch:
	bash scripts/fetch_wahlabend_st_mv.sh

wahlabend-ltw: wahlabend-ltw-fetch
	$(PY) code/wahlabend_ltw_nowcast.py --states st,mv

# Live ST nowcast from current StaLA CSV (same URL, updated after 18:00)
wahlabend-st-live:
	bash scripts/fetch_st_live.sh
	$(PY) code/wahlabend_st_live.py

district-forecast:
	$(PY) code/prepare_district_data.py --state all
	$(PY) code/incumbents.py --offline || $(PY) code/incumbents.py
	$(PY) code/aw_candidacies.py --offline || $(PY) code/aw_candidacies.py
	$(PY) code/district_forecast.py --state all
	$(PY) code/parliament_size_sim.py
	$(PY) code/listen_candidates.py
	$(PY) code/candidate_entry_sim.py

mv-district-forecast:
	$(PY) code/district_forecast.py --state MV
	$(PY) code/parliament_size_sim.py --states MV
	$(PY) code/listen_candidates.py --states MV
	$(PY) code/candidate_entry_sim.py --states MV

federal-forecast:
	$(R) federal-model/run_federal_forecast.R

publish: stimmung
	bash scripts/publish_to_website.sh

sync-mock: stimmung
	@echo "Syncing pipeline output to website-mock/static/data/..."
	@mkdir -p website-mock/static/data website-mock/static/js
	@cp output/*.json website-mock/static/data/ 2>/dev/null || true
	@cp -r output/archive website-mock/static/data/ 2>/dev/null || true
	@cp data/election_calendar.json website-mock/static/data/ 2>/dev/null || true
	@cp data/json_output/election_dates.json website-mock/static/data/ 2>/dev/null || true
	@cp output/party_order.json website-mock/static/data/ 2>/dev/null || true
	@cp website-integration/static/js/pipeline-data.js website-mock/static/js/
	@mkdir -p website-mock/themes/PaperMod/layouts/partials
	@cp website-integration/themes/PaperMod/layouts/partials/home_info_de.html website-mock/themes/PaperMod/layouts/partials/home_info_de.html
	@mkdir -p website-mock/content/blog/posts website-mock/content/archive/posts
	@cp -r website-integration/content/blog/posts/* website-mock/content/blog/posts/
	@rm -rf website-mock/content/archive/posts/polling-calculation-methods
	@if [ -d website-integration/content/archive/posts ]; then cp -r website-integration/content/archive/posts/* website-mock/content/archive/posts/; fi
	@if [ -x .bin/hugo ]; then cd website-mock && ../.bin/hugo --minify --baseURL http://localhost:1313/; else echo "Run: curl hugo or install hugo, then rebuild website-mock"; fi
	@echo "Done. Run 'cd website-mock && hugo server' or serve website-mock/public on port 1313."

status:
	@echo "=== Pipeline output ==="
	@ls -la $(OUTPUT_DIR) 2>/dev/null || echo "No output yet — run make stimmung"
	@echo "=== Election calendar ==="
	@ls -la data/election_calendar.json 2>/dev/null || echo "Not generated"

clean:
	rm -rf $(OUTPUT_DIR)/*

help:
	@echo "Targets:"
	@echo "  all             - election dates + Stimmung + display mode"
	@echo "  deps            - install R + Python dependencies"
	@echo "  stimmung        - run Kalman Stimmung pipeline (federal + 16 states)"
	@echo "  election-dates  - scrape wahlrecht.de dates + build election_calendar.json"
	@echo "  display-mode    - regenerate display_mode.json"
	@echo "  state-forecast  - run state model (STATE=.. DATE=..)"
	@echo "  district-train       - build historical panel + estimate Erst OLS coefs"
	@echo "  district-forecast    - BE/ST/MV district model + parliament size + candidate entry"
	@echo "  mv-district-forecast - MV only (alias)"
	@echo "  federal-forecast - run federal model skeleton"
	@echo "  wahlabend-st-live    - fetch StaLA CSV + live ST nowcast JSON"
	@echo "  publish         - stimmung + push JSON to website-source"
	@echo "  sync-mock       - stimmung + copy JSON to website-mock for local preview"
	@echo "  status          - show output file status"
	@echo "  clean           - remove generated output/"
