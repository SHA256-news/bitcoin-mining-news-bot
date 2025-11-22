import time
import pytest
from unittest.mock import patch
from src.state import (
    already_posted,
    mark_posted,
    _posted_load,
    _posted_identity_equal,
    _normalize_url,
)


@pytest.fixture
def mock_posted_state(tmp_path):
    """Mock the posted state file."""
    with patch("src.state._posted_path") as mock_path, patch("src.state._load", return_value={}):
        p = tmp_path / "posted.json"
        mock_path.return_value = p
        yield p


def test_normalize_url():
    assert _normalize_url("https://example.com/foo?bar=1") == "https://example.com/foo"
    assert _normalize_url("https://example.com/foo#baz") == "https://example.com/foo"
    assert _normalize_url("https://example.com/foo") == "https://example.com/foo"
    assert _normalize_url("") == ""


def test_mark_posted_stores_all_fields(mock_posted_state):
    mark_posted(
        url="https://example.com/1",
        event_uri="eng-123",
        article_uri="111",
        story_uri="story-999",
        fingerprint="fp1",
        tweet_id="1001",
    )

    data = _posted_load()
    items = data["items"]
    assert len(items) == 1
    item = items[0]
    assert item["url"] == "https://example.com/1"
    assert item["norm_url"] == "https://example.com/1"
    assert item["event_uri"] == "eng-123"
    assert item["article_uri"] == "111"
    assert item["story_uri"] == "story-999"
    assert item["fingerprint"] == "fp1"
    assert item["tweet_id"] == "1001"


def test_already_posted_matches_article_uri(mock_posted_state):
    mark_posted(article_uri="111", url="https://example.com/1")
    assert already_posted(article_uri="111", url="https://example.com/2") is True
    assert already_posted(article_uri="222", url="https://example.com/2") is False


def test_already_posted_matches_story_uri(mock_posted_state):
    mark_posted(story_uri="story-1", url="https://example.com/1")
    assert already_posted(story_uri="story-1", url="https://example.com/2") is True
    assert already_posted(story_uri="story-2", url="https://example.com/2") is False


def test_already_posted_matches_event_uri_with_window(mock_posted_state):
    mark_posted(event_uri="eng-1", url="https://example.com/1")

    # Default window
    assert already_posted(event_uri="eng-1", url="https://example.com/2") is True

    # Expired window (simulate time passing)
    with patch("src.state._now_ts", return_value=int(time.time()) + 73 * 3600):
        assert (
            already_posted(event_uri="eng-1", url="https://example.com/2", window_hours=72) is False
        )

    # Custom event window
    # Re-post item because previous block pruned it
    mark_posted(event_uri="eng-1", url="https://example.com/1")

    with patch("src.state._now_ts", return_value=int(time.time()) + 3600):
        assert (
            already_posted(event_uri="eng-1", url="https://example.com/2", event_window_hours=0.5)
            is False
        )
        assert (
            already_posted(event_uri="eng-1", url="https://example.com/2", event_window_hours=2)
            is True
        )


def test_already_posted_matches_fingerprint(mock_posted_state):
    mark_posted(fingerprint="fp1", url="https://example.com/1")
    assert already_posted(fingerprint="fp1", url="https://example.com/2") is True


def test_already_posted_matches_url_normalized(mock_posted_state):
    mark_posted(url="https://example.com/foo?a=1")
    # Should match exact
    assert already_posted(url="https://example.com/foo?a=1") is True
    # Should match normalized
    assert already_posted(url="https://example.com/foo?b=2") is True
    # Should not match different
    assert already_posted(url="https://example.com/bar") is False


def test_posted_identity_equal():
    a = {"article_uri": "1"}
    b = {"article_uri": "1", "url": "u2"}
    assert _posted_identity_equal(a, b) is True

    a = {"event_uri": "e1"}
    b = {"event_uri": "e1"}
    assert _posted_identity_equal(a, b) is True

    a = {"url": "u1"}
    b = {"url": "u2"}
    assert _posted_identity_equal(a, b) is False
