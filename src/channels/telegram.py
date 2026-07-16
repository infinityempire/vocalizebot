"""
Telegram Bot Channel Module.

Handles all Telegram-specific functionality including:
- Voice message reception and transcription routing
- Text message processing
- User session management
- Command handling
"""

import asyncio
from typing import Optional, Callable, Dict, Any
from loguru import logger

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

from src.config import settings
from src.models import MessageType, BotResponse
from src.services.transcription import get_transcription_service, TranscriptionError
from src.services.summarization import generate_summary


# Conversation states
(WAITING_TEXT_REPLY, WAITING_FEEDBACK, WAITING_LANGUAGE,) = range(3)


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
        1. Receives native OGG voice files from Telegram
        2. Downloads the audio data
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
        
        # Trigger chat action
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception as e:
            logger.warning(f"Failed to send chat action: {e}")
            
        user_lang = self._get_user_language(user_id)
        
        # Select status and error messages based on language
        if user_lang == "he":
            status_text = "🎙️ מעבד ומתמלל את הודעת השמע שלך... 🎧"
            error_text = "❌ מצטער, לא הצלחתי לתמלל את הודעת השמע הזו. אנא נסה שוב מאוחר יותר."
            unexpected_error_text = "⚠️ אירעה שגיאה בלתי צפויה. אנא נסה שוב מאוחר יותר."
        else:
            status_text = "🎙️ Processing and transcribing your audio... 🎧"
            error_text = "❌ Sorry, I couldn't transcribe this audio. Please try again later."
            unexpected_error_text = "⚠️ An unexpected error occurred. Please try again later."
            
        # Send "processing" indicator
        processing_msg = await update.message.reply_text(status_text)
        
        try:
            # Step 1: Download the voice file from Telegram
            voice_file = await context.bot.get_file(voice.file_id)
            voice_bytes = await voice_file.download_as_bytearray()
            
            logger.debug(f"Downloaded voice file: {len(voice_bytes)} bytes")
            
            # Step 2: Route to Google AI Studio Transcription Service
            transcription_service = get_transcription_service()
            
            result = await transcription_service.transcribe_audio(
                audio_data=bytes(voice_bytes),
                filename=f"voice_{user_id}.ogg",
                language=user_lang
            )
            
            # Step 3: Log the transcription result
            logger.info(
                f"Transcription completed for user {user_id}: "
                f"'{result.text[:50]}...' (confidence: {result.confidence})"
            )
            
            # Step 4: Generate summary if transcription is too long
            if len(result.text) > 500:
                try:
                    summary = await generate_summary(result.text, language=user_lang)
                    if user_lang == "he":
                        response_text = (
                            "📝 **תקציר מהיר (TL;DR):**\n"
                            + "\n".join([f"• {point}" for point in summary])
                            + "\n\n---\n"
                            + f"💬 **התמלול המלא:**\n{result.text}"
                        )
                    else:
                        response_text = (
                            "📝 **Quick Summary (TL;DR):**\n"
                            + "\n".join([f"• {point}" for point in summary])
                            + "\n\n---\n"
                            + f"💬 **Full Transcription:**\n{result.text}"
                        )
                except Exception as e:
                    logger.warning(f"Failed to generate summary: {e}")
                    if user_lang == "he":
                        response_text = f"📝 **תמלול:**\n\n{result.text}"
                        response_text += f"\n\n_מודל: {result.model_used}_"
                    else:
                        response_text = f"📝 **Transcription:**\n\n{result.text}"
                        response_text += f"\n\n_Model: {result.model_used}_"
            else:
                if user_lang == "he":
                    response_text = f"📝 **תמלול:**\n\n{result.text}"
                    response_text += f"\n\n_מודל: {result.model_used}_"
                else:
                    response_text = f"📝 **Transcription:**\n\n{result.text}"
                    response_text += f"\n\n_Model: {result.model_used}_"

            await processing_msg.edit_text(response_text, parse_mode="Markdown")
            
            # Store context for potential follow-up
            self._update_user_context(user_id, last_transcription=result.text)
            
        except TranscriptionError as e:
            logger.error(f"Transcription failed for user {user_id}: {e}")
            await processing_msg.edit_text(error_text)
            
        except Exception as e:
            logger.exception(f"Unexpected error handling voice message: {e}")
            await processing_msg.edit_text(unexpected_error_text)
    
    # =========================================================================
    # AUDIO MESSAGE HANDLING
    # =========================================================================
    
    async def _handle_audio_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle incoming audio files (as files, not voice notes).
        
        Similar to voice messages but handles audio files sent
        as documents with robust UX and error handling.
        """
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        audio = update.message.audio or update.message.document
        
        logger.info(f"Audio file received from user {user_id}: {audio.file_name}")
        
        # Trigger chat action
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception as e:
            logger.warning(f"Failed to send chat action: {e}")
            
        user_lang = self._get_user_language(user_id)
        
        # Select status and error messages based on language
        if user_lang == "he":
            status_text = "🎵 מעבד ומתמלל את קובץ השמע שלך... 🎧"
            error_text = "❌ מצטער, לא הצלחתי לתמלל את קובץ השמע הזה. אנא נסה שוב מאוחר יותר."
            unexpected_error_text = "⚠️ אירעה שגיאה בלתי צפויה. אנא נסה שוב מאוחר יותר."
        else:
            status_text = "🎵 Processing and transcribing your audio file... 🎧"
            error_text = "❌ Sorry, I couldn't transcribe this audio file. Please try again later."
            unexpected_error_text = "⚠️ An unexpected error occurred. Please try again later."
            
        processing_msg = await update.message.reply_text(status_text)
        
        try:
            # Download audio file
            audio_file = await context.bot.get_file(audio.file_id)
            audio_bytes = await audio_file.download_as_bytearray()
            
            # Get transcription
            transcription_service = get_transcription_service()
            result = await transcription_service.transcribe_audio(
                audio_data=bytes(audio_bytes),
                filename=audio.file_name or "audio.mp3",
                language=user_lang
            )
            
            # Edit the processing message with results
            if user_lang == "he":
                response_text = f"📝 **תמלול:**\n\n{result.text}"
                response_text += f"\n\n_מודל: {result.model_used}_"
            else:
                response_text = f"📝 **Transcription:**\n\n{result.text}"
                response_text += f"\n\n_Model: {result.model_used}_"
                
            await processing_msg.edit_text(response_text, parse_mode="Markdown")
            
        except TranscriptionError as e:
            logger.error(f"Audio transcription failed for user {user_id}: {e}")
            await processing_msg.edit_text(error_text)
            
        except Exception as e:
            logger.exception(f"Unexpected error handling audio message: {e}")
            await processing_msg.edit_text(unexpected_error_text)
    
    # =========================================================================
    # TEXT MESSAGE HANDLING
    # =========================================================================
    
    async def _handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming text messages."""
        user_id = update.effective_user.id
        text = update.message.text
        
        logger.info(f"Text message from user {user_id}: {text[:50]}...")
        
        # Echo with confirmation (placeholder for AI response)
        await update.message.reply_text(
            f"📨 הודעתך התקבלה: {text[:100]}...\n\n"
            "שלח הודעה קולית לתמלול."
        )
        
        self._update_user_context(user_id, last_message=text)
    
    # =========================================================================
    # COMMAND HANDLERS
    # =========================================================================
    
    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        welcome_text = """
🤖 *ברוך הבא לבוט התמלול!*

אני יכול לתמלל הודעות קוליות מ-Telegram בעזרת Google AI Studio.

*איך להשתמש:*
🎤 שלח הודעה קולית - ואתמלל אותה עבורך
🎵 שלח קובץ שמע - גם אותו אתמלל
/lang [he|en] - שנה שפת תמלול

נסה עכשיו! 🚀
        """
        await update.message.reply_text(welcome_text, parse_mode="Markdown")
    
    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command."""
        help_text = """
📚 *פקודות זמינות:*

/start - התחל שיחה חדשה
/help - הצג עזרה זו
/language - שנה שפת תמלול

💡 *טיפים:*
• שלח הודעות קוליות ברורות לתוצאות מיטביות
• נסה לדבר ברצף ללא הפסקות ארוכות
• תמלול עובד בעברית ובאנגלית
        """
        await update.message.reply_text(help_text, parse_mode="Markdown")
    
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
    
    async def _handle_unhandled(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle unhandled message types."""
        await update.message.reply_text(
            "🤔 אני יודע לעבד הודעות קוליות וטקסט. נסה לשלוח הודעה קולית!"
        )
    
    # =========================================================================
    # HELPER METHODS
    # =========================================================================
    
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
