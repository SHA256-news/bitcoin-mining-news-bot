import os
import logging
from typing import Dict, Tuple, List
import random

import time
import re

from google import genai
from google.genai import types
from src.state import (
    get_cached_summary,
    set_cached_summary,
    gemini_remaining,
    gemini_increment,
)

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    """Raised when API returns 429 rate limit error."""

    def __init__(self, message: str, retry_after: float = 0):
        super().__init__(message)
        self.retry_after = retry_after


GENERIC_BULLETS = {
    "cost/energy highlight",
    "policy/hardware note",
    "market impact",
}


def _heuristic_bullets(title: str, text: str) -> list[str]:
    # Very simple miner-focused extraction that NEVER loops forever, even with empty input
    import re

    blob = " ".join([t.strip() for t in [title or "", text or ""] if t])
    # Split into sentences; filter out empties and de-duplicate order-preserving
    raw_sentences = re.split(r"(?<=[.!?])\s+", blob) if blob else []
    seen: set[str] = set()
    sentences = []
    for s in raw_sentences[:20]:
        ss = s.strip()
        if ss and ss not in seen:
            seen.add(ss)
            sentences.append(ss)

    picks: list[str] = []
    themes = [
        ("hashrate", ["hashrate", "eh/s", "zh/s", "th/s"]),
        ("difficulty", ["difficulty", "retarget", "adjustment"]),
        ("energy/costs", ["energy", "power", "electric", "cost", "opex", "capex", "ppc", "pue"]),
        ("policy", ["policy", "ban", "tax", "subsidy", "regulat", "permit"]),
        ("hardware", ["asic", "s19", "m50", "jpro", "hydro", "immersion"]),
        ("market", ["revenue", "hashprice", "profit", "fee", "halving"]),
    ]
    for _, keys in themes:
        for s in sentences:
            if any(k in s.lower() for k in keys):
                picks.append(s)
                break
        if len(picks) >= 3:
            break

    # Pad safely without infinite looping
    if len(picks) < 3:
        for s in sentences:
            if s not in picks:
                picks.append(s)
            if len(picks) >= 3:
                break

    # If still short, synthesize compact generic-but-informative bullets from available text
    if len(picks) < 3:
        base = (title or text or "Bitcoin mining update").strip() or "Bitcoin mining update"
        # Create up to remaining bullets by chunking words
        words = re.findall(r"\w+", base)
        if words:
            chunk = max(3, min(10, len(words)))
            while len(picks) < 3 and words:
                picks.append(" ".join(words[:chunk]).strip())
                words = words[chunk:]
        while len(picks) < 3:
            picks.append("Update for miners")

    # shorten bullets
    return [p[:180] for p in picks[:3]]


# Global tracking per model: {model_name: [timestamp1, timestamp2, ...]}
_request_history: Dict[str, List[float]] = {}


def _throttle(model_name: str) -> None:
    """Rate-limit Gemini calls using sliding window to prevent burst violations.

    Maintains a history of recent requests and enforces RPM limits by waiting
    for the oldest request to expire if we're at the limit.
    """
    rpm_defaults = {
        "gemini-2.5-pro": int(os.getenv("GEMINI_PRO_RPM", "2")),
        "gemini-2.5-flash": int(os.getenv("GEMINI_FLASH_RPM", "10")),
    }
    rpm = rpm_defaults.get(model_name, 10)
    window_seconds = 60.0

    # Get or create request history for this model
    history = _request_history.setdefault(model_name, [])
    now = time.time()

    # Remove requests outside the sliding window
    cutoff = now - window_seconds
    history[:] = [ts for ts in history if ts > cutoff]

    # If we're at the limit, wait until oldest request expires
    if len(history) >= rpm:
        oldest = history[0]
        wait_time = (oldest + window_seconds) - now
        if wait_time > 0:
            logger.info(
                "Rate limit: waiting %.1fs for %s (have %d/%d requests in window)",
                wait_time,
                model_name,
                len(history),
                rpm,
            )
            time.sleep(wait_time)
            # Clean up again after sleeping
            now = time.time()
            cutoff = now - window_seconds
            history[:] = [ts for ts in history if ts > cutoff]

    # Record this request
    history.append(time.time())


def _exponential_backoff_with_jitter(
    attempt: int, base_delay: float = 1.0, max_delay: float = 60.0
) -> float:
    """Calculate exponential backoff delay with jitter."""
    delay = min(base_delay * (2**attempt), max_delay)
    jitter = random.uniform(0, delay * 0.1)  # ±10% jitter
    return delay + jitter


