import os
import logging
from dotenv import load_dotenv

from src.news_fetcher import fetch_bitcoin_mining_articles
from src.summarizer import summarize_for_miners
from src.formatter import compose_tweet_1, compose_tweet_2, sanitize_summary
from src.publisher import publish
from src.state import already_posted, mark_posted, save_fetched_article


def _init_logging():
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _truthy(val: str | None) -> bool:
    return bool(val) and val.strip().lower() in {"1", "true", "yes", "on"}


def run():
    load_dotenv()
    _init_logging()
    logger = logging.getLogger("main")

    limit_str = os.getenv("ARTICLES_LIMIT", "1").strip()
    limit = int(limit_str) if limit_str else 1
    query = os.getenv("TOPIC_QUERY", "bitcoin mining")
    dry_run = _truthy(os.getenv("DRY_RUN"))

    # Respect daily Gemini budget: cap items to remaining across models
    from src.state import gemini_remaining

    remaining_pro = gemini_remaining(os.getenv("GEMINI_MODEL", "gemini-2.5-pro"))
    remaining_flash = gemini_remaining(os.getenv("GEMINI_FLASH_MODEL", "gemini-2.5-flash"))
    budget_cap = max(1, min(limit, remaining_pro + remaining_flash))

    articles = (fetch_bitcoin_mining_articles(limit=limit, query=query) or [])[:budget_cap]
    prepared = []
    for art in articles:
        url = art.get("url", "")
        event_uri = art.get("event_uri", "")
        fp = art.get("fingerprint", "")
        source_title = art.get("title", "")
        # Bypass dedup if DRY_RUN, otherwise enforce 72h dedup
        if not dry_run and already_posted(
            url=url, event_uri=event_uri, fingerprint=fp, window_hours=72
        ):
            logger.info("main: skipping already-posted event=%s fp=%s url=%s", event_uri, fp, url)
            continue
        headline, bullets = summarize_for_miners(art)
        if not headline or not bullets:
            logger.info("main: skipping not-relevant article event=%s url=%s", event_uri, url)
            continue
        # Deterministic de-dup across headline/bullets
        headline2, bullets2 = sanitize_summary(headline, bullets, source_title)
        if not bullets2:
            logger.info(
                "main: skipping after sanitize (empty bullets) event=%s url=%s", event_uri, url
            )
            continue
        # Save to fetched_articles for daily brief (regardless of whether posted to Twitter)
        save_fetched_article(
            fingerprint=fp,
            headline=headline2,
            bullets=bullets2,
            url=url,
            event_uri=event_uri,
            source_title=source_title,
            source_date=art.get("date", ""),
        )
        prepared.append(
            {
                "headline": headline2,
                "bullets": bullets2,
                "url": url,
                "event_uri": event_uri,
                "fingerprint": fp,
            }
        )

    # DRY_RUN: preview all threads
    if dry_run:
        for item in prepared:
            t1 = compose_tweet_1(item["headline"], item["bullets"])
            t2 = compose_tweet_2(item["url"])
            publish(t1, t2)
        return

    # Real run: 1-per-execution: post one, queue the rest
    from src.queue import push_many, pop_one

    posted = False
    if prepared:
        item = prepared[0]
        t1 = compose_tweet_1(item["headline"], item["bullets"])
        t2 = compose_tweet_2(item["url"])
        tid1, tid2 = publish(t1, t2)
        if tid1:
            posted = True
            if len(prepared) > 1:
                push_many(prepared[1:])
        else:
            logger.warning(
                "main: publish failed event=%s fp=%s url=%s",
                item.get("event_uri", ""),
                item.get("fingerprint", ""),
                item.get("url", ""),
            )
        # Always mark as posted (even on failure) to prevent duplicate attempts
        mark_posted(
            url=item["url"], event_uri=item["event_uri"], fingerprint=item["fingerprint"]
        )
    if not posted:
        q = pop_one()
        if q:
            t1 = compose_tweet_1(q["headline"], q["bullets"])
            t2 = compose_tweet_2(q["url"])
            tid1, tid2 = publish(t1, t2)
            if not tid1:
                logger.warning(
                    "main: publish failed (queue) event=%s fp=%s url=%s",
                    q.get("event_uri", ""),
                    q.get("fingerprint", ""),
                    q.get("url", ""),
                )
            # Always mark as posted (even on failure) to prevent duplicate attempts
            mark_posted(
                url=q.get("url", ""),
                event_uri=q.get("event_uri", ""),
                fingerprint=q.get("fingerprint", ""),
            )


if __name__ == "__main__":
    run()
