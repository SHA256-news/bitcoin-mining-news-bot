import os
import logging
from typing import Dict, Tuple

import time
import re

import google.generativeai as genai
from src.state import (
    get_cached_summary,
    set_cached_summary,
    gemini_remaining,
    gemini_increment,
)

logger = logging.getLogger(__name__)


GENERIC_BULLETS = {
    "cost/energy highlight",
    "policy/hardware note",
    "market impact",
}


def _heuristic_bullets(title: str, text: str) -> list[str]:
    # Very simple miner-focused extraction
    import re

    blob = f"{title}. {text}"
    sentences = re.split(r"(?<=[.!?])\s+", blob)[:20]
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
            if any(k in s.lower() for k in keys) and len(s.strip()) > 0:
                picks.append(s.strip())
                break
        if len(picks) >= 3:
            break
    # pad if needed
    while len(picks) < 3:
        for s in sentences:
            if s.strip() and s.strip() not in picks:
                picks.append(s.strip())
                if len(picks) >= 3:
                    break
    # shorten bullets
    return [p[:180] for p in picks[:3]]


def summarize_for_miners(article: Dict) -> Tuple[str, list[str]]:
    """
    Returns (headline, bullets[3]) tailored for Bitcoin miners.
    """
    title = (article.get("title") or "").strip()
    text = (article.get("text") or "").strip()

    api_key = os.getenv("GOOGLE_API_KEY")
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
        h = title or "Bitcoin mining update"
        if "mining" not in h.lower() and "miner" not in h.lower():
            h = f"Bitcoin mining: {h}"[:80]
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
- headline: catchy but factual, target 70–80 characters (no emojis), rephrase and do not repeat the article title; avoid reusing more than 60% of the original title's words; explicitly reference Bitcoin miners or Bitcoin mining.
- bullets: exactly 3, <= 14 words each, no filler, no placeholders, no ellipses; do NOT end with punctuation unless it is a question mark for an open question; avoid repeating the same key word across bullets.
Prioritize: hashrate/difficulty, energy/costs, ASIC/hardware, policy, miner revenue/hashprice.

Title: {title}
Article:
{text[:6000]}

Respond ONLY as JSON with keys: relevant (boolean), headline (string when relevant), bullets (array of 3 strings when relevant), estimated_total_chars (int for `headline — • b1 • b2 • b3`).
If estimated_total_chars would exceed 260, shorten headline/bullets to fit. Do not use ellipses. Do not end bullets with periods.
"""

    def _throttle(model_name: str):
        rpm_defaults = {
            "gemini-2.5-pro": int(os.getenv("GEMINI_PRO_RPM", "2")),
            "gemini-2.5-flash": int(os.getenv("GEMINI_FLASH_RPM", "10")),
        }
        rpm = rpm_defaults.get(model_name, 10)
        # minimal inter-call delay in seconds
        min_gap = max(0.0, 60.0 / max(1, rpm))
        last_key = f"_last_call_{model_name}"
        last = globals().get(last_key, 0.0)
        now = time.time()
        sleep_s = last + min_gap - now
        if sleep_s > 0:
            time.sleep(sleep_s)
        globals()[last_key] = time.time()

    def _call(model_name: str, sys: str, usr: str) -> str:
        if gemini_remaining(model_name) <= 0:
            raise RuntimeError(f"no remaining daily budget for {model_name}")
        _throttle(model_name)
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name,
            generation_config={
                "temperature": 0.4,
                "response_mime_type": "application/json",
            },
        )
        try:
            resp = model.generate_content([sys, usr])
            gemini_increment(model_name)
            return resp.text or "{}"
        except Exception as e:
            msg = str(e)
            # Parse retry delay seconds if present
            m = re.search(r"retry in (\d+(?:\.\d+)?)s|seconds: (\d+)", msg, flags=re.I)
            if m:
                try:
                    secs = float(next(g for g in m.groups() if g))
                    time.sleep(min(secs, 30.0))
                except Exception:
                    time.sleep(30)
                # single retry
                resp = model.generate_content([sys, usr])
                gemini_increment(model_name)
                return resp.text or "{}"
            raise

    # choose model: prefer pro if allowed; otherwise flash
    chosen_model = (
        model_name_pro if prefer_pro and gemini_remaining(model_name_pro) > 0 else model_name_flash
    )
    logger.info(
        "summarizer: model=%s prefer_pro=%s rem_pro=%s rem_flash=%s fp=%s",
        chosen_model,
        prefer_pro,
        gemini_remaining(model_name_pro),
        gemini_remaining(model_name_flash),
        fp,
    )

    try:
        content = _call(chosen_model, system_prompt, user_prompt)
    except Exception as e:
        logger.warning("summarizer: API error: %s; falling back", e)
        # fallback to flash if not already
        if chosen_model != model_name_flash:
            try:
                content = _call(model_name_flash, system_prompt, user_prompt)
            except Exception as e2:
                logger.warning("summarizer: flash fallback failed: %s", e2)
                # On API failure, fallback but still ensure headline references mining
                h = (title or "Bitcoin mining update").strip()
                if "mining" not in h.lower() and "miner" not in h.lower():
                    h = f"Bitcoin mining: {h}"[:80]
                return (
                    h,
                    _heuristic_bullets(title, text),
                )
        else:
            # On API failure, fallback but still ensure headline references mining
            h = (title or "Bitcoin mining update").strip()
            if "mining" not in h.lower() and "miner" not in h.lower():
                h = f"Bitcoin mining: {h}"[:80]
            return (
                h,
                _heuristic_bullets(title, text),
            )

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
        # enforce explicit mining reference in headline
        head_l = headline.lower()
        if not ("mining" in head_l or "miner" in head_l):
            raise ValueError("headline lacks mining reference")
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
