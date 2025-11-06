import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.summarizer import summarize_for_miners


def test_summarizer_offline_fallback(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    art = {"title": "Test title", "text": "Body"}
    headline, bullets = summarize_for_miners(art)
    assert isinstance(headline, str)
    assert len(bullets) == 3


def test_summarizer_handles_very_short_input(monkeypatch):
    """Ensure offline heuristic never hangs and always returns 3 bullets even with <3 sentences."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    # Extremely short text without punctuation or multiple sentences
    art = {"title": "Update", "text": "hashrate up"}
    headline, bullets = summarize_for_miners(art)
    assert isinstance(headline, str)
    assert len(bullets) == 3
    assert all(isinstance(b, str) and b for b in bullets)
