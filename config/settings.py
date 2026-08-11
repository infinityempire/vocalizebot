"""
VocalizeBot - Application Settings
Open Hands Agent | Tal HaTil Empire
"""
from pydantic_settings import BaseSettings
from typing import Optional
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_name: str = "VocalizeBot"
    app_version: str = "2.0.0"
    debug: bool = False
    log_level: str = "INFO"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # AI Providers - Google AI Studio (Primary)
    google_ai_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    default_ai_provider: str = "google"
    ai_model: str = "gemini-1.5-pro"

    # Google AI Studio (Voice Transcription)
    google_speech_api_key: Optional[str] = None

    # WhatsApp (Twilio)
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_phone_number: Optional[str] = None
    whatsapp_webhook_secret: Optional[str] = None

    # Instagram
    instagram_access_token: Optional[str] = None
    instagram_app_secret: Optional[str] = None
    instagram_webhook_verify_token: str = "vocalizebot_verify_token"

    # Telegram (Primary Channel)
    telegram_bot_token: Optional[str] = None
    telegram_webhook_secret: Optional[str] = None
    telegram_allow_groups: bool = False
    telegram_admin_chat_id: Optional[str] = None  # Admin's Telegram ID for hot lead notifications & message monitoring

    # Database
    database_url: str = "sqlite+aiosqlite:///./vocalizebot.db"
    database_echo: bool = False

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_enabled: bool = False

    # Payment - PayPal (Primary)
    paypal_client_id: Optional[str] = None
    paypal_client_secret: Optional[str] = None
    paypal_mode: str = "sandbox"  # sandbox or live
    paypal_webhook_id: Optional[str] = None

    # Payment - Stripe (Secondary)
    stripe_api_key: Optional[str] = None
    stripe_webhook_secret: Optional[str] = None

    # Human Escalation
    human_escalation_webhook_url: Optional[str] = None
    blackout_mode_threshold: int = 3
    blackout_mode_escalation_enabled: bool = True

    # Lead Scoring
    initial_lead_score: int = 50
    max_lead_score: int = 100
    min_lead_score: int = 0

    # Customer Segments
    b2b_keywords: list = ["business", "company", "enterprise", "corporate", "bulk", "reseller"]
    b2c_keywords: list = ["personal", "home", "individual", "single"]

    # Rate Limiting
    rate_limit_messages_per_minute: int = 60
    rate_limit_enabled: bool = True

    # Security
    secret_key: str = "your-secret-key-change-in-production"
    allowed_origins: list = ["*"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
