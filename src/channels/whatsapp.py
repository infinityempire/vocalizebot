"""
VocalizeBot - WhatsApp Channel Integration (Twilio)
"""
import hashlib
import hmac
import base64
from typing import Optional, Dict, Any
from fastapi import APIRouter, Request, HTTPException, Header, Depends
from pydantic import BaseModel
from twilio.twiml.messaging_response import MessagingResponse
from twilio.request_validator import RequestValidator
from loguru import logger

from config.settings import get_settings
from src.agents.core import get_agent
from src.services.transcription import TranscriptionService
from src.database.connection import get_db_context
from src.database.models import Customer, Conversation, Message, MessageDirection, MessageType, CustomerSegment, BlackoutStatus

settings = get_settings()
router = APIRouter(prefix="/webhook/whatsapp", tags=["WhatsApp"])


class WhatsAppWebhookPayload(BaseModel):
    """WhatsApp webhook payload model."""
    From: str
    To: str
    Body: str
    MessageSid: str
    NumMedia: Optional[str] = "0"
    MediaUrl0: Optional[str] = None
    MediaContentType0: Optional[str] = None


async def verify_twilio_signature(
    request: Request,
    x_twilio_signature: str = Header(None)
) -> bool:
    """Verify that the request came from Twilio."""
    if not settings.twilio_webhook_secret:
        logger.warning("Twilio webhook secret not configured - skipping verification")
        return True
    
    if not x_twilio_signature:
        return False
    
    validator = RequestValidator(settings.twilio_auth_token)
    
    # Get the full URL
    url = str(request.url)
    
    # Get POST body
    form_data = await request.form()
    post_vars = dict(form_data)
    
    # Validate
    return validator.validate(url, post_vars, x_twilio_signature)


async def get_or_create_customer(phone: str) -> Customer:
    """Get existing customer or create new one."""
    async with get_db_context() as session:
        from sqlalchemy import select
        
        # Find existing customer
        stmt = select(Customer).where(Customer.phone == phone)
        result = await session.execute(stmt)
        customer = result.scalar_one_or_none()
        
        if not customer:
            # Create new customer
            customer = Customer(
                id=f"wa_{hashlib.md5(phone.encode()).hexdigest()[:12]}",
                phone=phone,
                segment=CustomerSegment.B2C,
                lead_score=settings.initial_lead_score
            )
            session.add(customer)
            await session.commit()
            await session.refresh(customer)
        
        return customer


async def get_or_create_conversation(customer: Customer, channel_id: str) -> Conversation:
    """Get active conversation or create new one."""
    async with get_db_context() as session:
        from sqlalchemy import select
        
        # Find active conversation
        stmt = select(Conversation).where(
            Conversation.customer_id == customer.id,
            Conversation.is_active == True
        )
        result = await session.execute(stmt)
        conversation = result.scalar_one_or_none()
        
        if not conversation:
            conversation = Conversation(
                id=f"conv_{hashlib.md5(channel_id.encode()).hexdigest()[:12]}",
                customer_id=customer.id,
                channel="whatsapp",
                channel_id=channel_id
            )
            session.add(conversation)
            await session.commit()
            await session.refresh(conversation)
        
        return conversation


async def store_message(
    conversation_id: str,
    direction: MessageDirection,
    message_type: MessageType,
    content: str,
    media_url: Optional[str] = None,
    transcription: Optional[str] = None,
    intent: Optional[str] = None,
    confidence: Optional[float] = None,
    ai_response: Optional[str] = None
) -> Message:
    """Store a message in the database."""
    async with get_db_context() as session:
        message = Message(
            id=f"msg_{hashlib.md5(content[:50].encode()).hexdigest()[:12]}",
            conversation_id=conversation_id,
            direction=direction,
            message_type=message_type,
            content=content,
            media_url=media_url,
            transcription=transcription,
            intent_detected=intent,
            confidence=confidence,
            ai_response=ai_response
        )
        session.add(message)
        await session.commit()
        await session.refresh(message)
        return message


@router.get("/webhook")
async def whatsapp_webhook_verify(
    hub_mode: str = None,
    hub_verify_token: str = None,
    hub_challenge: str = None
):
    """Webhook verification endpoint for Twilio."""
    if hub_verify_token == settings.instagram_webhook_verify_token:
        return int(hub_challenge) if hub_challenge else hub_challenge
    raise HTTPException(status_code=403, detail="Invalid verification token")


