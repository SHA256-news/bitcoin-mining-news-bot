import os
import logging
from typing import List, Dict
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


def _er_get(url: str, params: Dict, timeout: int = 20, context: str = "api") -> Dict | None:
    """Thin wrapper around Event Registry GET requests.

    Centralizes retries, error logging and JSON handling while preserving
    existing behavior in the callers.
    """
    try:
        resp = _session().get(url, params=params, timeout=timeout)
        if getattr(resp, "ok", False):
            return resp.json() or {}
        _log_er_error(resp, context)
    except Exception as e:
        logger.warning("eventregistry: %s request failed: %s", context, e)
    return None


def _session() -> requests.Session:
    s = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )
    return s


def _truthy(val: str | None) -> bool:
    if not val:
        return False
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _log_er_error(resp: requests.Response, context: str = "") -> None:
    try:
        status = getattr(resp, "status_code", None)
        text = getattr(resp, "text", "") or ""
        snippet = text[:300].replace("\n", " ")
        reason = ""
        if status in (401, 403):
            reason = "auth/permission"
        elif status == 429:
            reason = "rate/quota"
        elif status and status >= 500:
            reason = "server"
        else:
            reason = "client"
        logger.error(
            "eventregistry: %s error status=%s reason=%s body=%s",
            context or "api",
            status,
            reason,
            snippet,
        )
    except Exception:
        pass


def _is_btc_sha256_article(article: Dict) -> bool:
    """Return True if article is Bitcoin-only SHA-256 mining *or* clearly miner-relevant context.

    Rules (conservative but broader than just public miner headlines):
    - Must NOT be about altcoins (ethereum/eth, ltc, dogecoin, cloud mining, etc.).
    - Primary path (direct mining):
      * mentions "bitcoin" or "btc" AND
      * at least one of: mining/miner/sha-256/sha256/asic/hashrate/difficulty.
    - Secondary path (energy/policy context):
      * mentions "bitcoin" or "btc" AND
      * at least one energy/power/grid token, OR
      * mentions mining/ASIC/hashrate together with energy/power/grid tokens.
    """
    title = (article.get("title") or "").lower()
    text = (article.get("text") or "").lower()
    blob = f"{title} {text}"

    has_btc = "bitcoin" in blob or " btc" in blob or "btc " in blob

    include_tokens = [
        "mining",
        "miner",
        "miners",
        "sha-256",
        "sha256",
        "asic",
        "hashrate",
        "difficulty",
    ]
    has_mining = any(tok in blob for tok in include_tokens)

    energy_tokens = [
        "energy",
        "electricity",
        "power grid",
        "grid operator",
        "power prices",
        "electricity prices",
        "power cost",
        "electricity cost",
        "data center",
        "data centres",
        "data centers",
        "data-centre",
        "data-centers",
        "department of energy",
        " doe ",
        "energy ministry",
        "ministry of energy",
        "tenaga nasional",
        " tnb ",
    ]
    has_energy = any(tok in blob for tok in energy_tokens)

    # Exclude obvious non-Bitcoin or cloud/tokenization content
    exclude_tokens = [
        "cloud mining",
        "ethereum",
        " eth ",
        " eth,",
        " eth.",
        "litecoin",
        " ltc ",
        " ltc,",
        " ltc.",
        "dogecoin",
        " gpu",
    ]
    if any(tok in blob for tok in exclude_tokens):
        return False

    # Primary: explicit Bitcoin mining / ASIC / hashrate / difficulty
    if has_btc and has_mining:
        return True

    # Secondary: Bitcoin + energy/grid context (e.g., BTC price vs power costs)
    if has_btc and has_energy:
        return True

    # Secondary: mining/ASIC/hashrate + energy/grid context, even if "bitcoin" isn't repeated
    if has_mining and has_energy:
        return True

    return False


def _parse_list_env(name: str) -> list[str]:
    raw = os.getenv(name, "")
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    # strip leading www.
    return [p.removeprefix("www.") for p in parts]


