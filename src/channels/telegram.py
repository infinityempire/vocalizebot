"""
Telegram Bot Channel Module.

Handles all Telegram-specific functionality including:
- Voice message reception and transcription routing
- Text message processing
- User session management
- Command handling
- Sales funnel and payment flow
"""

import asyncio
import hashlib
from typing import Optional, Callable, Dict, Any
from datetime import datetime
from loguru import logger

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
)

from src.config import settings
from src.models import BotResponse
from src.services.transcription import get_transcription_service, TranscriptionError
from src.services.payment import get_payment_service
from src.services.sales import get_sales_service
from src.database.connection import get_db_context
from src.database.models import Customer, CustomerSegment, LeadStatus, Message, MessageDirection, MessageType as DBMessageType, Interaction


# Conversation states
(WAITING_TEXT_REPLY, WAITING_FEEDBACK, WAITING_LANGUAGE,) = range(3)

# Usage limits
FREE_TRANSCRIPTION_LIMIT = 3


class TelegramBot:
    """
    Telegram bot handler with voice message support.
    
    This class manages the Telegram bot lifecycle and routes
    incoming messages to appropriate handlers.
    """
    
    def __init__(self, token: Optional[str] = None):
        """
        Initialize the Telegram bot.
        
        Args:
            token: Telegram bot token. Uses settings if not provided.
        """
        self.token = token or settings.TELEGRAM_BOT_TOKEN
        if not self.token:
            raise ValueError("Telegram bot token is required")
        
        self.app: Optional[Application] = None
        self.user_contexts: Dict[int, Dict[str, Any]] = {}
        self._running = False
    
    async def start(self) -> None:
        """Start the Telegram bot polling."""
        logger.info("Starting Telegram bot...")
        
        self.app = Application.builder().token(self.token).build()
        
        # Register handlers
        self._register_handlers()
        
        # Start polling
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        
        self._running = True
        logger.info("Telegram bot started successfully")
    
    async def stop(self) -> None:
        """Stop the Telegram bot."""
        if self.app and self._running:
            logger.info("Stopping Telegram bot...")
            await self.app.updater.stop_polling()
            await self.app.stop()
            await self.app.shutdown()
            self._running = False
            logger.info("Telegram bot stopped")
    
    def _register_handlers(self) -> None:
        """Register all message and command handlers."""
        if not self.app:
            return
        
        app = self.app
        
        # Command handlers
        app.add_handler(CommandHandler("start", self._handle_start))
        app.add_handler(CommandHandler("help", self._handle_help))
        app.add_handler(CommandHandler("language", self._handle_language_command))
        app.add_handler(CommandHandler("upgrade", self._handle_upgrade))
        
        # Callback query handler for inline buttons
        app.add_handler(CallbackQueryHandler(self._handle_callback_query))
        
        # Voice message handler - This is the KEY routing logic
        app.add_handler(MessageHandler(
            filters.VOICE,
            self._handle_voice_message
        ))
        
        # Audio message handler (sent as files)
        app.add_handler(MessageHandler(
            filters.AUDIO & ~filters.VOICE,
            self._handle_audio_message
        ))
        
        # Text message handler
        app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self._handle_text_message
        ))
        
        # Default handler for other message types
        app.add_handler(MessageHandler(
            filters.ALL & ~filters.TEXT & ~filters.VOICE & ~filters.AUDIO,
            self._handle_unhandled
        ))
    
    # =========================================================================
    # VOICE MESSAGE HANDLING - The Core Routing Logic
    # =========================================================================
    
    async def _handle_voice_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle incoming voice messages.
        
        This is the main routing function that:
        1. Registers user if not exists
        2. Checks usage limit (paywall)
        3. Routes to Google AI Studio for transcription
        4. Returns the transcribed text to the user
        
        Args:
            update: Telegram update object containing the voice message
            context: Telegram context object
        """
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        voice = update.message.voice
        
        logger.info(
            f"Voice message received from user {user_id}, "
            f"duration: {voice.duration}s, file_id: {voice.file_id}"
        )
        
        # Step 0: Ensure user is registered
        customer = await self._ensure_user_registered(update.effective_user)
        if not customer:
            await update.message.reply_text("❌ שגיאה בזיהוי המשתמש. אנא נסה שוב.")
            return
        
        # Step 1: Check if user is premium (has paid)
        if customer.segment == CustomerSegment.EXISTING_CUSTOMER:
            # Premium user - allow transcription
            await self._process_transcription(update, context, customer)
            return
        
        # Step 2: Check usage limit for free users
        transcription_count = await self._get_user_transcription_count(customer.id)
        remaining = FREE_TRANSCRIPTION_LIMIT - transcription_count
        
        if remaining <= 0:
            # User exceeded limit - trigger sales flow
            await self._handle_locked_user(update, context, customer)
            return
        
        # Send "processing" indicator with remaining uses
        remaining_text = f"📊 נותרו לך {remaining} תמלולים חינם"
        processing_msg = await update.message.reply_text(f"🎙️ מעבד הודעה קולית...\n{remaining_text}")
        
        try:
            # Download the voice file from Telegram
            voice_file = await context.bot.get_file(voice.file_id)
            voice_bytes = await voice_file.download_as_bytearray()
            
            logger.debug(f"Downloaded voice file: {len(voice_bytes)} bytes")
            
            # Get user language preference
            user_lang = self._get_user_language(user_id)
            
            # Route to Google AI Studio Transcription Service
            transcription_service = get_transcription_service()
            
            result = await transcription_service.transcribe_audio(
                audio_data=bytes(voice_bytes),
                filename=f"voice_{user_id}.ogg",
                language=user_lang
            )
            
            # Log the transcription result
            logger.info(
                f"Transcription completed for user {user_id}: "
                f"'{result.text[:50]}...' (confidence: {result.confidence})"
            )
            
            # Save message to database
            await self._save_message(
                customer_id=customer.id,
                content=result.text,
                direction=MessageDirection.OUTBOUND,
                message_type=DBMessageType.VOICE,
                transcription=result.text
            )
            
            # Update remaining count
            new_remaining = remaining - 1
            
            # Build response with paywall prompt if approaching limit
            response_text = f"📝 **תמלול:**\n\n{result.text}"
            response_text += f"\n\n_מודל: {result.model_used}_"
            
            if new_remaining == 0:
                response_text += "\n\n" + self._get_upgrade_prompt()
                keyboard = [[InlineKeyboardButton("💳 שדרג עכשיו לחשבון פרימיום", callback_data="upgrade")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await processing_msg.edit_text(response_text, parse_mode="Markdown", reply_markup=reply_markup)
            else:
                response_text += f"\n\n📊 נותרו לך {new_remaining} תמלולים חינם"
                await processing_msg.edit_text(response_text, parse_mode="Markdown")
            
            # Store context for potential follow-up
            self._update_user_context(user_id, last_transcription=result.text)
            
            # Update last interaction
            await self._update_customer_interaction(customer.id)
            
        except TranscriptionError as e:
            logger.error(f"Transcription failed for user {user_id}: {e}")
            await processing_msg.edit_text(
                "❌ אירעה שגיאה בתמלול ההודעה. אנא נסה שוב."
            )
            
        except Exception as e:
            logger.exception(f"Unexpected error handling voice message: {e}")
            await processing_msg.edit_text(
                "⚠️ אירעה שגיאה בלתי צפויה. אנא נסה שוב מאוחר יותר."
            )

    async def _process_transcription(self, update: Update, context: ContextTypes.DEFAULT_TYPE, customer) -> None:
        """Process transcription for premium users."""
        user_id = update.effective_user.id
        voice = update.message.voice
        
        processing_msg = await update.message.reply_text("🎙️ מעבד הודעה קולית... (פרימיום)")
        
        try:
            # Download the voice file
            voice_file = await context.bot.get_file(voice.file_id)
            voice_bytes = await voice_file.download_as_bytearray()
            
            # Get transcription
            transcription_service = get_transcription_service()
            result = await transcription_service.transcribe_audio(
                audio_data=bytes(voice_bytes),
                filename=f"voice_{user_id}.ogg",
                language=self._get_user_language(user_id)
            )
            
            # Save message to database
            await self._save_message(
                customer_id=customer.id,
                content=result.text,
                direction=MessageDirection.OUTBOUND,
                message_type=DBMessageType.VOICE,
                transcription=result.text
            )
            
            # Send response
            response_text = f"📝 **תמלול:**\n\n{result.text}"
            response_text += f"\n\n_מודל: {result.model_used}_\n\n✅ פרימיום"
            
            await processing_msg.edit_text(response_text, parse_mode="Markdown")
            
            # Update last interaction
            await self._update_customer_interaction(customer.id)
            
        except Exception as e:
            logger.error(f"Transcription failed for premium user: {e}")
            await processing_msg.edit_text(
                "❌ אירעה שגיאה. אנא נסה שוב."
            )

    async def _handle_locked_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE, customer) -> None:
        """Handle user who has exceeded free transcription limit."""
        user_id = update.effective_user.id
        
        locked_text = f"""
