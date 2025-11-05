# Bitcoin Mining News Bot

A bot that fetches Bitcoin mining news from Event Registry, summarizes with Gemini 2.5 Pro, and posts a rapid-fire two-tweet set:

- Tweet 1: catchy headline + 3 bullet points (<= 280 chars)
- Tweet 2: source URL

It runs on GitHub Actions roughly every 90 minutes and will later power a GitHub Pages blog with daily briefs and image selection logic.

## Status
Initial scaffold evolving toward production: runtime config, retries, dedup, and basic tests/linting.

## Environment
Copy `.env.example` to `.env` (for local development) and fill values:
- `EVENTREGISTRY_API_KEY`
- `GOOGLE_API_KEY`
- `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET`
- Optional: `ARTICLES_LIMIT`, `TOPIC_QUERY`, `GEMINI_MODEL`
- Local/dev toggles: `DRY_RUN=1` to print instead of post; `STATE_FILE` (default `.state/state.json`).

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

## Lint/Format
```bash
ruff check .
black --check .  # or: black . to auto-format
```

Optional pre-commit hooks:
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
Pages is scaffolded under `docs/`. Enable Pages to serve from the `docs/` folder on the `main` branch.

## Roadmap
- Image selection library and logic to attach 2 relevant images
- Daily blog generation with broader context (energy, politics, etc.)
- Caching/deduplication and rate-limit handling
- Unit tests and linting
