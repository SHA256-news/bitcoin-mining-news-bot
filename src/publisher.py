import os
import logging
from typing import Tuple

try:
    import tweepy
except Exception:
    tweepy = None

logger = logging.getLogger(__name__)


def _truthy(val: str | None) -> bool:
    if not val:
        return False
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _client():
    # DRY-RUN short-circuit
    if _truthy(os.getenv("DRY_RUN")):
        return None

    x_api_key = os.getenv("X_API_KEY")
    x_api_secret = os.getenv("X_API_SECRET")
    x_access_token = os.getenv("X_ACCESS_TOKEN")
    x_access_token_secret = os.getenv("X_ACCESS_TOKEN_SECRET")

    # Use Tweepy v2 Client (Free tier supports create_tweet)
    if not all([x_api_key, x_api_secret, x_access_token, x_access_token_secret, tweepy]):
        return None

    try:
        client = tweepy.Client(
            consumer_key=x_api_key,
            consumer_secret=x_api_secret,
            access_token=x_access_token,
            access_token_secret=x_access_token_secret,
            wait_on_rate_limit=True,
        )
        logger.info("publisher: initialized Tweepy Client for v2 create_tweet (OAuth 1.0a user context)")
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

    # First tweet
    try:
        resp1 = client.create_tweet(text=tweet1, user_auth=True)
        tid1 = str(resp1.data.get("id")) if getattr(resp1, "data", None) else ""
    except Exception as e:
        logger.error("publisher: failed to create first tweet (v2 /2/tweets): %s", _extract_error_detail(e))
        return "", ""

    # Reply with second tweet (URL)
    try:
        resp2 = client.create_tweet(text=tweet2, in_reply_to_tweet_id=tid1 if tid1 else None, user_auth=True)
        tid2 = str(resp2.data.get("id")) if getattr(resp2, "data", None) else ""
    except Exception as e:
        logger.error("publisher: failed to create reply tweet: %s", _extract_error_detail(e))
        tid2 = ""

    return tid1, tid2
