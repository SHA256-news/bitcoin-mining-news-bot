import os
import re
from typing import List, Dict, Optional

from src.state import mark_posted
from src.queue import _load as _queue_load, purge_posted


def _extract_keywords(text: str) -> List[str]:
    s = (text or "").strip()
    if not s:
        return []
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9.'-]{2,}", s)
    stop = {
        "bitcoin",
        "mining",
        "miners",
        "ceo",
        "board",
        "directors",
        "company",
        "companies",
        "public",
        "nasdaq",
        "shares",
        "stock",
        "inc",
        "llc",
        "corp",
        "ltd",
        "co",
        "and",
        "the",
        "for",
        "of",
        "with",
        "to",
        "a",
        "an",
        "on",
        "at",
    }
    kws = []
    for t in tokens:
        tl = t.lower().strip(".-')(")
        if len(tl) < 3 or tl in stop:
            continue
        kws.append(tl)
    # de-dup preserve order
    seen = set()
    out = []
    for k in kws:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out[:8]


def _match_unique_queue_item(head_text: str) -> Optional[Dict]:
    keywords = _extract_keywords(head_text)
    if not keywords:
        return None
    q = _queue_load()
    scored = []
    for it in q:
        title = (it.get("headline") or "").lower()
        score = sum(1 for k in keywords if k and k in title)
        if score:
            scored.append((score, it))
    if not scored:
        return None
    # If exactly one item has the max score and it's >= 2, choose it
    scored.sort(key=lambda x: x[0], reverse=True)
    max_score = scored[0][0]
    if max_score >= 2 and sum(1 for s, _ in scored if s == max_score) == 1:
        return scored[0][1]
    # Else if exactly one item matched at all (score>=1), choose it
    if len(scored) == 1:
        return scored[0][1]
    return None


def sync_posted_from_x(max_heads: int = 50) -> Dict:
    """Sync posted URLs from X thread heads; if a reply has no URL, match by keywords to a unique queue item and mark its URL as posted.

    Returns summary dict with counts.
    """
    try:
        import tweepy  # type: ignore
    except Exception:
        return {"synced": 0, "fallback_matched": 0, "purged": 0, "reason": "tweepy_not_installed"}

    x_api_key = os.getenv("X_API_KEY")
    x_api_secret = os.getenv("X_API_SECRET")
    x_access_token = os.getenv("X_ACCESS_TOKEN")
    x_access_token_secret = os.getenv("X_ACCESS_TOKEN_SECRET")
    if not all([x_api_key, x_api_secret, x_access_token, x_access_token_secret]):
        return {"synced": 0, "fallback_matched": 0, "purged": 0, "reason": "missing_x_creds"}

    client = tweepy.Client(
        consumer_key=x_api_key,
        consumer_secret=x_api_secret,
        access_token=x_access_token,
        access_token_secret=x_access_token_secret,
        wait_on_rate_limit=True,
    )

    me = client.get_me(user_auth=True).data
    resp = client.get_users_tweets(
        id=me.id,
        max_results=100,
        tweet_fields=[
            "created_at",
            "in_reply_to_user_id",
            "referenced_tweets",
            "conversation_id",
            "entities",
            "text",
        ],
        user_auth=True,
    )
    tweets = resp.data or []
    by_conv: Dict[str, List] = {}
    for t in tweets:
        by_conv.setdefault(str(t.conversation_id), []).append(t)

    def is_reply_to(t, parent_id: str) -> bool:
        refs = getattr(t, "referenced_tweets", None) or []
        for r in refs:
            try:
                if getattr(r, "type", None) == "replied_to" and str(getattr(r, "id", "")) == str(
                    parent_id
                ):
                    return True
            except Exception:
                pass
        return False

    def extract_url(t) -> str:
        ents = getattr(t, "entities", None) or {}
        urls = ents.get("urls") if isinstance(ents, dict) else None
        if urls:
            for u in urls:
                eu = u.get("expanded_url") or u.get("url")
                if eu and eu.startswith("http"):
                    return eu
        m = re.search(r"https?://\S+", getattr(t, "text", "") or "")
        return m.group(0) if m else ""

    synced = 0
    fallback = 0

    heads = []
    for _, arr in by_conv.items():
        arr.sort(key=lambda x: x.created_at)
        head = next((t for t in arr if getattr(t, "in_reply_to_user_id", None) in (None, "")), None)
        if not head:
            continue
        reply = next((t for t in arr if t is not head and is_reply_to(t, head.id)), None)
        url = extract_url(reply) if reply else ""
        heads.append((head, url))

    for head, url in heads[:max_heads]:
        if url:
            mark_posted(url=url)
            synced += 1
            continue
        # Fallback match by keywords from head text
        cand = _match_unique_queue_item(getattr(head, "text", "") or "")
        if cand and cand.get("url"):
            mark_posted(url=cand["url"])
            fallback += 1

    purged = purge_posted(event_hours=int(os.getenv("QUEUE_POST_EVENT_SKIP_HOURS", "168") or "168"))
    return {"synced": synced, "fallback_matched": fallback, "purged": purged}


if __name__ == "__main__":
    import json
    import sys
    from dotenv import load_dotenv

    # Load .env if present (no stack introspection)
    load_dotenv(".env")
    try:
        summary = sync_posted_from_x()
        print(json.dumps(summary))
        if summary.get("reason") == "missing_x_creds":
            sys.exit(2)
        sys.exit(0)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
