import os
import logging
import time
from typing import Tuple

try:
    import tweepy
except Exception:
    tweepy = None

logger = logging.getLogger(__name__)


def _has_x_credentials() -> bool:
    """Return True when all required X (Twitter) credentials are present."""
    required = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET")
    return all(os.getenv(k) for k in required)


def _truthy(val: str | None) -> bool:
    if not val:
        return False
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _client():
    # DRY-RUN or missing dependencies short-circuit
    if _truthy(os.getenv("DRY_RUN")) or not tweepy or not _has_x_credentials():
        return None

    x_api_key = os.getenv("X_API_KEY")
    x_api_secret = os.getenv("X_API_SECRET")
    x_access_token = os.getenv("X_ACCESS_TOKEN")
    x_access_token_secret = os.getenv("X_ACCESS_TOKEN_SECRET")

    # Use Tweepy v2 Client (Free tier supports create_tweet)

    try:
        client = tweepy.Client(
            consumer_key=x_api_key,
            consumer_secret=x_api_secret,
            access_token=x_access_token,
            access_token_secret=x_access_token_secret,
            wait_on_rate_limit=False,  # We'll handle limited, single retry ourselves
        )
        logger.info(
            "publisher: initialized Tweepy Client for v2 create_tweet (OAuth 1.0a user context)"
        )
        return client
    except Exception as e:
        logger.warning("publisher: failed to init tweepy client: %s", e)
        return None


def _extract_error_detail(exc: Exception) -> str:
    try:
        # Tweepy HTTPExceptions often have response with text/json
        resp = getattr(exc, "response", None)
        if resp is not None:
            try:
                return resp.text
            except Exception:
                pass
    except Exception:
        pass
    # Fallback string
    return str(exc)


def _rate_limit_wait_seconds(exc: Exception) -> float:
    """Best-effort parse of rate limit reset; fallback to env seconds."""
    try:
        resp = getattr(exc, "response", None)
        if resp is not None:
            reset = resp.headers.get("x-rate-limit-reset")
            if reset:
                try:
                    # Header is epoch seconds; add small buffer
                    wait_s = float(reset) - time.time() + 2.0
                    return max(5.0, min(wait_s, float(os.getenv("X_RATE_RETRY_MAX", "180"))))
                except Exception:
                    pass
    except Exception:
        pass
    return float(os.getenv("X_RATE_RETRY_SECONDS", "75"))


def _maybe_retry_rate_limited(client, create_kwargs) -> Tuple[str, str]:
    """Try create_tweet with one retry on rate limit. Returns (id, err)."""
    try:
        resp = client.create_tweet(**create_kwargs)
        tid = str(resp.data.get("id")) if getattr(resp, "data", None) else ""
        return tid, ""
    except tweepy.errors.TooManyRequests as e:
        if not _truthy(os.getenv("RETRY_ON_X_RATELIMIT", "1")):
            logger.warning("publisher: rate limit exceeded - no retry")
            return "", _extract_error_detail(e)
        wait_s = _rate_limit_wait_seconds(e)
        logger.warning("publisher: rate limit; retrying once after %.1fs", wait_s)
        time.sleep(wait_s)
        try:
            resp = client.create_tweet(**create_kwargs)
            tid = str(resp.data.get("id")) if getattr(resp, "data", None) else ""
            return tid, ""
        except Exception as e2:
            return "", _extract_error_detail(e2)
    except Exception as e:
        return "", _extract_error_detail(e)


def publish(tweet1: str, tweet2: str) -> Tuple[str, str]:
    """
    Publish two tweets (thread) via X API v2. Returns (id1, id2) or prints when not configured.
    """
    client = _client()
    if not client:
        logger.info("publisher: DRY-RUN or not configured; printing tweets")
        print("[DRY-RUN] Tweet 1:\n", tweet1)
        print("[DRY-RUN] Tweet 2:\n", tweet2)
        return "", ""

    # Optional sanity check: who are we posting as?
    try:
        me = client.get_me(user_auth=True)
        uid = str(getattr(getattr(me, "data", None), "id", "") or "")
        if uid:
            logger.info("publisher: authenticated as user_id=%s", uid)
    except Exception as e:
        logger.warning("publisher: get_me failed (continuing): %s", _extract_error_detail(e))

    # First tweet (with single retry on rate limit)
    tid1, err = _maybe_retry_rate_limited(client, {"text": tweet1, "user_auth": True})
    if not tid1:
        logger.warning("publisher: failed to create first tweet: %s", err or "unknown error")
        return "", ""
    
    logger.info("publisher: Tweet 1 posted (id=%s). Posting reply...", tid1)

    # Reply with second tweet (URL) (also retry once on rate limit)
    tid2, err2 = _maybe_retry_rate_limited(
        client,
        {"text": tweet2, "in_reply_to_tweet_id": tid1, "user_auth": True},
    )
    if err2:
        logger.warning("publisher: failed to create reply tweet: %s", err2)
        # Rollback: attempt to delete the first tweet so we don't leave a half-thread
        try:
            logger.info("publisher: attempting rollback (deleting tweet %s)", tid1)
            client.delete_tweet(tid1)
            logger.info("publisher: rollback successful")
        except Exception as e:
            logger.error("publisher: rollback failed for tweet %s: %s", tid1, e)
        # Return empty so main.py knows it failed and can retry later
        return "", ""

    return tid1, tid2
