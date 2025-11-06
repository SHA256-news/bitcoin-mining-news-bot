"""Generate daily brief blog posts from fetched articles."""

import datetime
import json
import logging
import pathlib
from typing import List, Dict

from src.state import get_fetched_articles_since

logger = logging.getLogger(__name__)


def _format_date(date_str: str) -> str:
    """Format date string for display."""
    if not date_str:
        return ""
    try:
        # Try parsing ISO format
        dt = datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%B %d, %Y")
    except Exception:
        return date_str


def generate_daily_brief(hours: int = 24) -> str:
    """Generate HTML blog post for all fetched articles in the last N hours.

    Returns the filename of the generated post.
    """
    articles = get_fetched_articles_since(hours)

    if not articles:
        logger.info("daily_brief: no articles to include in brief")
        return ""

    # Sort by timestamp (newest first)
    articles.sort(key=lambda a: a.get("ts", 0), reverse=True)

    # Generate date string for post
    now = datetime.datetime.utcnow()
    date_str = now.strftime("%Y-%m-%d")
    display_date = now.strftime("%B %d, %Y")

    # Create post filename
    post_filename = f"{date_str}-daily-brief.html"

    # Generate HTML content
    html = _generate_post_html(articles, display_date)

    # Write to docs/posts/
    posts_dir = pathlib.Path("docs/posts")
    posts_dir.mkdir(parents=True, exist_ok=True)

    post_path = posts_dir / post_filename
    post_path.write_text(html, encoding="utf-8")

    logger.info(f"daily_brief: generated {post_filename} with {len(articles)} articles")

    # Update posts index
    _update_posts_index(post_filename, display_date, len(articles))

    return post_filename


def _generate_post_html(articles: List[Dict], display_date: str) -> str:
    """Generate HTML for a blog post."""

    # Build articles HTML
    articles_html = []
    for art in articles:
        headline = art.get("headline", "")
        bullets = art.get("bullets", [])
        url = art.get("url", "")
        source_title = art.get("source_title", "")

        bullets_html = "\n".join([f"              <li>{bullet}</li>" for bullet in bullets])

        articles_html.append(
            f"""
          <article class="border-b border-zinc-800 pb-8 mb-8">
            <h3 class="font-serif text-2xl mb-3">{headline}</h3>
            <ul class="list-disc list-inside space-y-1 text-zinc-300 mb-3">
{bullets_html}
            </ul>
            <div class="text-sm text-zinc-400">
              Source: <a href="{url}" target="_blank" rel="noopener noreferrer" class="text-emerald-400 underline">{source_title or "Article"}</a>
            </div>
          </article>"""
        )

    articles_section = "\n".join(articles_html)

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Daily Brief - {display_date} | SHA256 News</title>
    <meta name="description" content="Bitcoin mining news daily brief for {display_date}" />
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
      :root {{ color-scheme: dark; }}
      html, body {{ height: 100%; }}
      .font-serif {{ font-family: ui-serif, Georgia, Cambria, "Times New Roman", Times, serif; }}
    </style>
  </head>
  <body class="bg-zinc-950 text-zinc-100">
    <div class="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col">
      <header class="border-b border-zinc-800">
        <div class="mx-auto max-w-3xl px-4 sm:px-6 lg:px-8">
          <div class="py-6 text-center">
            <h1 class="font-serif text-4xl sm:text-5xl"><a href="/" class="hover:text-zinc-300">SHA256 News</a></h1>
            <div class="mt-2 text-[11px] tracking-widest uppercase text-zinc-400">
              Bitcoin Mining • Daily Brief
            </div>
          </div>
        </div>
      </header>
      
      <main class="flex-1 mx-auto w-full max-w-3xl px-4 sm:px-6 lg:px-8 py-12">
        <header class="mb-12">
          <h2 class="font-serif text-3xl sm:text-4xl mb-3">Daily Brief</h2>
          <div class="text-zinc-400">
            <time>{display_date}</time>
            <span class="mx-2">•</span>
            <span>{len(articles)} articles</span>
          </div>
        </header>
        
        <div class="space-y-8">
{articles_section}
        </div>
        
        <div class="mt-12 pt-8 border-t border-zinc-800 text-center">
          <a href="/" class="text-emerald-400 underline">← Back to Home</a>
        </div>
      </main>
      
      <footer class="border-t border-zinc-800 py-6 text-sm text-zinc-400 text-center">
        <div>© {datetime.datetime.utcnow().year} SHA256 Media — Bitcoin Mining Only</div>
      </footer>
    </div>
  </body>
</html>"""


def _update_posts_index(filename: str, display_date: str, article_count: int) -> None:
    """Update posts/index.json with new post metadata."""
    posts_dir = pathlib.Path("docs/posts")
    index_path = posts_dir / "index.json"

    # Load existing index
    if index_path.exists():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            index = {"posts": []}
    else:
        index = {"posts": []}

    # Check if already exists
    posts = index.get("posts", [])
    if not any(p.get("filename") == filename for p in posts):
        posts.insert(
            0,
            {
                "filename": filename,
                "date": display_date,
                "article_count": article_count,
            },
        )
        index["posts"] = posts

        # Save updated index
        index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # Allow custom hours via CLI
    hours = int(sys.argv[1]) if len(sys.argv) > 1 else 24

    filename = generate_daily_brief(hours)
    if filename:
        print(f"Generated: docs/posts/{filename}")
    else:
        print("No articles found in the specified time range")
