"""Generate an editorial daily brief from a manually provided list of articles, using
Google Search grounding via the Gemini API, and publish to docs/posts/.

Usage:
  GEMINI_EDITORIAL_KEY=... python -m src.editorial_manual

This script is a one-off helper for days when Event Registry rate limits prevent
state-based generation. It mirrors src/editorial_daily_brief.py behavior but
injects the article list directly from the request.
"""

import datetime
import logging
import os
import pathlib
from typing import List, Dict

from google import genai
from google.genai import types

# Reuse HTML generation and index update from the editorial generator
from src.editorial_daily_brief import _generate_post_html, _update_posts_index

logger = logging.getLogger(__name__)


def _today_strings() -> tuple[str, str]:
    now = datetime.datetime.utcnow()
    return now.strftime("%Y-%m-%d"), now.strftime("%B %d, %Y")


def _build_article_text(articles: List[Dict]) -> str:
    return "\n\n".join(
        [
            f"**{i+1}. {art['headline']}** ({art.get('source_title', '')} — {art.get('source_date', '')})\n"
            + "\n".join([f"  • {b}" for b in art.get("bullets", [])])
            for i, art in enumerate(articles)
        ]
    )


def generate_editorial_from_list(articles: List[Dict]) -> str:
    api_key = os.getenv("GEMINI_EDITORIAL_KEY")
    if not api_key:
        logger.error("editorial_manual: No API key provided (set GEMINI_EDITORIAL_KEY)")
        return ""

    if not articles:
        logger.info("editorial_manual: empty manual articles list")
        return ""

    date_str, display_date = _today_strings()
    article_text = _build_article_text(articles)

    prompt = f"""You are a senior editor at SHA256 News, a premium Bitcoin mining publication read by mining executives, operators, and institutional investors.

Your task: Create a comprehensive daily brief for the last 24 hours. First, list today's mining headlines clearly. Then provide deep editorial analysis enriched with research on adjacent developments (energy, policy, tech, macro) that impact mining operations.

TODAY'S MINING STORIES (provided):
{article_text}

BRIEF REQUIREMENTS:

**PART 1: Today's Headlines** (scannable list)
- List each story with 1-line summary
- Organized by importance/theme
- Include key numbers/facts

**PART 2: Analysis & Research**
Go beyond the mining stories. Research and incorporate:
1. Energy Markets: Power prices, grid conditions, renewable trends affecting mining
2. Policy/Regulatory: Crypto regulation, data center policy, mining taxes
3. Technology: Chip supply (Nvidia/TSMC), data center economics, cooling tech
4. Macro Context: BTC price drivers, institutional moves, broader crypto trends
5. Adjacent Industries: Cloud computing and AI compute demand, TX/UAE infrastructure

Connect dots across energy, policy, corporate actions, and global trends.

**PART 3: Key Implications**
Report factual implications and what industry experts are saying. DO NOT give advice or recommendations. Report what analysts observe, what data shows, questions raised, and emerging trends.

ETHICAL JOURNALISM STANDARDS (apply all):
- Seek truth and report it; verify facts; cite sources when possible
- Minimize harm; respect privacy
- Act independently; avoid conflicts of interest
- Be accountable and transparent about sources/methods
- Ensure fairness; present multiple perspectives
- Verify information rigorously
- Distinguish news from opinion; clearly label analysis
- Never prescribe actions or investment advice
- Attribute numerical claims and avoid sensationalism
- Use precise language and avoid loaded terms

STYLE:
- WSJ/FT quality; authoritative, analytical, factual
- Use grounded search to verify key claims and numbers
- Short paragraphs, precise numbers, zero hype, zero advice

OUTPUT FORMAT (Markdown):
# Daily Brief: {display_date}

## Today's Headlines

**Industry Shifts**
- [Story]: [Key fact/implication]

**Operations & Capacity**
- [Story]: [Key fact/implication]

**Market Moves**
- [Story]: [Key fact/implication]

## Analysis: [Thematic Headline]
[Editorial analysis enriched with research on energy, policy, tech trends, macro factors. Connect WHY NOW.]

## Key Implications
- [Theme]: [Factual observation grounded in sources]
"""

    try:
        client = genai.Client(api_key=api_key)
        grounding_tool = types.Tool(google_search=types.GoogleSearch())
        config = types.GenerateContentConfig(tools=[grounding_tool], temperature=0.7)
        logger.info("editorial_manual: generating with Google Search grounding…")
        response = client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=prompt,
            config=config,
        )
        content = response.text
    except Exception as e:
        logger.error(f"editorial_manual: generation failed: {e}")
        return ""

    # Write HTML post
    html = _generate_post_html(content, display_date, len(articles))
    posts_dir = pathlib.Path("docs/posts")
    posts_dir.mkdir(parents=True, exist_ok=True)
    post_filename = f"{date_str}-editorial-brief.html"
    (posts_dir / post_filename).write_text(html, encoding="utf-8")

    logger.info(f"editorial_manual: generated {post_filename} with {len(articles)} articles")

    # Update index
    _update_posts_index(post_filename, display_date, len(articles))
    return post_filename


