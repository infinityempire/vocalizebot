"""
Telegram Voice Bot - FastAPI Application

Main entry point for the application with health checks,
webhook support, and graceful shutdown handling.
"""

import asyncio
import httpx
from contextlib import asynccontextmanager
from typing import Optional
from loguru import logger
from fastapi import FastAPI, HTTPException, status, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from src.config import settings
from src.channels.telegram import start_telegram_bot, stop_telegram_bot
from src.services.transcription import get_transcription_service
from subscription_manager import SubscriptionManager # NEW: Import SubscriptionManager


# ============================================================================
# TELEGRAM WEBHOOK SETUP
# ============================================================================

# Global Telegram application instance for webhook handling
telegram_app: Optional[Application] = None
# NEW: Global SubscriptionManager instance
subscription_manager_instance: Optional[SubscriptionManager] = None


async def setup_telegram_webhook(webhook_url: str) -> bool:
    """
    Set up Telegram webhook by calling setWebhook API.
    
    This function is called automatically on server startup to register
    the webhook URL with Telegram, so all bot messages are forwarded
    directly to our FastAPI endpoint.
    
    Args:
        webhook_url: The full URL where Telegram should send updates
                     (e.g., https://yourdomain.com/webhook)
    
    Returns:
        True if webhook was set successfully, False otherwise
    """
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.error("Cannot setup webhook: TELEGRAM_BOT_TOKEN not configured")
        return False
    
    api_url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/setWebhook"
    
    payload = {
        "url": webhook_url,
        "allowed_updates": ["message", "edited_message", "callback_query"],
        "drop_pending_updates": True
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(api_url, json=payload)
            result = response.json()
            
            if result.get("ok"):
                logger.info(f"✅ Telegram webhook set successfully: {webhook_url}")
                logger.info(f"   Response: {result}")
                return True
            else:
                logger.error(f"❌ Failed to set webhook: {result}")
                return False
                
    except Exception as e:
        logger.error(f"❌ Error setting Telegram webhook: {e}")
        return False


async def delete_telegram_webhook() -> bool:
    """
    Delete the Telegram webhook (useful for switching to polling mode).
    
    Returns:
        True if webhook was deleted successfully
    """
    if not settings.TELEGRAM_BOT_TOKEN:
        return False
    
    api_url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/deleteWebhook"
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(api_url)
            result = response.json()
            return result.get("ok", False)
    except Exception as e:
        logger.error(f"Error deleting webhook: {e}")
        return False


def get_webhook_update_handler(app: Application):
    """Create a webhook update handler for FastAPI."""
    async def handle_webhook(request: Request) -> str:
        """Handle incoming Telegram webhook updates."""
        try:
            data = await request.json()
            update = Update.de_json(data, app.bot)
            await app.process_update(update)
            return "OK"
        except Exception as e:
            logger.error(f"Error processing webhook update: {e}")
            return "ERROR"
    
    return handle_webhook


# ============================================================================
# LIFESPAN MANAGEMENT
# ============================================================================

telegram_task: Optional[asyncio.Task] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    
    Handles startup and shutdown:
    1. Initializes the SubscriptionManager
    2. Sets up Telegram webhook automatically or starts polling
    3. Initializes the Telegram bot application
    4. Cleans up on shutdown
    """
    global telegram_task, telegram_app, subscription_manager_instance # MODIFIED: Added subscription_manager_instance
    
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    
    # Startup
    
    # NEW: Initialize SubscriptionManager
    # The database path should ideally come from settings (e.g., settings.SUBSCRIPTION_DB_PATH).
    # For now, using a default 'subscriptions.db'.
    db_path = getattr(settings, 'SUBSCRIPTION_DB_PATH', 'subscriptions.db')
    subscription_manager_instance = SubscriptionManager(db_path=db_path)
    logger.info(f"SubscriptionManager initialized with DB: {db_path}")

    if settings.TELEGRAM_BOT_TOKEN:
        try:
            # Build webhook URL from request (will be updated on first request)
            # For production, set TELEGRAM_WEBHOOK_URL environment variable
            webhook_url = getattr(settings, 'TELEGRAM_WEBHOOK_URL', None)
            
            if webhook_url:
                # Set up webhook automatically on startup
                await setup_telegram_webhook(webhook_url)
                
                # Initialize Telegram application for webhook handling
                telegram_app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
                
                # Register message handlers
                from src.channels.telegram import TelegramBot
                # MODIFIED: Pass the subscription_manager_instance to TelegramBot
                tb = TelegramBot(subscription_manager=subscription_manager_instance)
                tb.app = telegram_app
                tb._register_handlers()
                
                logger.info("Telegram webhook mode enabled")
            else:
                logger.warning("TELEGRAM_WEBHOOK_URL not set - falling back to polling mode")
                # In polling mode, start_telegram_bot() is responsible for creating and running the bot.
                # It would need to be updated in src/channels/telegram.py to also pass the
                # subscription_manager_instance to the TelegramBot constructor if it instantiates it.
                telegram_task = asyncio.create_task(start_telegram_bot(subscription_manager=subscription_manager_instance)) # MODIFIED
                logger.info("Telegram polling mode started")
                
        except Exception as e:
            logger.error(f"Failed to initialize Telegram: {e}")
    else:
        logger.warning("TELEGRAM_BOT_TOKEN not set - Telegram bot disabled")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    if telegram_app:
        await telegram_app.shutdown()
    if telegram_task:
        await stop_telegram_bot()


# ============================================================================
# FASTAPI APPLICATION
# ============================================================================

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Telegram Voice Bot with Google AI Studio transcription",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class HealthResponse(BaseModel):
    status: str
    version: str
    telegram_connected: bool
    transcription_ready: bool


class TranscriptionRequest(BaseModel):
    audio_url: Optional[str] = None
    language: Optional[str] = None


class TranscriptionResponse(BaseModel):
    success: bool
    text: str
    confidence: float
    model: str


# ============================================================================
# ENDPOINTS
# ============================================================================

@app.get("/", tags=["Root"])
async def root():
    """Root endpoint."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running"
    }


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """
    Health check endpoint.
    
    Returns the status of all system components.
    """
    transcription_ready = False
    try:
        service = get_transcription_service()
        transcription_ready = bool(service.api_key)
    except Exception:
        pass
    
    return HealthResponse(
        status="healthy" if transcription_ready else "degraded",
        version=settings.APP_VERSION,
        telegram_connected=bool(settings.TELEGRAM_BOT_TOKEN),
        transcription_ready=transcription_ready,
    )


