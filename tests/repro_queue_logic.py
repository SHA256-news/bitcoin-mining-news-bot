import unittest
import os
from unittest.mock import patch

# Set env vars before importing to avoid side effects
os.environ["QUEUE_FILE"] = ".state/test_queue.json"
os.environ["STATE_FILE"] = ".state/test_state.json"
os.environ["POSTED_FILE"] = ".state/test_posted.json"

from src import queue


class TestQueueLogic(unittest.TestCase):
    def setUp(self):
        os.makedirs(".state", exist_ok=True)
        # Clear state
        if os.path.exists(".state/test_queue.json"):
            os.remove(".state/test_queue.json")
        if os.path.exists(".state/test_posted.json"):
            os.remove(".state/test_posted.json")

    def tearDown(self):
        pass

    def test_lifo_ordering_fixed(self):
        """Verify that pushing REVERSED list allows popping the NEWEST item first."""
        # Simulate main.py pushing 'rest' with reversed()
        # rest = [Middle, Oldest]
        # push_many(reversed(rest)) -> push_many([Oldest, Middle])
        # Queue: [Oldest, Middle]
        # pop_one() -> Middle (Correct!)

        rest = [
            {"headline": "Middle", "url": "u2", "fingerprint": "f2"},
            {"headline": "Oldest", "url": "u3", "fingerprint": "f3"},
        ]
        queue.push_many(list(reversed(rest)))

        # Verify queue content on disk
        q = queue._load()
        self.assertEqual(q[0]["headline"], "Oldest")
        self.assertEqual(q[1]["headline"], "Middle")

        # Verify pop behavior
        popped = queue.pop_one()
        self.assertIsNotNone(popped)
        if popped:
            self.assertEqual(popped["headline"], "Middle")

    @patch("src.publisher.publish")
    @patch("src.state.already_posted")
    def test_poison_pill_fixed(self, mock_already_posted, mock_publish):
        """Verify that failed items are buried, allowing the next item to be processed."""
        mock_already_posted.return_value = False
        mock_publish.return_value = ("", "")  # Failure

        # Queue: [Good, Bad] (Bad is at top/end)
        items = [
            {"headline": "Good", "url": "good", "fingerprint": "good"},
            {"headline": "Bad", "url": "bad", "fingerprint": "bad"},
        ]
        queue.push_many(items)

        # Simulate new fallback logic:
        # 1. pop Bad
        # 2. fail publish
        # 3. bury Bad (insert at 0)
        # 4. next pop should be Good

        # Iteration 1
        q = queue.pop_one()
        self.assertIsNotNone(q)
        if q:
            self.assertEqual(q["headline"], "Bad")

            # Fail publish -> Bury
            queue.bury_many([q])

        # Verify Queue state: [Bad, Good]
        q_state = queue._load()
        self.assertEqual(q_state[0]["headline"], "Bad")
        self.assertEqual(q_state[1]["headline"], "Good")

        # Iteration 2
        q2 = queue.pop_one()
        self.assertIsNotNone(q2)
        if q2:
            self.assertEqual(q2["headline"], "Good")  # Success! Bad is buried.


if __name__ == "__main__":
    unittest.main()
