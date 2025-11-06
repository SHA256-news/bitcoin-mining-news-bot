# GitHub Pages Setup Instructions

## Overview
This repository now includes a complete GitHub Pages blog that displays daily briefs of all fetched Bitcoin mining news articles.

## What's New

### 1. Static Website (`docs/index.html`)
- Modern, minimal design with dark theme
- Displays daily briefs automatically
- Shows latest headlines from Twitter
- Fully responsive, mobile-friendly

### 2. Daily Brief System
- **Automatic**: Runs daily at midnight UTC via GitHub Actions
- **Comprehensive**: Includes ALL fetched articles, not just tweeted ones
- **Archived**: Posts are saved as HTML files in `docs/posts/`

### 3. State Tracking
- All fetched articles are now saved to `.state/state.json`
- Includes headlines, bullets, URLs, and timestamps
- Kept for 7 days for weekly brief capability

## Setup Steps

### 1. Enable GitHub Pages
1. Go to your repository on GitHub
2. Click **Settings** → **Pages**
3. Under "Build and deployment":
   - Source: **Deploy from a branch**
   - Branch: **main**
   - Folder: **/docs**
4. Click **Save**

Your site will be live at: `https://<your-username>.github.io/bitcoin-mining-news-bot/`

### 2. Required Secrets (Already Set)
The daily brief workflow needs:
- `EVENTREGISTRY_API_KEY` - For fetching articles
- `GOOGLE_API_KEY` - For summarization (optional, has offline fallback)

These are the same secrets used by your existing news bot workflow.

### 3. Test Locally

Generate a daily brief manually:
```bash
# Activate your virtual environment
source .venv/bin/activate

# Generate brief for last 24 hours
python -m src.daily_brief

# Or specify custom hours
python -m src.daily_brief 48  # last 48 hours
```

This creates:
- `docs/posts/YYYY-MM-DD-daily-brief.html` - The blog post
- Updates `docs/posts/index.json` - Post index for the homepage

### 4. View Locally

Open `docs/index.html` in a browser to preview the site.

## How It Works

### Article Flow
1. **News bot runs** (every ~90 min) → Fetches articles → Summarizes → Posts to Twitter
2. **All fetched articles** are saved to state (even if not posted)
3. **Daily brief workflow** (midnight UTC) → Collects last 24h of articles → Generates HTML blog post
4. **Blog post is committed** and pushed to GitHub
5. **GitHub Pages** automatically deploys the updated site

### File Structure
```
docs/
├── index.html              # Homepage (SHA256 News)
└── posts/
    ├── index.json          # List of all posts
    ├── 2025-11-06-daily-brief.html
    ├── 2025-11-07-daily-brief.html
    └── ...
```

## Customization

### Change Daily Brief Schedule
Edit `.github/workflows/daily-brief.yml`:
```yaml
on:
  schedule:
    - cron: "0 0 * * *"  # Change this (currently midnight UTC)
```

### Change Article Window
Edit `src/daily_brief.py`:
```python
def generate_daily_brief(hours: int = 24):  # Change default here
```

### Customize Design
- Homepage: `docs/index.html` (React app with Tailwind CSS)
- Blog posts: `src/daily_brief.py` → `_generate_post_html()` function

## Troubleshooting

### No briefs appearing?
1. Check workflow runs: GitHub Actions → "Generate Daily Brief"
2. Verify articles are being fetched: Check `.state/state.json` → `fetched_articles`
3. Run manually: `python -m src.daily_brief`

### Homepage shows "No daily briefs available"?
- Ensure `docs/posts/index.json` exists and has posts
- Check browser console for fetch errors
- Verify GitHub Pages is serving the site correctly

### Workflow fails to commit?
- Check repository permissions: Settings → Actions → Workflow permissions
- Should be set to "Read and write permissions"

## Next Steps

### Recommended Enhancements
1. Add RSS feed for subscribers
2. Add newsletter signup integration
3. Add search/filter functionality
4. Add market data integration (hashrate, difficulty, etc.)
5. Add image attachments to blog posts

### Current Limitations
- No pagination (shows last 7 briefs)
- No search functionality
- No categories or tags
- Newsletter form is non-functional (placeholder)

## Support

For issues or questions, create an issue in this repository.
