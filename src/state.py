import json
import os
import pathlib
import time
from typing import Dict, List, Any

DEFAULT_STATE_FILE = os.getenv("STATE_FILE", ".state/state.json")
POSTED_FILE = os.getenv("POSTED_FILE", ".state/posted.json")


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


# New, from-scratch posted registry (separate file, simple and robust)


def _posted_path() -> pathlib.Path:
    p = pathlib.Path(POSTED_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _posted_default() -> Dict:
    return {"items": []}  # each: {url?, event_uri?, article_uri?, fingerprint?, ts}


def _posted_load() -> Dict:
    p = _posted_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return _posted_default()
    # First-time migration from legacy state.json if present
    st = _load()
    items: List[Dict] = []
    now = _now_ts()

    def _migrate_seq(seq_key: str, field_in: str, field_out: str) -> None:
        for obj in st.get(seq_key) or []:
            if isinstance(obj, dict) and obj.get(field_in):
                items.append({field_out: str(obj.get(field_in)), "ts": int(obj.get("ts", now))})

    _migrate_seq("posted_urls", "url", "url")
    _migrate_seq("posted_events", "event", "event_uri")
    _migrate_seq("posted_article_uris", "article_uri", "article_uri")
    _migrate_seq("posted_fingerprints", "fp", "fingerprint")

    return {"items": items}


def _posted_save(obj: Dict) -> None:
    p = _posted_path()
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _save(state: Dict) -> None:
    p = _state_path()
    _ensure_parent(p)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _now_ts() -> int:
    return int(time.time())


def _prune(state: Dict, window_hours: int = 72) -> None:
    cutoff = _now_ts() - window_hours * 3600
    # prune summary cache
    cache: List[Dict] = state.get("summary_cache") or []
    state["summary_cache"] = [x for x in cache if isinstance(x, dict) and x.get("ts", 0) >= cutoff]
    # prune fetched articles (keep 7 days for weekly brief)
    articles: List[Dict] = state.get("fetched_articles") or []
    week_cutoff = _now_ts() - 168 * 3600  # 7 days
    state["fetched_articles"] = [
        x for x in articles if isinstance(x, dict) and x.get("ts", 0) >= week_cutoff
    ]


def _posted_prune(window_hours: int = 168) -> None:
    obj = _posted_load()
    cutoff = _now_ts() - window_hours * 3600
    items: List[Dict] = obj.get("items") or []
    obj["items"] = [x for x in items if isinstance(x, dict) and int(x.get("ts", 0)) >= cutoff]
    _posted_save(obj)


def already_posted(
    url: str = "",
    event_uri: str = "",
    fingerprint: str = "",
    article_uri: str = "",
    window_hours: int = 72,
    event_window_hours: int | None = None,
) -> bool:
    """Return True if we've posted this item recently (rebuilt, minimal and robust).

    Checks, in order: article_uri, event_uri (with its own window), fingerprint, url.
    """
    import logging as _logging

    _log = _logging.getLogger(__name__)
    # prune caches (non-posted state)
    _prune(_load(), max(window_hours, event_window_hours or window_hours))

    # prune posted registry
    _posted_prune(max(window_hours, event_window_hours or window_hours))
    obj = _posted_load()
    items: List[Dict] = obj.get("items") or []

    now = _now_ts()
    # Article URI (strongest)
    if article_uri:
        for it in items:
            if (
                it.get("article_uri") == article_uri
                and (now - int(it.get("ts", 0))) <= window_hours * 3600
            ):
                _log.debug("already_posted: match=article_uri uri=%s", article_uri)
                return True

    # Event URI with its own window
    ev_win = event_window_hours if event_window_hours is not None else window_hours
    if event_uri:
        for it in items:
            if it.get("event_uri") == event_uri and (now - int(it.get("ts", 0))) <= ev_win * 3600:
                _log.debug("already_posted: match=event event=%s", event_uri)
                return True

    # Fingerprint
    if fingerprint:
        for it in items:
            if (
                it.get("fingerprint") == fingerprint
                and (now - int(it.get("ts", 0))) <= window_hours * 3600
            ):
                _log.debug("already_posted: match=fingerprint fp=%s", fingerprint)
                return True

    # URL
    if url:
        for it in items:
            if it.get("url") == url and (now - int(it.get("ts", 0))) <= window_hours * 3600:
                _log.debug("already_posted: match=url url=%s", url)
                return True

    return False


def _posted_identity_equal(a: Dict, b: Dict) -> bool:
    """Return True when two posted entries refer to the same underlying item.

    Identity is any matching non-empty value among article_uri, event_uri,
    fingerprint or url. This is used consistently for mark_posted dedup.
    """
    for k in ("article_uri", "event_uri", "fingerprint", "url"):
        if a.get(k) and b.get(k) and a.get(k) == b.get(k):
            return True
    return False


def mark_posted(
    url: str = "",
    event_uri: str = "",
    fingerprint: str = "",
    article_uri: str = "",
    max_entries: int = 2000,
) -> None:
    """Record this item as posted (rebuilt, minimal and robust)."""
    now = _now_ts()
    obj = _posted_load()
    items: List[Dict] = obj.get("items") or []
    entry: Dict[str, Any] = {"ts": now}
    if url:
        entry["url"] = url
    if event_uri:
        entry["event_uri"] = event_uri
    if article_uri:
        entry["article_uri"] = article_uri
    if fingerprint:
        entry["fingerprint"] = fingerprint

    # Deduplicate by any present key
    items = [it for it in items if not _posted_identity_equal(it, entry)]
    items.append(entry)
    if len(items) > max_entries:
        items = items[-max_entries:]
    obj["items"] = items
    _posted_save(obj)


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

    return _dt.date.today().strftime("%Y-%m-%d")


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
    usage = state.get("gemini_usage") or {}
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
