"""Generate editorial daily briefs with Google Search grounding."""

import datetime
import json
import logging
import os
import pathlib

from google import genai
from google.genai import types
from src.state import get_fetched_articles_since

logger = logging.getLogger(__name__)


def generate_editorial_brief(hours: int = 24, api_key: str | None = None) -> str:
    """Generate editorial daily brief with Google Search grounding.

    Args:
        hours: Look back window for articles (default 24)
        api_key: Gemini API key for editorial brief (uses GEMINI_EDITORIAL_KEY env var if not provided)

    Returns:
        Filename of generated post
    """
    # Get API key
    if not api_key:
        api_key = os.getenv("GEMINI_EDITORIAL_KEY") or os.getenv("GOOGLE_API_KEY")

    if not api_key:
        logger.error(
            "editorial_brief: No API key provided (set GEMINI_EDITORIAL_KEY or GOOGLE_API_KEY)"
        )
        return ""

    # Get articles from state
    articles = get_fetched_articles_since(hours)

    if not articles:
        logger.info("editorial_brief: no articles to include in brief")
        return ""

    # Sort by timestamp (newest first)
    articles.sort(key=lambda a: a.get("ts", 0), reverse=True)

    logger.info(f"editorial_brief: processing {len(articles)} articles from last {hours}h")

    # Build article list for prompt
    article_text = "\n\n".join(
        [
            f"**{i+1}. {art.get('headline', 'Untitled')}** ({art.get('source_date', 'N/A')})\n"
            + "\n".join([f"  • {bullet}" for bullet in art.get("bullets", [])])
            for i, art in enumerate(articles)
        ]
    )

    # Generate date string for post
    now = datetime.datetime.now(datetime.timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    display_date = now.strftime("%B %d, %Y")

    # Enhanced editorial prompt with grounding
    prompt = f"""You are a senior editor at SHA256 News, a premium Bitcoin mining publication read by mining executives, operators, and institutional investors.

Your task: Create a comprehensive daily brief for the last 24 hours. First, list today's mining headlines clearly. Then provide deep editorial analysis enriched with research on adjacent developments (energy, policy, tech, macro) that impact mining operations.

TODAY'S MINING STORIES:
{article_text}

BRIEF REQUIREMENTS:

**PART 1: Today's Headlines** (scannable list)
- List each story with 1-line summary
- Organized by importance/theme
- Include key numbers/facts

**PART 2: Analysis & Research** 
Go beyond the mining stories. Research and incorporate:

1. **Energy Markets**: Power prices, grid conditions, renewable trends affecting mining
2. **Policy/Regulatory**: Any crypto regulations, mining taxes, data center policies
3. **Technology**: Chip supply (Nvidia/TSMC), data center economics, cooling tech
4. **Macro Context**: What's driving BTC price, institutional moves, broader crypto trends  
5. **Adjacent Industries**: Cloud computing trends, AI compute demand, Texas/UAE infrastructure

For each mining story, ask: "What else is happening that explains this or matters for miners?"

Connect dots between:
- Mining stories AND energy news
- Corporate moves AND policy changes  
- Local developments AND global trends

**PART 3: Key Implications**
Report the factual implications and what industry experts are saying. DO NOT give advice or recommendations. Simply report:
- What industry analysts are observing
- What the data shows
- What questions these developments raise
- What trends are emerging

You are a JOURNALIST, not a consultant. Report facts and context, never prescribe action.

ETHICAL JOURNALISM STANDARDS:
- Seek truth and report it - verify all facts
- Minimize harm - respect privacy, be sensitive
- Act independently - no conflicts of interest, no advice
- Be accountable - transparent about sources and methods
- Ensure fairness - present multiple perspectives
- Verify information - fact-check everything
- Distinguish news from opinion - clearly label analysis
- Never advise or recommend - you are a reporter, not a consultant

STYLE:
- WSJ/FT quality - authoritative, analytical, factual
- Use grounded search to verify claims
- Report what experts say, not what readers should do
- Short paragraphs, precise numbers, zero hype, zero advice

OUTPUT FORMAT (Markdown):

# Daily Brief: {display_date}

## Today's Headlines

**Industry Shifts**
- [Story]: [Key fact/implication]
- [Story]: [Key fact/implication]

**Operations & Capacity**  
- [Story]: [Key fact/implication]

**Market Moves**
- [Story]: [Key fact/implication]

## Analysis: [Thematic Headline]

[Editorial analysis enriched with research on energy, policy, tech trends, macro factors]

[Connect mining stories to broader context - explain WHY these things are happening NOW]

[Include relevant developments in adjacent sectors]

## Key Implications

**[Thematic Area]**: [Factual observation about what this means, what experts say, what data shows]

**[Thematic Area]**: [Factual observation about industry trends, questions raised, emerging patterns]

**[Thematic Area]**: [Factual observation about market dynamics, what companies are doing, what's changing]

Write the brief now. Use your knowledge to add depth beyond just the mining articles."""

    try:
        # Configure Gemini client with grounding
        client = genai.Client(api_key=api_key)

        grounding_tool = types.Tool(google_search=types.GoogleSearch())

        config = types.GenerateContentConfig(
            tools=[grounding_tool],
            temperature=0.7,
        )

        logger.info("editorial_brief: generating with Google Search grounding...")

        # Generate the brief
        response = client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=prompt,
            config=config,
        )

        brief_content = response.text

        # Log grounding metadata if available
        if hasattr(response, "candidates") and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, "grounding_metadata") and candidate.grounding_metadata:
                metadata = candidate.grounding_metadata
                if hasattr(metadata, "web_search_queries") and metadata.web_search_queries:
                    logger.info(
                        f"editorial_brief: executed {len(metadata.web_search_queries)} search queries"
                    )

    except Exception as e:
        logger.error(f"editorial_brief: generation failed: {e}")
        return ""

    # Create post filename
    post_filename = f"{date_str}-editorial-brief.html"

    # Generate HTML from markdown
    html = _generate_post_html(brief_content, display_date, len(articles), articles)

    # Write to docs/posts/
    posts_dir = pathlib.Path("docs/posts")
    posts_dir.mkdir(parents=True, exist_ok=True)

    post_path = posts_dir / post_filename
    post_path.write_text(html, encoding="utf-8")

    logger.info(f"editorial_brief: generated {post_filename} with {len(articles)} articles")

    # Update posts index
    _update_posts_index(post_filename, display_date, len(articles))

    return post_filename


