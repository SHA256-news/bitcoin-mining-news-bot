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
    if not val:
        return False
    return val.strip().lower() in {"1", "true", "yes", "on"}


def run():
    load_dotenv()
    _init_logging()
    logger = logging.getLogger("main")

    # One-time queue cleanup: dedupe, purge banned tokens, purge posted, collapse company duplicates (keep most authoritative domain)
    try:
        from src.article_queue import (
            dedupe as _dedupe_queue,
            purge_banned_crypto as _purge_crypto,
            purge_posted as _purge_posted,
            purge_company_duplicates_keep_best_domain as _purge_company_dupes,
        )

        _dedupe_queue()
        removed_c = _purge_crypto()
        removed_p = _purge_posted(event_hours=int(os.getenv("POST_EVENT_SKIP_HOURS", "72") or "72"))
        removed_company = _purge_company_dupes()

        # Get current queue size for logging
        from src.article_queue import _load as _load_queue

        q_size = len(_load_queue())

        logger.info(
            "main: queue cleanup done size=%d purged_crypto=%s purged_posted=%s purged_company_dupes=%s",
            q_size,
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
    skip_summarizer = _truthy(os.getenv("SKIP_SUMMARIZER"))

    # Respect daily Gemini budget: cap items to remaining across models
    from src.state import gemini_remaining

    remaining_pro = gemini_remaining(os.getenv("GEMINI_MODEL", "gemini-2.5-pro"))
    remaining_flash = gemini_remaining(os.getenv("GEMINI_FLASH_MODEL", "gemini-2.5-flash"))
    budget_cap = max(1, min(limit, remaining_pro + remaining_flash))

    articles = (fetch_bitcoin_mining_articles(limit=limit, query=query) or [])[:budget_cap]

    # Configurable de-dup windows
    window_hours = int(os.getenv("DEDUP_WINDOW_HOURS", "72") or "72")
    # EVENT_DEDUP_HOURS controls how long we treat an Event Registry event URI as
    # "recent". Values <= 0 or invalid values fall back to the main window so we
    # never accidentally disable event-based deduplication.

    def _dedupe_prepared(items: list[dict]) -> list[dict]:
        """Deduplicate prepared items using story/article/event URIs, then fingerprint, then URL.

        This mirrors the StoryIdentity priority: article_uri > story_uri > event_uri
        > fingerprint > url. Within a single run this prevents us from staging
        multiple variants of the same underlying story.
        """
        seen: set[str] = set()
        out: list[dict] = []
        for it in items:
            k = (
                (it.get("article_uri") or "").strip()
                or (it.get("story_uri") or "").strip()
                or (it.get("event_uri") or "").strip()
                or (it.get("fingerprint") or "").strip()
                or (it.get("url") or "").strip()
            )
            if not k or k in seen:
                continue
            seen.add(k)
            out.append(it)
        return out

    def _queue_candidates(
        items: list[dict],
        window_hours: int,
    ) -> list[dict]:
        """Return deduped items that are not already posted in the given windows."""
        return [
            it
            for it in _dedupe_prepared(items)
            if not already_posted(
                url=it.get("url", ""),
                event_uri=it.get("event_uri", ""),
                fingerprint=it.get("fingerprint", ""),
                article_uri=it.get("article_uri", ""),
                story_uri=it.get("story_uri", ""),
                window_hours=window_hours,
                event_window_hours=window_hours,
            )
        ]

    def _fallback_from_queue(
        window_hours: int,
        post_event_skip_hours: int,
    ) -> None:
        """Try posting one item from the queue when nothing new was posted.

        Follows the existing behavior: skip duplicates, publish once,
        mark as posted on success, and requeue on failure.
        """
        from src.article_queue import pop_one

        # Try up to 3 times to find a postable item
        failed_items = []
        for _ in range(3):
            q = pop_one()
            while q and already_posted(
                url=q.get("url", ""),
                event_uri=q.get("event_uri", ""),
                fingerprint=q.get("fingerprint", ""),
                article_uri=q.get("article_uri", ""),
                story_uri=q.get("story_uri", ""),
                window_hours=window_hours,
                event_window_hours=post_event_skip_hours,
            ):
                q = pop_one()

            if not q:
                break

            # JIT Summarization for queue items
            headline = q.get("headline", "")
            bullets = q.get("bullets", [])

            # If no bullets, we need to summarize (unless it's a dry run skip or we have a cache hit inside summarize)
            if not bullets:
                # We need to reconstruct a minimal article dict for the summarizer
                # The queue item might not have the full text, but hopefully it has enough or we can fetch?
                # Actually, the queue item IS the article dict usually.
                h, b = summarize_for_miners(q)
                if not h or not b:
                    logger.info("main: queue item not relevant after summary: %s", q.get("url"))
                    continue

                # Sanitize
                h2, b2 = sanitize_summary(h, b, q.get("title", ""))
                if not b2:
                    logger.info("main: queue item empty bullets after sanitize: %s", q.get("url"))
                    continue

                headline = h2
                bullets = b2

                # Update the item with the new summary so we don't re-summarize if we fail to post and re-queue
                q["headline"] = headline
                q["bullets"] = bullets

                # Also save to fetched articles for daily brief visibility
                save_fetched_article(
                    fingerprint=q.get("fingerprint", ""),
                    headline=headline,
                    bullets=bullets,
                    url=q.get("url", ""),
                    event_uri=q.get("event_uri", ""),
                    source_title=q.get("title", ""),
                    source_date=q.get("date", ""),
                )

            t1 = compose_tweet_1(headline, bullets)
            t2 = compose_tweet_2(q["url"])
            tid1, tid2 = publish(t1, t2)
            if tid1:
                mark_posted(
                    url=q.get("url", ""),
                    event_uri=q.get("event_uri", ""),
                    article_uri=q.get("article_uri", ""),
                    story_uri=q.get("story_uri", ""),
                    fingerprint=q.get("fingerprint", ""),
                    tweet_id=str(tid1),
                )
                # Success! Stop trying.
                break
            else:
                logger.warning(
                    "main: publish failed (queue) event=%s fp=%s url=%s",
                    q.get("event_uri", ""),
                    q.get("fingerprint", ""),
                    q.get("url", ""),
                )
                failed_items.append(q)

        if failed_items:
            from src.article_queue import bury_many

            bury_many(failed_items)

    # -------------------------------------------------------------------------
    # JIT Summarization Logic
    # -------------------------------------------------------------------------

    # 1. Filter candidates that are NOT already posted
    # Strict skip window for posting decision
    post_event_skip_hours = int(os.getenv("POST_EVENT_SKIP_HOURS", "72") or "72")

    candidates = _queue_candidates(articles, window_hours)

    # 2. If we have candidates, try to summarize and post the first valid one
    posted = False

    if candidates:
        # We iterate through candidates. The first one that passes summarization gets posted.
        # The rest get queued as raw.

        for i, art in enumerate(candidates):
            url = art.get("url", "")
            event_uri = art.get("event_uri", "")
            fp = art.get("fingerprint", "")
            source_title = art.get("title", "")

            if skip_summarizer:
                # Fast path for testing/skipping AI
                head = (source_title or "Bitcoin mining update").strip()[
                    :120
                ] or "Bitcoin mining update"
                art["headline"] = head
                art["bullets"] = []

                # Post immediately
                t1 = compose_tweet_1(head, [])
                t2 = compose_tweet_2(url)
                tid1, tid2 = publish(t1, t2)

                if tid1:
                    posted = True
                    mark_posted(
                        url=url,
                        event_uri=event_uri,
                        article_uri=art.get("article_uri", ""),
                        story_uri=art.get("story_uri", ""),
                        fingerprint=fp,
                        tweet_id=str(tid1),
                    )
                    # Queue the REST of the candidates (raw)
                    remaining = candidates[i + 1 :]
                    if remaining:
                        from src.article_queue import push_many

                        push_many(list(reversed(remaining)))
                    break  # Done
                else:
                    # Failed to publish, maybe try next? Or just queue it?
                    # Existing logic usually retries or queues. Let's queue it and try next.
                    from src.article_queue import push_many

                    push_many([art])
                    continue

            # Real Summarization
            headline, bullets = summarize_for_miners(art)

            if not headline or not bullets:
                logger.info("main: skipping not-relevant article event=%s url=%s", event_uri, url)
                # It was processed but rejected. Do NOT queue it.
                continue

            # Deterministic de-dup across headline/bullets
            headline2, bullets2 = sanitize_summary(headline, bullets, source_title)
            if not bullets2:
                logger.info(
                    "main: skipping after sanitize (empty bullets) event=%s url=%s", event_uri, url
                )
                continue

            # Save to fetched_articles for daily brief
            save_fetched_article(
                fingerprint=fp,
                headline=headline2,
                bullets=bullets2,
                url=url,
                event_uri=event_uri,
                source_title=source_title,
                source_date=art.get("date", ""),
            )

            # Update article object
            art["headline"] = headline2
            art["bullets"] = bullets2

            # Attempt to publish
            t1 = compose_tweet_1(headline2, bullets2)
            t2 = compose_tweet_2(url)
            tid1, tid2 = publish(t1, t2)

            if tid1:
                posted = True
                mark_posted(
                    url=url,
                    event_uri=event_uri,
                    article_uri=art.get("article_uri", ""),
                    story_uri=art.get("story_uri", ""),
                    fingerprint=fp,
                    tweet_id=str(tid1),
                )

                # We successfully posted.
                # Queue the REST of the candidates (raw) for later.
                # We do NOT queue the one we just posted.
                remaining = candidates[i + 1 :]
                if remaining:
                    from src.article_queue import push_many

                    # Push in reverse order so the first item in 'remaining' (the next best candidate)
                    # ends up at the top of the stack (last in list).
                    push_many(list(reversed(remaining)))

                break  # Stop processing candidates
            else:
                logger.warning("main: publish failed event=%s fp=%s url=%s", event_uri, fp, url)
                # Failed to publish valid content. Queue it so we can try again later (maybe transient error).
                from src.article_queue import push_many

                push_many([art])
                # Continue to try the next candidate in this run?
                # Yes, let's try to find *something* to post.
                continue

    # 3. If we went through all candidates and posted nothing (or had no candidates), try queue fallback
    if not posted:
        # If we had candidates but none were relevant/postable, they are already handled (rejected or queued if failed publish)
        # So we just fall back to the queue.

        # Note: If we had candidates but they were all rejected as irrelevant, we effectively "wasted" those API calls
        # but that's the price of filtering. We still want to try the queue.

        # However, if we had candidates and simply didn't post because they were irrelevant,
        # we should make sure we didn't lose the "raw" ones that we didn't even touch?
        # The loop `for i, art in enumerate(candidates)` goes through ALL of them if we don't break.
        # So if we finish the loop and posted=False, it means we checked everyone and they were either irrelevant or failed publish.
        # So nothing left to queue from `candidates`.

        _fallback_from_queue(window_hours, post_event_skip_hours)


if __name__ == "__main__":
    run()
