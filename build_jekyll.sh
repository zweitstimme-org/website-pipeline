#!/bin/bash
# Legacy helper — the live site is built from website-source (Hugo at repo root).
# Pipeline outputs are published to website-source/static/data/ by GitHub Actions.

echo "Website build happens in github.com/zweitstimme-org/website-source"
echo "Run 'make stimmung' here, then 'make publish' (with WEBSITE_DEPLOY_TOKEN set)."
