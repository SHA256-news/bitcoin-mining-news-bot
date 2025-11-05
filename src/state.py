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
        # daily usage counts
        "gemini_usage": {"date": "", "counts": {}},
        # cached summaries: list of {fp, ts, headline, bullets}
        "summary_cache": [],
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
    # prune summary cache
    cache: List[Dict] = state.get("summary_cache") or []
    state["summary_cache"] = [x for x in cache if isinstance(x, dict) and x.get("ts", 0) >= cutoff]


def already_posted(
    url: str = "", event_uri: str = "", fingerprint: str = "", window_hours: int = 72
) -> bool:
    state = _load()
    _prune(state, window_hours)
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
    url: str = "", event_uri: str = "", fingerprint: str = "", max_entries: int = 1000
) -> None:
    state = _load()
    _prune(state)
    now = _now_ts()
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