🔒 **הגעת למכסת התמלולים החינמיים!**

ניסית את {FREE_TRANSCRIPTION_LIMIT} התמלולים החינמיים שלנו - עכשיו הגיע הזמן לחווייה מלאה!

💎 **מה תקבל בפרימיום:**
• תמלולים ללא הגבלה
• גישה מהירה וללא המתנה
• עדיפות בתמיכה

💰 **מחיר מיוחד לגולשי Telegram:** {self._get_premium_price()}

לחץ על הכפתור למטה כדי לרכוש:
        """
        
        keyboard = [[InlineKeyboardButton("💳 שדרג עכשיו לחשבון פרימיום", callback_data="upgrade")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(locked_text, parse_mode="Markdown", reply_markup=reply_markup)
        
        # Log the paywall trigger
        await self._log_interaction(
            customer_id=customer.id,
            interaction_type="paywall_triggered",
            description=f"User exceeded free limit ({FREE_TRANSCRIPTION_LIMIT} transcriptions)"
        )
    
    # =========================================================================
    # AUDIO MESSAGE HANDLING
    # =========================================================================
    
    async def _handle_audio_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle incoming audio files (as files, not voice notes).
        
        Similar to voice messages but handles audio files sent
        as documents. Also applies paywall logic.
        """
        user_id = update.effective_user.id
        audio = update.message.audio or update.message.document
        
        logger.info(f"Audio file received from user {user_id}: {audio.file_name}")
        
        # Ensure user is registered
        customer = await self._ensure_user_registered(update.effective_user)
        if not customer:
            await update.message.reply_text("❌ שגיאה בזיהוי המשתמש. אנא נסה שוב.")
            return
        
        # Check premium status
        if customer.segment != CustomerSegment.EXISTING_CUSTOMER:
            transcription_count = await self._get_user_transcription_count(customer.id)
            if transcription_count >= FREE_TRANSCRIPTION_LIMIT:
                await self._handle_locked_user(update, context, customer)
                return
        
        processing_msg = await update.message.reply_text("🎵 מעבד קובץ שמע...")
        
        try:
            # Download audio file
            audio_file = await context.bot.get_file(audio.file_id)
            audio_bytes = await audio_file.download_as_bytearray()
            
            # Get transcription
            transcription_service = get_transcription_service()
            result = await transcription_service.transcribe_audio(
                audio_data=bytes(audio_bytes),
                filename=audio.file_name or "audio.mp3",
                language=self._get_user_language(user_id)
            )
            
            # Save message to database
            await self._save_message(
                customer_id=customer.id,
                content=result.text,
                direction=MessageDirection.OUTBOUND,
                message_type=DBMessageType.AUDIO,
                transcription=result.text
            )
            
            # Log the transcription
            logger.info(f"Audio transcription completed for user {user_id}: '{result.text[:50]}...'")
            
            # Update last interaction
            await self._update_customer_interaction(customer.id)
            
            await processing_msg.edit_text(
                f"📝 **תמלול:**\n\n{result.text}",
                parse_mode="Markdown"
            )
            
        except Exception as e:
            logger.error(f"Audio transcription failed: {e}")
            await processing_msg.edit_text(
                "❌ אירעה שגיאה בתמלול קובץ השמע."
            )
    
    # =========================================================================
    # TEXT MESSAGE HANDLING
    # =========================================================================
    
    async def _handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming text messages - supports sales flow for locked users."""
        user_id = update.effective_user.id
        text = update.message.text
        chat_id = update.effective_chat.id
        
        logger.info(f"Text message from user {user_id}: {text[:50]}...")
        
        # Ensure user is registered
        customer = await self._ensure_user_registered(update.effective_user)
        if not customer:
            await update.message.reply_text("❌ שגיאה בזיהוי המשתמש. אנא נסה שוב.")
            return
        
        # Check if user is locked (exceeded free limit)
        is_locked = customer.segment != CustomerSegment.EXISTING_CUSTOMER
        if is_locked:
            transcription_count = await self._get_user_transcription_count(customer.id)
            is_locked = transcription_count >= FREE_TRANSCRIPTION_LIMIT
        
        if is_locked:
            # Route through AI sales layer to handle objections
            await self._handle_locked_user_text(update, context, customer, text)
        else:
            # Free user with remaining transcriptions
            await update.message.reply_text(
                f"📨 הודעתך התקבלה: {text[:100]}...\n\n"
                "שלח הודעה קולית לתמלול."
            )
        
        self._update_user_context(user_id, last_message=text)

    async def _handle_locked_user_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE, customer, text: str) -> None:
        """Handle text messages from locked users using AI sales layer."""
        user_id = update.effective_user.id
        
        # Keywords that should trigger payment flow
        payment_keywords = ["upgrade", "רוצה", "want", "buy", "קניתי", "paid", "שילמתי", "כרטיס", "credit"]
        skip_objection_keywords = ["כבר", "already", "already paid"]
        
        # Check if user is saying they already paid
        if any(kw in text.lower() for kw in skip_objection_keywords):
            await update.message.reply_text(
                "✅ מעולה! אם שילמת, שלח את אישור התשלום או צלם את קבלה ונפעיל לך את החשבון פרימיום.\n\n"
                "📧 או שלח הודעה לתמיכה: @support"
            )
            return
        
        # Check if user wants to upgrade
        if any(kw in text.lower() for kw in payment_keywords) or "upgrade" in text.lower():
            await self._send_upgrade_link(update, customer)
            return
        
        # Handle objections using SalesService AI
        sales_service = get_sales_service()
        try:
            objection_result = await sales_service.handle_objection(
                customer_id=customer.id,
                objection=text
            )
            
            if objection_result.get("success"):
                response_text = objection_result.get("response", "")
                
                # Add upgrade button
                keyboard = [[InlineKeyboardButton("💳 שדרג עכשיו לחשבון פרימיום", callback_data="upgrade")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    response_text,
                    reply_markup=reply_markup
                )
                
                # Log the objection
                await self._log_interaction(
                    customer_id=customer.id,
                    interaction_type="objection",
                    description=f"User objection: {text[:100]}"
                )
            else:
                # Fallback response
                await self._send_upgrade_link(update, customer)
                
        except Exception as e:
            logger.error(f"Error handling objection: {e}")
            # Fallback - just send upgrade link
            await self._send_upgrade_link(update, customer)

    async def _send_upgrade_link(self, update: Update, customer) -> None:
        """Send payment upgrade link to user."""
        payment_service = get_payment_service()
        sales_service = get_sales_service()
        
        try:
            # Create payment link
            premium_price = self._get_premium_price()
            payment_result = await sales_service.create_sales_payment(
                customer_id=customer.id,
                amount=premium_price.get("amount", 29.90),
                currency=premium_price.get("currency", "USD"),
                description="Premium Subscription - Unlimited Transcriptions"
            )
            
            if payment_result.get("success"):
                payment_url = payment_result.get("payment_url")
                
                upgrade_text = f"""
