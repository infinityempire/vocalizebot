#!/usr/bin/env python3
"""
VocalizeBot - Automated Renewal Response Script
================================================
Scans for customers needing subscription renewal and generates
automated Hebrew responses with PayPal payment links.

Usage:
    python3 auto_renewal.py                    # Show findings only (dry run)
    python3 auto_renewal.py --send             # Send responses via Telegram
    python3 auto_renewal.py --schedule         # Run as a scheduled cron job

Cron example (daily at 9am):
    0 9 * * * cd /root/vocalize && python3 auto_renewal.py --send >> logs/auto_renewal.log 2>&1
"""
import argparse
import asyncio
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# --- Configuration ---
SUBSCRIPTIONS_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "subscriptions.db")
VOCALIZE_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vocalizebot.db")
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# Hebrew response template
RENEWAL_MESSAGE_TEMPLATE = """
שלום, קיבלנו את פנייתך לגבי חידוש הגישה לבוט השירות.
כדי לחדש את הגישה ולהמשיך בשימוש רציף, ניתן להסדיר את המנוי בקישור הבא:
[https://www.paypal.me/talderie]

ברגע שהעדכון יבוצע, הגישה תחודש באופן אוטומטי.
""".strip()

# Tier pricing
TIER_PRICES = {
    "premium": 29,  # $29/month
    "vip": 99,      # $99/month
}

# --- Helper Functions ---

