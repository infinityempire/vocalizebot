import os
import unittest
import sqlite3  # Added import for sqlite3
from datetime import datetime, timedelta
from subscription_manager import SubscriptionManager

class TestSubscriptionManager(unittest.TestCase):
    def setUp(self):
        """Set up a temporary database for testing."""
        self.test_db = "test_subscriptions.db"
        self.manager = SubscriptionManager(db_path=self.test_db)

    def tearDown(self):
        """Clean up the temporary database after tests."""
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    def test_add_user_defaults_to_free(self):
        """Test that a new user is added with the 'free' tier by default."""
        self.manager.add_user("user1")
        with sqlite3.connect(self.test_db) as conn: # Fixed: connect directly to the test DB
            cursor = conn.cursor()
            cursor.execute("SELECT tier FROM users WHERE user_id = ?", ("user1",))
            tier = cursor.fetchone()[0]
        self.assertEqual(tier, "free")

    def test_free_tier_limits(self):
        """Test the limits of the 'free' tier."""
        self.manager.add_user("user2")

        # Test exceeding voice length when daily count is not yet reached
        allowed, message = self.manager.can_transcribe("user2", 31)
        self.assertFalse(allowed)
        self.assertEqual(message, "Voice note exceeds maximum allowed length.")

        # Test within daily limits
        for _ in range(3):
            allowed, message = self.manager.can_transcribe("user2", 30)
            self.assertTrue(allowed)
            self.manager.increment_transcription_count("user2") # Fixed: increment count after successful transcription

        # Test exceeding daily limit
        allowed, message = self.manager.can_transcribe("user2", 30)
        self.assertFalse(allowed)
        self.assertEqual(message, "Daily transcription limit reached.")


    def test_upgrade_to_premium(self):
        """Test upgrading a user to the 'premium' tier."""
        self.manager.add_user("user3")
        self.manager.upgrade_tier("user3", "premium", duration_days=30)
        with sqlite3.connect(self.test_db) as conn: # Fixed: connect directly to the test DB
            cursor = conn.cursor()
            cursor.execute("SELECT tier, tier_expiration FROM users WHERE user_id = ?", ("user3",))
            tier, expiration = cursor.fetchone()
        self.assertEqual(tier, "premium")
        self.assertEqual(datetime.strptime(expiration, "%Y-%m-%d").date(), (datetime.now() + timedelta(days=30)).date())
        # Test premium limits
        allowed, message = self.manager.can_transcribe("user3", 300)
        self.assertTrue(allowed)
        # Test exceeding premium voice length
        allowed, message = self.manager.can_transcribe("user3", 301)
        self.assertFalse(allowed)
        self.assertEqual(message, "Voice note exceeds maximum allowed length.")

if __name__ == "__main__":
    unittest.main()
