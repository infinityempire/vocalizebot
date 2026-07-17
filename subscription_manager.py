"""
VocalizeBot - Subscription Manager
בוט שירות לקוחות ומכירות חכם - ניהול מנויים וחומת תשלומים
"""
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Tuple

# Load from environment or use defaults
FREE_MAX_LEADS = int(os.environ.get('FREE_MAX_LEADS', 30))  # לידים בחינם ליום
FREE_MAX_RESPONSES = int(os.environ.get('FREE_MAX_RESPONSES', 50))  # תגובות בחינם ליום
FREE_TRIAL_DAYS = int(os.environ.get('FREE_TRIAL_DAYS', 7))  # ימי ניסיון
PREMIUM_PRICE_USD = os.environ.get('PREMIUM_PRICE_USD', '9.99')
PAYPAL_LINK = os.environ.get('PAYPAL_UPGRADE_LINK', 'https://paypal.me/talhatil/premium')

# Define user tiers - מודל עסקי של שירות לקוחות
USER_TIERS = {
    "free": {
        "max_leads_per_day": FREE_MAX_LEADS, 
        "max_responses_per_day": FREE_MAX_RESPONSES, 
        "crm_integration": False,
        "analytics": False,
        "custom_branding": False,
        "trial_days": 0
    },
    "starter": {
        "max_leads_per_day": 100,
        "max_responses_per_day": 200,
        "crm_integration": True,
        "analytics": False,
        "custom_branding": False,
        "trial_days": 0
    },
    "premium": {
        "max_leads_per_day": 500,
        "max_responses_per_day": 1000,
        "crm_integration": True,
        "analytics": True,
        "custom_branding": False,
        "trial_days": 14
    },
    "vip": {
        "max_leads_per_day": float('inf'),
        "max_responses_per_day": float('inf'),
        "crm_integration": True,
        "analytics": True,
        "custom_branding": True,
        "trial_days": 30
    },
}


def get_upgrade_message(user_lang: str = 'he') -> str:
    """Generate a paywall upgrade message for customer service bot."""
    if user_lang == 'he':
        return f"""
🎉 *הגעת למכסה היומית שלך!*

📊 *סיכום:*
• לידים שטופלו: {FREE_MAX_LEADS}/{FREE_MAX_LEADS}
• תגובות ללקוחות: {FREE_MAX_RESPONSES}/{FREE_MAX_RESPONSES}
• סיימת את המכסה החינמית שלך! 🌙

💎 *שדרג לפרימיום וקבל:*
✅ לידים ללא הגבלה - תפספס פחות הזדמנויות
✅ מענה אוטומטי 24/7 ללקוחות
✅ אינטגרציה מלאה עם CRM
✅ אנליטיקס מתקדם ודוחות מכירות
✅ זיהוי לידים חמים אוטומטי
✅ עדיפות בתור התמיכה

💰 *מחיר: ${PREMIUM_PRICE_USD}/חודש*

🔗 [לשדרוג - לחץ כאן]({PAYPAL_LINK})

או שלח /upgrade כדי לראות את האפשרויות!
"""
    else:
        return f"""
🎉 *You've reached your daily limit!*

📊 *Summary:*
• Leads processed: {FREE_MAX_LEADS}/{FREE_MAX_LEADS}
• Customer responses: {FREE_MAX_RESPONSES}/{FREE_MAX_RESPONSES}
• You've finished your free daily quota! 🌙

💎 *Upgrade to Premium:*
✅ Unlimited leads - never miss an opportunity
✅ 24/7 automatic customer responses
✅ Full CRM integration
✅ Advanced analytics & sales reports
✅ Automatic hot lead detection
✅ Priority support queue

💰 *Price: ${PREMIUM_PRICE_USD}/month*

🔗 [Upgrade Now]({PAYPAL_LINK})

Or send /upgrade to see options!
"""


