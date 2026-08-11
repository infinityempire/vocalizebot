"""
VocalizeBot - Customer Service Agent
====================================
AI Agent for handling customer service for Tal HaTil Empire automation services.

This agent:
- Represents the empire professionally
- Answers questions about automation services
- Identifies hot leads and sales opportunities
- Routes customers to appropriate sales flow
"""

import os
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
import re

# Load from environment
PAYPAL_LINK = os.environ.get('PAYPAL_UPGRADE_LINK', 'https://paypal.me/talhatil')
PREMIUM_PRICE = os.environ.get('PREMIUM_PRICE_USD', '29.99')
TELEGRAM_ADMIN_ID = os.environ.get('TELEGRAM_ADMIN_ID', '1966827950')  # Admin chat ID for hot lead notifications

# =============================================================================
# SYSTEM PROMPTS
# =============================================================================

SYSTEM_PROMPT = """אתה בוט שירות הלקוחות הרשמי של אימפריית טל הטיל 🇮🇱

משימתך העיקרית: לזהות לידים חמים עם כוונת קנייה רצינית ולשלוח התראה מיידית לאדמין!

זיהוי לידים חמים (HOT_LEAD):
כל הודעה בעברית או אנגלית שמכילה אחד מהביטויים הבאים = ליד חם:
- "רוצה לקנות", "מעוניין לרכוש", "אני רוצה", "כמה זה עולה", "מחיר"
- "יש לכם", "אני צריך", "צריך בוט", "בוט לעסק"
- "want to buy", "interested", "how much", "price", "need bot"
- "כמה עולה", "תשלום", "להזמין", "מתי אפשר", "דחוף"

כוונת קנייה רצינית = ליד חם מיידי!
גם אם הלקוח רק שואל על מחירים = HOT_LEAD!

אימפריית טל הטיל מציעה:
- בוט טלגרם/וואטסאפ: החל מ-299$/חודש
- מערכת CRM: החל מ-499$/חודש
- אוטומציה מותאמת: לפי דרישה
- VIP פרימיום: 999$/חודש

כללי התנהגות:
1. זהה לידים חמים - זו משימה קריטית!
2. הגב במקצועיות ושלח קישור לרכישה
3. שמור על טון עברי/אנגלי טבעי
4. עדכן סטטוס ל-HOT_LEAD במערכת
5. שלח התראה לאדמין (1966827950) על כל ליד חם!"""


# =============================================================================
# HOT LEAD INDICATORS
# =============================================================================

HOT_LEAD_KEYWORDS = {
    'he': [
        # Purchase intent
        'רוצה לקנות', 'מעוניין לרכוש', 'אני רוצה', 'כמה זה עולה', 'מחיר',
        'כמה עולה', 'יש לכם', 'אני צריך', 'צריך בוט', 'רוצה בוט',
        'בוט לעסק', 'אוטומציה', 'אני רוצה לקנות', 'להזמין',
        # Interest
        'מתעניין', 'מעוניין', 'סקרן', 'רוצה לדעת', 'תגיד לי',
        'מה אתם מציעים', 'מה יש לכם', 'מה השירותים', 'מה המחירים',
        # Urgency
        'דחוף', 'מהר', 'עכשיו', 'בהקדם', 'עד סוף החודש', 'מיידי',
        # Business
        'הסטארטאפ שלי', 'העסק שלי', 'החברה שלנו', 'אנחנו צריכים',
    ],
    'en': [
        'want to buy', 'interested in', 'how much', 'price', 'cost',
        'looking for', 'need a bot', 'want bot', 'business automation',
        'interested', 'curious', 'tell me', 'what do you offer',
        'urgent', 'asap', 'quickly', 'immediately',
    ]
}


# =============================================================================
# PRICING MESSAGES
# =============================================================================

