"""Unit tests for rate limiting functionality in summarizer.py."""

import time
import unittest
from unittest.mock import patch, MagicMock
from src.summarizer import (
    _throttle,
    _exponential_backoff_with_jitter,
    _call_gemini,
    RateLimitError,
    _request_history,
)


class TestRateLimiting(unittest.TestCase):
    """Test rate limiting and backoff logic."""

    def setUp(self):
        """Clear request history before each test."""
        _request_history.clear()

    def test_sliding_window_basic(self):
        """Test that sliding window tracks requests correctly."""
        model = "test-model"
        # Set RPM to 3 for testing
        with patch.dict("os.environ", {"GEMINI_PRO_RPM": "3"}):
            # First 3 requests should be fast
            start = time.time()
            for _ in range(3):
                _throttle(model)
            elapsed = time.time() - start
            # Should be very fast (< 1 second)
            self.assertLess(elapsed, 1.0)

            # 4th request should wait for window to clear
            # This will wait ~60 seconds in real execution, so we'll just verify
            # the history has 3 entries
            self.assertEqual(len(_request_history.get(model, [])), 3)

    def test_sliding_window_cleanup(self):
        """Test that old requests are removed from sliding window."""
        model = "test-model"
        history = _request_history.setdefault(model, [])
        now = time.time()

        # Add some old requests (>60 seconds ago)
        history.append(now - 90)
        history.append(now - 75)

        # Add recent request
        history.append(now - 5)

        # Call throttle which should clean up old requests
        with patch.dict("os.environ", {"GEMINI_PRO_RPM": "10"}):
            _throttle(model)

        # Should have removed the old ones and added a new one
        remaining = _request_history.get(model, [])
        # At least the recent one (now-5) and the new one from throttle
        self.assertGreaterEqual(len(remaining), 1)
        # All remaining should be recent (within last 60 seconds)
        for ts in remaining:
            self.assertGreater(ts, now - 60)

    def test_exponential_backoff_increases(self):
        """Test that exponential backoff delays increase correctly."""
        # Test progression: attempt 0, 1, 2, 3
        delay0 = _exponential_backoff_with_jitter(0, base_delay=1.0, max_delay=60.0)
        delay1 = _exponential_backoff_with_jitter(1, base_delay=1.0, max_delay=60.0)
        delay2 = _exponential_backoff_with_jitter(2, base_delay=1.0, max_delay=60.0)
        delay3 = _exponential_backoff_with_jitter(3, base_delay=1.0, max_delay=60.0)

        # Should increase exponentially (with jitter tolerance)
        # Base pattern: 1s, 2s, 4s, 8s (with ±10% jitter)
        self.assertGreater(delay1, delay0 * 0.8)  # Allow for jitter
        self.assertGreater(delay2, delay1 * 0.8)
        self.assertGreater(delay3, delay2 * 0.8)

    def test_exponential_backoff_caps_at_max(self):
        """Test that exponential backoff respects max_delay."""
        delay = _exponential_backoff_with_jitter(10, base_delay=1.0, max_delay=30.0)
        # Should be capped at max_delay + 10% jitter
        self.assertLessEqual(delay, 30.0 * 1.1)

    @patch("src.summarizer.genai.Client")
    @patch("src.summarizer.gemini_remaining")
    @patch("src.summarizer.gemini_increment")
    def test_rate_limit_error_raised(self, mock_increment, mock_remaining, mock_client_class):
        """Test that 429 errors raise RateLimitError."""
        _request_history.clear()

        # Setup mocks
        mock_remaining.return_value = 10
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Simulate 429 error
        mock_client.models.generate_content.side_effect = Exception(
            "429 Resource has been exhausted (e.g. check quota)"
        )

        with self.assertRaises(RateLimitError) as context:
            _call_gemini("gemini-2.5-pro", "fake-key", "system", "user", max_retries=1)

        # Verify it's a RateLimitError
        self.assertIsInstance(context.exception, RateLimitError)

    @patch("src.summarizer.genai.Client")
    @patch("src.summarizer.gemini_remaining")
    @patch("src.summarizer.gemini_increment")
    @patch("src.summarizer.time.sleep")
    def test_non_rate_limit_error_retries(
        self, mock_sleep, mock_increment, mock_remaining, mock_client_class
    ):
        """Test that non-429 errors retry with exponential backoff."""
        _request_history.clear()

        # Setup mocks
        mock_remaining.return_value = 10
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Simulate transient error on first two attempts, success on third
        mock_client.models.generate_content.side_effect = [
            Exception("Network error"),
            Exception("Timeout error"),
            MagicMock(text='{"result": "success"}'),
        ]

        result = _call_gemini("gemini-2.5-pro", "fake-key", "system", "user", max_retries=3)

        # Should succeed after retries
        self.assertIsNotNone(result)
        # Should have slept for backoff
        self.assertGreater(mock_sleep.call_count, 0)

    @patch("src.summarizer.genai.Client")
    @patch("src.summarizer.gemini_remaining")
    @patch("src.summarizer.gemini_increment")
    def test_success_on_first_attempt(self, mock_increment, mock_remaining, mock_client_class):
        """Test successful API call without retries."""
        _request_history.clear()

        # Setup mocks
        mock_remaining.return_value = 10
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_response = MagicMock()
        mock_response.text = '{"result": "success"}'
        mock_client.models.generate_content.return_value = mock_response

        result = _call_gemini("gemini-2.5-pro", "fake-key", "system", "user")

        # Should return response text
        self.assertEqual(result, '{"result": "success"}')
        # Should increment usage
        mock_increment.assert_called_once_with("gemini-2.5-pro")


if __name__ == "__main__":
    unittest.main()
