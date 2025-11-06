import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.formatter import compose_tweet_1, compose_tweet_2, MAX_TWEET_LEN


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