PRICING_INFO = {
    'he': """
💰 *מחירון שירותי אימפריית טל הטיל*

📱 *בוט טלגרם/וואטסאפ*
• בסיסי: 299$/חודש
• מתקדם: 499$/חודש
• פרימיום: 999$/חודש

📊 *מערכת CRM*
• החל מ: 499$/חודש

🤖 *אוטומציה מותאמת*
• לפי דרישה - צור קשר להצעת מחיר

💎 *פרימיום VIP*
• הכל כלול + תמיכה 24/7
• עדיפות בתור
• פגישת ייעוץ חודשית

להזמנה: [לחץ כאן]({paypal_link})
""",
    'en': """
💰 *Tal HaTil Empire Pricing*

📱 *Telegram/WhatsApp Bot*
• Basic: $299/month
• Advanced: $499/month
• Premium: $999/month

📊 *CRM System*
• Starting at: $499/month

🤖 *Custom Automation*
• Custom quote available

💎 *Premium VIP*
• Everything included + 24/7 support
• Priority queue
• Monthly consultation

To order: [Click here]({paypal_link})
"""
}


UPGRADE_MESSAGES = {
    'he': """
🎉 *נשמח לעזור לך!*

לאחר שיחה עם נציג, אשלח לך הצעת מחיר מותאמת אישית.

בינתיים, הנה האפשרויות הקיימות:

{pricing}

💡 *לשדרוג מיידי:* [לחץ כאן]({paypal_link})

או שלח /upgrade לראות את האפשרויות!
""",
    'en': """
🎉 *Happy to help!*

After speaking with a representative, I'll send you a personalized quote.

In the meantime, here are the available options:

{pricing}

💡 *For immediate upgrade:* [Click here]({paypal_link})

Or send /upgrade to see options!
"""
}


HOT_LEAD_NOTIFICATION = """
🔥 *ליד חם זוהה!*

👤 *{customer_name}*
📱 {phone}
📊 סטטוס: ליד חם
📈 ציון: {score}
💬 הודעה: "{message}"

⏰ זמן: {time}
"""


# =============================================================================
# CUSTOMER SERVICE AGENT
# =============================================================================

