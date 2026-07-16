import sqlite3
from datetime import datetime, timedelta

# Define user tiers
USER_TIERS = {
    "free": {"max_transcriptions": 3, "max_voice_length": 30, "custom_prompts": False},
    "premium": {"max_transcriptions": float("inf"), "max_voice_length": 300, "custom_prompts": False},
    "vip": {"max_transcriptions": float("inf"), "max_voice_length": float("inf"), "custom_prompts": True},
}

class SubscriptionManager:
    def __init__(self, db_path="subscriptions.db"):
        self.db_path = db_path
        self._initialize_database()

    def _initialize_database(self):
        """Initialize the SQLite database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    tier TEXT NOT NULL,
                    daily_transcriptions INTEGER DEFAULT 0,
                    tier_expiration DATE
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS daily_reset (
                    id INTEGER PRIMARY KEY,
                    last_reset DATE
                )
            ''')
            # Initialize daily reset table if empty
            cursor.execute('SELECT COUNT(*) FROM daily_reset')
            if cursor.fetchone()[0] == 0:
                cursor.execute('INSERT INTO daily_reset (last_reset) VALUES (?)', (datetime.now().date(),))
            conn.commit()

    def add_user(self, user_id, tier="free"):
        """Add a new user with the specified tier."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO users (user_id, tier, daily_transcriptions, tier_expiration)
                VALUES (?, ?, 0, NULL)
            ''', (user_id, tier))
            conn.commit()

    def can_transcribe(self, user_id, voice_length):
        """Check if a user is allowed to transcribe a voice note."""
        self._reset_daily_counts_if_needed()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT tier, daily_transcriptions, tier_expiration FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            if not result:
                return False, "User not found."

            tier, daily_transcriptions, tier_expiration = result
            tier_info = USER_TIERS.get(tier, USER_TIERS["free"])

            # Check if subscription has expired
            if tier_expiration and datetime.strptime(tier_expiration, "%Y-%m-%d") < datetime.now():
                tier = "free"
                tier_info = USER_TIERS["free"]
                cursor.execute('UPDATE users SET tier = ?, tier_expiration = NULL WHERE user_id = ?', (tier, user_id))
                conn.commit()

            # Check daily transcription limit and voice length
            if daily_transcriptions >= tier_info["max_transcriptions"]:
                return False, "Daily transcription limit reached."
            if voice_length > tier_info["max_voice_length"]:
                return False, "Voice note exceeds maximum allowed length."

            return True, "Allowed to transcribe."

    def increment_transcription_count(self, user_id):
        """Increment the user's daily transcription count."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET daily_transcriptions = daily_transcriptions + 1 WHERE user_id = ?', (user_id,))
            conn.commit()

    def upgrade_tier(self, user_id, new_tier, duration_days=30):
        """Upgrade a user's tier with an expiration date."""
        expiration_date = (datetime.now() + timedelta(days=duration_days)).date()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users
                SET tier = ?, tier_expiration = ?
                WHERE user_id = ?
            ''', (new_tier, expiration_date, user_id))
            conn.commit()

    def _reset_daily_counts_if_needed(self):
        """Reset daily transcription counts if a new day has started."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT last_reset FROM daily_reset')
            last_reset = datetime.strptime(cursor.fetchone()[0], "%Y-%m-%d").date()
            today = datetime.now().date()

            if today > last_reset:
                cursor.execute('UPDATE users SET daily_transcriptions = 0')
                cursor.execute('UPDATE daily_reset SET last_reset = ?', (today,))
                conn.commit()