# Preferred domains first (lower index = higher preference). Extendable via env.
# Includes user-specified preferences at the top by default; can be overridden via SOURCE_DOMAIN_ALLOWLIST
DOMAIN_PREF_ORDER = [
    # User-preferred
    "wsj.com",  # The Wall Street Journal
    "ft.com",  # The Financial Times
    "blockspace.media",
    "beincrypto.com",
    # General tier-1
    "bloomberg.com",
    "reuters.com",
    # Bitcoin/mining specialist
    "coindesk.com",
    "theblock.co",
    "blockworks.co",
    "bitcoinmagazine.com",
    "braiins.com",
    # Crypto media
    "cointelegraph.com",
]
DOMAIN_PREF_ORDER = _parse_list_env("SOURCE_DOMAIN_ALLOWLIST") or DOMAIN_PREF_ORDER

# Deprioritize/avoid these domains unless no alternative exists
DOMAIN_DENY = [
    "coinmarketcap.com",
    "crypto.news",
    "streetinsider.com",
    "seekingalpha.com",
    "benzinga.com",
    "ambcrypto.com",
    # User-requested permanent bans also appear here for redundancy
    "hashrateindex.com",
]
extra_deny = _parse_list_env("SOURCE_DOMAIN_DENYLIST")
if extra_deny:
    DOMAIN_DENY.extend(extra_deny)

# Hard bans: never publish if domain matches or if banned keywords appear
BANNED_DOMAINS = set(["hashrateindex.com"]) | set(_parse_list_env("SOURCE_BANNED_DOMAINS"))
BANNED_KEYWORDS = {
    "luxor",
    "vnish",
    # Topic bans
    "cloud mining",
    "cloud service",
    "cloud-based mining",
    "buy hashrate",
    "sell hash power",
    "hash power",
    "rent computing power",
    "rent hashrate",
    "hashrate rental",
    "contract mining",
    # Tokenization bans
    "tokenized hashrate",
    "tokenize hashrate",
    "tokenized",
    "tokenize",
    "tokenization",
} | set(_parse_list_env("SOURCE_BANNED_KEYWORDS"))


def _is_eth_domain(host: str) -> bool:
    """Return True if the host clearly references Ethereum (eth/ethereum) in its domain name.

    Rules (conservative to avoid false positives like health.com or bethesda.org):
    - Any label equals "eth" (e.g., eth.link, eth.example.com)
    - The registrable domain contains "ethereum" anywhere
    - The left-most label starts with "eth" (e.g., etherscan.io, ethnews.com)
    """
    if not host:
        return False
    h = host.lower()
    labels = [p for p in h.split(".") if p]
    if "ethereum" in h:
        return True
    if any(lbl == "eth" for lbl in labels):
        return True
    if labels and labels[0].startswith("eth"):
        return True
    return False


NEG_ENV_TOKENS = {
    "carbon footprint",
    "carbon emissions",
    "greenhouse gas",
    "pollution",
    "environmental impact",
    "climate change",
    "climate crisis",
    "power grid",
}

# Sponsored/advertorial detection
SPONSORED_TOKENS = {
    "sponsored",
    "advertorial",
    "paid partnership",
    "partner content",
    "promoted",
}


def _domain(host: str | None) -> str:
    if not host:
        return ""
    return host.lower().removeprefix("www.")


def _domain_score(u: str) -> int:
    try:
        host = _domain(urlparse(u).netloc)
        # Absolute ban
        if host in BANNED_DOMAINS or _is_eth_domain(host):
            return 1_000_000
        # Hard penalty for denylist
        if host in DOMAIN_DENY:
            return 10_000 + DOMAIN_DENY.index(host)
        # Prefer allowlist by rank
        if host in DOMAIN_PREF_ORDER:
            return DOMAIN_PREF_ORDER.index(host)
        # prefer common news TLDs
        if host.endswith((".com", ".co", ".org", ".net")):
            return 500
        return 800
    except Exception:
        return 9999


def _pick_best(group: List[Dict]) -> Dict:
    # Rank: lower domain score first, higher social score, then longer body
    allowed = [g for g in group if _domain(urlparse(g.get("url", "")).netloc) not in BANNED_DOMAINS]
    base = allowed or group
    return sorted(
        base,
        key=lambda a: (
            _domain_score(a.get("url", "")),
            -a.get("social_score", 0),  # Prioritize higher social engagement
            -len(a.get("text", "")),
        ),
    )[0]