def log(msg: str, level: str = "INFO"):
    """Simple logging with timestamp."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{level}] {msg}")
    # Also write to log file
    log_file = os.path.join(LOG_DIR, f"auto_renewal_{datetime.now().strftime('%Y%m')}.log")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] [{level}] {msg}\n")


def scan_subscription_db() -> List[Dict]:
    """
    Scan subscriptions.db for users needing renewal.
    Returns users who:
    - Have an expired tier (tier_expiration in the past)
    - Are on free tier (potential upgrade candidates)
    """
    needs_renewal = []
    
    if not os.path.exists(SUBSCRIPTIONS_DB_PATH):
        log(f"Subscriptions DB not found at {SUBSCRIPTIONS_DB_PATH}", "WARNING")
        return needs_renewal
    
    try:
        conn = sqlite3.connect(SUBSCRIPTIONS_DB_PATH)
        cursor = conn.cursor()
        
        # Check table structure
        cursor.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if "user_id" not in columns:
            log("'users' table missing expected columns", "WARNING")
            return needs_renewal
        
        # Get all users
        cursor.execute("SELECT user_id, tier, daily_transcriptions, tier_expiration FROM users")
        users = cursor.fetchall()
        
        today = datetime.now().date()
        
        for user_id, tier, daily_count, expiration_str in users:
            user_info = {
                "user_id": user_id,
                "tier": tier,
                "daily_transcriptions": daily_count,
                "source": "subscriptions_db",
            }
            
            # Check for expired subscription
            if expiration_str:
                try:
                    exp_date = datetime.strptime(expiration_str, "%Y-%m-%d").date()
                    if exp_date < today:
                        user_info["renewal_reason"] = "פג תוקף המנוי"
                        user_info["expired_since"] = (today - exp_date).days
                        user_info["suggested_tier"] = tier  # Renew same tier
                        needs_renewal.append(user_info)
                        continue
                except ValueError:
                    pass
            
            # Free tier users who've used their daily limit are potential upgrade candidates
            if tier == "free":
                user_info["renewal_reason"] = "משתמש חינמי - מועמד לשדרוג"
                user_info["suggested_tier"] = "premium"
                user_info["expired_since"] = 0
                needs_renewal.append(user_info)
        
        conn.close()
        
    except Exception as e:
        log(f"Error scanning subscriptions.db: {e}", "ERROR")
    
    return needs_renewal


async def scan_vocalize_db() -> List[Dict]:
    """
    Scan vocalizebot.db (SQLAlchemy) for customers who may need renewal.
    Checks customers with low lead scores or who haven't interacted recently.
    """
    needs_renewal = []
    
    if not os.path.exists(VOCALIZE_DB_PATH):
        log(f"Vocalize DB not found at {VOCALIZE_DB_PATH} — may not be initialized yet", "INFO")
        return needs_renewal
    
    try:
        from sqlalchemy import select, create_engine
        from sqlalchemy.orm import Session
        
        # Use sync engine for simplicity in CLI script
        engine = create_engine(f"sqlite:///{VOCALIZE_DB_PATH}")
        
        with Session(engine) as session:
            # Import models
            from src.database.models import Customer, Conversation, Message, Interaction, PaymentLink
            
            # Check if tables exist
            from sqlalchemy import inspect
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            
            if "customers" not in tables:
                log("Customers table not found in vocalizebot.db", "INFO")
                return needs_renewal
            
            # Find customers who haven't interacted in 7+ days
            week_ago = datetime.utcnow() - timedelta(days=7)
            stmt = select(Customer).where(
                Customer.is_active == True,
                Customer.last_interaction < week_ago
            ).order_by(Customer.last_interaction)
            
            result = session.execute(stmt)
            customers = result.scalars().all()
            
            for c in customers:
                needs_renewal.append({
                    "user_id": c.id,
                    "name": c.name or c.phone or c.instagram_handle or c.id,
                    "tier": "customer",
                    "daily_transcriptions": 0,
                    "source": "vocalizebot_db",
                    "renewal_reason": "לקוח לא פעיל (7+ ימים ללא אינטראקציה)",
                    "suggested_tier": "premium",
                    "expired_since": (datetime.utcnow() - c.last_interaction).days if c.last_interaction else 0,
                    "last_interaction": c.last_interaction.isoformat() if c.last_interaction else None,
                    "lead_score": c.lead_score,
                    "segment": c.segment.value if c.segment else "unknown",
                })
        
        engine.dispose()
        
    except Exception as e:
        log(f"Error scanning vocalizebot.db: {e}", "ERROR")
    
    return needs_renewal


def format_findings(users: List[Dict]) -> str:
    """Format the findings as a readable report."""
    if not users:
        return "לא נמצאו לקוחות הזקוקים לחידוש מנוי כרגע.\n\n"
    
    lines = []
    lines.append("=" * 60)
    lines.append(f"דוח חידוש מנוי - {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    lines.append("=" * 60)
    lines.append(f"נמצאו {len(users)} לקוחות הזקוקים לטיפול:\n")
    
    for i, u in enumerate(users, 1):
        lines.append(f"{'─' * 50}")
        lines.append(f"#{i}: {u.get('name', u['user_id'])}")
        
        if u.get("name") and u["name"] != u["user_id"]:
            lines.append(f"   מזהה: {u['user_id']}")
        
        lines.append(f"   Tier נוכחי: {u['tier']}")
        lines.append(f"   סיבה: {u['renewal_reason']}")
        
        if u.get("expired_since", 0) > 0:
            lines.append(f"   ימים מאז פגת תוקף: {u['expired_since']}")
        
        lines.append(f"   Tier מוצע: {u.get('suggested_tier', 'premium')}")
        lines.append(f"   מקור: {u.get('source', 'unknown')}")
        
        if u.get("source") == "subscriptions_db":
            lines.append(f"   שימושים יומיים: {u['daily_transcriptions']}")
        
        lines.append("")
    
    lines.append("=" * 60)
    lines.append("תבנית הודעה שתישלח:")
    lines.append("─" * 50)
    lines.append(RENEWAL_MESSAGE_TEMPLATE)
    lines.append("─" * 50)
    lines.append(f"\n* הערה: ההרצה במצב DRY RUN - לא נשלחות הודעות")
    lines.append("* להפעלה עם שליחה אמיתית, הרץ עם הפרמטר --send\n")
    
    return "\n".join(lines)


async def send_renewal_notification(user: Dict) -> bool:
    """
    Send the Hebrew renewal notification via Telegram.
    
    This function would integrate with the Telegram bot to send
    the actual message. Currently in simulation mode.
    
    Returns True if sent successfully.
    """
    user_id = user["user_id"]
    
    # Build personalized message
    suggested_tier = user.get("suggested_tier", "premium")
    price = TIER_PRICES.get(suggested_tier, 29)
    
    message = f"""שלום,