def get_feature_locked_message(feature: str, user_lang: str = 'he') -> str:
    """Generate message when a feature is locked for free tier."""
    feature_messages_he = {
        "crm": "אינטגרציה עם CRM",
        "analytics": "דוחות אנליטיקס",
        "custom_branding": "מיתוג מותאם אישית",
        "hot_lead_detection": "זיהוי לידים חמים מתקדם"
    }
    
    feature_messages_en = {
        "crm": "CRM Integration",
        "analytics": "Analytics Reports",
        "custom_branding": "Custom Branding",
        "hot_lead_detection": "Advanced Hot Lead Detection"
    }
    
    if user_lang == 'he':
        return f"""
🔒 *פיצ'ר זה זמין רק בפרימיום!*

📊 *הפיצ'ר:* {feature_messages_he.get(feature, feature)}

💎 *שדרג לפרימיום וקבל:*
✅ גישה לכל הפיצ'רים המתקדמים
✅ לידים ללא הגבלה
✅ תמיכה 24/7

💰 *מחיר: ${PREMIUM_PRICE_USD}/חודש*

🔗 [לשדרוג עכשיו]({PAYPAL_LINK})
"""
    else:
        return f"""
🔒 *This feature is available only in Premium!*

📊 *Feature:* {feature_messages_en.get(feature, feature)}

💎 *Upgrade to Premium:*
✅ Access to all advanced features
✅ Unlimited leads
✅ 24/7 support

💰 *Price: ${PREMIUM_PRICE_USD}/month*

🔗 [Upgrade Now]({PAYPAL_LINK})
"""