💳 **VocalizeBot - הגיע הזמן לפרימיום!**

לחץ על הקישור לתשלום מאובטח:
{payment_url}

💰 **סכום:** {premium_price.get("amount", 29.90)} {premium_price.get("currency", "USD")}

✅ לאחר התשלום תקבל גישה מיידית!
                """
                
                keyboard = [[InlineKeyboardButton("💳 לתשלום", url=payment_url)]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(upgrade_text, parse_mode="Markdown", reply_markup=reply_markup)
            else:
                # Fallback to simple PayPal link
                await self._send_fallback_payment_link(update, customer)
                
        except Exception as e:
            logger.error(f"Error creating payment link: {e}")
            await self._send_fallback_payment_link(update, customer)

    async def _send_fallback_payment_link(self, update: Update, customer) -> None:
        """Send fallback PayPal.me link."""
        premium_price = self._get_premium_price()
        amount = int(premium_price.get("amount", 29.90))
        
        upgrade_text = f"""
💳 **VocalizeBot - הגיע הזמן לפרימיום!**

📌 **לתשלום:**
1. לחץ על הקישור: https://paypal.me/talhatil/{amount}
2. בצע את התשלום
3. שלח לנו צילום מסך של האישור!

💰 **סכום:** {amount} {premium_price.get("currency", "USD")}
        """
        
        keyboard = [[InlineKeyboardButton("💳 לתשלום בפייפאל", url=f"https://paypal.me/talhatil/{amount}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(upgrade_text, parse_mode="Markdown", reply_markup=reply_markup)
    
    # =========================================================================
    # COMMAND HANDLERS
    # =========================================================================
    
    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command - registers user and shows welcome."""
        user = update.effective_user
        
        # Ensure user is registered
        customer = await self._ensure_user_registered(user)
        
        # Check user status
        if customer:
            transcription_count = await self._get_user_transcription_count(customer.id)
            remaining = max(0, FREE_TRANSCRIPTION_LIMIT - transcription_count)
            is_premium = customer.segment == CustomerSegment.EXISTING_CUSTOMER
            
            if is_premium:
                status_text = "✅ **חשבון פרימיום פעיל** - תמלולים ללא הגבלה!"
            else:
                status_text = f"📊 **{remaining} תמלולים חינם נותרו**"
        else:
            status_text = "❌ שגיאה בזיהוי"
        
        welcome_text = f"""
🤖 *ברוך הבא ל-VocalizeBot!*

*VocalizeBot — תמלול קולי חכם*

אני יכול לתמלל הודעות קוליות מ-Telegram בעזרת Google AI Studio.

{status_text}

*איך להשתמש:*
🎤 שלח הודעה קולית - ואתמלל אותה עבורך
🎵 שלח קובץ שמע - גם אותו אתמלל
/upgrade - שדרג לפרימיום
/language - שנה שפת תמלול

נסה עכשיו! 🚀
        """
        await update.message.reply_text(welcome_text, parse_mode="Markdown")
    
    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command."""
        help_text = """
