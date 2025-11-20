# Bitcoin Mining News Bot

A bot that fetches Bitcoin mining news from Event Registry, summarizes with Gemini 2.5 Pro, and posts a rapid-fire two-tweet set:

- Tweet 1: catchy headline + 3 bullet points (<= 280 chars)
- Tweet 2: source URL

It runs on GitHub Actions roughly every 90 minutes and powers a GitHub Pages blog with daily briefs of all fetched articles.

## Status
Initial scaffold evolving toward production: runtime config, retries, dedup, and basic tests/linting.

## Environment
Copy `.env.example` to `.env` (for local development) and fill values:
- `EVENTREGISTRY_API_KEY`
- `GOOGLE_API_KEY`
- `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET`
- Optional: `ARTICLES_LIMIT`, `TOPIC_QUERY`, `GEMINI_MODEL`
- Emergency Override: `MANUAL_POSTED_URLS` (comma-separated list of URLs to treat as posted, useful if X sync fails).
- Local/dev toggles: `DRY_RUN=1` to print instead of post; `STATE_FILE` (default `.state/state.json`), `POSTED_FILE` (default `.state/posted.json`).

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt  # tools: pytest, ruff, black, pre-commit
cp .env.example .env # then edit
python -m src.main
```

## Tests
```bash
pytest -q
pytest tests/test_formatter.py -k compose  # run a single test pattern
```

## Lint/Format/Type Check
```bash
ruff check .
black --check .
mypy .
```

**Mandatory** pre-commit hooks (runs all the above):
```bash
pre-commit install
pre-commit run --all-files
```

## GitHub Actions
The workflow in `.github/workflows/news-bot.yml` triggers twice every 3 hours (approx. every 90 minutes total). Provide secrets in repository settings:
- `EVENTREGISTRY_API_KEY`, `GOOGLE_API_KEY`, `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET`
It includes concurrency control and caches `.state/` weekly to support URL dedup across runs.

Additional CI (`ci.yml`) runs `ruff`, `black --check`, and `pytest` on pushes/PRs.

## GitHub Pages

### Setup
1. Enable GitHub Pages in repository settings
2. Set source to "Deploy from a branch"
3. Select branch: `main`, folder: `/docs`
4. Your site will be available at `https://<username>.github.io/<repo-name>/`

### Daily Brief
The bot generates a daily brief of all fetched articles (regardless of whether they were posted to Twitter). This runs automatically via `.github/workflows/daily-brief.yml` at midnight UTC.

**Manual generation:**
```bash
python -m src.editorial_daily_brief         # last 24 hours
python -m src.editorial_daily_brief 48      # last 48 hours
```

The daily brief:
- Collects all articles fetched in the last 24 hours
- Generates an editorial HTML blog post in `docs/posts/YYYY-MM-DD-editorial-brief.html`
- Updates `docs/posts/index.json` with post metadata
- The homepage automatically displays the latest briefs

## Roadmap
- Image selection library and logic to attach 2 relevant images
- Enhanced blog features (categories, search, RSS feed)
- Newsletter integration
- Analytics and engagement tracking
