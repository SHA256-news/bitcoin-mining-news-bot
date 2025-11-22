"""Utility to inspect recently posted stories from .state/posted.json.

Usage:
  python -m src.show_posted [N]

Prints the last N posted items (default 20) with timestamp, URL, tweet_id and
story identity keys (event_uri, article_uri, fingerprint).
"""

import json
import sys
import datetime as _dt

from src.state import _posted_path  # type: ignore


def _load_posted() -> list[dict]:
    p = _posted_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("items") or []
    except Exception:
        return []


def main(argv: list[str]) -> None:
    try:
        limit = int(argv[1]) if len(argv) > 1 else 20
    except Exception:
        limit = 20

    items = _load_posted()
    items.sort(key=lambda x: int(x.get("ts", 0)), reverse=True)
    for it in items[:limit]:
        ts = int(it.get("ts", 0))
        dt = _dt.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S UTC") if ts else "?"
        url = it.get("url", "")
        tweet_id = it.get("tweet_id", "")
        event_uri = it.get("event_uri", "")
        article_uri = it.get("article_uri", "")
        story_uri = it.get("story_uri", "")
        fp = it.get("fingerprint", "")
        norm = it.get("norm_url", "")
        print(
            f"[{dt}] url={url} tweet_id={tweet_id} event_uri={event_uri} "
            f"article_uri={article_uri} story_uri={story_uri} fp={fp} norm_url={norm}"
        )


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv)