📚 *פקודות זמינות:*

/start - התחל שיחה חדשה
/help - הצג עזרה זו
/upgrade - שדרג לפרימיום
/language - שנה שפת תמלול

💡 *טיפים:*
• שלח הודעות קוליות ברורות לתוצאות מיטביות
• נסה לדבר ברצף ללא הפסקות ארוכות
• תמלול עובד בעברית ובאנגלית
        """
        await update.message.reply_text(help_text, parse_mode="Markdown")
    
    async def _handle_upgrade(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /upgrade command - sends payment link."""
        user = update.effective_user
        
        # Ensure user is registered
        customer = await self._ensure_user_registered(user)
        if not customer:
            await update.message.reply_text("❌ שגיאה בזיהוי המשתמש. אנא נסה שוב.")
            return
        
        # Check if already premium
        if customer.segment == CustomerSegment.EXISTING_CUSTOMER:
            await update.message.reply_text(
                "✅ **אתה כבר משתמש פרימיום!**\n\nתמלולים ללא הגבלה 🚀"
            )
            return
        
        # Send upgrade link
        await self._send_upgrade_link(update, customer)
    
    async def _handle_language_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle /language command - start language selection."""
        keyboard = [
            [
                InlineKeyboardButton("🇮🇱 עברית", callback_data="lang_he"),
                InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🌐 בחר שפת תמלול:",
            reply_markup=reply_markup
        )
        return WAITING_LANGUAGE
    
    async def _handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle callback queries from inline buttons."""
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        data = query.data
        
        if data == "upgrade":
            # Handle upgrade button press
            customer = await self._ensure_user_registered(user)
            if customer and customer.segment != CustomerSegment.EXISTING_CUSTOMER:
                await self._send_upgrade_link(update, query.message, customer)
            else:
                await query.edit_message_text(
                    "✅ **אתה כבר משתמש פרימיום!**\n\nתמלולים ללא הגבלה 🚀"
                )
        elif data.startswith("lang_"):
            lang = data.replace("lang_", "")
            self._update_user_context(user.id, language=lang)
            lang_name = "עברית" if lang == "he" else "English"
            await query.edit_message_text(f"🌐 שפת התמלול הוגדרה ל: **{lang_name}**")
    
    async def _handle_unhandled(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle unhandled message types."""
        await update.message.reply_text(
            "🤔 אני יודע לעבד הודעות קוליות וטקסט. נסה לשלוח הודעה קולית!"
        )
    
    # =========================================================================
    # HELPER METHODS - DATABASE OPERATIONS
    # =========================================================================
    
    async def _ensure_user_registered(self, user) -> Optional[Customer]:
        """
        Ensure user is registered in the database.
        Creates a new customer record if not exists.
        
        Args:
            user: Telegram user object
            
        Returns:
            Customer object or None on error
        """
        try:
            async with get_db_context() as session:
                from sqlalchemy import select
                
                # Look for existing customer by telegram_id
                stmt = select(Customer).where(Customer.telegram_id == str(user.id))
                result = await session.execute(stmt)
                customer = result.scalar_one_or_none()
                
                if customer:
                    # Update last interaction
                    customer.last_interaction = datetime.utcnow()
                    await session.commit()
                    return customer
                
                # Create new customer
                new_customer = Customer(
                    id=f"tg_{hashlib.md5(str(user.id).encode()).hexdigest()[:12]}",
                    telegram_id=str(user.id),
                    telegram_username=user.username or None,
                    name=f"{user.first_name} {user.last_name or ''}".strip() or None,
                    segment=CustomerSegment.B2C,
                    lead_status=LeadStatus.NEW,
                    lead_score=50,
                    created_at=datetime.utcnow(),
                    last_interaction=datetime.utcnow(),
                    is_active=True
                )
                
                session.add(new_customer)
                await session.commit()
                
                logger.info(f"New user registered: {user.id} (@{user.username})")
                
                # Refresh to get the committed object
                await session.refresh(new_customer)
                return new_customer
                
        except Exception as e:
            logger.error(f"Error registering user: {e}")
            return None

    async def _get_user_transcription_count(self, customer_id: str) -> int:
        """
        Get the number of voice transcriptions a user has performed.
        
        Args:
            customer_id: Customer ID
            
        Returns:
            Count of voice/audio transcriptions
        """
        try:
            async with get_db_context() as session:
                from sqlalchemy import select, func
                from src.database.models import Conversation
                
                # First get all conversation IDs for this customer
                conv_stmt = select(Conversation.id).where(Conversation.customer_id == customer_id)
                conv_result = await session.execute(conv_stmt)
                conversation_ids = [row[0] for row in conv_result.fetchall()]
                
                if not conversation_ids:
                    return 0
                
                # Count voice/audio messages
                msg_stmt = select(func.count()).select_from(Message).where(
                    Message.conversation_id.in_(conversation_ids),
                    Message.message_type.in_([DBMessageType.VOICE, DBMessageType.AUDIO])
                )
                msg_result = await session.execute(msg_stmt)
                count = msg_result.scalar()
                
                return count or 0
                
        except Exception as e:
            logger.error(f"Error getting transcription count: {e}")
            return 0

    async def _save_message(
        self,
        customer_id: str,
        content: str,
        direction: MessageDirection,
        message_type: DBMessageType,
        transcription: Optional[str] = None
    ) -> None:
        """
        Save a message to the database.
        
        Args:
            customer_id: Customer ID
            content: Message content
            direction: INBOUND or OUTBOUND
            message_type: Message type (VOICE, TEXT, etc.)
            transcription: Transcription text if applicable
        """
        try:
            async with get_db_context() as session:
                from sqlalchemy import select
                from src.database.models import Conversation
                
                # Get or create active conversation
                stmt = select(Conversation).where(
                    Conversation.customer_id == customer_id,
                    Conversation.is_active == True
                )
                result = await session.execute(stmt)
                conversation = result.scalar_one_or_none()
                
                if not conversation:
                    conversation = Conversation(
                        id=f"conv_{hashlib.md5(str(datetime.utcnow().timestamp()).encode()).hexdigest()[:12]}",
                        customer_id=customer_id,
                        channel="telegram",
                        is_active=True
                    )
                    session.add(conversation)
                    await session.flush()
                
                # Save message
                message = Message(
                    id=f"msg_{hashlib.md5(str(datetime.utcnow().timestamp()).encode()).hexdigest()[:12]}",
                    conversation_id=conversation.id,
                    direction=direction,
                    message_type=message_type,
                    content=content,
                    transcription=transcription,
                    created_at=datetime.utcnow(),
                    processed_at=datetime.utcnow()
                )
                session.add(message)
                await session.commit()
                
        except Exception as e:
            logger.error(f"Error saving message: {e}")

    async def _update_customer_interaction(self, customer_id: str) -> None:
        """Update customer's last interaction timestamp."""
        try:
            async with get_db_context() as session:
                from sqlalchemy import select
                stmt = select(Customer).where(Customer.id == customer_id)
                result = await session.execute(stmt)
                customer = result.scalar_one_or_none()
                
                if customer:
                    customer.last_interaction = datetime.utcnow()
                    await session.commit()
                    
        except Exception as e:
            logger.error(f"Error updating customer interaction: {e}")

    async def _log_interaction(
        self,
        customer_id: str,
        interaction_type: str,
        description: str
    ) -> None:
        """Log a customer interaction."""
        try:
            async with get_db_context() as session:
                interaction = Interaction(
                    id=f"int_{datetime.utcnow().timestamp()}_{hashlib.md5(str(customer_id).encode()).hexdigest()[:6]}",
                    customer_id=customer_id,
                    interaction_type=interaction_type,
                    description=description,
                    created_at=datetime.utcnow()
                )
                session.add(interaction)
                await session.commit()
                
        except Exception as e:
            logger.error(f"Error logging interaction: {e}")

    def _get_upgrade_prompt(self) -> str:
        """Get the upgrade prompt text."""
        return """
🔔 **נותרו לך 0 תמלולים חינם!**

**VocalizeBot - הגיע הזמן לשדרג לפרימיום:**
• תמלולים ללא הגבלה
• גישה מהירה
• עדיפות בתמיכה
        """

    def _get_premium_price(self) -> Dict[str, Any]:
        """Get premium subscription price - can be configured via settings."""
        # Default prices - can be overridden via environment variables
        return {
            "amount": 29.90,  # USD
            "currency": "USD",
            "description": "VocalizeBot Premium - Unlimited Transcriptions"
        }

    def _get_user_language(self, user_id: int) -> str:
        """Get user's preferred language."""
        context = self.user_contexts.get(user_id, {})
        return context.get("language", "he")
    
    def _update_user_context(
        self,
        user_id: int,
        **kwargs
    ) -> None:
        """Update user context data."""
        if user_id not in self.user_contexts:
            self.user_contexts[user_id] = {}
        self.user_contexts[user_id].update(kwargs)


# Singleton instance
_telegram_bot: Optional[TelegramBot] = None


def get_telegram_bot() -> TelegramBot:
    """Get or create the global Telegram bot instance."""
    global _telegram_bot
    if _telegram_bot is None:
        _telegram_bot = TelegramBot()
    return _telegram_bot


async def start_telegram_bot() -> TelegramBot:
    """Start the Telegram bot and return the instance."""
    bot = get_telegram_bot()
    await bot.start()
    return bot


async def stop_telegram_bot() -> None:
    """Stop the Telegram bot."""
    global _telegram_bot
    if _telegram_bot:
        await _telegram_bot.stop()
        _telegram_bot = None