@router.post("/webhook")
async def whatsapp_webhook(request: Request):
    """
    Main webhook endpoint for WhatsApp messages.
    Receives messages from Twilio and processes them through the AI agent.
    """
    try:
        # Parse form data
        form_data = await request.form()
        data = dict(form_data)
        
        # Extract message details
        from_number = data.get("From", "").replace("whatsapp:", "")
        to_number = data.get("To", "").replace("whatsapp:", "")
        body = data.get("Body", "")
        message_sid = data.get("MessageSid", "")
        num_media = int(data.get("NumMedia", 0))
        media_url = data.get("MediaUrl0") if num_media > 0 else None
        media_content_type = data.get("MediaContentType0", "")
        
        logger.info(f"Received WhatsApp message from {from_number}: {body[:50]}...")
        
        # Get or create customer and conversation
        customer = await get_or_create_customer(from_number)
        conversation = await get_or_create_conversation(customer, message_sid)
        
        # Determine message type
        message_type = MessageType.TEXT
        processed_content = body
        
        # Handle voice notes
        if media_url and ("audio" in media_content_type or "ogg" in media_content_type):
            message_type = MessageType.VOICE
            # Transcribe voice note
            transcription_service = TranscriptionService()
            processed_content = await transcription_service.transcribe(media_url)
            if processed_content:
                logger.info(f"Transcribed voice: {processed_content[:50]}...")
        
        # Handle images
        elif media_url and "image" in media_content_type:
            message_type = MessageType.IMAGE
            processed_content = f"[Image received] {body or 'Image attached'}"
        
        # Store incoming message
        incoming_msg = await store_message(
            conversation_id=conversation.id,
            direction=MessageDirection.INBOUND,
            message_type=message_type,
            content=processed_content,
            media_url=media_url,
            transcription=processed_content if message_type == MessageType.VOICE else None
        )
        
        # Update customer last interaction
        from datetime import datetime
        async with get_db_context() as session:
            from sqlalchemy import select
            stmt = select(Customer).where(Customer.id == customer.id)
            result = await session.execute(stmt)
            cust = result.scalar_one_or_none()
            if cust:
                cust.last_interaction = datetime.utcnow()
                cust.blackout_count = 0
                cust.blackout_status = BlackoutStatus.NORMAL
                await session.commit()
        
        # Get AI response
        agent = get_agent()
        context = {
            "customer_name": customer.name or from_number,
            "customer_id": customer.id,
            "segment": customer.segment.value,
            "lead_score": customer.lead_score,
            "channel": "whatsapp"
        }
        
        ai_result = await agent.get_ai_response(
            message=processed_content,
            customer_id=customer.id,
            context=context
        )
        
        response_text = ai_result["message"]
        
        # Store AI response
        await store_message(
            conversation_id=conversation.id,
            direction=MessageDirection.OUTBOUND,
            message_type=MessageType.TEXT,
            content=response_text,
            intent=ai_result.get("intent"),
            confidence=ai_result.get("confidence"),
            ai_response=response_text
        )
        
        # Update conversation
        async with get_db_context() as session:
            from sqlalchemy import select
            stmt = select(Conversation).where(Conversation.id == conversation.id)
            result = await session.execute(stmt)
            conv = result.scalar_one_or_none()
            if conv:
                conv.last_ai_response = response_text
                if ai_result.get("escalation"):
                    conv.is_escalated = True
                await session.commit()
        
        # Update lead score
        if ai_result.get("lead_score_impact"):
            async with get_db_context() as session:
                from sqlalchemy import select
                stmt = select(Customer).where(Customer.id == customer.id)
                result = await session.execute(stmt)
                cust = result.scalar_one_or_none()
                if cust:
                    new_score = cust.lead_score + ai_result["lead_score_impact"]
                    cust.lead_score = max(0, min(settings.max_lead_score, new_score))
                    await session.commit()
        
        # Handle escalation if needed
        if ai_result.get("escalation") and settings.human_escalation_webhook_url:
            await trigger_escalation(customer, conversation, ai_result)
        
        # Generate TwiML response
        twiml = MessagingResponse()
        twiml.message(response_text)
        
        return twiml.to_xml()
        
    except Exception as e:
        logger.error(f"Error processing WhatsApp message: {e}")
        # Return a friendly error message
        twiml = MessagingResponse()
        twiml.message("Desculpe, houve um erro ao processar sua mensagem. Tente novamente em breve.")
        return twiml.to_xml()


async def trigger_escalation(
    customer: Customer,
    conversation: Conversation,
    ai_result: Dict[str, Any]
):
    """Trigger human escalation via webhook."""
    import httpx
    
    if not settings.human_escalation_webhook_url:
        return
    
    payload = {
        "customer_id": customer.id,
        "customer_phone": customer.phone,
        "customer_name": customer.name,
        "conversation_id": conversation.id,
        "channel": "whatsapp",
        "reason": "AI escalation",
        "ai_result": ai_result,
        "priority": "high"
    }
    
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                settings.human_escalation_webhook_url,
                json=payload,
                timeout=10.0
            )
        logger.info(f"Escalation triggered for customer {customer.id}")
    except Exception as e:
        logger.error(f"Failed to trigger escalation: {e}")


@router.get("/status/{message_sid}")
async def get_message_status(message_sid: str):
    """Check the status of a sent message."""
    # This would integrate with Twilio API to get message status
    # For now, return a placeholder
    return {"status": "sent", "message_sid": message_sid}
