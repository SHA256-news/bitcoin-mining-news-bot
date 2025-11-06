# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Common commands

- Setup (Python 3.11)
  - python -m venv .venv && source .venv/bin/activate
  - pip install -r requirements.txt && pip install -r requirements-dev.txt
- Run locally
  - python -m src.main
- Generate daily brief
  - python -m src.daily_brief  # last 24 hours
  - python -m src.daily_brief 48  # last 48 hours
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
  - **NEW**: Saves all fetched articles to state (even if not posted) for daily brief generation.
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
  - **NEW**: Tracks all fetched articles with `save_fetched_article()` and `get_fetched_articles_since()`.
  - Keeps fetched articles for 7 days (168h) to support weekly briefs.
- Daily brief: src/daily_brief.py
  - **NEW**: Generates HTML blog posts from all fetched articles in the last N hours (default 24).
  - Creates `docs/posts/YYYY-MM-DD-daily-brief.html` with all articles.
  - Updates `docs/posts/index.json` with post metadata.
- Docs/Pages: docs/index.html is a complete SHA256 News blog site.
  - Displays daily briefs automatically via React + Tailwind CSS.
  - Shows latest Twitter headlines widget.
  - Fully responsive, dark theme design.
- CI: .github/workflows/news-bot.yml runs approx. every 90 minutes, enforces concurrency, and caches `.state/` weekly; ci.yml runs lint/tests on pushes/PRs.
  - **NEW**: .github/workflows/daily-brief.yml runs daily at midnight UTC to generate and commit daily briefs.

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
- GitHub Pages is LIVE: Enable Pages to serve from `docs/` folder on main branch.
  - Homepage: docs/index.html
  - Daily briefs: docs/posts/YYYY-MM-DD-daily-brief.html
  - Site URL: https://<username>.github.io/bitcoin-mining-news-bot/

## Daily Brief System

- All fetched articles (tweeted or not) are saved to state with timestamps
- Daily workflow generates HTML blog post at midnight UTC
- Posts include headline, bullets, source URL for each article
- Homepage automatically displays latest 7 briefs
- Run manually: `python -m src.daily_brief [hours]`