def _call_gemini(
    model_name: str,
    api_key: str | None,
    system_prompt: str,
    user_prompt: str,
    max_retries: int = 3,
) -> str:
    """Call Gemini with JSON response, budget checks, throttle, and exponential backoff.

    Raises RateLimitError on 429 to allow intelligent fallback to Flash.
    """
    if gemini_remaining(model_name) <= 0:
        raise RuntimeError(f"no remaining daily budget for {model_name}")

    _throttle(model_name)
    client = genai.Client(api_key=api_key) if api_key else genai.Client()
    config = types.GenerateContentConfig(
        temperature=0.4,
        response_mime_type="application/json",
    )

    for attempt in range(max_retries):
        try:
            resp = client.models.generate_content(
                model=model_name,
                contents=[system_prompt, user_prompt],
                config=config,
            )
            gemini_increment(model_name)
            return resp.text or "{}"
        except Exception as e:
            msg = str(e).lower()

            # Detect 429 rate limit errors
            if "429" in msg or "rate limit" in msg or "quota" in msg:
                # Parse Retry-After header or delay from error message
                retry_after = 0.0
                m = re.search(r"retry[- ]?after[:\s]*(\d+)", msg, flags=re.I)
                if not m:
                    m = re.search(r"retry in (\d+(?:\.\d+)?)s|seconds: (\d+)", msg, flags=re.I)
                if m:
                    try:
                        retry_after = float(next(g for g in m.groups() if g))
                    except Exception:
                        pass

                logger.warning(
                    "Rate limit (429) from %s on attempt %d/%d: %s",
                    model_name,
                    attempt + 1,
                    max_retries,
                    str(e)[:100],
                )

                # For 429 errors, raise immediately to allow fallback to Flash
                # Don't waste retries on rate limits
                raise RateLimitError(str(e), retry_after=retry_after)

            # For other errors, use exponential backoff
            if attempt < max_retries - 1:
                # Parse retry delay if present in error message
                m = re.search(r"retry in (\d+(?:\.\d+)?)s|seconds: (\d+)", msg, flags=re.I)
                if m:
                    try:
                        delay = float(next(g for g in m.groups() if g))
                        delay = min(delay, 30.0)
                    except Exception:
                        delay = _exponential_backoff_with_jitter(attempt)
                else:
                    delay = _exponential_backoff_with_jitter(attempt)

                logger.warning(
                    "API error from %s (attempt %d/%d), retrying in %.1fs: %s",
                    model_name,
                    attempt + 1,
                    max_retries,
                    delay,
                    str(e)[:100],
                )
                time.sleep(delay)
            else:
                # Last attempt, raise the error
                raise

    # Fallback if all retries exhausted (should never reach here due to raise above)
    return "{}"


