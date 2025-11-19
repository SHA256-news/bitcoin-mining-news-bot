import json
import os
import pathlib
import time
from typing import List, Dict, Optional

QUEUE_FILE = os.getenv("QUEUE_FILE", ".state/queue.json")


def _path() -> pathlib.Path:
    p = pathlib.Path(QUEUE_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load() -> List[Dict]:
    p = _path()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(items: List[Dict]) -> None:
    p = _path()
    p.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _key(it: Dict) -> str:
    # Prefer event-level dedup first, then fingerprint, then article, then URL
    for k in ("event_uri", "fingerprint", "fp", "article_uri", "url"):
        v = (it.get(k) or "").strip()
        if v:
            return v.lower()
    return ""


def _dedupe(items: List[Dict]) -> List[Dict]:
    seen = set()
    out_rev: List[Dict] = []
    # Keep newest occurrence for each key (iterate from end)
    for it in reversed(items):
        k = _key(it)
        if not k:
            k = f"_idx_{len(out_rev)}"
        if k in seen:
            continue
        seen.add(k)
        out_rev.append(it)
    return list(reversed(out_rev))


def dedupe() -> None:
    q = _load()
    _save(_dedupe(q))


def _filter_queue(pred) -> int:
    """Load, filter queue by predicate, save, and return count removed."""
    q = _load()
    before = len(q)
    q = [it for it in q if not pred(it)]
    _save(q)
    return before - len(q)


def purge_banned_crypto() -> int:
    """Remove items whose headline/url contain banned 'crypto' tokens."""
    import re

    def bad(it: dict) -> bool:
        h = (it.get("headline") or "").lower()
        u = (it.get("url") or "").lower()
        pats = [r"\bcrypto\b", r"crypto-", r"cryptocurrenc"]
        return any(re.search(p, h) or re.search(p, u) for p in pats)

    return _filter_queue(bad)


def purge_posted(event_hours: int = 168, window_hours: int = 168) -> int:
    """Remove queue items that have already been posted recently (by event/url/fp/article)."""
    from src.state import already_posted

    def is_posted(it: dict) -> bool:
        return already_posted(
            url=it.get("url", ""),
            event_uri=it.get("event_uri", ""),
            fingerprint=it.get("fingerprint", ""),
            article_uri=it.get("article_uri", ""),
            window_hours=window_hours,
            event_window_hours=event_hours,
        )

    return _filter_queue(is_posted)


def remove_by_url(url: str) -> int:
    """Remove all queue items matching the exact URL."""
    url_l = (url or "").strip()

    def bad(it: dict) -> bool:
        return (it.get("url", "").strip() == url_l)

    return _filter_queue(bad)


def remove_by_urls(urls: list[str]) -> int:
    set_urls = {u.strip() for u in (urls or []) if u and u.strip()}

    def bad(it: dict) -> bool:
        return it.get("url", "").strip() in set_urls

    return _filter_queue(bad)


def remove_by_title_substr(substr: str) -> int:
    """Remove all queue items whose headline contains the substring (case-insensitive)."""
    s = (substr or "").lower()

    def bad(it: dict) -> bool:
        return s in (it.get("headline", "").lower())

    return _filter_queue(bad)


def purge_company_duplicates_keep_best_domain() -> int:
    """If multiple queue items are about the same company, keep only the best domain.

    Company is inferred from headline tokens. Best domain is computed via news_fetcher._domain_score (lower score = higher authority) — keep the lowest score.
    """
    try:
        from src.news_fetcher import _domain_score  # type: ignore
    except Exception:
        return 0
    companies = [
        "terawulf",
        "wulf",
        "riot",
        "marathon",
        "mara",
        "ciphers",
        "cipher",
        "cleanspark",
        "hut",
        "bitfarms",
        "corescientific",
        "core scientific",
        "cango",
        "iren",
        "iris",
        "alps",
        "bitdeer",
    ]

    def company_key(title: str) -> str:
        t = (title or "").lower()
        for c in companies:
            if c in t:
                return "corescientific" if c == "core scientific" else c
        return ""

    q = _load()
    before = len(q)
    groups: dict[str, list[dict]] = {}
    for it in q:
        ckey = company_key(it.get("headline", ""))
        if not ckey:
            continue
        groups.setdefault(ckey, []).append(it)

    to_keep = set()
    to_drop = set()
    # For each company, pick best by domain score (lower is better)
    for ckey, items in groups.items():
        if len(items) <= 1:
            continue
        best = None
        best_score = None
        for it in items:
            score = _domain_score(it.get("url", "") or "")
            if best is None or score < best_score:
                best = it
                best_score = score
        for it in items:
            if it is not best:
                to_drop.add(it.get("url", ""))
            else:
                to_keep.add(it.get("url", ""))

    if not to_drop:
        return 0

    q2 = [it for it in q if it.get("url", "") not in to_drop]
    _save(q2)
    return before - len(q2)


def push_many(items: List[Dict]) -> None:
    q = _load()
    ts = int(time.time())
    for it in items:
        it2 = dict(it)
        it2["ts"] = ts
        q.append(it2)
    q = _dedupe(q)
    _save(q)


def pop_one() -> Optional[Dict]:
    q = _load()
    if not q:
        return None
    item = q.pop()  # LIFO
    _save(q)
    return item