def _signature(title: str) -> str:
    import re

    t = (title or "").lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _numbers_and_units(text: str) -> list[str]:
    import re

    s = (text or "").lower()
    parts = []
    # Capture numbers with units like mw, gw, eh/s, zh/s, btc, $, %
    for pat in [
        r"\b\$?\d+[,.\d]*\s*(mw|gw|eh/s|zh/s|th/s|btc|%|usd)\b",
        r"\b\d{1,3}(?:,\d{3})+\b",
        r"\b\d+\.?\d*\s*(mw|gw|eh/s|zh/s|th/s)\b",
    ]:
        parts += re.findall(pat, s)
    # Also keep raw numbers of key sizes, but exclude likely years (19xx, 20xx) unless they are clearly not years
    # We'll just exclude 4-digit numbers starting with 19 or 20 for simplicity in this context
    nums = re.findall(r"\b\d{2,}\b", s)
    filtered_nums = []
    for n in nums:
        # Skip likely years
        if len(n) == 4 and (n.startswith("19") or n.startswith("20")):
            continue
        filtered_nums.append(n)
    parts += filtered_nums[:5]
    return list(dict.fromkeys(parts))[:10]


def _get_concept_uris(api_key: str, query: str) -> List[str]:
    """Get concept URIs for a search term using Event Registry's suggest API."""
    try:
        url = "https://eventregistry.org/api/v1/suggestConceptsFast"
        data = _er_get(
            url,
            params={"apiKey": api_key, "prefix": query},
            timeout=10,
            context="suggestConceptsFast",
        )
        if not data:
            return []
        # Return URIs of top 3 most relevant concepts
        return [c.get("uri") for c in data[:3] if c.get("uri")]
    except Exception as e:
        logger.debug("news_fetcher: concept URI fetch failed: %s", e)
    return []


def _get_trending_score(api_key: str, query: str) -> Dict:
    """Get time aggregation to detect spikes in article volume."""
    try:
        url = "https://eventregistry.org/api/v1/article/getArticles"
        params = {
            "apiKey": api_key,
            "keyword": query,
            "resultType": "timeAggr",
            "lang": "eng",
            "dataType": ["news"],
        }
        data = _er_get(url, params=params, timeout=10, context="timeAggr")
        if not data:
            return {"recent": 0, "average": 0, "is_spike": False}
        results = (data.get("timeAggr", {}) or {}).get("results", [])
        if results:
            # Calculate if recent volume is significantly higher than average
            recent = results[-1].get("count", 0) if results else 0
            avg = sum(x.get("count", 0) for x in results) / len(results) if results else 1
            return {"recent": recent, "average": avg, "is_spike": recent > avg * 1.5}
    except Exception as e:
        logger.debug("news_fetcher: trending score fetch failed: %s", e)
    return {"recent": 0, "average": 0, "is_spike": False}


def _fetch_events_first(api_key: str, query: str, concept_uris: List[str]) -> List[Dict]:
    """Fetch clustered events first, then get articles about those events."""
    from datetime import datetime, timedelta, timezone

    try:
        url = "https://eventregistry.org/api/v1/event/getEvents"
        # Align event window with article recency (default last 24h)
        now = datetime.now(timezone.utc)
        max_hours = int(os.getenv("ARTICLES_MAX_HOURS", "24") or "24")
        params = {
            "apiKey": api_key,
            "resultType": "events",
            "eventsSortBy": "socialScore",  # Prioritize trending events
            "eventsSortByAsc": False,
            "lang": "eng",
            "eventsCount": 20,
            "minArticlesInEvent": 2,  # Only events with multiple sources
            "dateStart": (now - timedelta(hours=max_hours)).strftime("%Y-%m-%d"),
            "dateEnd": now.strftime("%Y-%m-%d"),
            "dataType": ["news"],
            "includeEventSocialScore": True,
            "includeEventArticleCounts": True,
        }

        # Use concept URIs if available, otherwise fall back to keyword
        if concept_uris:
            params["conceptUri"] = concept_uris
            params["conceptOper"] = "or"
        else:
            params["keyword"] = query

        data = _er_get(url, params=params, timeout=20, context="getEvents")
        if not data:
            return []
        events = (data.get("events", {}) or {}).get("results", [])
        logger.info("news_fetcher: found %d clustered events", len(events))
        return events
    except Exception as e:
        logger.warning("news_fetcher: event fetch failed: %s", e)
    return []