@app.post("/webhook", tags=["Telegram"])
async def telegram_webhook(request: Request):
    """
    Telegram webhook endpoint.
    
    Receives updates from Telegram and processes them.
    This endpoint is called by Telegram when new messages arrive.
    """
    global telegram_app
    
    if not telegram_app:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram bot not initialized"
        )
    
    try:
        data = await request.json()
        update = Update.de_json(data, telegram_app.bot)
        await telegram_app.process_update(update)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@app.post("/webhook/setup", tags=["Telegram"])
async def setup_webhook_endpoint(webhook_url: str): # FIXED: Completed function definition
    """
    Manually set up Telegram webhook.
    
    Args:
        webhook_url: The full URL for Telegram to send updates to
    """
    success = await setup_telegram_webhook(webhook_url)
    if success:
        return {"status": "ok", "message": f"Webhook set to {webhook_url}"}
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Failed to set webhook"
    )


@app.post("/webhook/delete", tags=["Telegram"])
async def delete_webhook_endpoint():
    """Delete the Telegram webhook."""
    success = await delete_telegram_webhook()
    if success:
        return {"status": "ok", "message": "Webhook deleted"}
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Failed to delete webhook"
    )


@app.post("/transcribe", response_model=TranscriptionResponse, tags=["Transcription"])
async def transcribe_audio(request: TranscriptionRequest):
    """
    Manual transcription endpoint.
    
    Allows transcribing audio from a URL without going through Telegram.
    """
    if not request.audio_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="audio_url is required"
        )
    
    if not settings.GOOGLE_AI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Transcription service not configured"
        )
    
    try:
        service = get_transcription_service()
        result = await service.transcribe_from_url(
            file_url=request.audio_url,
            language=request.language
        )
        
        return TranscriptionResponse(
            success=True,
            text=result.text,
            confidence=result.confidence,
            model=result.model_used,
        )
        
    except Exception as e:
        logger.error(f"Transcription request failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@app.get("/config", tags=["Config"])
async def get_config():
    """
    Get current configuration status.
    
    Returns which features are enabled (without exposing sensitive data).
    """
    return {
        "app_name": settings.APP_NAME,
        "debug": settings.DEBUG,
        "telegram_enabled": bool(settings.TELEGRAM_BOT_TOKEN),
        "transcription_enabled": bool(settings.GOOGLE_AI_API_KEY),
        "paypal_enabled": bool(settings.PAYPAL_CLIENT_ID),
        "google_ai_model": settings.GOOGLE_AI_MODEL,
    }


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        log_level="info" if not settings.DEBUG else "debug",
    )
