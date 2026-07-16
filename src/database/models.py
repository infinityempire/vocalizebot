"""
VocalizeBot - Database Models
"""
from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, Text, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field

Base = declarative_base()


class CustomerSegment(str, Enum):
    """Customer segment types."""
    B2B = "b2b"
    B2C = "b2c"
    EXISTING_CUSTOMER = "existing_customer"


class LeadStatus(str, Enum):
    """Lead qualification status."""
    NEW = "new"
    CONTACTED = "contacted"
    INTERESTED = "interested"
    PROPOSAL = "proposal"
    NEGOTIATION = "negotiation"
    CLOSED_WON = "closed_won"
    CLOSED_LOST = "closed_lost"


class MessageDirection(str, Enum):
    """Message direction."""
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageType(str, Enum):
    """Message content types."""
    TEXT = "text"
    VOICE = "voice"
    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"


class BlackoutStatus(str, Enum):
    """AI blackout status."""
    NORMAL = "normal"
    SUSPECTED = "suspected"
    ACTIVE = "active"
    ESCALATED = "escalated"


class Customer(Base):
    """Customer database model."""
    __tablename__ = "customers"

    id = Column(String, primary_key=True)
    phone = Column(String, unique=True, nullable=True)
    instagram_handle = Column(String, unique=True, nullable=True)
    telegram_id = Column(String, unique=True, nullable=True)  # Primary channel
    telegram_username = Column(String, nullable=True)
    segment = Column(SQLEnum(CustomerSegment), default=CustomerSegment.B2C)
    
    # Lead scoring
    lead_score = Column(Integer, default=50)
    lead_status = Column(SQLEnum(LeadStatus), default=LeadStatus.NEW)
    
    # Customer info
    name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    company = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_interaction = Column(DateTime, nullable=True)
    
    # State
    is_active = Column(Boolean, default=True)
    blackout_count = Column(Integer, default=0)
    blackout_status = Column(SQLEnum(BlackoutStatus), default=BlackoutStatus.NORMAL)

    # Relationships
    conversations = relationship("Conversation", back_populates="customer", cascade="all, delete-orphan")
    interactions = relationship("Interaction", back_populates="customer", cascade="all, delete-orphan")


class Conversation(Base):
    """Conversation database model."""
    __tablename__ = "conversations"

    id = Column(String, primary_key=True)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False)
    channel = Column(String)  # whatsapp, instagram
    channel_id = Column(String, nullable=True)  # WhatsApp SID, Instagram DM ID
    
    # Status
    is_active = Column(Boolean, default=True)
    is_escalated = Column(Boolean, default=False)
    
    # AI State
    last_ai_response = Column(Text, nullable=True)
    consecutive_errors = Column(Integer, default=0)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)

    # Relationships
    customer = relationship("Customer", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    """Message database model."""
    __tablename__ = "messages"

    id = Column(String, primary_key=True)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=False)
    
    direction = Column(SQLEnum(MessageDirection), nullable=False)
    message_type = Column(SQLEnum(MessageType), default=MessageType.TEXT)
    content = Column(Text, nullable=False)
    
    # For voice notes
    media_url = Column(String, nullable=True)
    transcription = Column(Text, nullable=True)
    
    # AI metadata
    intent_detected = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    ai_response = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")


class Interaction(Base):
    """Customer interaction tracking."""
    __tablename__ = "interactions"

    id = Column(String, primary_key=True)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False)
    
    interaction_type = Column(String)  # message, purchase, complaint, payment
    description = Column(Text)
    interaction_metadata = Column("metadata", Text, nullable=True)  # JSON data
    
    created_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer", back_populates="interactions")


class PaymentLink(Base):
    """Payment link tracking."""
    __tablename__ = "payment_links"

    id = Column(String, primary_key=True)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False)
    
    amount = Column(Float, nullable=False)
    currency = Column(String, default="USD")
    description = Column(Text)
    
    # Stripe
    stripe_payment_intent_id = Column(String, nullable=True)
    payment_link_url = Column(String, nullable=True)
    
    status = Column(String, default="pending")  # pending, paid, expired, cancelled
    expires_at = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    paid_at = Column(DateTime, nullable=True)


# Pydantic schemas for API
class CustomerCreate(BaseModel):
    phone: Optional[str] = None
    instagram_handle: Optional[str] = None
    segment: Optional[CustomerSegment] = CustomerSegment.B2C
    name: Optional[str] = None
    email: Optional[str] = None
    company: Optional[str] = None


class CustomerResponse(BaseModel):
    id: str
    phone: Optional[str] = None
    instagram_handle: Optional[str] = None
    segment: CustomerSegment
    lead_score: int
    lead_status: LeadStatus
    name: Optional[str] = None
    email: Optional[str] = None
    company: Optional[str] = None
    created_at: datetime
    last_interaction: Optional[datetime] = None
    is_active: bool

    class Config:
        from_attributes = True


class MessageCreate(BaseModel):
    content: str
    message_type: MessageType = MessageType.TEXT
    media_url: Optional[str] = None


class MessageResponse(BaseModel):
    id: str
    conversation_id: str
    direction: MessageDirection
    message_type: MessageType
    content: str
    created_at: datetime
    ai_response: Optional[str] = None

    class Config:
        from_attributes = True