MANUAL_ARTICLES: List[Dict] = [
    {
        "headline": "October Bitcoin Mining Report: Rising Costs and the AI Pivot Trend",
        "source_title": "BeInCrypto",
        "source_date": "Fri, 07 Nov 2025, 05:49",
        "bullets": [
            "Top miners modestly raised October output; network difficulty hit ATH; operating costs climbed.",
            "Consolidation expected in 2026 as miners integrate HPC/AI with BTC mining for efficiency.",
        ],
    },
    {
        "headline": "How to Start Mining Bitcoin? Top 8 Free Bitcoin Cloud Mining Sites",
        "source_title": "Live Bitcoin News",
        "source_date": "Fri, 07 Nov 2025, 06:01",
        "bullets": [
            "BTC > $100k revived retail interest; higher on-chain fees push some users toward cloud mining.",
            "Cites Statista/CoinMarketCap volumes up ~45% YoY; emphasizes low-capex alternatives.",
        ],
    },
    {
        "headline": "Texans' latest attempts to fight Bitcoin mining noise fails",
        "source_title": "CoinGeek",
        "source_date": "Fri, 07 Nov 2025, 07:17",
        "bullets": [
            "Hood County proposal to incorporate a city to regulate noise from a MARA site was rejected.",
            "Residents cite 2022-built site noise; local governance limits spotlight regulatory gaps.",
        ],
    },
    {
        "headline": "IREN rebounds from Bitcoin bust to $9.7B AI deal with Microsoft",
        "source_title": "Cryptopolitan",
        "source_date": "Fri, 07 Nov 2025, 02:14",
        "bullets": [
            "Pivoted to AI infrastructure ~18 months ago; now a $9.7B agreement with Microsoft (per Bloomberg).",
            "Founders Daniel & Will Roberts reoriented business from mining to AI cloud.",
        ],
    },
    {
        "headline": "Block spent ~$68 million on an event for employees last quarter, stock falls",
        "source_title": "Sherwood News",
        "source_date": "Fri, 07 Nov 2025, 06:26",
        "bullets": [
            "Block pursues mining hardware and BTC acceptance for merchants; shares slide on Q3 miss.",
            "Expense scrutiny as company pitches Bitcoin adjacency for growth.",
        ],
    },
    {
        "headline": "IREN glänzt im Quartal – Mining und Microsoft-Deal treiben Aktie",
        "source_title": "FinanzNachrichten.de",
        "source_date": "Fri, 07 Nov 2025, 02:30",
        "bullets": [
            "Quarter shows strong revenue and mining contribution; market reaction positive intraday.",
        ],
    },
    {
        "headline": "Cipher Mining Secures $1.4B to Launch Texas Data Center",
        "source_title": "CoinCu News",
        "source_date": "Thu, 06 Nov 2025, 21:04",
        "bullets": [
            "High-yield debt financing to build Barber Lake, TX data center; Google partner; Morgan Stanley underwriter.",
            "Signals shift from BTC mining to AI/data center infrastructure financing.",
        ],
    },
    {
        "headline": "American Bitcoin Adds 139 BTC; reserve reaches 4,004 BTC",
        "source_title": "Barchart.com",
        "source_date": "Fri, 07 Nov 2025, 06:41",
        "bullets": [
            "Reserve growth via mining plus strategic purchases since Oct 24; disclosed via PR.",
        ],
    },
    {
        "headline": "IREN glänzt – Microsoft-Deal treibt Aktie",
        "source_title": "wallstreet:online",
        "source_date": "Fri, 07 Nov 2025, 02:23",
        "bullets": [
            "Quarterly revenue ~$240.3M (period ending Sep 30, 2025) highlighted across coverage.",
        ],
    },
    {
        "headline": "Block shares tumble after-hours on Q3 earnings miss",
        "source_title": "Cointelegraph",
        "source_date": "Thu, 06 Nov 2025, 22:47",
        "bullets": [
            "Despite strong gross profit growth in Cash App & Square, EPS and revenue missed estimates.",
        ],
    },
    {
        "headline": "Block Inc. verzeichnet Kursrückgang nach enttäuschenden Quartalszahlen",
        "source_title": "IT BOLTWISE",
        "source_date": "Thu, 06 Nov 2025, 22:54",
        "bullets": [
            "German-language recap of Block’s results; shares fell materially post-earnings.",
        ],
    },
    {
        "headline": "Block Targets 19% Q4 Profit Growth",
        "source_title": "Yahoo! Finance (reprint)",
        "source_date": "Fri, 07 Nov 2025, 07:18",
        "bullets": [
            "Guidance points to ~19% gross profit growth into Q4 while pursuing BTC mining hardware strategy.",
        ],
    },
    {
        "headline": "American Bitcoin increases holdings to 4,004 BTC",
        "source_title": "StreetInsider",
        "source_date": "Fri, 07 Nov 2025, 06:47",
        "bullets": [
            "Confirms reserve figures; mix of self-mined and market purchases.",
        ],
    },
    {
        "headline": "IREN Aktie: Verzwickte Lage!",
        "source_title": "Börse Express",
        "source_date": "Fri, 07 Nov 2025, 07:07",
        "bullets": [
            "Despite $9.7B Microsoft deal and revenue growth, shares fell >12% after hours; investors cautious.",
        ],
    },
    {
        "headline": "IREN Reports Record Q1 Revenue; Microsoft deal accelerates AI Cloud",
        "source_title": "CoinDesk",
        "source_date": "Fri, 07 Nov 2025, 05:11",
        "bullets": [
            "$9.7B Microsoft partnership expected to drive ~$1.9B annualized AI Cloud revenue; new multi‑year contracts cited.",
        ],
    },
    {
        "headline": "Block Announces Third Quarter 2025 Results",
        "source_title": "Crypto Reporter (PR)",
        "source_date": "Fri, 07 Nov 2025, 04:15",
        "bullets": [
            "Company posted Q3 results and scheduled call; continues Bitcoin mining rig and merchant acceptance initiatives.",
        ],
    },
    {
        "headline": "Phoenix signs 30MW energy deal for Ethiopian data mine",
        "source_title": "African Review of Business and Technology",
        "source_date": "Fri, 07 Nov 2025, 02:30",
        "bullets": [
            "Abu Dhabi’s Phoenix Group to deploy 30MW hydropower-backed data mining facility in Addis Ababa.",
        ],
    },
    {
        "headline": "Could tech bros like Mike Cannon‑Brookes become the new climate pariahs?",
        "source_title": "The Age",
        "source_date": "Fri, 07 Nov 2025, 02:13",
        "bullets": [
            "Explores AI/data center energy footprints; investor pressure on cloud companies to justify AI spend.",
        ],
    },
    {
        "headline": "HIVE Digital to release fiscal Q2 2026 results Nov 17 (Newsfile)",
        "source_title": "StreetInsider / Barchart reprints",
        "source_date": "Fri, 07 Nov 2025, ~02:00",
        "bullets": [
            "Earnings date set; company positions as diversified digital infrastructure operator.",
        ],
    },
]


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    filename = generate_editorial_from_list(MANUAL_ARTICLES)
    if filename:
        print(f"Generated: docs/posts/{filename}")
    else:
        print("Failed to generate editorial brief from manual list")