קיבלנו את פנייתך לגבי חידוש הגישה לבוט השירות.
כדי לחדש את הגישה ולהמשיך בשימוש רציף, ניתן להסדיר את המנוי בקישור הבא:
[https://www.paypal.me/talderie/{price}]

ברגע שהעדכון יבוצע, הגישה תחודש באופן אוטומטי."""
    
    log(f"Would send to user {user_id}: {message[:80]}...", "INFO")
    
    # Actual sending logic would go here:
    # from src.channels.telegram import get_telegram_bot
    # bot = get_telegram_bot()
    # await bot.send_message(chat_id=user_id, text=message)
    
    return True


async def generate_payment_links(users: List[Dict]) -> List[Dict]:
    """Generate PayPal payment links for users needing renewal."""
    payment_links = []
    
    for user in users:
        tier = user.get("suggested_tier", "premium")
        amount = TIER_PRICES.get(tier, 29)
        
        paypal_link = f"https://paypal.me/talderie/{amount}"
        user_id = user.get("user_id", "unknown")
        
        payment_links.append({
            "user_id": user_id,
            "tier": tier,
            "amount": amount,
            "currency": "USD",
            "paypal_link": paypal_link,
            "generated_at": datetime.now().isoformat(),
        })
        
        log(f"Payment link generated for {user_id}: {paypal_link} (${amount})", "INFO")
    
    return payment_links


async def process_send_mode(users: List[Dict]):
    """Process and send renewal notifications to all identified users."""
    if not users:
        log("No users to send notifications to.", "INFO")
        return
    
    log(f"Sending renewal notifications to {len(users)} users...", "INFO")
    
    # Generate payment links
    payment_links = await generate_payment_links(users)
    
    # Log payment links
    links_file = os.path.join(LOG_DIR, f"payment_links_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(links_file, "w", encoding="utf-8") as f:
        json.dump(payment_links, f, ensure_ascii=False, indent=2)
    log(f"Payment links saved to {links_file}", "INFO")
    
    # Would send via Telegram here in production
    for user in users:
        await send_renewal_notification(user)
    
    log("✅ Notifications processed. (Simulation mode — actual sending disabled)", "INFO")


async def process_schedule_mode():
    """Run in scheduled mode - find users and generate links ready for sending."""
    log("=" * 50, "INFO")
    log("Starting scheduled renewal check...", "INFO")
    
    users_sub = scan_subscription_db()
    users_vocalize = await scan_vocalize_db()
    
    all_users = users_sub + users_vocalize
    
    log(f"Found {len(all_users)} users needing attention "
        f"({len(users_sub)} from subscriptions.db, {len(users_vocalize)} from vocalizebot.db)", "INFO")
    
    if all_users:
        # Generate payment links and save report
        payment_links = await generate_payment_links(all_users)
        report_file = os.path.join(LOG_DIR, f"renewal_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "total_users": len(all_users),
                "users": all_users,
                "payment_links": payment_links,
                "message_template": RENEWAL_MESSAGE_TEMPLATE,
            }, f, ensure_ascii=False, indent=2)
        
        log(f"Report saved to {report_file}", "INFO")
    
    log("Scheduled check complete.", "INFO")


async def main():
    parser = argparse.ArgumentParser(
        description="VocalizeBot - Automated Renewal Response Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 auto_renewal.py              # Show findings only (dry run)
  python3 auto_renewal.py --send       # Send responses
  python3 auto_renewal.py --schedule   # Cron mode - check and report
        """
    )
    parser.add_argument("--send", action="store_true", help="Send renewal notifications")
    parser.add_argument("--schedule", action="store_true", help="Run in scheduled/cron mode")
    
    args = parser.parse_args()
    
    if args.schedule:
        await process_schedule_mode()
        return
    
    log("=" * 60, "INFO")
    log("VocalizeBot - Automated Renewal Scanner", "INFO")
    log("=" * 60, "INFO")
    log("", "INFO")
    
    # Scan subscription database
    log("📁 Scanning subscriptions.db...", "INFO")
    users_sub = scan_subscription_db()
    
    # Scan vocalize database
    log("📁 Scanning vocalizebot.db...", "INFO")
    users_vocalize = await scan_vocalize_db()
    
    all_users = users_sub + users_vocalize
    
    log("", "INFO")
    log("📊 RESULTS", "INFO")
    log("─" * 40, "INFO")
    log(f"   subscriptions.db:  {len(users_sub)} users found", "INFO")
    log(f"   vocalizebot.db:    {len(users_vocalize)} users found", "INFO")
    log(f"   Total:             {len(all_users)} users", "INFO")
    log("", "INFO")
    
    # Print formatted report
    print()
    print(format_findings(all_users))
    print()
    
    if args.send:
        log("🚀 --send mode activated", "INFO")
        await process_send_mode(all_users)
    else:
        log("ℹ️  DRY RUN mode — use --send to send actual notifications", "INFO")
        log("ℹ️  Use --schedule for cron/scheduled mode", "INFO")


if __name__ == "__main__":
    asyncio.run(main())
