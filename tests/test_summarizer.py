from src.summarizer import summarize_for_miners


def test_summarizer_offline_fallback(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    art = {"title": "Test title", "text": "Body"}
    headline, bullets = summarize_for_miners(art)
    assert isinstance(headline, str)
    assert len(bullets) == 3
