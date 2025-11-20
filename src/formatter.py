import re

MAX_TWEET_LEN = 280


def _tokens(text: str) -> set[str]:
    s = (text or "").lower()
    # words and numbers/currencies
    words = re.findall(r"[a-z0-9$€£]+(?:[./,][a-z0-9]+)?", s)
    # include common multiword phrases
    phrases = []
    if "bitcoin mining" in s:
        phrases.append("bitcoin mining")
    if "bitcoin miner" in s:
        phrases.append("bitcoin miner")
    return set(words + phrases)


def _numbers(text: str) -> set[str]:
    s = (text or "").lower()
    return set(re.findall(r"\$?\d[\d,\.]*%?", s))


def sanitize_summary(
    headline: str, bullets: list[str], source_title: str = ""
) -> tuple[str, list[str]]:
    # Ensure headline differs from source title; avoid repeating headline numbers/phrases in bullets
    head = (headline or "").strip()
    if source_title:
        ht = set(_tokens(head))
        st = set(_tokens(source_title))
        overlap = len(ht & st)
        ratio = (overlap / max(1, len(ht))) if ht else 0.0
        if ht and ratio > 0.6:
            # Try a conservative rewrite: keep readability; avoid aggressive token stripping
            cleaned_tokens = [
                t
                for t in head.split()
                if t.lower() not in st and t.lower() not in {"the", "a", "an"}
            ]
            candidate = " ".join(cleaned_tokens).strip()
            # If aggressive removal degrades readability, keep original without adding generic prefixes
            words = candidate.split()
            head = candidate if (len(candidate) >= 24 and len(words) >= 4) else head
    # Allow a longer, more informative hook
    head = head[:110]

    # Exact phrases and numbers to avoid in bullets
    headline_l = head.lower()
    banned_phrase_patterns = []
    # Avoid repeating common phrases if present in headline
    for phrase in ["bitcoin mining", "bitcoin miner", "btc miners"]:
        if phrase in headline_l:
            banned_phrase_patterns.append(re.compile(rf"\b{re.escape(phrase)}\b", re.I))
    # Avoid repeating headline numbers (currencies/units)
    num_unit_pat = r"\$?\d[\d,\.]*%?(?:\s*(?:MW|GW|EH/s|ZH/s|TH/s|BTC|USD|EHps))?"
    headline_nums = set(re.findall(num_unit_pat, head))

    def strip_forbidden(text: str, allow_nums: bool) -> str:
        out = text
        # Remove banned phrases first
        for pat in banned_phrase_patterns:
            out = pat.sub("", out)
        # Remove headline numbers unless this bullet is allowed to keep them
        if not allow_nums:
            for n in headline_nums:
                out = re.sub(re.escape(n), "", out)
        # Collapse spaces
        out = re.sub(r"\s+", " ", out).strip()
        return out

    def _cap_first_alpha(s: str) -> str:
        for i, ch in enumerate(s):
            if ch.isalpha():
                return s[:i] + ch.upper() + s[i + 1 :]
        return s

    cleaned: list[str] = []
    seen_bullets: set[str] = set()
    kept_nums_once = False

    # Precompute headline tokens for prefix-duplication cleanup in bullets
    head_tokens = re.findall(r"[A-Za-z0-9$€£]+", head.lower()) if head else []

    for b in bullets:
        s = (b or "").strip()
        if not s:
            continue
        # Remove trailing punctuation except ?
        if s.endswith((".", "!", ";", ":")):
            s = s.rstrip(".!;:")

        # If the bullet starts by repeating the headline phrase, strip that prefix
        if head_tokens:
            b_tokens = re.findall(r"[A-Za-z0-9$€£]+", s.lower())
            if b_tokens:
                # Compare first few tokens for overlap
                k = min(6, len(head_tokens), len(b_tokens))
                if k >= 3 and b_tokens[:k] == head_tokens[:k]:
                    # Drop that many tokens from the original bullet
                    original_parts = s.split()
                    if len(original_parts) > k:
                        s = " ".join(original_parts[k:]).lstrip(",: ") or s

        # Decide if this bullet can keep headline numbers
        allow_nums = (not kept_nums_once) and any((n in s) for n in headline_nums)
        if allow_nums:
            kept_nums_once = True
        s2 = strip_forbidden(s, allow_nums=allow_nums)
        # Normalize spaces around units like MW/EH/s
        s2 = re.sub(r"\s+(MW|GW|EH/s|ZH/s|TH/s|BTC|USD|EHps)\b", r" \1", s2)
        # Enforce <=14 words by words without stripping inner punctuation
        words = re.findall(r"\S+", s2)
        if len(words) > 14:
            s2 = " ".join(words[:14])
        s2 = _cap_first_alpha(s2)
        if not s2:
            continue
        key = s2.lower()
        if key in seen_bullets:
            continue
        seen_bullets.add(key)
        cleaned.append(s2)
        if len(cleaned) == 3:
            break
    return head, cleaned[:3]


def _word_trim(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    cut = text[:limit]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.strip()


def _compose_smart(headline: str, bullets: list[str], limit: int = MAX_TWEET_LEN) -> str:
    """Compose multiline tweet:
    Headline

    • b1
    • b2
    • b3
    Fits within the limit by dropping bullets if necessary, then trimming headline.
    """
    head = (headline or "").strip()
    bs = [b.strip("• -\u2022 ") for b in bullets if b and b.strip()][:3]
    # Pre-trim each bullet lightly and strip trailing punctuation
    bs = [_word_trim(b.strip().rstrip(".").rstrip("!"), 90) for b in bs]

    def build(h: str, blts: list[str]) -> str:
        if not blts:
            return _word_trim(h, limit)
        body = "\n".join(f"• {b}" for b in blts)
        return f"{_word_trim(h, limit)}\n\n{body}".strip()

    # Try with 3→1 bullets, then headline-only
    for nb in range(len(bs), -1, -1):
        cand = build(head, bs[:nb])
        if len(cand) <= limit:
            return cand

    # Fallback (shouldn't happen): trim headline only
    return _word_trim(head or "", limit)


def trim_to_limit(text: str, limit: int = MAX_TWEET_LEN) -> str:
    text = " ".join(text.split())  # normalize whitespace
    return text[:limit]


def compose_tweet_1(headline: str, bullets: list[str]) -> str:
    # Format: Headline — • b1 • b2 • b3, with smart fitting under 280 chars
    return _compose_smart(headline, bullets, MAX_TWEET_LEN)


def compose_tweet_2(url: str) -> str:
    return _word_trim(url, MAX_TWEET_LEN)
