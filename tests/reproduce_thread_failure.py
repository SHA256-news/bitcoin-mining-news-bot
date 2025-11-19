import unittest
from unittest.mock import MagicMock, patch
from src.publisher import publish

class TestPublisherPartialFailure(unittest.TestCase):
    @patch("src.publisher._client")
    @patch("src.publisher._has_x_credentials")
    def test_publish_partial_failure(self, mock_has_creds, mock_client_factory):
        # Setup mocks
        mock_has_creds.return_value = True
        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        
        # Mock tweet 1 success
        mock_resp1 = MagicMock()
        mock_resp1.data = {"id": "1001"}
        
        # Mock tweet 2 failure (raises Exception)
        mock_client.create_tweet.side_effect = [
            mock_resp1,                 # 1st call succeeds
            Exception("Simulated API Error") # 2nd call fails
        ]
        
        # Call publish
        tid1, tid2 = publish("Tweet 1", "Tweet 2")
        
        print(f"TID1: {tid1}, TID2: {tid2}")
        
        # Assertions
        # With rollback, both should be empty so main.py retries
        self.assertEqual(tid1, "")
        self.assertEqual(tid2, "")
        
        # Verify create_tweet was called twice
        self.assertEqual(mock_client.create_tweet.call_count, 2)
        # Verify delete_tweet was called once (rollback)
        mock_client.delete_tweet.assert_called_once_with("1001")

if __name__ == "__main__":
    unittest.main()
