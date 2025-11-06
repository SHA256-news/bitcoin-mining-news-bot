import sys
import os
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.news_fetcher import (
    _pick_best,
    _get_concept_uris,
    _get_trending_score,
    _fetch_events_first,
    fetch_bitcoin_mining_articles,
)


class TestPickBest:
    """Test _pick_best function prioritization logic."""

    def test_prioritizes_higher_social_score_when_domain_scores_equal(self):
        """Test that _pick_best prioritizes articles with higher social scores when domain scores are equal."""
        group = [
            {
                "url": "https://coindesk.com/article-1",
                "title": "Article 1",
                "text": "Short text",
                "social_score": 50,
            },
            {
                "url": "https://coindesk.com/article-2",
                "title": "Article 2",
                "text": "Short text",
                "social_score": 150,
            },
            {
                "url": "https://coindesk.com/article-3",
                "title": "Article 3",
                "text": "Short text",
                "social_score": 100,
            },
        ]

        best = _pick_best(group)

        # Should pick article with highest social_score (150)
        assert best["social_score"] == 150
        assert best["url"] == "https://coindesk.com/article-2"

    def test_prioritizes_domain_score_over_social_score(self):
        """Test that domain score takes precedence over social score."""
        group = [
            {
                "url": "https://benzinga.com/article",  # domain_deny, high penalty
                "title": "Article 1",
                "text": "text",
                "social_score": 500,
            },
            {
                "url": "https://bloomberg.com/article",  # tier-1, low penalty
                "title": "Article 2",
                "text": "text",
                "social_score": 10,
            },
        ]

        best = _pick_best(group)

        # Should pick bloomberg despite lower social score
        assert "bloomberg.com" in best["url"]

    def test_prioritizes_longer_text_when_other_factors_equal(self):
        """Test that longer text is used as tiebreaker."""
        group = [
            {
                "url": "https://coindesk.com/article-1",
                "title": "Article 1",
                "text": "Short",
                "social_score": 100,
            },
            {
                "url": "https://coindesk.com/article-2",
                "title": "Article 2",
                "text": "Much longer text with more details and information",
                "social_score": 100,
            },
        ]

        best = _pick_best(group)

        # Should pick article with longer text
        assert len(best["text"]) > 20


class TestGetConceptUris:
    """Test _get_concept_uris function."""

    @patch("src.news_fetcher._session")
    def test_returns_correct_uris_for_query(self, mock_session):
        """Test that _get_concept_uris returns correct URIs for a given query."""
        # Mock the API response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = [
            {"uri": "http://en.wikipedia.org/wiki/Bitcoin", "label": "Bitcoin"},
            {"uri": "http://en.wikipedia.org/wiki/Bitcoin_mining", "label": "Bitcoin mining"},
            {"uri": "http://en.wikipedia.org/wiki/Cryptocurrency", "label": "Cryptocurrency"},
            {"uri": "http://en.wikipedia.org/wiki/Blockchain", "label": "Blockchain"},
        ]

        mock_session_instance = MagicMock()
        mock_session_instance.get.return_value = mock_response
        mock_session.return_value = mock_session_instance

        result = _get_concept_uris("test_api_key", "bitcoin mining")

        # Should return top 3 URIs
        assert len(result) == 3
        assert result[0] == "http://en.wikipedia.org/wiki/Bitcoin"
        assert result[1] == "http://en.wikipedia.org/wiki/Bitcoin_mining"
        assert result[2] == "http://en.wikipedia.org/wiki/Cryptocurrency"

        # Verify API call was made correctly
        mock_session_instance.get.assert_called_once()
        call_args = mock_session_instance.get.call_args
        assert call_args[0][0] == "https://eventregistry.org/api/v1/suggestConceptsFast"
        assert call_args[1]["params"]["apiKey"] == "test_api_key"
        assert call_args[1]["params"]["prefix"] == "bitcoin mining"

    @patch("src.news_fetcher._session")
    def test_returns_empty_list_on_api_failure(self, mock_session):
        """Test that _get_concept_uris returns empty list on API failure."""
        mock_response = Mock()
        mock_response.ok = False

        mock_session_instance = MagicMock()
        mock_session_instance.get.return_value = mock_response
        mock_session.return_value = mock_session_instance

        result = _get_concept_uris("test_api_key", "bitcoin mining")

        assert result == []

    @patch("src.news_fetcher._session")
    def test_handles_concepts_without_uri(self, mock_session):
        """Test that concepts without URI field are filtered out."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = [
            {"uri": "http://example.com/1", "label": "Label 1"},
            {"label": "Label 2"},  # No URI
            {"uri": "http://example.com/3", "label": "Label 3"},
        ]

        mock_session_instance = MagicMock()
        mock_session_instance.get.return_value = mock_response
        mock_session.return_value = mock_session_instance

        result = _get_concept_uris("test_api_key", "test query")

        # Should only return concepts with URIs
        assert len(result) == 2
        assert result[0] == "http://example.com/1"
        assert result[1] == "http://example.com/3"


class TestGetTrendingScore:
    """Test _get_trending_score function."""

    @patch("src.news_fetcher._session")
    def test_accurately_detects_article_volume_spike(self, mock_session):
        """Test that _get_trending_score accurately detects article volume spikes."""
        # Mock API response with a spike: recent count much higher than average
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "timeAggr": {
                "results": [
                    {"date": "2024-01-01", "count": 10},
                    {"date": "2024-01-02", "count": 12},
                    {"date": "2024-01-03", "count": 11},
                    {"date": "2024-01-04", "count": 50},  # Spike!
                ]
            }
        }

        mock_session_instance = MagicMock()
        mock_session_instance.get.return_value = mock_response
        mock_session.return_value = mock_session_instance

        result = _get_trending_score("test_api_key", "bitcoin mining")

        # Recent count is 50, average is (10+12+11+50)/4 = 20.75
        # 50 > 20.75 * 1.5 (31.125), so should detect spike
        assert result["recent"] == 50
        assert result["average"] == 20.75
        assert result["is_spike"] is True

    @patch("src.news_fetcher._session")
    def test_no_spike_when_volume_stable(self, mock_session):
        """Test that _get_trending_score correctly identifies no spike when volume is stable."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "timeAggr": {
                "results": [
                    {"date": "2024-01-01", "count": 10},
                    {"date": "2024-01-02", "count": 12},
                    {"date": "2024-01-03", "count": 11},
                    {"date": "2024-01-04", "count": 13},  # Stable
                ]
            }
        }

        mock_session_instance = MagicMock()
        mock_session_instance.get.return_value = mock_response
        mock_session.return_value = mock_session_instance

        result = _get_trending_score("test_api_key", "bitcoin mining")

        # Recent count is 13, average is (10+12+11+13)/4 = 11.5
        # 13 < 11.5 * 1.5 (17.25), so no spike
        assert result["recent"] == 13
        assert result["average"] == 11.5
        assert result["is_spike"] is False

    @patch("src.news_fetcher._session")
    def test_returns_default_on_api_failure(self, mock_session):
        """Test that _get_trending_score returns safe defaults on API failure."""
        mock_response = Mock()
        mock_response.ok = False

        mock_session_instance = MagicMock()
        mock_session_instance.get.return_value = mock_response
        mock_session.return_value = mock_session_instance

        result = _get_trending_score("test_api_key", "bitcoin mining")

        assert result["recent"] == 0
        assert result["average"] == 0
        assert result["is_spike"] is False


