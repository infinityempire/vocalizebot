"""
VocalizeBot - Broadcast System
מערכת הפצת הודעות למשתמשים רשומים
"""
import asyncio
import sqlite3
from typing import List, Dict, Any
from datetime import datetime
from loguru import logger
import httpx

from src.config import settings


class BroadcastManager:
    """מנהל הפצות - שולח הודעות לכל המשתמשים הרשומים"""
    
    def __init__(self, db_path: str = "subscriptions.db"):
        self.db_path = db_path
    
    def get_all_users(self) -> List[str]:
        """קבל רשימת כל המשתמשים"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT user_id FROM users')
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"שגיאה בקבלת משתמשים: {e}")
            return []
    
    def get_premium_users(self) -> List[str]:
        """קבל רשימת משתמשי פרימיום"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT user_id FROM users 
                    WHERE tier != 'free' 
                    AND (tier_expiration IS NULL OR tier_expiration >= date('now'))
                ''')
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"שגיאה בקבלת משתמשי פרימיום: {e}")
            return []
    
    def get_free_users(self) -> List[str]:
        """קבל רשימת משתמשים חינמיים"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT user_id FROM users WHERE tier = "free"')
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"שגיאה בקבלת משתמשים חינמיים: {e}")
            return []
    
    async def send_telegram_message(self, chat_id: str, message: str) -> Dict[str, Any]:
        """שלח הודעה לטלגרם"""
        if not settings.TELEGRAM_BOT_TOKEN:
            return {"success": False, "error": "TELEGRAM_BOT_TOKEN not configured"}
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": message,
                        "parse_mode": "Markdown"
                    },
                    timeout=30.0
                )
                
                result = response.json()
                if result.get("ok"):
                    return {"success": True, "chat_id": chat_id}
                else:
                    return {"success": False, "chat_id": chat_id, "error": result.get("description")}
        except Exception as e:
            logger.error(f"שגיאה בשליחת הודעה ל-{chat_id}: {e}")
            return {"success": False, "chat_id": chat_id, "error": str(e)}
    
    async def broadcast(
        self, 
        message: str, 
        user_filter: str = "all",
        delay_seconds: float = 0.5
    ) -> Dict[str, Any]:
        """
        שלח הודעה לכל המשתמשים
        
        Args:
            message: תוכן ההודעה
            user_filter: "all", "premium", "free"
            delay_seconds: עיכוב בין הודעות למניעת rate limit
        
        Returns:
            סיכום תוצאות
        """
        if user_filter == "premium":
            users = self.get_premium_users()
        elif user_filter == "free":
            users = self.get_free_users()
        else:
            users = self.get_all_users()
        
        logger.info(f"מתחיל הפצה ל-{len(users)} משתמשים...")
        
        results = {"total": len(users), "success": 0, "failed": 0, "errors": []}
        
        for i, user_id in enumerate(users):
            result = await self.send_telegram_message(user_id, message)
            
            if result["success"]:
                results["success"] += 1
            else:
                results["failed"] += 1
                results["errors"].append({
                    "chat_id": user_id,
                    "error": result.get("error", "Unknown")
                })
            
            # עיכוב למניעת rate limit
            if i < len(users) - 1:
                await asyncio.sleep(delay_seconds)
            
            # לוג התקדמות כל 10 משתמשים
            if (i + 1) % 10 == 0:
                logger.info(f"התקדמות: {i + 1}/{len(users)}")
        
        logger.info(f"הפצה הסתיימה: {results['success']} הצלחות, {results['failed']} כישלונות")
        
        return results


# Singleton instance
_broadcast_manager: BroadcastManager = None


def get_broadcast_manager() -> BroadcastManager:
    """קבל מופע יחיד של BroadcastManager"""
    global _broadcast_manager
    if _broadcast_manager is None:
        _broadcast_manager = BroadcastManager()
    return _broadcast_manager


# =============================================================================
# MAIN - הפעלה ישירה של הפצה
# =============================================================================
if __name__ == "__main__":
    import sys
    import os
    
    # טען משתני סביבה
    from dotenv import load_dotenv
    load_dotenv()
    
    async def main():
        if len(sys.argv) < 2:
            print("""
🎙️ VocalizeBot - מערכת הפצה

שימוש:
    python broadcast.py <message> [--filter=all|premium|free] [--delay=0.5]

דוגמאות:
    python broadcast.py "🎉 הודעה לכולם!"
    python broadcast.py "💎 הצעה מיוחדת לפרימיום!" --filter=premium
    python broadcast.py "👋 הודעה למשתמשים חינמיים" --filter=free
""")
            return
        
        message = sys.argv[1]
        user_filter = "all"
        delay = 0.5
        
        # פרוס ארגומנטים
        for arg in sys.argv[2:]:
            if arg.startswith("--filter="):
                user_filter = arg.replace("--filter=", "")
            elif arg.startswith("--delay="):
                delay = float(arg.replace("--delay=", ""))
        
        manager = get_broadcast_manager()
        print(f"\n📤 מתחיל הפצה...")
        print(f"   הודעה: {message[:50]}...")
        print(f"   מסנן: {user_filter}")
        print(f"   עיכוב: {delay}s\n")
        
        results = await manager.broadcast(message, user_filter, delay)
        
        print(f"""
✅ הפצה הסתיימה!
   
📊 סיכום:
   סה"כ: {results['total']}
   הצלחות: {results['success']}
   כישלונות: {results['failed']}
""")
        
        if results['errors']:
            print("⚠️ שגיאות:")
            for err in results['errors'][:5]:
                print(f"   - {err['chat_id']}: {err['error']}")
    
    asyncio.run(main())
