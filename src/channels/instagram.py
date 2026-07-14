"""
VocalizeBot - Instagram Channel Integration
"""
import hashlib
import hmac
import time
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Request, HTTPException, Header, Depends
from pydantic import BaseModel
from loguru import logger
import httpx

from config.settings import get_settings
from src.agents.core import get_agent
from src.services.transcription import TranscriptionService
from src.database.connection import get_db_context
from src.database.models import Customer, Conversation, Message, MessageDirection, MessageType, CustomerSegment, BlackoutStatus

settings = get_settings()
router = APIRouter(prefix="/webhook/instagram", tags=["Instagram"])


class InstagramMessagePayload(BaseModel):
    """Instagram message payload model."""
    messaging: List[Dict[str, Any]]


def verify_instagram_webhook(
    mode: str,
    token: str,
    challenge: str
) -> bool:
    """Verify Instagram webhook subscription."""
    if mode == "subscribe" and token == settings.instagram_webhook_verify_token:
        return True
    return False


def generate_instagram_signature(
    payload: str,
    secret: str
) -> str:
    """Generate HMAC-SHA256 signature for Instagram webhook."""
    return hmac.new(
        secret.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()


async def get_or_create_customer(instagram_id: str, username: str) -> Customer:
    """Get existing customer or create new one from Instagram."""
    async with get_db_context() as session:
        from sqlalchemy import select
        
        # Find existing customer
        stmt = select(Customer).where(Customer.instagram_handle == username)
        result = await session.execute(stmt)
        customer = result.scalar_one_or_none()
        
        if not customer:
            # Create new customer
            customer = Customer(
                id=f"ig_{hashlib.md5(instagram_id.encode()).hexdigest()[:12]}",
                instagram_handle=username,
                segment=CustomerSegment.B2C,
                lead_score=settings.initial_lead_score
            )
            session.add(customer)
            await session.commit()
            await session.refresh(customer)
        
        return customer


async def get_or_create_conversation(customer: Customer, ig_id: str) -> Conversation:
    """Get active conversation or create new one."""
    async with get_db_context() as session:
        from sqlalchemy import select
        
        # Find active conversation
        stmt = select(Conversation).where(
            Conversation.customer_id == customer.id,
            Conversation.channel == "instagram",
            Conversation.is_active == True
        )
        result = await session.execute(stmt)
        conversation = result.scalar_one_or_none()
        
        if not conversation:
            conversation = Conversation(
                id=f"conv_ig_{hashlib.md5(ig_id.encode()).hexdigest()[:12]}",
                customer_id=customer.id,
                channel="instagram",
                channel_id=ig_id
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
            id=f"msg_ig_{hashlib.md5(content[:50].encode()).hexdigest()[:12]}",
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


async def get_instagram_user_profile(ig_id: str) -> Dict[str, Any]:
    """Get Instagram user profile information."""
    if not settings.instagram_access_token:
        return {"username": f"user_{ig_id}", "name": None}
    
    url = f"https://graph.instagram.com/{ig_id}"
    params = {
        "fields": "username,name,profile_picture_url",
        "access_token": settings.instagram_access_token
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=10.0)
            if response.status_code == 200:
                return response.json()
            return {"username": f"user_{ig_id}", "name": None}
    except Exception as e:
        logger.error(f"Error fetching Instagram profile: {e}")
        return {"username": f"user_{ig_id}", "name": None}


async def send_instagram_message(recipient_id: str, message: str, access_token: str) -> bool:
    """Send a message via Instagram Direct API."""
    if not access_token:
        logger.warning("No Instagram access token configured")
        return False
    
    url = "https://graph.facebook.com/v18.0/me/messages"
    headers = {"Content-Type": "application/json"}
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": message},
        "access_token": access_token
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers, timeout=10.0)
            if response.status_code == 200:
                logger.info(f"Instagram message sent to {recipient_id}")
                return True
            else:
                logger.error(f"Failed to send Instagram message: {response.text}")
                return False
    except Exception as e:
        logger.error(f"Error sending Instagram message: {e}")
        return False


@router.get("/webhook")
async def instagram_webhook_verify(
    hub_mode: str = None,
    hub_verify_token: str = None,
    hub_challenge: str = None
):
    """Webhook verification endpoint for Instagram."""
    if hub_verify_token == settings.instagram_webhook_verify_token:
        return int(hub_challenge) if hub_challenge else hub_challenge
    raise HTTPException(status_code=403, detail="Invalid verification token")


@router.post("/webhook")
async def instagram_webhook(request: Request):
    """
    Main webhook endpoint for Instagram messages.
    Receives messages from Instagram and processes them through the AI agent.
    """
    try:
        # Get request body for signature verification
        body = await request.body()
        
        # Verify signature (if app secret is configured)
        if settings.instagram_app_secret:
            signature = request.headers.get("x-hub-signature-256", "")
            expected = f"sha256={generate_instagram_signature(body.decode(), settings.instagram_app_secret)}"
            if not hmac.compare_digest(signature, expected):
                raise HTTPException(status_code=403, detail="Invalid signature")
        
        # Parse payload
        import json
        payload = json.loads(body)
        
        # Handle webhook verification
        if "object" in payload and payload["object"] == "instagram":
            # This is a verification request
            return {"status": "ok"}
        
        # Process messages
        if "entry" not in payload:
            return {"status": "ok"}
        
        responses_sent = []
        
        for entry in payload.get("entry", []):
            for messaging in entry.get("messaging", []):
                sender_id = messaging.get("sender", {}).get("id")
                recipient_id = messaging.get("recipient", {}).get("id")
                message_data = messaging.get("message", {})
                
                # Skip echo messages (messages sent by the page)
                if message_data.get("is_echo"):
                    continue
                
                # Get message content
                message_text = message_data.get("text", "")
                attachments = message_data.get("attachments", [])
                message_id = message_data.get("mid")
                
                logger.info(f"Received Instagram message from {sender_id}: {message_text[:50]}...")
                
                # Get user profile
                profile = await get_instagram_user_profile(sender_id)
                username = profile.get("username", f"user_{sender_id}")
                
                # Get or create customer and conversation
                customer = await get_or_create_customer(sender_id, username)
                conversation = await get_or_create_conversation(customer, message_id or sender_id)
                
                # Update customer name if available
                if profile.get("name") and not customer.name:
                    async with get_db_context() as session:
                        from sqlalchemy import select
                        stmt = select(Customer).where(Customer.id == customer.id)
                        result = await session.execute(stmt)
                        cust = result.scalar_one_or_none()
                        if cust:
                            cust.name = profile["name"]
                            await session.commit()
                
                # Process message content
                processed_content = message_text
                message_type = MessageType.TEXT
                media_url = None
                
                # Handle attachments
                for attachment in attachments:
                    attachment_type = attachment.get("type")
                    attachment_payload = attachment.get("payload", {})
                    url = attachment_payload.get("url")
                    
                    if attachment_type == "image":
                        message_type = MessageType.IMAGE
                        processed_content = f"[Image received] {message_text or 'Image attached'}"
                        media_url = url
                    elif attachment_type == "audio":
                        message_type = MessageType.VOICE
                        # Transcribe audio
                        transcription_service = TranscriptionService()
                        processed_content = await transcription_service.transcribe(url) or "[Audio message]"
                        media_url = url
                    elif attachment_type == "video":
                        message_type = MessageType.VIDEO
                        processed_content = f"[Video received] {message_text or 'Video attached'}"
                        media_url = url
                    elif attachment_type == "file":
                        message_type = MessageType.DOCUMENT
                        processed_content = f"[Document received] {message_text or 'Document attached'}"
                        media_url = url
                
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
                    "customer_name": customer.name or username,
                    "customer_id": customer.id,
                    "segment": customer.segment.value,
                    "lead_score": customer.lead_score,
                    "channel": "instagram"
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
                
                # Send response via Instagram API
                sent = await send_instagram_message(sender_id, response_text, settings.instagram_access_token or "")
                responses_sent.append({"recipient": sender_id, "sent": sent})
        
        return {"status": "ok", "processed": len(responses_sent)}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing Instagram message: {e}")
        return {"status": "error", "message": str(e)}


async def trigger_escalation(
    customer: Customer,
    conversation: Conversation,
    ai_result: Dict[str, Any]
):
    """Trigger human escalation via webhook."""
    if not settings.human_escalation_webhook_url:
        return
    
    payload = {
        "customer_id": customer.id,
        "customer_handle": customer.instagram_handle,
        "customer_name": customer.name,
        "conversation_id": conversation.id,
        "channel": "instagram",
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


@router.get("/profile/{ig_id}")
async def get_profile(ig_id: str):
    """Get Instagram user profile."""
    profile = await get_instagram_user_profile(ig_id)
    return profile