class TestFetchEventsFirst:
    """Test _fetch_events_first function."""

    @patch("src.news_fetcher._session")
    def test_fetches_events_with_correct_parameters(self, mock_session):
        """Test that _fetch_events_first fetches events with correct parameters."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "events": {
                "results": [
                    {
                        "uri": "event-123",
                        "title": {"eng": "Bitcoin mining event"},
                        "socialScore": 100,
                    },
                    {
                        "uri": "event-456",
                        "title": {"eng": "Mining difficulty adjustment"},
                        "socialScore": 80,
                    },
                ]
            }
        }

        mock_session_instance = MagicMock()
        mock_session_instance.get.return_value = mock_response
        mock_session.return_value = mock_session_instance

        concept_uris = [
            "http://en.wikipedia.org/wiki/Bitcoin",
            "http://en.wikipedia.org/wiki/Bitcoin_mining",
        ]
        result = _fetch_events_first("test_api_key", "bitcoin mining", concept_uris)

        # Should return events
        assert len(result) == 2
        assert result[0]["uri"] == "event-123"
        assert result[1]["uri"] == "event-456"

        # Verify API call parameters
        mock_session_instance.get.assert_called_once()
        call_args = mock_session_instance.get.call_args
        params = call_args[1]["params"]

        assert params["apiKey"] == "test_api_key"
        assert params["resultType"] == "events"
        assert params["eventsSortBy"] == "socialScore"
        assert params["eventsSortByAsc"] is False
        assert params["lang"] == "eng"
        assert params["eventsCount"] == 20
        assert params["minArticlesInEvent"] == 2
        assert params["dataType"] == ["news"]
        assert params["includeEventSocialScore"] is True
        assert params["includeEventArticleCounts"] is True
        assert params["conceptUri"] == concept_uris
        assert params["conceptOper"] == "or"

    @patch("src.news_fetcher._session")
    def test_uses_keyword_when_no_concept_uris(self, mock_session):
        """Test that _fetch_events_first falls back to keyword search when no concept URIs."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"events": {"results": []}}

        mock_session_instance = MagicMock()
        mock_session_instance.get.return_value = mock_response
        mock_session.return_value = mock_session_instance

        _fetch_events_first("test_api_key", "bitcoin mining", [])

        # Verify keyword was used instead of conceptUri
        call_args = mock_session_instance.get.call_args
        params = call_args[1]["params"]

        assert "keyword" in params
        assert params["keyword"] == "bitcoin mining"
        assert "conceptUri" not in params

    @patch("src.news_fetcher._session")
    def test_filters_events_with_date_range(self, mock_session):
        """Test that _fetch_events_first includes correct date range (last 3 days)."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"events": {"results": []}}

        mock_session_instance = MagicMock()
        mock_session_instance.get.return_value = mock_response
        mock_session.return_value = mock_session_instance

        _fetch_events_first("test_api_key", "bitcoin mining", [])

        call_args = mock_session_instance.get.call_args
        params = call_args[1]["params"]

        # Verify date range parameters are present
        assert "dateStart" in params
        assert "dateEnd" in params

        # Date format should be YYYY-MM-DD
        assert len(params["dateStart"]) == 10
        assert len(params["dateEnd"]) == 10

    @patch("src.news_fetcher._session")
    def test_returns_empty_list_on_failure(self, mock_session):
        """Test that _fetch_events_first returns empty list on API failure."""
        mock_session_instance = MagicMock()
        mock_session_instance.get.side_effect = Exception("API error")
        mock_session.return_value = mock_session_instance

        result = _fetch_events_first("test_api_key", "bitcoin mining", [])

        assert result == []


class TestFetchBitcoinMiningArticles:
    """Test fetch_bitcoin_mining_articles function."""

    @patch("src.news_fetcher._session")
    def test_filters_out_very_negative_sentiment_articles(self, mock_session):
        """Test that fetch_bitcoin_mining_articles filters out articles with very negative sentiment."""
        # Mock API responses
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "articles": {
                "results": [
                    {
                        "uri": "article-1",
                        "title": "Bitcoin mining expansion using ASIC miners",
                        "body": "Bitcoin miners deploy new SHA-256 ASIC hardware to increase hashrate capacity.",
                        "url": "https://coindesk.com/article-1",
                        "sentiment": -0.5,  # Very negative, should be filtered
                        "shares": {"facebook": 100},
                        "source": {"title": "CoinDesk"},
                    },
                    {
                        "uri": "article-2",
                        "title": "Bitcoin hashrate reaches new high with ASIC deployment",
                        "body": "New Bitcoin mining facilities using SHA-256 ASICs bring hashrate to record levels.",
                        "url": "https://bloomberg.com/article-2",
                        "sentiment": 0.2,  # Positive, should be included
                        "shares": {"facebook": 50},
                        "source": {"title": "Bloomberg"},
                    },
                    {
                        "uri": "article-3",
                        "title": "Bitcoin mining difficulty adjustment affects ASIC profitability",
                        "body": "Bitcoin mining difficulty increases as SHA-256 hashrate grows across the network.",
                        "url": "https://reuters.com/article-3",
                        "sentiment": -0.2,  # Slightly negative, should be included (threshold is -0.3)
                        "shares": {"facebook": 75},
                        "source": {"title": "Reuters"},
                    },
                ]
            }
        }

        mock_session_instance = MagicMock()
        mock_session_instance.get.return_value = mock_response
        mock_session.return_value = mock_session_instance

        with patch.dict(os.environ, {"EVENTREGISTRY_API_KEY": "test_key"}):
            result = fetch_bitcoin_mining_articles(limit=5, query="bitcoin mining")

        # Should filter out article-1 (sentiment -0.5 < -0.3)
        # Should keep article-2 and article-3
        assert len(result) <= 2

        # Verify no article with sentiment < -0.3 is in results
        for article in result:
            if article.get("sentiment") is not None:
                assert article["sentiment"] >= -0.3

    @patch("src.news_fetcher._get_trending_score")
    @patch("src.news_fetcher._get_concept_uris")
    @patch("src.news_fetcher._fetch_events_first")
    @patch("src.news_fetcher._session")
    def test_includes_sentiment_in_api_request(
        self, mock_session, mock_events, mock_concepts, mock_trending
    ):
        """Test that sentiment is requested in API parameters."""
        # Setup mocks
        mock_concepts.return_value = []
        mock_trending.return_value = {"recent": 0, "average": 0, "is_spike": False}
        mock_events.return_value = []

        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"articles": {"results": []}}

        mock_session_instance = MagicMock()
        mock_session_instance.get.return_value = mock_response
        mock_session.return_value = mock_session_instance

        with patch.dict(os.environ, {"EVENTREGISTRY_API_KEY": "test_key"}):
            fetch_bitcoin_mining_articles(limit=5, query="bitcoin mining")

        # Verify API call included sentiment parameter
        call_args = mock_session_instance.get.call_args
        params = call_args[1]["params"]

        assert "includeArticleSentiment" in params
        assert params["includeArticleSentiment"] is True

    def test_returns_placeholder_without_api_key(self):
        """Test that fetch_bitcoin_mining_articles returns placeholder when no API key."""
        with patch.dict(os.environ, {}, clear=True):
            result = fetch_bitcoin_mining_articles(limit=5, query="bitcoin mining")

        assert len(result) == 1
        assert result[0]["title"] == "Bitcoin miners eye energy market shifts"
        assert "example.com" in result[0]["url"]
