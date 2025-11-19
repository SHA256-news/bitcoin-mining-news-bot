import pytest
from src.summarizer import summarize_for_miners
from unittest.mock import patch, MagicMock

@patch("src.summarizer._call_gemini")
@patch("src.summarizer.get_cached_summary")
def test_summarizer_strictness(mock_get_cache, mock_call_gemini):
    import os
    os.environ["GOOGLE_API_KEY"] = "fake"
    mock_get_cache.return_value = None
    # Mock Gemini response with a valid but "numberless" headline
    mock_call_gemini.return_value = '{"relevant": true, "headline": "Bitcoin miners expand operations in Texas", "bullets": ["New facility opens", "Capacity increases", "Jobs created"], "estimated_total_chars": 100}'

    article = {
        "title": "Miners expand",
        "text": "Bitcoin miners are expanding in Texas.",
        "fingerprint": "fp1"
    }

    # This should NOT raise ValueError if we relax the check, but currently it might
    # We expect it to return the fallback (heuristic) if it fails validation
    headline, bullets = summarize_for_miners(article)
    
    # If validation fails, it falls back to heuristic which uses the title "Miners expand"
    # If validation passes, it uses the Gemini headline "Bitcoin miners expand operations in Texas"
    
    assert headline == "Bitcoin miners expand operations in Texas"