def _fingerprint(article: Dict) -> str:
    # Build a stable fingerprint using normalized title + key numbers/units + top tokens
    import re

    title = (article.get("title") or "").lower()
    # Use more text for better dedup (1200 chars instead of 600)
    text = (article.get("text") or "").lower()[:1200]
    base = f"{title} {text}"
    # remove non-alnum
    base = re.sub(r"[^a-z0-9\s]", " ", base)
    tokens = [
        t
        for t in base.split()
        if len(t) > 2
        and t
        not in {
            "the",
            "and",
            "for",
            "with",
            "from",
            "that",
            "this",
            "into",
            "over",
            "under",
            "amid",
            "into",
            "have",
            "has",
            "was",
            "were",
            "will",
            "your",
            "their",
            "ours",
            "they",
            "but",
            "are",
            "not",
            "you",
            "his",
            "her",
            "its",
            "our",
            "out",
        }
    ]

    # Extract company names (common mining companies)
    company_names = {
        "hut",
        "cleanspark",
        "riot",
        "marathon",
        "cipher",
        "iris",
        "bitfarms",
        "canaan",
        "bitmain",
        "microbt",
        "core",
        "scientific",
        "argo",
        "terawulf",
        "stronghold",
        "greenidge",
        "bitdeer",
        "cango",
        "alps",
    }
    companies = [t for t in tokens if t in company_names]

    # Extract topic indicators (earnings, expansion, etc)
    topic_indicators = {
        "earnings",
        "revenue",
        "q1",
        "q2",
        "q3",
        "q4",
        "quarter",
        "quarterly",
        "expansion",
        "capacity",
        "hashrate",
        "acquisition",
        "merger",
        "ipo",
        "holdings",
        "treasury",
        "reserve",
        "liquidation",
        "sale",
        "pivot",
    }
    topics = [t for t in tokens if t in topic_indicators]

    # prioritize company + topic combination for better duplicate detection
    keep = []

    # Add companies first (most important for dedup)
    keep.extend(companies[:3])

    # Add topic indicators
    keep.extend(topics[:3])

    # Add priority mining terms
    for t in tokens:
        if t in {
            "bitcoin",
            "mining",
            "miner",
            "miners",
            "hashrate",
            "difficulty",
            "asic",
        }:
            keep.append(t)

    # add first few significant tokens (but fewer now since we have companies/topics)
    keep += tokens[:8]

    # add key numbers/units (fewer to reduce noise)
    keep += _numbers_and_units(f"{title} {text}")[:5]

    # dedupe and join
    seen = []
    for k in keep:
        if k not in seen:
            seen.append(k)
    # Use 20 tokens (better balance between uniqueness and similarity detection)
    fp = " ".join(seen[:20]).strip()
    return fp


def _fetch_minute_stream_articles(
    api_key: str, query: str, concept_uris: List[str], minutes: int = 3
) -> List[Dict]:
    try:
        url = "https://eventregistry.org/api/v1/minuteStreamArticles"
        params = {
            "apiKey": api_key,
            "recentActivityArticlesUpdatesAfterMinsAgo": max(1, min(minutes, 240)),
            "articleBodyLen": -1,
            "dataType": ["news"],
            "lang": "eng",
        }
        if concept_uris:
            params["conceptUri"] = concept_uris
            params["conceptOper"] = "or"
        else:
            params["keyword"] = query
        data = _er_get(url, params=params, timeout=15, context="minuteStreamArticles")
        if not data:
            return []
        activity = (data.get("recentActivityArticles") or {}).get("activity") or []
        return activity
    except Exception as e:
        logger.warning("news_fetcher: minuteStreamArticles failed: %s", e)
    return []


