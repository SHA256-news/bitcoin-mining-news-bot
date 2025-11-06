import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.formatter import compose_tweet_1, compose_tweet_2, MAX_TWEET_LEN, sanitize_summary


def test_compose_tweet_1_basic():
    h = "Miners pivot as energy prices shift"
    bullets = ["Policy update", "Energy costs down", "Hardware lead times ease"]
    t = compose_tweet_1(h, bullets)
    assert h in t
    assert "• Policy update" in t
    assert len(t) <= MAX_TWEET_LEN


def test_compose_tweet_2_trims():
    url = "https://example.com/" + ("x" * 500)
    t = compose_tweet_2(url)
    assert len(t) <= MAX_TWEET_LEN


def test_sanitize_high_overlap_fallback():
    # When headline and source title overlap heavily, sanitizer should keep readability
    head, blts = sanitize_summary(
        headline="Cango builds 50 EH/s fleet, acquires 50 MW site for refresh",
        bullets=[
            "Built a 50 EH/s fleet since late 2024 mining entry",
            "Acquired 50 MW Georgia site to refresh 6 EH/s of ASICs",
            "Explores HPC pivot while facing potential US regulatory review",
        ],
        source_title="Cango builds 50 EH/s fleet, acquires 50 MW site for refresh",
    )
    assert head  # non-empty
    # Should avoid unreadable outputs like "For Bitcoin miners: Miner After Rapid Expansion"
    assert "Bitcoin mining:" in head or head.startswith("Cango")
    assert len(blts) == 3