def summarize_for_miners(article: Dict) -> Tuple[str, list[str]]:
    """
    Returns (headline, bullets[3]) tailored for Bitcoin miners.
    """
    title = (article.get("title") or "").strip()
    text = (article.get("text") or "").strip()

    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    model_name_pro = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
    model_name_flash = os.getenv("GEMINI_FLASH_MODEL", "gemini-2.5-flash")
    prefer_pro = bool(os.getenv("PREFER_GEMINI_PRO", "1") not in {"0", "false", "no"})

    # Summary cache by fingerprint
    fp = (article.get("fingerprint") or "").strip()
    if fp:
        cached = get_cached_summary(fp)
        if cached:
            h, b = cached
            if h and b:
                return h, b

    if not api_key:
        # Offline fallback for dev
        logger.info("summarizer: no GOOGLE_API_KEY; using offline fallback")
        h = (title or "Update").strip()[:110]
        return (
            h,
            _heuristic_bullets(title, text),
        )

    system_prompt = (
        "You write for professional Bitcoin (BTC) SHA-256 miners. Return concise, factual outputs."
    )
    user_prompt = f"""
First, silently decide if this article is DIRECTLY RELEVANT to Bitcoin miners (mining operations, hashrate/difficulty, energy costs, ASIC/hardware, policy that impacts miners, miner revenue/hashprice). If not, set relevant=false and STOP.
Then, if relevant=true, generate:
- headline: write a sharp 70–100 character hook (no emojis). Do NOT say "Bitcoin mining" or "Bitcoin miners" unless essential; instead, lead with the concrete outcome (beat/miss/guidance), key numbers, and the subject (e.g., company/ticker, capacity, margin, EH/s, MW). Rephrase and do not repeat the article title; avoid reusing >60% of its words.
- bullets: exactly 3, <= 14 words each, no filler/placeholders/ellipses; no trailing periods. Each bullet should carry a distinct fact: production/units/EH/s or BTC; costs/margins/PPAs; policy/permits/deals/guidance.
Prioritize: hashrate/difficulty, energy/costs, ASIC/hardware, policy, miner revenue/hashprice. Include the specific beat/miss vs forecasts when available.

Title: {title}
Article:
{text[:6000]}

Respond ONLY as JSON with keys: relevant (boolean), headline (string when relevant), bullets (array of 3 strings when relevant), estimated_total_chars (int for `headline — • b1 • b2 • b3`).
If estimated_total_chars would exceed 260, shorten headline/bullets to fit. Do not use ellipses. Do not end bullets with periods.
"""

    # Choose model: prefer pro if allowed; otherwise flash
    chosen_model = (
        model_name_pro if prefer_pro and gemini_remaining(model_name_pro) > 0 else model_name_flash
    )
    logger.info(
        "summarizer: attempting model=%s prefer_pro=%s rem_pro=%s rem_flash=%s fp=%s",
        chosen_model,
        prefer_pro,
        gemini_remaining(model_name_pro),
        gemini_remaining(model_name_flash),
        fp,
    )

    # Try Pro first (if selected), with automatic fallback to Flash on rate limits
    try:
        content = _call_gemini(chosen_model, api_key, system_prompt, user_prompt)
        logger.info("summarizer: success with model=%s", chosen_model)
    except RateLimitError as e:
        # Rate limit hit - immediately fallback to Flash (don't retry Pro)
        logger.warning(
            "summarizer: rate limit (429) from %s, falling back to flash (retry_after=%.1fs)",
            chosen_model,
            e.retry_after,
        )
        if chosen_model != model_name_flash and gemini_remaining(model_name_flash) > 0:
            # Wait if retry_after was provided
            if e.retry_after > 0:
                wait_time = min(e.retry_after, 60.0)  # cap at 60s
                logger.info("summarizer: waiting %.1fs before trying flash", wait_time)
                time.sleep(wait_time)
            try:
                content = _call_gemini(model_name_flash, api_key, system_prompt, user_prompt)
                logger.info("summarizer: success with fallback model=flash")
            except RateLimitError as e2:
                # Flash also rate limited - use exponential backoff
                logger.warning("summarizer: flash also rate limited, backing off")
                wait_time = min(e2.retry_after or 30.0, 60.0)
                time.sleep(wait_time)
                # Final offline fallback
                logger.warning("summarizer: all models rate limited, using offline fallback")
                h = (title or "Bitcoin mining update").strip()
                if "mining" not in h.lower() and "miner" not in h.lower():
                    h = f"Bitcoin mining: {h}"[:80]
                return (h, _heuristic_bullets(title, text))
            except Exception as e2:
                logger.warning("summarizer: flash fallback failed: %s", e2)
                h = (title or "Bitcoin mining update").strip()
                if "mining" not in h.lower() and "miner" not in h.lower():
                    h = f"Bitcoin mining: {h}"[:80]
                return (h, _heuristic_bullets(title, text))
        else:
            # No Flash budget or Flash was already chosen
            logger.warning("summarizer: no flash budget available, using offline fallback")
            h = (title or "Update").strip()[:110]
            return (h, _heuristic_bullets(title, text))
    except Exception as e:
        # Non-rate-limit error - try fallback to flash if not already
        logger.warning(
            "summarizer: API error from %s: %s; falling back", chosen_model, str(e)[:100]
        )
        if chosen_model != model_name_flash and gemini_remaining(model_name_flash) > 0:
            try:
                content = _call_gemini(model_name_flash, api_key, system_prompt, user_prompt)
                logger.info("summarizer: success with fallback model=flash")
            except Exception as e2:
                logger.warning("summarizer: flash fallback failed: %s", str(e2)[:100])
                h = (title or "Bitcoin mining update").strip()
                if "mining" not in h.lower() and "miner" not in h.lower():
                    h = f"Bitcoin mining: {h}"[:80]
                return (h, _heuristic_bullets(title, text))
        else:
            # Offline fallback
            h = (title or "Update").strip()[:110]
            return (h, _heuristic_bullets(title, text))

    import json

    try:
        data = json.loads(content)
        # relevance gate
        if not bool(data.get("relevant")):
            raise ValueError("not relevant to miners")
        headline = (data.get("headline") or title or "Bitcoin mining update").strip()
        bullets = [b.strip() for b in (data.get("bullets") or [])][:3]
        # guard against generic/placeholders and enforce 3 bullets
        norm = {b.lower() for b in bullets}
        if len(bullets) != 3 or any(x in norm for x in GENERIC_BULLETS) or not all(bullets):
            raise ValueError("generic or invalid bullets")
        # ensure headline conveys a concrete outcome or number
        # Relaxed: allow if it has numbers OR if it has strong keywords
        has_number = len(re.findall(r"\d", headline)) > 0
        has_keyword = bool(
            re.search(
                r"\b(beat|miss|record|guidance|surge|plunge|deal|contract|open|opens|expand|expands|launch|launches|partner|partners|secure|secures|approve|approves|ban|bans|tax|taxes)\b",
                headline,
                flags=re.I,
            )
        )

        if not has_number and not has_keyword:
            # Fallback for very generic headlines that might still be useful if they aren't just "Bitcoin mining update"
            if len(headline.split()) < 4 or headline.lower() in [
                "bitcoin mining update",
                "market update",
                "mining news",
            ]:
                raise ValueError("headline lacks concrete hook")
        # Optional: trust but verify budget
        est = data.get("estimated_total_chars")
        if isinstance(est, int) and est > 260:
            raise ValueError("over budget; fallback")
        # cache result by fingerprint
        if fp and headline and bullets:
            set_cached_summary(fp, headline, bullets)
        return headline, bullets
    except Exception:
        # signal skip by returning empty headline/bullets
        return ("", [])
