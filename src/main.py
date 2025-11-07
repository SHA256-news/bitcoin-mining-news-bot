import os
import logging
from dotenv import load_dotenv

from src.news_fetcher import fetch_bitcoin_mining_articles
from src.summarizer import summarize_for_miners
from src.formatter import compose_tweet_1, compose_tweet_2, sanitize_summary
from src.publisher import publish
from src.state import already_posted, mark_posted, save_fetched_article


def _init_logging():
    # Centralized JSON logging (set LOG_PLAIN=1 for text)
    from src.logging_setup import setup_logging

    setup_logging()


def _truthy(val: str | None) -> bool:
    return bool(val) and val.strip().lower() in {"1", "true", "yes", "on"}


def run():
    load_dotenv()
    _init_logging()
    logger = logging.getLogger("main")

    # One-time queue cleanup: dedupe, purge banned tokens, purge posted, collapse company duplicates (keep most authoritative domain)
    try:
        from src.queue import (
            dedupe as _dedupe_queue,
            purge_banned_crypto as _purge_crypto,
            purge_posted as _purge_posted,
            purge_company_duplicates_keep_best_domain as _purge_company_dupes,
        )

        _dedupe_queue()
        removed_c = _purge_crypto()
        removed_p = _purge_posted(event_hours=int(os.getenv("QUEUE_POST_EVENT_SKIP_HOURS", "168") or "168"))
        removed_company = _purge_company_dupes()
        logger.info(
            "main: queue cleanup done deduped=1 purged_crypto=%s purged_posted=%s purged_company_dupes=%s",
            removed_c,
            removed_p,
            removed_company,
        )
    except Exception:
        pass

    # Optional: sync posted from X (with keyword fallback) to prevent re-queueing older stories
    if _truthy(os.getenv("SYNC_POSTED_FROM_X")):
        try:
            from src.sync_posted import sync_posted_from_x

            summary = sync_posted_from_x()
            logger.info(
                "main: synced posted from X: %s",
                summary,
            )
        except Exception as e:
            logger.warning("main: sync_posted_from_x failed: %s", e)

    # Default to 5 to ensure we consider multiple candidates per run
    limit_str = os.getenv("ARTICLES_LIMIT", "5").strip()
    limit = int(limit_str) if limit_str else 5
    query = os.getenv("TOPIC_QUERY", "bitcoin mining")
    dry_run = _truthy(os.getenv("DRY_RUN"))
    skip_summarizer = _truthy(os.getenv("SKIP_SUMMARIZER"))

    # Respect daily Gemini budget: cap items to remaining across models
    from src.state import gemini_remaining

    remaining_pro = gemini_remaining(os.getenv("GEMINI_MODEL", "gemini-2.5-pro"))
    remaining_flash = gemini_remaining(os.getenv("GEMINI_FLASH_MODEL", "gemini-2.5-flash"))
    budget_cap = max(1, min(limit, remaining_pro + remaining_flash))

    articles = (fetch_bitcoin_mining_articles(limit=limit, query=query) or [])[:budget_cap]
    prepared = []
    # Configurable de-dup windows
    window_hours = int(os.getenv("DEDUP_WINDOW_HOURS", "72") or "72")
    event_window_hours = os.getenv("EVENT_DEDUP_HOURS")
    event_window_hours = (
        int(event_window_hours) if (event_window_hours or "").strip().isdigit() else window_hours
    )

    def _dedupe_prepared(items: list[dict]) -> list[dict]:
        seen: set[str] = set()
        out: list[dict] = []
        for it in items:
            k = (
                (it.get("event_uri") or "").strip()
                or (it.get("fingerprint") or "").strip()
                or (it.get("article_uri") or "").strip()
                or (it.get("url") or "").strip()
            )
            if not k or k in seen:
                continue
            seen.add(k)
            out.append(it)
        return out

    for art in articles:
        url = art.get("url", "")
        event_uri = art.get("event_uri", "")
        article_uri = art.get("article_uri", "")
        fp = art.get("fingerprint", "")
        source_title = art.get("title", "")
        # Bypass dedup if DRY_RUN, otherwise enforce configured windows
        if not dry_run and already_posted(
            url=url,
            event_uri=event_uri,
            fingerprint=fp,
            article_uri=article_uri,
            window_hours=window_hours,
            event_window_hours=event_window_hours,
        ):
            logger.info(
                "main: skipping already-posted article event=%s url=%s",
                event_uri,
                url,
            )
            continue
        if skip_summarizer:
            # Stage raw title without calling Gemini; don't save fetched article
            head = (source_title or "Bitcoin mining update").strip()[:120] or "Bitcoin mining update"
            prepared.append(
                {
                    "headline": head,
                    "bullets": [],
                    "url": url,
                    "event_uri": event_uri,
                    "article_uri": article_uri,
                    "fingerprint": fp,
                }
            )
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
                "article_uri": article_uri,
                "fingerprint": fp,
            }
        )

    # If skip_summarizer: stage and exit early to avoid any Gemini usage
    if skip_summarizer:
        if prepared:
            from src.queue import push_many
            post_event_skip_hours = int(os.getenv("POST_EVENT_SKIP_HOURS", "72") or "72")
            to_stage = [
                it
                for it in _dedupe_prepared(prepared)
                if not already_posted(
                    url=it.get("url", ""),
                    event_uri=it.get("event_uri", ""),
                    fingerprint=it.get("fingerprint", ""),
                    article_uri=it.get("article_uri", ""),
                    window_hours=window_hours,
                    event_window_hours=post_event_skip_hours,
                )
            ]
            if to_stage:
                push_many(to_stage)
        return

    # DRY_RUN: preview all threads
    if dry_run:
        # Stage prepared items into the queue so a subsequent real run can post the newest first
        if prepared:
            from src.queue import push_many
            # Skip anything already posted within the posting decision window
            post_event_skip_hours = int(os.getenv("POST_EVENT_SKIP_HOURS", "72") or "72")
            to_stage = [
                it
                for it in _dedupe_prepared(prepared)
                if not already_posted(
                    url=it.get("url", ""),
                    event_uri=it.get("event_uri", ""),
                    fingerprint=it.get("fingerprint", ""),
                    article_uri=it.get("article_uri", ""),
                    window_hours=window_hours,
                    event_window_hours=post_event_skip_hours,
                )
            ]
            if to_stage:
                push_many(to_stage)
        for item in prepared:
            t1 = compose_tweet_1(item["headline"], item["bullets"])
            t2 = compose_tweet_2(item["url"])
            publish(t1, t2)
        return

    # Real run: choose the newest non-duplicate candidate first; queue the rest
    from src.queue import push_many, pop_one

    # Strict skip window for posting decision (independent of EVENT_DEDUP_HOURS)
    post_event_skip_hours = int(os.getenv("POST_EVENT_SKIP_HOURS", "72") or "72")

    # Filter prepared items for a non-duplicate candidate to post now
    post_candidates = []
    for item in prepared:
        if not already_posted(
            url=item.get("url", ""),
            event_uri=item.get("event_uri", ""),
            fingerprint=item.get("fingerprint", ""),
            article_uri=item.get("article_uri", ""),
            window_hours=window_hours,
            event_window_hours=post_event_skip_hours,
        ):
            post_candidates.append(item)

    posted = False
    if post_candidates:
        item = post_candidates[0]
        t1 = compose_tweet_1(item["headline"], item["bullets"])
        t2 = compose_tweet_2(item["url"])
        tid1, tid2 = publish(t1, t2)
        # Stage ALL prepared items (including the used one) into the queue, newest first, minus the one we just used
        rest = [x for x in prepared if x is not item]
        if rest:
            # Skip anything already posted within the posting decision window
            rest2 = [
                it
                for it in _dedupe_prepared(rest)
                if not already_posted(
                    url=it.get("url", ""),
                    event_uri=it.get("event_uri", ""),
                    fingerprint=it.get("fingerprint", ""),
                    article_uri=it.get("article_uri", ""),
                    window_hours=window_hours,
                    event_window_hours=post_event_skip_hours,
                )
            ]
            if rest2:
                push_many(rest2)
        if tid1:
            posted = True
            # Only mark as posted on success
            mark_posted(
                url=item["url"],
                event_uri=item["event_uri"],
                article_uri=item.get("article_uri", ""),
                fingerprint=item["fingerprint"],
            )
        else:
            logger.warning(
                "main: publish failed event=%s fp=%s url=%s",
                item.get("event_uri", ""),
                item.get("fingerprint", ""),
                item.get("url", ""),
            )
            # Requeue the failed candidate so it can be attempted next run
            push_many([item])
    else:
        # No fresh candidates found; push all prepared into queue for later
        if prepared:
            # Skip anything already posted within the posting decision window
            post_event_skip_hours = int(os.getenv("POST_EVENT_SKIP_HOURS", "72") or "72")
            to_stage = [
                it
                for it in _dedupe_prepared(prepared)
                if not already_posted(
                    url=it.get("url", ""),
                    event_uri=it.get("event_uri", ""),
                    fingerprint=it.get("fingerprint", ""),
                    article_uri=it.get("article_uri", ""),
                    window_hours=window_hours,
                    event_window_hours=post_event_skip_hours,
                )
            ]
            if to_stage:
                push_many(to_stage)

    if not posted:
        # Try queue fallback, skipping duplicates within the posting decision window
        q = pop_one()
        while q and already_posted(
            url=q.get("url", ""),
            event_uri=q.get("event_uri", ""),
            fingerprint=q.get("fingerprint", ""),
            article_uri=q.get("article_uri", ""),
            window_hours=window_hours,
            event_window_hours=post_event_skip_hours,
        ):
            q = pop_one()
        if q:
            t1 = compose_tweet_1(q["headline"], q["bullets"])
            t2 = compose_tweet_2(q["url"])
            tid1, tid2 = publish(t1, t2)
            if tid1:
                mark_posted(
                    url=q.get("url", ""),
                    event_uri=q.get("event_uri", ""),
                    article_uri=q.get("article_uri", ""),
                    fingerprint=q.get("fingerprint", ""),
                )
            else:
                logger.warning(
                    "main: publish failed (queue) event=%s fp=%s url=%s",
                    q.get("event_uri", ""),
                    q.get("fingerprint", ""),
                    q.get("url", ""),
                )
                # Requeue the item to avoid losing it on transient failures (e.g., rate limits)
                from src.queue import push_many as _requeue
                _requeue([q])


if __name__ == "__main__":
    run()
