# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Common commands

- Setup (Python 3.11)
  - python -m venv .venv && source .venv/bin/activate
  - pip install -r requirements.txt && pip install -r requirements-dev.txt
- Run locally
  - python -m src.main
- Override inputs
  - ARTICLES_LIMIT=3 TOPIC_QUERY="bitcoin mining policy" python -m src.main
- DRY run
  - DRY_RUN=1 python -m src.main
- Tests
  - pytest -q
  - pytest tests/test_formatter.py -k compose
- Lint/format
  - ruff check .
  - black --check .  # use `black .` to auto-format
- Pre-commit hooks
  - pre-commit install && pre-commit run --all-files

## High-level architecture

- Orchestrator: src/main.py
  - Loads .env via python-dotenv, initializes logging, reads ARTICLES_LIMIT (default 5) and TOPIC_QUERY (default "bitcoin mining").
  - Per-article pipeline: fetch → summarize → format → publish → mark URL posted (dedup).
- Fetch: src/news_fetcher.py
  - Calls Event Registry REST (getArticles) with keyword=query; requests session with retries/timeouts.
  - Without EVENTREGISTRY_API_KEY, returns a placeholder article (dev-friendly).
- Summarize: src/summarizer.py
  - Uses google-generativeai GenerativeModel (GEMINI_MODEL env, default "gemini-2.5-pro"); offline fallback when GOOGLE_API_KEY is unset or API fails.
- Format: src/formatter.py
  - Composes Tweet 1 as: "Headline — • b1 • b2 • b3" within 280 chars; Tweet 2 is the URL.
- Publish: src/publisher.py
  - Uses tweepy OAuth1 (X_* env vars). When DRY_RUN=1 or creds/tweepy missing, logs and prints tweets instead.
- Dedup state: src/state.py
  - Tracks previously posted URLs in `.state/state.json` (configurable via STATE_FILE); used by main to skip repeats.
- Docs/Pages: docs/index.md scaffold for a future daily brief site.
- CI: .github/workflows/news-bot.yml runs approx. every 90 minutes, enforces concurrency, and caches `.state/` weekly; ci.yml runs lint/tests on pushes/PRs.

## Environment configuration

- Required for full run
  - EVENTREGISTRY_API_KEY, GOOGLE_API_KEY,
  - X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET
- Optional
  - ARTICLES_LIMIT (int, default 5)
  - TOPIC_QUERY (string, default "bitcoin mining")
  - GEMINI_MODEL (default "gemini-2.5-pro")
  - DRY_RUN (1 to print instead of post)
  - STATE_FILE (path, default `.state/state.json`)

## Notes from README and CI

- Local run mirrors CI: `python -m src.main` after installing requirements.
- GitHub Actions uses Python 3.11; provide the listed secrets; repo Variables may set ARTICLES_LIMIT and TOPIC_QUERY.
- Enable GitHub Pages to serve from `docs/` on main when the blog feature is ready.