def _build_article_from_er(a: Dict) -> Dict | None:
    import datetime as _dt

    # Compute max age in hours: prefer ARTICLES_MAX_HOURS, else ARTICLES_MAX_DAYS*24 (default 24h)
    try:
        max_hours_env = os.getenv("ARTICLES_MAX_HOURS", "")
        if max_hours_env.strip():
            max_age_hours = max(1, int(max_hours_env))
        else:
            max_days = int(os.getenv("ARTICLES_MAX_DAYS", "1") or "1")
            max_age_hours = max(1, max_days * 24)
    except Exception:
        max_age_hours = 24

    now = _dt.datetime.now(_dt.timezone.utc)

    uri = a.get("uri") or ""
    url = a.get("url") or ""
    # Extract social score and sentiment
    social_score = (
        (a.get("shares") or {}).get("facebook", 0) if isinstance(a.get("shares"), dict) else 0
    )
    sentiment = a.get("sentiment")
    # Filter out articles with very negative sentiment (< -0.3)
    if sentiment is not None and sentiment < -0.3:
        return None
    art = {
        "title": a.get("title") or "",
        "url": url,
        "text": a.get("body") or a.get("text") or "",
        # Primary Event Registry identifiers for story identity
        "event_uri": a.get("eventUri") or a.get("eventUriWgt") or "",
        "article_uri": uri,
        # Some ER payloads may include a storyUri/cluster identifier; capture if present
        "story_uri": a.get("storyUri") or "",
        "date": a.get("dateTime") or a.get("date") or "",
        "source": (
            (a.get("source") or {}).get("title") if isinstance(a.get("source"), dict) else ""
        ),
        "social_score": social_score,
        "sentiment": sentiment,
        "concepts": a.get("concepts", []),
        "source_rank": (
            (a.get("source") or {}).get("ranking", {}).get("importanceRank")
            if isinstance(a.get("source"), dict)
            else None
        ),
    }
    # Drop stale items by publication time before spending extract quota
    dt_str = a.get("dateTime") or a.get("date") or art["date"]
    if dt_str:
        try:
            dt_parsed = None
            # Try ISO first
            try:
                dt_parsed = _dt.datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            except Exception:
                # Try YYYY-MM-DD
                if len(dt_str) == 10:
                    dt_parsed = _dt.datetime.fromisoformat(dt_str + "T00:00:00+00:00")
            if dt_parsed and dt_parsed.tzinfo is None:
                dt_parsed = dt_parsed.replace(tzinfo=_dt.timezone.utc)
            if dt_parsed is not None:
                age_h = (now - dt_parsed).total_seconds() / 3600.0
                if age_h > max_age_hours:
                    return None
        except Exception:
            # If parsing fails, continue (will be constrained by API dateStart)
            pass

    # Drop if hard-banned by domain or keyword
    url_str = art.get("url", "")
    host = _domain(urlparse(url_str).netloc)
    blob = f"{art.get('title','')} {art.get('text','')} {art.get('source','')} {url_str}".lower()

    sponsored_url = "/sponsored/" in url_str.lower() or "sponsored" in url_str.lower()
    if (
        host in BANNED_DOMAINS
        or _is_eth_domain(host)
        or any(k in blob for k in BANNED_KEYWORDS)
        or sponsored_url
        or any(k in blob for k in SPONSORED_TOKENS)
    ):
        return None
    if not _is_btc_sha256_article(art):
        return None
    # compute fingerprint once text is final
    art["fingerprint"] = _fingerprint(art)
    return art


def _enrich_article_body_if_needed(art: Dict, api_key: str) -> None:
    """Optionally call Event Registry extractArticleInfo for a small set of final candidates.

    This is called only for the deduplicated articles we are about to use, to
    avoid spending extract quota on every raw result.
    """
    url = art.get("url") or ""
    if not url:
        return
    # Skip if we already have a sufficiently long body
    if art.get("text") and len(art["text"]) >= 500:
        return
    try:
        ext_url = "https://analytics.eventregistry.org/api/v1/extractArticleInfo"
        er = _session().get(ext_url, params={"apiKey": api_key, "url": url}, timeout=15)
        if er.ok:
            ej = er.json() or {}
            body = ej.get("body") or ""
            if body and len(body) > len(art.get("text", "")):
                art["text"] = body
        else:
            _log_er_error(er, "extractArticleInfo")
    except Exception as e:
        logger.debug("news_fetcher: extractArticleInfo failed for %s: %s", url, e)


def _group_articles_by_event_or_fingerprint(articles: List[Dict]) -> Dict[str, List[Dict]]:
    """Group articles by event URI when present, else by fingerprint/title signature.

    This preserves the existing grouping logic used for deduplication.
    """
    grouped: Dict[str, List[Dict]] = {}
    for art in articles:
        fp = art.get("fingerprint", "") or ""
        ev = art.get("event_uri") or ""
        key = ev if ev else (fp if fp else _signature(art.get("title", "")))
        grouped.setdefault(key, []).append(art)
    return grouped


