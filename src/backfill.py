import os
import logging
from dotenv import load_dotenv

from src.news_fetcher import fetch_bitcoin_mining_articles
from src.article_queue import push_many, _load as _load_queue
from src.state import already_posted
from src.logging_setup import setup_logging


def run():
    load_dotenv()
    setup_logging()
    logger = logging.getLogger("backfill")

    # Override max hours to 5 days (120 hours)
    os.environ["ARTICLES_MAX_HOURS"] = "120"

    # Fetch a larger batch
    limit = 50
    query = os.getenv("TOPIC_QUERY", "bitcoin mining")

    logger.info("backfill: fetching up to %d articles from the last 5 days...", limit)
    articles = fetch_bitcoin_mining_articles(limit=limit, query=query) or []

    logger.info("backfill: fetched %d raw candidates", len(articles))

    # Filter out already posted
    candidates = []
    window_hours = 120  # 5 days

    for art in articles:
        if not already_posted(
            url=art.get("url", ""),
            event_uri=art.get("event_uri", ""),
            fingerprint=art.get("fingerprint", ""),
            article_uri=art.get("article_uri", ""),
            story_uri=art.get("story_uri", ""),
            window_hours=window_hours,
            event_window_hours=window_hours,
        ):
            candidates.append(art)

    logger.info("backfill: %d candidates remain after checking posted history", len(candidates))

    if candidates:
        # Push to queue (reverse order so oldest is at bottom of stack, but we want LIFO?
        # Actually, push_many appends. If we want them to be popped in order of relevance/recency...
        # The queue is LIFO (pop() takes from end).
        # fetch_bitcoin_mining_articles returns sorted by relevance/date (best first).
        # If we want the BEST articles to be popped FIRST, they should be at the END of the list.
        # So we should append them in reverse order (worst to best), or just append them as is?
        # push_many appends.
        # If 'candidates' is [Best, 2ndBest, ... Worst]
        # push_many([Best, 2ndBest]) -> Queue: [..., Best, 2ndBest]
        # pop() -> 2ndBest.
        # Wait, if we want Best popped first, it should be at the end.
        # So push_many([Best, 2ndBest]) results in [..., Best, 2ndBest].
        # pop() gives 2ndBest.
        # So we actually want to push in REVERSE order of 'candidates' if 'candidates' is sorted Best->Worst.
        # candidates is [Best, ... Worst].
        # reversed(candidates) is [Worst, ... Best].
        # push_many(reversed) -> Queue: [..., Worst, ..., Best].
        # pop() -> Best. Correct.

        push_many(list(reversed(candidates)))
        logger.info("backfill: pushed %d items to queue", len(candidates))

        q_size = len(_load_queue())
        logger.info("backfill: new queue size is %d", q_size)
    else:
        logger.info("backfill: no new items to queue")


if __name__ == "__main__":
    run()
