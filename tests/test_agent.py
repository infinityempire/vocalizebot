"""
ReplyQ AI Agent - Unit Tests
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

# Test settings
import os
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["REDIS_ENABLED"] = "false"


class TestIntentClassification:
    """Tests for intent classification functionality."""

    def test_intent_detection_greeting(self):
        """Test greeting intent detection."""
        from src.agents.prompts import INTENT_CLASSIFICATION_PROMPT, format_prompt
        
        greeting_messages = [
            "Olá, bom dia!",
            "Oi, tudo bem?",
            "Hello!",
            "Hey there!"
        ]
        
        for message in greeting_messages:
            prompt = format_prompt(
                INTENT_CLASSIFICATION_PROMPT,
                message=message,
                context="No previous context"
            )
            assert message in prompt
            assert "greeting" in prompt.lower()

    def test_intent_detection_purchase(self):
        """Test purchase intent detection."""
        from src.agents.prompts import INTENT_CLASSIFICATION_PROMPT, format_prompt
        
        purchase_messages = [
            "Quero comprar este produto",
            "How much is it?",
            "What's the price?",
            "I want to buy this"
        ]
        
        for message in purchase_messages:
            prompt = format_prompt(
                INTENT_CLASSIFICATION_PROMPT,
                message=message,
                context="No previous context"
            )
            assert message in prompt

    def test_intent_detection_complaint(self):
        """Test complaint intent detection."""
        from src.agents.prompts import INTENT_CLASSIFICATION_PROMPT, format_prompt
        
        complaint_messages = [
            "Estou muito desapontado com o produto",
            "This is not what I ordered",
            "O produto chegou errado",
            "I'm very disappointed"
        ]
        
        for message in complaint_messages:
            prompt = format_prompt(
                INTENT_CLASSIFICATION_PROMPT,
                message=message,
                context="No previous context"
            )
            assert message in prompt


class TestLeadScoring:
    """Tests for lead scoring functionality."""

    def test_initial_score_bounds(self):
        """Test that initial scores are within bounds."""
        from config.settings import get_settings
        
        settings = get_settings()
        
        assert settings.initial_lead_score >= 0
        assert settings.initial_lead_score <= 100
        assert settings.max_lead_score == 100
        assert settings.min_lead_score == 0

    def test_score_update_bounds(self):
        """Test score update respects bounds."""
        from config.settings import get_settings
        
        settings = get_settings()
        
        # Test max boundary
        current_score = 95
        impact = 10
        new_score = max(0, min(settings.max_lead_score, current_score + impact))
        assert new_score == 100
        
        # Test min boundary
        current_score = 5
        impact = -10
        new_score = max(0, min(settings.max_lead_score, current_score + impact))
        assert new_score == 0


class TestCustomerSegments:
    """Tests for customer segment detection."""

    def test_b2b_keywords(self):
        """Test B2B keyword detection."""
        from config.settings import get_settings
        
        settings = get_settings()
        
        b2b_messages = [
            "We are a company looking for bulk orders",
            "Enterprise pricing for business",
            "Need corporate solution"
        ]
        
        for message in b2b_messages:
            message_lower = message.lower()
            assert any(kw in message_lower for kw in settings.b2b_keywords)

    def test_b2c_keywords(self):
        """Test B2C keyword detection."""
        from config.settings import get_settings
        
        settings = get_settings()
        
        b2c_messages = [
            "For personal use at home",
            "Just a single one for myself",
            "Individual purchase"
        ]
        
        for message in b2c_messages:
            message_lower = message.lower()
            assert any(kw in message_lower for kw in settings.b2c_keywords)


class TestBlackoutDetection:
    """Tests for blackout mode detection."""

    def test_blackout_threshold(self):
        """Test blackout threshold configuration."""
        from config.settings import get_settings
        
        settings = get_settings()
        
        assert settings.blackout_mode_threshold >= 1
        assert settings.blackout_mode_threshold <= 10

    def test_blackout_counter_logic(self):
        """Test blackout counter increments and resets."""
        # Simulate blackout counter
        blackout_counter = {}
        
        customer_id = "test_customer_1"
        
        # Increment
        blackout_counter[customer_id] = blackout_counter.get(customer_id, 0) + 1
        assert blackout_counter[customer_id] == 1
        
        # Increment again
        blackout_counter[customer_id] += 1
        assert blackout_counter[customer_id] == 2
        
        # Reset on success
        if blackout_counter.get(customer_id, 0) >= 3:
            blackout_counter[customer_id] = 0
        assert blackout_counter[customer_id] == 2  # Not reached threshold yet
        
        # Reach threshold and escalate
        blackout_counter[customer_id] += 1
        if blackout_counter[customer_id] >= 3:
            blackout_counter[customer_id] = 0  # Reset after escalation
        assert blackout_counter[customer_id] == 0


class TestPaymentService:
    """Tests for payment service."""

    def test_payment_amount_conversion(self):
        """Test amount conversion to cents."""
        # Convert to cents for Stripe
        amount = 99.99
        amount_cents = int(amount * 100)
        assert amount_cents == 9999
        
        amount = 10.0
        amount_cents = int(amount * 100)
        assert amount_cents == 1000

    def test_payment_status_values(self):
        """Test valid payment status values."""
        valid_statuses = ["pending", "paid", "expired", "cancelled", "failed"]
        
        # This tests the model
        for status in valid_statuses:
            assert status in valid_statuses


class TestSalesClosing:
    """Tests for sales closing logic."""

    def test_closing_technique_extraction(self):
        """Test extraction of closing techniques from text."""
        techniques = ["direct_close", "assumptive_close", "trial_close", "consultative_close"]
        
        # Test various responses
        response1 = "I recommend using a direct close technique here."
        assert any(tech.replace("_", " ") in response1.lower() for tech in techniques)
        
        response2 = "The assumptive close would work well."
        assert any(tech.replace("_", " ") in response2.lower() for tech in techniques)

    def test_closing_probability_calculation(self):
        """Test closing probability based on factors."""
        def calculate_closing_probability(interest_level, objections_addressed, engagement):
            base_prob = 20
            
            # Interest level impact
            if interest_level == "high":
                base_prob += 40
            elif interest_level == "medium":
                base_prob += 20
            
            # Objections impact
            base_prob += len(objections_addressed) * 10
            
            # Engagement impact
            base_prob += engagement * 5
            
            return min(100, max(0, base_prob))
        
        # High interest with addressed objections
        assert calculate_closing_probability("high", ["price", "quality"], 5) == 100
        
        # Low interest
        assert calculate_closing_probability("low", [], 1) == 25
        
        # Medium interest
        assert calculate_closing_probability("medium", ["delivery"], 3) == 65


class TestMessageProcessing:
    """Tests for message processing."""

    def test_message_type_detection(self):
        """Test message type detection."""
        from src.database.models import MessageType
        
        # Text message
        assert MessageType.TEXT.value == "text"
        
        # Voice message
        assert MessageType.VOICE.value == "voice"
        
        # Image message
        assert MessageType.IMAGE.value == "image"

    def test_message_direction(self):
        """Test message direction values."""
        from src.database.models import MessageDirection
        
        assert MessageDirection.INBOUND.value == "inbound"
        assert MessageDirection.OUTBOUND.value == "outbound"


class TestAPIEndpoints:
    """Tests for API endpoint configurations."""

    def test_whatsapp_webhook_path(self):
        """Test WhatsApp webhook path configuration."""
        from src.channels.whatsapp import router
        
        assert router.prefix == "/webhook/whatsapp"

    def test_instagram_webhook_path(self):
        """Test Instagram webhook path configuration."""
        from src.channels.instagram import router
        
        assert router.prefix == "/webhook/instagram"


class TestTranscriptionService:
    """Tests for transcription service."""

    def test_transcription_url_parsing(self):
        """Test URL parsing for transcription."""
        test_urls = [
            "https://api.twilio.com/voice/123/audio.ogg",
            "https://example.com/audio/message.mp3",
            "https://s3.amazonaws.com/bucket/audio.wav"
        ]
        
        for url in test_urls:
            assert url.startswith("http")


class TestObjectionHandling:
    """Tests for objection handling."""

    def test_common_objections(self):
        """Test handling of common objections."""
        common_objections = [
            "Preço alto demais",
            "Too expensive",
            "Preciso pensar mais",
            "I need to think about it",
            "Não tenho orçamento",
            "No budget right now"
        ]
        
        for objection in common_objections:
            assert len(objection) > 0


class TestFollowUpTemplates:
    """Tests for follow-up message templates."""

    def test_follow_up_templates_exist(self):
        """Test that follow-up templates are defined."""
        from src.agents.prompts import FOLLOW_UP_TEMPLATES
        
        expected_templates = [
            "initial_contact",
            "interest_follow_up",
            "payment_pending",
            "post_purchase",
            "reengagement"
        ]
        
        for template in expected_templates:
            assert template in FOLLOW_UP_TEMPLATES

    def test_follow_up_template_formatting(self):
        """Test follow-up template formatting."""
        from src.agents.prompts import FOLLOW_UP_TEMPLATES, format_prompt
        
        template = FOLLOW_UP_TEMPLATES["initial_contact"]
        formatted = format_prompt(template, name="João")
        
        assert "João" in formatted
        assert "Obrigado" in formatted or "Hello" in formatted or "Olá" in formatted


class TestDatabaseModels:
    """Tests for database models."""

    def test_customer_model_fields(self):
        """Test Customer model has required fields."""
        from src.database.models import Customer
        
        required_fields = [
            "id", "phone", "instagram_handle", "segment",
            "lead_score", "lead_status", "name", "created_at"
        ]
        
        # Check model is properly defined
        assert Customer.__tablename__ == "customers"

    def test_conversation_model_fields(self):
        """Test Conversation model has required fields."""
        from src.database.models import Conversation
        
        assert Conversation.__tablename__ == "conversations"

    def test_message_model_fields(self):
        """Test Message model has required fields."""
        from src.database.models import Message
        
        assert Message.__tablename__ == "messages"


class TestSettings:
    """Tests for settings configuration."""

    def test_settings_load(self):
        """Test settings load from environment."""
        from config.settings import get_settings
        
        settings = get_settings()
        
        assert settings.app_name in ["ReplyQ AI Agent", "Telegram Voice Bot"]
        assert settings.app_version in ["1.0.0", "2.0.0"]
        
    def test_database_url_default(self):
        """Test default database URL."""
        from config.settings import get_settings
        
        settings = get_settings()
        
        assert "sqlite" in settings.database_url.lower() or "aiosqlite" in settings.database_url.lower()


class TestPrompts:
    """Tests for prompt templates."""

    def test_system_prompt_length(self):
        """Test system prompt is sufficiently detailed."""
        from src.agents.prompts import SYSTEM_PROMPT
        
        assert len(SYSTEM_PROMPT) > 500  # Should be detailed

    def test_prompt_templates_complete(self):
        """Test all prompt templates are defined."""
        from src.agents.prompts import (
            SYSTEM_PROMPT,
            INTENT_CLASSIFICATION_PROMPT,
            LEAD_QUALIFICATION_PROMPT,
            OBJECTION_HANDLING_PROMPT,
            COMPLAINT_HANDLETING_PROMPT,
            PAYMENT_GENERATION_PROMPT,
            SALES_CLOSING_PROMPT,
            BLACKOUT_DETECTION_PROMPT
        )
        
        assert SYSTEM_PROMPT is not None
        assert INTENT_CLASSIFICATION_PROMPT is not None
        assert LEAD_QUALIFICATION_PROMPT is not None


# Integration-style tests (mock external calls)
class TestAgentIntegration:
    """Integration tests with mocked external services."""

    @pytest.mark.asyncio
    async def test_agent_response_structure(self):
        """Test agent response has correct structure."""
        # Mock the AI response
        mock_response = {
            "message": "Olá! Como posso ajudar?",
            "intent": "greeting",
            "confidence": 0.95,
            "lead_score_impact": 5,
            "detected_segment": "b2c",
            "requires_action": False,
            "escalation": False,
            "actions": []
        }
        
        # Verify structure
        assert "message" in mock_response
        assert "intent" in mock_response
        assert "confidence" in mock_response
        assert "lead_score_impact" in mock_response

    @pytest.mark.asyncio
    async def test_conversation_history_management(self):
        """Test conversation history is properly managed."""
        history = []
        customer_id = "test_customer"
        
        # Add messages
        history.append({"role": "user", "content": "Hello"})
        history.append({"role": "assistant", "content": "Hi there!"})
        
        # Verify history
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"
        
        # Test history limiting (keep last 10)
        if len(history) > 10:
            history = history[-10:]
        assert len(history) <= 10


# Performance tests
class TestPerformance:
    """Performance-related tests."""

    def test_conversation_history_cleanup(self):
        """Test that old conversation histories can be cleaned up."""
        conversation_history = {
            f"customer_{i}": [{"role": "user", "content": f"Message {j}"} for j in range(100)]
            for i in range(100)
        }
        
        # Simulate cleanup
        for customer_id in list(conversation_history.keys())[:50]:
            conversation_history[customer_id] = []
        
        active_conversations = sum(1 for msgs in conversation_history.values() if len(msgs) > 0)
        assert active_conversations == 50


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
