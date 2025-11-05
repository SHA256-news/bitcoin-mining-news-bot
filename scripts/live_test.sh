#!/usr/bin/env bash
set -euo pipefail

# Live pipeline test: fetch from Event Registry and summarize via Gemini; never post to X.
# Usage: bash scripts/live_test.sh [ARTICLES_LIMIT] [TOPIC_QUERY]
# It will securely prompt for your API keys.

ARTICLES_LIMIT_INPUT="${1:-1}"
TOPIC_QUERY_INPUT="${2:-bitcoin mining policy}"

# Create venv and install deps
if [ ! -d .venv ]; then
  python -m venv .venv
fi
source .venv/bin/activate
python -m pip install --upgrade pip >/dev/null
pip install -r requirements.txt -r requirements-dev.txt >/dev/null

# Securely prompt for secrets (input is hidden)
read -s -p "Event Registry API key: " EVENTREGISTRY_API_KEY; echo
read -s -p "Google Gemini API key: " GOOGLE_API_KEY; echo

# Export env for this run (not written to disk)
export EVENTREGISTRY_API_KEY
export GOOGLE_API_KEY
export DRY_RUN=1        # prevents posting; fetch/summarize still happen
export LOG_LEVEL=DEBUG
export ARTICLES_LIMIT="$ARTICLES_LIMIT_INPUT"
export TOPIC_QUERY="$TOPIC_QUERY_INPUT"

# Execute
python -m src.main