class SubscriptionManager:
    def __init__(self, db_path: str = "subscriptions.db"):
        self.db_path = db_path
        self._initialize_database()

    def _initialize_database(self):
        """Initialize the SQLite database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    tier TEXT NOT NULL DEFAULT 'free',
                    daily_transcriptions INTEGER DEFAULT 0,
                    total_transcriptions INTEGER DEFAULT 0,
                    tier_expiration DATE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS daily_reset (
                    id INTEGER PRIMARY KEY,
                    last_reset DATE
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    tier TEXT,
                    amount REAL,
                    currency TEXT,
                    status TEXT,
                    transaction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            # Initialize daily reset table if empty
            cursor.execute('SELECT COUNT(*) FROM daily_reset')
            if cursor.fetchone()[0] == 0:
                cursor.execute('INSERT INTO daily_reset (last_reset) VALUES (?)', (datetime.now().date(),))
            conn.commit()

    def add_user(self, user_id: str, tier: str = "free") -> None:
        """Add a new user with the specified tier."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO users (user_id, tier, daily_transcriptions, total_transcriptions, tier_expiration)
                VALUES (?, ?, 0, 0, NULL)
            ''', (user_id, tier))
            conn.commit()

    def get_user_tier(self, user_id: str) -> str:
        """Get user's current tier."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT tier FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            return result[0] if result else "free"

    def get_remaining_transcriptions(self, user_id: str) -> int:
        """Get remaining transcriptions for today."""
        self._reset_daily_counts_if_needed()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT tier, daily_transcriptions FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            if not result:
                return FREE_MAX_TRANSCRIPTIONS
            tier, used = result
            tier_info = USER_TIERS.get(tier, USER_TIERS["free"])
            limit = tier_info["max_transcriptions"]
            if limit == float('inf'):
                return -1  # Unlimited
            return max(0, int(limit - used))

    def can_transcribe(self, user_id: str, voice_length: int) -> Tuple[bool, str]:
        """Check if a user is allowed to transcribe a voice note.
        
        Returns:
            Tuple of (allowed, message_or_reason)
        """
        self._reset_daily_counts_if_needed()
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT tier, daily_transcriptions, tier_expiration FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            
            if not result:
                # Auto-create user as free tier
                self.add_user(user_id)
                return self.can_transcribe(user_id, voice_length)

            tier, daily_transcriptions, tier_expiration = result
            tier_info = USER_TIERS.get(tier, USER_TIERS["free"])

            # Check if subscription has expired
            if tier_expiration:
                try:
                    exp_date = datetime.strptime(tier_expiration, "%Y-%m-%d").date()
                    if exp_date < datetime.now().date():
                        tier = "free"
                        tier_info = USER_TIERS["free"]
                        cursor.execute('UPDATE users SET tier = ?, tier_expiration = NULL WHERE user_id = ?', (tier, user_id))
                        conn.commit()
                except (ValueError, TypeError):
                    pass

            # Check daily transcription limit
            if daily_transcriptions >= tier_info["max_transcriptions"]:
                return False, get_upgrade_message('he' if self._is_hebrew_user(user_id) else 'en')
            
            # Check voice length
            if voice_length > tier_info["max_voice_length"]:
                return False, get_voice_too_long_message(tier_info["max_voice_length"], 'he' if self._is_hebrew_user(user_id) else 'en')

            return True, "Allowed to transcribe."

    def _is_hebrew_user(self, user_id: str) -> bool:
        """Check if user prefers Hebrew (default True for new users)."""
        return True  # Default to Hebrew

    def increment_transcription_count(self, user_id: str) -> None:
        """Increment the user's daily and total transcription count."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET daily_transcriptions = daily_transcriptions + 1, total_transcriptions = total_transcriptions + 1 WHERE user_id = ?', (user_id,))
            conn.commit()

    def upgrade_tier(self, user_id: str, new_tier: str, duration_days: int = 30) -> bool:
        """Upgrade a user's tier with an expiration date.
        
        Args:
            user_id: The user's Telegram ID
            new_tier: 'premium' or 'vip'
            duration_days: Subscription duration
            
        Returns:
            True if upgrade successful
        """
        if new_tier not in USER_TIERS:
            return False
            
        expiration_date = (datetime.now() + timedelta(days=duration_days)).strftime("%Y-%m-%d")
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users
                SET tier = ?, tier_expiration = ?
                WHERE user_id = ?
            ''', (new_tier, expiration_date, user_id))
            
            # Log transaction
            cursor.execute('''
                INSERT INTO transactions (user_id, tier, amount, currency, status)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, new_tier, PREMIUM_PRICE_USD, 'USD', 'completed'))
            
            conn.commit()
            
        return True

    def get_user_stats(self, user_id: str) -> dict:
        """Get user's subscription statistics."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT tier, daily_transcriptions, total_transcriptions, tier_expiration, created_at
                FROM users WHERE user_id = ?
            ''', (user_id,))
            result = cursor.fetchone()
            
            if not result:
                return {
                    "tier": "free",
                    "daily_used": 0,
                    "total_used": 0,
                    "remaining_today": FREE_MAX_TRANSCRIPTIONS,
                    "expiration": None
                }
            
            tier, daily, total, expiration, created = result
            tier_info = USER_TIERS.get(tier, USER_TIERS["free"])
            limit = tier_info["max_transcriptions"]
            
            return {
                "tier": tier,
                "daily_used": daily,
                "total_used": total,
                "remaining_today": -1 if limit == float('inf') else max(0, int(limit - daily)),
                "daily_limit": limit,
                "expiration": expiration,
                "created_at": created
            }

    def _reset_daily_counts_if_needed(self) -> None:
        """Reset daily transcription counts if a new day has started."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT last_reset FROM daily_reset')
            result = cursor.fetchone()
            if not result:
                cursor.execute('INSERT INTO daily_reset (last_reset) VALUES (?)', (datetime.now().date(),))
                conn.commit()
                return
                
            last_reset = datetime.strptime(result[0], "%Y-%m-%d").date()
            today = datetime.now().date()

            if today > last_reset:
                cursor.execute('UPDATE users SET daily_transcriptions = 0')
                cursor.execute('UPDATE daily_reset SET last_reset = ?', (today,))
                conn.commit()

    def get_all_users(self) -> list:
        """Get all registered users (for broadcast)."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT user_id FROM users')
            return [row[0] for row in cursor.fetchall()]

    def get_premium_users(self) -> list:
        """Get all premium users."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT user_id FROM users 
                WHERE tier != 'free' 
                AND (tier_expiration IS NULL OR tier_expiration >= date('now'))
            ''')
            return [row[0] for row in cursor.fetchall()]