def _pick_group_representatives(grouped: Dict[str, List[Dict]], limit: int) -> List[Dict]:
    """Pick one representative article per group using _pick_best, up to limit."""
    picked: List[Dict] = []
    for _, group in grouped.items():
        picked.append(_pick_best(group))
        if len(picked) >= limit:
            break
    return picked


def _log_fetch_metrics(
    picked: List[Dict],
    articles: List[Dict],
    query: str,
    event_uris: List[str],
    trending: Dict,
) -> None:
    """Log summary metrics about fetched and deduplicated articles."""
    avg_social = sum(a.get("social_score", 0) for a in picked) / len(picked) if picked else 0
    avg_sentiment = (
        sum(a.get("sentiment", 0) for a in picked if a.get("sentiment") is not None) / len(picked)
        if picked
        else 0
    )

    logger.info(
        "news_fetcher: fetched raw=%s filtered=%s dedup=%s query=%s events=%d",
        len(articles) + (0),  # raw_total is logged separately in fetch_bitcoin_mining_articles
        len(articles),
        len(picked),
        query,
        len(event_uris),
    )
    logger.info(
        "news_fetcher: avg_social_score=%.1f avg_sentiment=%.2f spike=%s",
        avg_social,
        avg_sentiment,
        trending.get("is_spike", False),
    )

    if picked:
        dates = [a.get("date", "unknown") for a in picked]
        logger.info("news_fetcher: picked article dates: %s", dates)


def _build_articles_query_params(
    api_key: str,
    query: str,
    concept_uris: List[str],
    trending: Dict,
) -> Dict:
    """Build the base parameter payload for Event Registry article getArticles.

    This keeps all request parameters in one place while preserving the
    existing behavior and environment-driven tuning.
    """
    from datetime import datetime, timedelta, timezone

    # Date window for recency (defaults to last 24 hours)
    max_hours = int(os.getenv("ARTICLES_MAX_HOURS", "24") or "24")
    now = datetime.now(timezone.utc)
    date_start = (now - timedelta(hours=max_hours)).strftime("%Y-%m-%d")
    date_end = now.strftime("%Y-%m-%d")

    # Source rank percentile (env-tunable)
    start_rank = int(os.getenv("START_SOURCE_RANK_PERCENTILE", "0") or "0")
    end_rank = int(os.getenv("END_SOURCE_RANK_PERCENTILE", "50") or "50")

    # Event-only filter (env-tunable). Default keepAll for better recall within 24h.
    events_only = _truthy(os.getenv("EVENTS_ONLY"))
    event_filter_val = "skipArticlesWithoutEvent" if events_only else "keepAll"

    params: Dict = {
        "apiKey": api_key,
        "resultType": "articles",
        "articlesSortBy": "socialScore" if trending.get("is_spike") else "date",
        "lang": "eng",
        # Ask Event Registry to return full article body when possible
        "articleBodyLen": -1,
        # Skip duplicate articles at API level
        "isDuplicateFilter": "skipDuplicates",
        # Source quality filtering (top X% only)
        "startSourceRankPercentile": start_rank,
        "endSourceRankPercentile": end_rank,
        # Only news articles (exclude blogs, press releases)
        "dataType": ["news"],
        # Event filter (keepAll by default)
        "eventFilter": event_filter_val,
        # Include social score for filtering
        "includeArticleSocialScore": True,
        # Include sentiment for filtering
        "includeArticleSentiment": True,
        # Include concepts for better context
        "includeArticleConcepts": True,
        # Include source ranking info
        "includeSourceRanking": True,
        # Date constraints to avoid stale items
        "dateStart": date_start,
        "dateEnd": date_end,
    }

    # Use concept URIs if available, otherwise fall back to keyword
    if concept_uris:
        params["conceptUri"] = concept_uris
        params["conceptOper"] = "or"
    else:
        params["keyword"] = query
    return params