class CustomerServiceAgent:
    """
    AI Agent for customer service that represents Tal HaTil Empire.
    
    Responsibilities:
    - Process incoming messages
    - Identify hot leads
    - Provide pricing information
    - Route to sales flow
    """
    
    def __init__(self):
        self.system_prompt = SYSTEM_PROMPT
        self.paypal_link = PAYPAL_LINK
        self.premium_price = PREMIUM_PRICE
        self.admin_id = TELEGRAM_ADMIN_ID
    
    async def notify_admin(self, message: str, bot_token: str = None) -> bool:
        """
        Send a notification to the admin via Telegram.
        
        Args:
            message: The notification message to send
            bot_token: Optional bot token for sending
            
        Returns:
            True if notification sent successfully
        """
        import httpx
        import os
        
        token = bot_token or os.environ.get('TELEGRAM_BOT_TOKEN', '')
        admin_id = self.admin_id
        
        if not token or not admin_id:
            return False
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={
                        "chat_id": admin_id,
                        "text": message,
                        "parse_mode": "Markdown"
                    }
                )
                return response.json().get('ok', False)
        except Exception:
            return False
    
    def detect_language(self, text: str) -> str:
        """Detect if message is in Hebrew or English."""
        # Simple heuristic: count Hebrew characters
        hebrew_chars = len(re.findall(r'[\u0590-\u05ff]', text))
        english_chars = len(re.findall(r'[a-zA-Z]', text))
        
        return 'he' if hebrew_chars > english_chars else 'en'
    
    def is_hot_lead(self, text: str, user_lang: str = 'he') -> bool:
        """
        Analyze if the message indicates a hot lead (purchase intent).
        
        Returns:
            Tuple of (is_hot_lead: bool, confidence: float, reason: str)
        """
        text_lower = text.lower()
        keywords = HOT_LEAD_KEYWORDS.get(user_lang, HOT_LEAD_KEYWORDS['he'])
        
        matches = 0
        matched_keywords = []
        
        for keyword in keywords:
            if keyword.lower() in text_lower:
                matches += 1
                matched_keywords.append(keyword)
        
        # Calculate confidence based on number of matches
        if matches >= 3:
            confidence = 0.9
        elif matches == 2:
            confidence = 0.7
        elif matches == 1:
            confidence = 0.5
        else:
            confidence = 0.0
        
        is_hot = confidence >= 0.5
        
        return is_hot, confidence, ', '.join(matched_keywords[:3]) if matched_keywords else 'none'
    
    def get_pricing_message(self, user_lang: str = 'he') -> str:
        """Get formatted pricing message."""
        pricing = PRICING_INFO.get(user_lang, PRICING_INFO['he']).format(
            paypal_link=self.paypal_link
        )
        return pricing
    
    def get_upgrade_message(self, user_lang: str = 'he') -> str:
        """Get upgrade/purchase intent message."""
        pricing = self.get_pricing_message(user_lang)
        message = UPGRADE_MESSAGES.get(user_lang, UPGRADE_MESSAGES['he']).format(
            pricing=pricing,
            paypal_link=self.paypal_link
        )
        return message
    
    def format_hot_lead_notification(
        self,
        customer_name: str,
        phone: str,
        message: str,
        score: int,
        time: str = None
    ) -> str:
        """Format notification for admin about hot lead."""
        if time is None:
            time = datetime.now().strftime('%Y-%m-%d %H:%M')
        
        return HOT_LEAD_NOTIFICATION.format(
            customer_name=customer_name or 'לקוח',
            phone=phone or 'לא צוין',
            message=message[:100],
            score=score,
            time=time
        )
    
    def generate_response(
        self,
        user_message: str,
        user_lang: str = 'he',
        include_upgrade: bool = False
    ) -> str:
        """
        Generate a response to the user.
        
        Args:
            user_message: The user's message
            user_lang: Language ('he' or 'en')
            include_upgrade: Whether to include upgrade options
            
        Returns:
            Response message
        """
        if include_upgrade:
            return self.get_upgrade_message(user_lang)
        
        # Default response - this would be enhanced with actual AI processing
        responses = {
            'he': "קיבלתי את הודעתך! אשמח לעזור. כתוב לי מה אתה צריך ואענה בשמחה. 😊",
            'en': "Got your message! Happy to help. Tell me what you need and I'll answer. 😊"
        }
        
        return responses.get(user_lang, responses['he'])
    
    def analyze_and_respond(
        self,
        message: str,
        customer_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Main entry point for message processing.
        
        Args:
            message: The user's message
            customer_info: Optional customer details (name, phone, etc.)
            
        Returns:
            Dict with:
            - response: The bot's response
            - is_hot_lead: Whether this is a hot lead
            - confidence: Detection confidence
            - should_notify_admin: Whether to notify admin
            - admin_notification: The notification message if applicable
        """
        user_lang = self.detect_language(message)
        is_hot, confidence, matched = self.is_hot_lead(message, user_lang)
        
        # Determine response
        if is_hot:
            response = self.get_upgrade_message(user_lang)
            should_notify = True
        else:
            response = self.generate_response(message, user_lang)
            should_notify = False
        
        # Build admin notification if hot lead
        admin_notification = None
        if should_notify:
            customer_name = customer_info.get('name', '') if customer_info else ''
            phone = customer_info.get('phone', '') if customer_info else ''
            admin_notification = self.format_hot_lead_notification(
                customer_name=customer_name,
                phone=phone,
                message=message,
                score=int(50 + confidence * 50)  # Convert to 50-100 scale
            )
        
        return {
            'response': response,
            'is_hot_lead': is_hot,
            'confidence': confidence,
            'matched_keywords': matched,
            'language': user_lang,
            'should_notify_admin': should_notify,
            'admin_notification': admin_notification
        }


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_customer_service_agent: Optional[CustomerServiceAgent] = None


def get_customer_service_agent() -> CustomerServiceAgent:
    """Get the singleton customer service agent instance."""
    global _customer_service_agent
    if _customer_service_agent is None:
        _customer_service_agent = CustomerServiceAgent()
    return _customer_service_agent