def _generate_post_html(
    markdown_content: str, display_date: str, article_count: int, articles=None
) -> str:
    """Generate HTML for editorial blog post.
    - Strip a leading "# Daily Brief: ..." heading
    - Use prose-lg styling
    - Optionally linkify key terms to source URLs using provided article metadata
    """
    import re

    # 1) Strip redundant heading if present
    markdown_content = re.sub(
        r"^\s*#\s*Daily\s*Brief:.*\n?",
        "",
        markdown_content,
        count=1,
        flags=re.IGNORECASE | re.MULTILINE,
    )

    # 2) Convert headers
    html_content = markdown_content
    html_content = re.sub(
        r"^# (.+)$",
        r'<h1 class="font-serif text-3xl sm:text-4xl mb-6">\1</h1>',
        html_content,
        flags=re.MULTILINE,
    )
    html_content = re.sub(
        r"^## (.+)$",
        r'<h2 class="font-serif text-2xl mb-4 mt-8">\1</h2>',
        html_content,
        flags=re.MULTILINE,
    )
    html_content = re.sub(
        r"^\*\*(.+?)\*\*:", r"<strong>\1</strong>:", html_content, flags=re.MULTILINE
    )

    # 3) Paragraphs/line breaks
    html_content = html_content.replace("\n\n", "</p><p>")
    html_content = html_content.replace("\n", "<br>")

    # 4) Best-effort linkify using article hints
    if articles:
        link_map: dict[str, str] = {}
        for a in articles:
            url = a.get("url")
            if not url:
                continue
            t = (a.get("headline") or a.get("source_title") or "").lower()
            if "iren" in t:
                link_map.setdefault("IREN", url)
            if "cipher" in t:
                link_map.setdefault("Cipher Mining", url)
                link_map.setdefault("Cipher", url)
            if "phoenix" in t:
                link_map.setdefault("Phoenix", url)
                link_map.setdefault("Phoenix Group", url)
            if "american bitcoin" in t or "abtc" in t:
                link_map.setdefault("American Bitcoin", url)
            if "hive" in t:
                link_map.setdefault("HIVE", url)
                link_map.setdefault("HIVE Digital", url)
            if "block" in t:
                link_map.setdefault("Block", url)
            if "mara" in t:
                link_map.setdefault("MARA", url)
        for term, url in link_map.items():
            html_content = re.sub(
                rf"(?<![\w-])({re.escape(term)})(?![\w-])",
                rf'<a href="{url}" target="_blank" rel="noopener noreferrer" class="text-emerald-400 underline">\1</a>',
                html_content,
                count=1,
            )

    return f"""<!doctype html>
<html lang=\"en\">\n  <head>\n    <meta charset=\"utf-8\" />\n    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n    <title>Daily Brief - {display_date} | SHA256 News</title>\n    <meta name=\"description\" content=\"Bitcoin mining daily editorial brief for {display_date}\" />\n    <script src=\"https://cdn.tailwindcss.com\"></script>\n    <style>\n      :root {{ color-scheme: dark; }}\n      html, body {{ height: 100%; }}\n      .font-serif {{ font-family: ui-serif, Georgia, Cambria, \"Times New Roman\", Times, serif; }}\n    </style>\n  </head>\n  <body class=\"bg-zinc-950 text-zinc-100\">\n    <div class=\"min-h-screen bg-zinc-950 text-zinc-100 flex flex-col\">\n      <header class=\"border-b border-zinc-800\">\n        <div class=\"mx-auto max-w-3xl px-4 sm:px-6 lg:px-8\">\n          <div class=\"py-6 text-center\">\n            <h1 class=\"font-serif text-4xl sm:text-5xl\"><a href=\"/\" class=\"hover:text-zinc-300\">SHA256 News</a></h1>\n            <div class=\"mt-2 text-[11px] tracking-widest uppercase text-zinc-400\">\n              Bitcoin Mining • Editorial Brief\n            </div>\n          </div>\n        </div>\n      </header>\n      \n      <main class=\"flex-1 mx-auto w-full max-w-3xl px-4 sm:px-6 lg:px-8 py-12\">\n        <article class=\"prose prose-lg prose-invert prose-zinc max-w-none\">\n          <p>{html_content}</p>\n        </article>\n        \n        <div class=\"mt-12 pt-8 border-t border-zinc-800 text-center\">\n          <a href=\"/\" class=\"text-zinc-400 underline hover:text-zinc-100\">← Back to Home</a>\n        </div>\n      </main>\n      \n      <footer class=\"border-t border-zinc-800 py-6 text-sm text-zinc-400 text-center\">\n        <div>© {datetime.datetime.utcnow().year} SHA256 Media — Bitcoin Mining Only</div>\n      </footer>\n    </div>\n  </body>\n</html>"""


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

    filename = generate_editorial_brief(hours)
    if filename:
        print(f"Generated: docs/posts/{filename}")
    else:
        print("Failed to generate editorial brief")