def fetch_bitcoin_mining_articles(limit: int = 5, query: str = "bitcoin mining") -> List[Dict]:
    """
    Fetch recent articles related to bitcoin mining using Event Registry API optimizations.
    Features:
    - Event-based clustering for better signal
    - Concept URI search for precision
    - Source quality filtering (top 50% only)
    - Social score and sentiment filtering
    - Data type filtering (news only, no blogs/PR)
    - Spike detection for breaking news
    """
    api_key = os.getenv("EVENTREGISTRY_API_KEY")
    if not api_key:
        # Return placeholder item to allow local dry-run
        logger.info("news_fetcher: no EVENTREGISTRY_API_KEY; returning placeholder article")
        return [
            {
                "title": "Bitcoin miners eye energy market shifts",
                "url": "https://example.com/bitcoin-miners-energy",
                "text": "Analysts report miners adjusting strategies amid energy price volatility...",
            }
        ]

    # Get concept URIs for more precise search
    concept_uris = _get_concept_uris(api_key, query)
    if concept_uris:
        logger.info("news_fetcher: using concept URIs: %s", concept_uris)

    # Check for trending spikes
    trending = _get_trending_score(api_key, query)
    if trending.get("is_spike"):
        logger.info(
            "news_fetcher: SPIKE DETECTED - recent=%d avg=%.1f",
            trending["recent"],
            trending["average"],
        )

    # Optional minuteStream fast-path (only when explicitly enabled)
    # Note: we do NOT auto-enable this on spikes to keep Event Registry usage predictable.
    use_stream = _truthy(os.getenv("USE_MINUTE_STREAM"))
    stream_minutes = int(os.getenv("MINUTE_STREAM_MINS", "3") or "3")
    event_uris: List[str] = []
    stream_raw: List[Dict] = []
    if use_stream:
        stream_raw = _fetch_minute_stream_articles(api_key, query, concept_uris, stream_minutes)

    # Try event-based fetching first for better clustering
    events = _fetch_events_first(api_key, query, concept_uris)
    event_uris = [str(e.get("uri")) for e in events if e.get("uri")]

    # Enhanced query payload with all optimizations
    base_params = _build_articles_query_params(api_key, query, concept_uris, trending)
    url = "https://eventregistry.org/api/v1/article/getArticles"
    try:
        articles: List[Dict] = []
        raw_total = 0
        seen_uris: set[str] = set()
        picked: List[Dict] = []
        # paginate a small number of pages to collect enough unique events
        # If minute stream returned items, process those first
        search_batches = []
        if stream_raw:
            search_batches.append(("minuteStream", stream_raw))
        # Paginated getArticles results next (1–2 pages max)
        for page in range(1, 3):
            params = {**base_params, "articlesPage": page, "articlesCount": 3}
            data = _er_get(url, params=params, timeout=20, context="getArticles")
            if not data:
                continue
            raw_results = (data.get("articles", {}) or {}).get("results", [])
            search_batches.append((f"page-{page}", raw_results))

        for label, batch in search_batches:
            if len(picked) >= limit:
                break
            raw_total += len(batch)
            # Process each article
            for a in batch:
                uri = a.get("uri") or ""
                if uri in seen_uris:
                    continue
                seen_uris.add(uri)

                art = _build_article_from_er(a)
                if art:
                    articles.append(art)
            # Deduplicate by fingerprint first (most specific), with event_uri as secondary grouping
            # This allows multiple articles per event if they have different fingerprints
            grouped = _group_articles_by_event_or_fingerprint(articles)
            picked = _pick_group_representatives(grouped, limit)

        # Enrich final picked articles with full body only when we are about to use them.
        # To keep Event Registry extractArticleInfo usage bounded, cap per-run enriches.
        try:
            max_enrich = int(os.getenv("EXTRACT_MAX_PER_RUN", "3") or "3")
        except Exception:
            max_enrich = 3
        for art in picked[:max_enrich]:
            _enrich_article_body_if_needed(art, api_key)

        # Log summary with new metrics (including spike info and dates)
        logger.info(
            "news_fetcher: fetched raw=%s filtered=%s dedup=%s query=%s events=%d",
            raw_total,
            len(articles),
            len(picked),
            query,
            len(event_uris),
        )
        _log_fetch_metrics(picked, articles, query, event_uris, trending)

        # Add metadata to picked articles
        for art in picked:
            art["_spike_detected"] = trending.get("is_spike", False)
            art["_event_count"] = len(event_uris)

        return picked
    except Exception as e:
        logger.warning("news_fetcher: fetch error: %s", e)
        # Fail soft with empty list
        return []
