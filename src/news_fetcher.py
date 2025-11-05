import os
import logging
from typing import List, Dict
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


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


def _extract_main_text(html: str) -> str:
    try:
        soup = BeautifulSoup(html, "html.parser")
        # Prefer <article>
        art = soup.find("article")
        if art:
            paras = [p.get_text(" ", strip=True) for p in art.find_all("p")]
            text = "\n".join([p for p in paras if p])
            if len(text) > 400:
                return text
        # Fallback: role=main or id includes 'content'
        main = soup.find(attrs={"role": "main"}) or soup.find(
            id=lambda x: x and "content" in x.lower()
        )
        if main:
            paras = [p.get_text(" ", strip=True) for p in main.find_all("p")]
            text = "\n".join([p for p in paras if p])
            if len(text) > 300:
                return text
        # Last resort: all paragraphs
        paras = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        text = "\n".join([p for p in paras if p])
        return text
    except Exception as e:
        logger.debug("news_fetcher: html parse error: %s", e)
        return ""


def _is_btc_sha256_article(article: Dict) -> bool:
    """Return True if article is Bitcoin-only SHA-256 mining related.
    Rules:
    - Must mention bitcoin or btc AND at least one of: sha-256/sha256/asic/hashrate/difficulty.
    - Must NOT mention: cloud mining, ethereum/eth, litecoin/ltc, dogecoin, gpu.
    """
    title = (article.get("title") or "").lower()
    text = (article.get("text") or "").lower()
    blob = f"{title} {text}"

    if not ("bitcoin" in blob or " btc" in blob or "btc " in blob):
        return False

    include_tokens = ["sha-256", "sha256", "asic", "hashrate", "difficulty"]
    if not any(tok in blob for tok in include_tokens):
        return False

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
    return True


def _parse_list_env(name: str) -> list[str]:
    raw = os.getenv(name, "")
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    # strip leading www.
    return [p.removeprefix("www.") for p in parts]


# Preferred domains first (lower index = higher preference). Extendable via env.
DOMAIN_PREF_ORDER = [
    # General tier-1
    "bloomberg.com",
    "reuters.com",
    "wsj.com",
    "ft.com",
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
    "finance.yahoo.com",
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
        if host in BANNED_DOMAINS:
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
    # Rank: lower domain score first, then longer body (more context for summarization)
    allowed = [g for g in group if _domain(urlparse(g.get("url", "")).netloc) not in BANNED_DOMAINS]
    base = allowed or group
    return sorted(
        base,
        key=lambda a: (
            _domain_score(a.get("url", "")),
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
    # Also keep raw numbers of key sizes
    nums = re.findall(r"\b\d{2,}\b", s)
    parts += nums[:5]
    return list(dict.fromkeys(parts))[:10]


def _fingerprint(article: Dict) -> str:
    # Build a stable fingerprint using normalized title + key numbers/units + top tokens
    import re

    title = (article.get("title") or "").lower()
    text = (article.get("text") or "").lower()[:600]
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
    # prioritize company/mining terms
    keep = []
    for t in tokens:
        if t in {
            "bitcoin",
            "mining",
            "miner",
            "miners",
            "hashrate",
            "difficulty",
            "asic",
            "reserve",
            "treasury",
            "expansion",
            "capacity",
        }:
            keep.append(t)
    # add first few significant tokens
    keep += tokens[:8]
    # add numbers/units
    keep += _numbers_and_units(f"{title} {text}")
    # dedupe and join
    seen = []
    for k in keep:
        if k not in seen:
            seen.append(k)
    fp = " ".join(seen[:20]).strip()
    return fp


def fetch_bitcoin_mining_articles(limit: int = 5, query: str = "bitcoin mining") -> List[Dict]:
    """
    Fetch recent articles related to bitcoin mining.
    NOTE: This is a simple placeholder hitting Event Registry's REST endpoint style.
    Replace with official SDK if preferred.
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

    # Basic query payload; adjust to official API shape as needed
    base_params = {
        "apiKey": api_key,
        "keyword": query,
        "resultType": "articles",
        "sortBy": "date",
        "lang": "eng",
        # Ask Event Registry to return full article body when possible
        "articleBodyLen": -1,
    }
    url = "https://eventregistry.org/api/v1/article/getArticles"
    try:
        articles: List[Dict] = []
        raw_total = 0
        seen_uris: set[str] = set()
        picked: List[Dict] = []
        # paginate a few pages to collect enough unique events
        for page in range(1, 6):
            if len(picked) >= limit:
                break
            params = {
                **base_params,
                "articlesPage": page,
                "articlesCount": 50,
            }
            r = _session().get(url, params=params, timeout=20)
            r.raise_for_status()
            data = r.json()
            raw_results = (data.get("articles", {}) or {}).get("results", [])
            raw_total += len(raw_results)
            # Process each article
            for a in raw_results:
                uri = a.get("uri") or ""
                if uri in seen_uris:
                    continue
                seen_uris.add(uri)
                art = {
                    "title": a.get("title") or "",
                    "url": a.get("url") or "",
                    "text": a.get("body") or a.get("text") or "",
                    "event_uri": a.get("eventUri") or a.get("eventUriWgt") or "",
                    "article_uri": uri,
                    "source": (
                        (a.get("source") or {}).get("title")
                        if isinstance(a.get("source"), dict)
                        else ""
                    ),
                }
                # If API body is missing/short, optionally fetch full article HTML and extract text
                if (not art["text"]) or len(art["text"]) < 500:
                    url2 = art["url"]
                    if url2:
                        try:
                            hr = _session().get(url2, timeout=15)
                            if hr.ok and hr.text:
                                full = _extract_main_text(hr.text)
                                if len(full) > len(art["text"]):
                                    art["text"] = full
                        except Exception as e:
                            logger.debug(
                                "news_fetcher: full-article fetch failed for %s: %s", url2, e
                            )
                # Drop if hard-banned by domain or keyword
                url_str = art.get("url", "")
                host = _domain(urlparse(url_str).netloc)
                blob = f"{art.get('title','')} {art.get('text','')} {art.get('source','')} {url_str}".lower()
                sponsored_url = "/sponsored/" in url_str.lower() or "sponsored" in url_str.lower()
                if (
                    host in BANNED_DOMAINS
                    or any(k in blob for k in BANNED_KEYWORDS)
                    or any(k in blob for k in NEG_ENV_TOKENS)
                    or sponsored_url
                    or any(k in blob for k in SPONSORED_TOKENS)
                ):
                    continue
                if _is_btc_sha256_article(art):
                    # compute fingerprint once text is final
                    art["fingerprint"] = _fingerprint(art)
                    articles.append(art)
            # Deduplicate by eventUri if present, otherwise by fingerprint, else by normalized title signature
            grouped: Dict[str, List[Dict]] = {}
            for art in articles:
                key = (
                    art.get("event_uri")
                    or art.get("fingerprint")
                    or _signature(art.get("title", ""))
                )
                grouped.setdefault(key, []).append(art)
            picked = []
            for key, group in grouped.items():
                picked.append(_pick_best(group))
                if len(picked) >= limit:
                    break
        logger.info(
            "news_fetcher: fetched raw=%s filtered=%s dedup=%s query=%s",
            raw_total,
            len(articles),
            len(picked),
            query,
        )
        return picked
    except Exception as e:
        logger.warning("news_fetcher: fetch error: %s", e)
        # Fail soft with empty list
        return []
