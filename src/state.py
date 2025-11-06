import json
import os
import pathlib
import time
from typing import Dict, List

DEFAULT_STATE_FILE = os.getenv("STATE_FILE", ".state/state.json")


def _ensure_parent(path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _state_path() -> pathlib.Path:
    return pathlib.Path(DEFAULT_STATE_FILE)


def _default_state() -> Dict:
    return {
        "posted_urls": [],
        "posted_events": [],
        # list of {"fp": str, "ts": int}
        "posted_fingerprints": [],
        # list of {"article_uri": str, "ts": int} - Event Registry article URIs (primary dedup key)
        "posted_article_uris": [],
        # daily usage counts
        "gemini_usage": {"date": "", "counts": {}},
        # cached summaries: list of {fp, ts, headline, bullets}
        "summary_cache": [],
        # all fetched articles: list of {fp, ts, headline, bullets, url, event_uri, source_title, source_date}
        "fetched_articles": [],
    }


def _load() -> Dict:
    p = _state_path()
    if not p.exists():
        return _default_state()
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        # ensure keys
        for k, v in _default_state().items():
            obj.setdefault(k, v)
        return obj
    except Exception:
        return _default_state()


def _save(state: Dict) -> None:
    p = _state_path()
    _ensure_parent(p)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _now_ts() -> int:
    return int(time.time())


def _prune(state: Dict, window_hours: int = 72) -> None:
    cutoff = _now_ts() - window_hours * 3600
    # prune posted_fingerprints (dicts with ts)
    fps: List[Dict] = state.get("posted_fingerprints") or []
    state["posted_fingerprints"] = [
        x for x in fps if isinstance(x, dict) and x.get("ts", 0) >= cutoff
    ]
    # prune posted_urls (migrate legacy strings by dropping them)
    urls = state.get("posted_urls") or []
    new_urls: List[Dict] = []
    for u in urls:
        if isinstance(u, dict):
            ts = int(u.get("ts", 0))
            if ts >= cutoff and u.get("url"):
                new_urls.append({"url": str(u.get("url")), "ts": ts})
        # legacy string entries are considered old and are dropped
    state["posted_urls"] = new_urls
    # prune posted_events (migrate legacy strings by dropping them)
    evs = state.get("posted_events") or []
    new_evs: List[Dict] = []
    for e in evs:
        if isinstance(e, dict):
            ts = int(e.get("ts", 0))
            if ts >= cutoff and e.get("event"):
                new_evs.append({"event": str(e.get("event")), "ts": ts})
        # legacy string entries are considered old and are dropped
    state["posted_events"] = new_evs
    # prune posted_article_uris
    article_uris = state.get("posted_article_uris") or []
    state["posted_article_uris"] = [
        x for x in article_uris if isinstance(x, dict) and x.get("ts", 0) >= cutoff
    ]
    # prune summary cache
    cache: List[Dict] = state.get("summary_cache") or []
    state["summary_cache"] = [x for x in cache if isinstance(x, dict) and x.get("ts", 0) >= cutoff]
    # prune fetched articles (keep 7 days for weekly brief)
    articles: List[Dict] = state.get("fetched_articles") or []
    week_cutoff = _now_ts() - 168 * 3600  # 7 days
    state["fetched_articles"] = [x for x in articles if isinstance(x, dict) and x.get("ts", 0) >= week_cutoff]


def already_posted(
    url: str = "", event_uri: str = "", fingerprint: str = "", article_uri: str = "", window_hours: int = 72
) -> bool:
    state = _load()
    _prune(state, window_hours)
    # Check article_uri FIRST (most reliable from Event Registry)
    if article_uri:
        for a in state.get("posted_article_uris") or []:
            if isinstance(a, dict) and a.get("article_uri") == article_uri:
                return True
    # Check recent events within window
    if event_uri:
        for e in state.get("posted_events") or []:
            if isinstance(e, dict) and e.get("event") == event_uri:
                return True
    # Check recent fingerprints within window
    if fingerprint:
        for x in state.get("posted_fingerprints") or []:
            if isinstance(x, dict) and x.get("fp") == fingerprint:
                return True
    # Check recent urls within window
    if url:
        for u in state.get("posted_urls") or []:
            if isinstance(u, dict) and u.get("url") == url:
                return True
    return False


def mark_posted(
    url: str = "", event_uri: str = "", fingerprint: str = "", article_uri: str = "", max_entries: int = 1000
) -> None:
    state = _load()
    _prune(state)
    now = _now_ts()
    # Track article_uri (primary key from Event Registry)
    if article_uri:
        article_uris = state.get("posted_article_uris") or []
        if not any(isinstance(a, dict) and a.get("article_uri") == article_uri for a in article_uris):
            article_uris.append({"article_uri": article_uri, "ts": now})
            if len(article_uris) > max_entries:
                article_uris = article_uris[-max_entries:]
            state["posted_article_uris"] = article_uris
    if url:
        urls = state.get("posted_urls") or []
        # avoid duplicates
        if not any(isinstance(u, dict) and u.get("url") == url for u in urls):
            urls.append({"url": url, "ts": now})
            if len(urls) > max_entries:
                urls = urls[-max_entries:]
            state["posted_urls"] = urls
    if event_uri:
        evs = state.get("posted_events") or []
        if not any(isinstance(e, dict) and e.get("event") == event_uri for e in evs):
            evs.append({"event": event_uri, "ts": now})
            if len(evs) > max_entries:
                evs = evs[-max_entries:]
            state["posted_events"] = evs
    if fingerprint:
        fps: List[Dict] = state.get("posted_fingerprints") or []
        # avoid duplicates
        if not any(isinstance(f, dict) and f.get("fp") == fingerprint for f in fps):
            fps.append({"fp": fingerprint, "ts": now})
            if len(fps) > max_entries:
                fps = fps[-max_entries:]
            state["posted_fingerprints"] = fps
    _save(state)


# Summary cache (72h window)


def get_cached_summary(fingerprint: str, window_hours: int = 72):
    state = _load()
    _prune(state, window_hours)
    for x in state.get("summary_cache") or []:
        if isinstance(x, dict) and x.get("fp") == fingerprint:
            return x.get("headline"), x.get("bullets")
    return None


def set_cached_summary(
    fingerprint: str, headline: str, bullets: list[str], max_entries: int = 2000
) -> None:
    state = _load()
    _prune(state)
    cache: List[Dict] = state.get("summary_cache") or []
    cache.append({"fp": fingerprint, "ts": _now_ts(), "headline": headline, "bullets": bullets})
    if len(cache) > max_entries:
        cache = cache[-max_entries:]
    state["summary_cache"] = cache
    _save(state)


# Gemini usage tracking (per day)


def _today() -> str:
    import datetime as _dt

    return _dt.datetime.utcnow().strftime("%Y-%m-%d")


def _ensure_usage_day(state: Dict) -> None:
    usage = state.get("gemini_usage") or {"date": "", "counts": {}}
    if usage.get("date") != _today():
        state["gemini_usage"] = {"date": _today(), "counts": {}}


def gemini_counts() -> Dict:
    state = _load()
    _ensure_usage_day(state)
    _save(state)
    return state.get("gemini_usage") or {"date": _today(), "counts": {}}


def gemini_increment(model: str) -> None:
    state = _load()
    _ensure_usage_day(state)
    usage = state.get("gemini_usage")
    counts = usage.get("counts") or {}
    counts[model] = int(counts.get(model, 0)) + 1
    usage["counts"] = counts
    state["gemini_usage"] = usage
    _save(state)


def gemini_remaining(model: str) -> int:
    # Defaults per free tier
    default_limits = {
        "gemini-2.5-pro": int(os.getenv("GEMINI_PRO_RPD", "50")),
        "gemini-2.5-flash": int(os.getenv("GEMINI_FLASH_RPD", "250")),
    }
    limit = default_limits.get(model, int(os.getenv("GEMINI_DEFAULT_RPD", "250")))
    usage = gemini_counts()
    used = int((usage.get("counts") or {}).get(model, 0))
    return max(0, limit - used)


# Fetched articles tracking (all articles, not just posted)


def save_fetched_article(
    fingerprint: str,
    headline: str,
    bullets: list[str],
    url: str,
    event_uri: str = "",
    source_title: str = "",
    source_date: str = "",
    max_entries: int = 5000,
) -> None:
    """Save a fetched article to state for daily brief generation."""
    state = _load()
    _prune(state)
    articles: List[Dict] = state.get("fetched_articles") or []
    # Check if already exists (by fingerprint)
    if not any(isinstance(a, dict) and a.get("fp") == fingerprint for a in articles):
        articles.append(
            {
                "fp": fingerprint,
                "ts": _now_ts(),
                "headline": headline,
                "bullets": bullets,
                "url": url,
                "event_uri": event_uri,
                "source_title": source_title,
                "source_date": source_date,
            }
        )
        if len(articles) > max_entries:
            articles = articles[-max_entries:]
        state["fetched_articles"] = articles
        _save(state)


def get_fetched_articles_since(hours: int = 24) -> List[Dict]:
    """Get all fetched articles from the last N hours."""
    state = _load()
    cutoff = _now_ts() - hours * 3600
    articles: List[Dict] = state.get("fetched_articles") or []
    return [a for a in articles if isinstance(a, dict) and a.get("ts", 0) >= cutoff]
