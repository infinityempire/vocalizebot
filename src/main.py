"""
VocalizeBot - Main Application Entry Point
Open Hands Agent | Tal HaTil Empire
"""
import asyncio
import sqlite3
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from config.settings import get_settings
from src.database.connection import init_db, close_db
from src.channels.telegram import router as telegram_router
from src.channels.whatsapp import router as whatsapp_router
from src.channels.instagram import router as instagram_router
from src.services.payment import get_payment_service
from src.services.sales import get_sales_service

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting VocalizeBot...")
    
    # Initialize database
    await init_db()
    logger.info("Database initialized")
    
    # Initialize services
    _ = get_payment_service()
    _ = get_sales_service()
    logger.info("Services initialized")
    
    yield
    
    # Shutdown
    logger.info("Shutting down VocalizeBot...")
    await close_db()
    logger.info("Database connections closed")


# Create FastAPI app
app = FastAPI(
    title="VocalizeBot",
    description="Advanced AI Agent for Customer Management, Sales & Business Operations on WhatsApp and Instagram",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(telegram_router)
app.include_router(whatsapp_router)
app.include_router(instagram_router)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "VocalizeBot",
        "version": "1.0.0",
        "status": "running",
        "description": "Advanced AI Agent for Customer Management, Sales & Business Operations"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "services": {
            "database": "connected",
            "ai_provider": "configured" if settings.openai_api_key else "not_configured",
            "payment_provider": "configured" if settings.stripe_api_key else "not_configured"
        }
    }


@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events."""
    try:
        body = await request.json()
        
        # Verify Stripe signature
        if settings.stripe_webhook_secret:
            sig = request.headers.get("stripe-signature", "")
            # In production, verify the signature here
            pass
        
        # Process the event
        payment_service = get_payment_service()
        result = await payment_service.handle_payment_webhook(body)
        
        return result
        
    except Exception as e:
        logger.error(f"Stripe webhook error: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/customers")
async def list_customers(
    segment: str = None,
    status: str = None,
    limit: int = 50,
    offset: int = 0
):
    """List all customers with optional filters."""
    from sqlalchemy import select
    from src.database.connection import get_db_context
    from src.database.models import Customer
    
    try:
        async with get_db_context() as session:
            query = select(Customer).order_by(Customer.lead_score.desc())
            
            if segment:
                query = query.where(Customer.segment == segment)
            if status:
                query = query.where(Customer.lead_status == status)
            
            query = query.limit(limit).offset(offset)
            result = await session.execute(query)
            customers = result.scalars().all()
            
            return {
                "total": len(customers),
                "customers": [
                    {
                        "id": c.id,
                        "phone": c.phone,
                        "instagram_handle": c.instagram_handle,
                        "name": c.name,
                        "segment": c.segment.value,
                        "lead_score": c.lead_score,
                        "lead_status": c.lead_status.value,
                        "last_interaction": c.last_interaction.isoformat() if c.last_interaction else None
                    }
                    for c in customers
                ]
            }
    except Exception as e:
        logger.error(f"Error listing customers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/customers/{customer_id}")
async def get_customer(customer_id: str):
    """Get customer details."""
    from sqlalchemy import select
    from src.database.connection import get_db_context
    from src.database.models import Customer
    
    try:
        async with get_db_context() as session:
            stmt = select(Customer).where(Customer.id == customer_id)
            result = await session.execute(stmt)
            customer = result.scalar_one_or_none()
            
            if not customer:
                raise HTTPException(status_code=404, detail="Customer not found")
            
            return {
                "id": customer.id,
                "phone": customer.phone,
                "instagram_handle": customer.instagram_handle,
                "name": customer.name,
                "email": customer.email,
                "company": customer.company,
                "segment": customer.segment.value,
                "lead_score": customer.lead_score,
                "lead_status": customer.lead_status.value,
                "notes": customer.notes,
                "created_at": customer.created_at.isoformat() if customer.created_at else None,
                "last_interaction": customer.last_interaction.isoformat() if customer.last_interaction else None
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting customer: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/customers/{customer_id}")
async def update_customer(customer_id: str, request: Request):
    """Update customer details."""
    from sqlalchemy import select
    from src.database.connection import get_db_context
    from src.database.models import Customer
    
    try:
        body = await request.json()
        
        async with get_db_context() as session:
            stmt = select(Customer).where(Customer.id == customer_id)
            result = await session.execute(stmt)
            customer = result.scalar_one_or_none()
            
            if not customer:
                raise HTTPException(status_code=404, detail="Customer not found")
            
            # Update allowed fields
            if "name" in body:
                customer.name = body["name"]
            if "email" in body:
                customer.email = body["email"]
            if "company" in body:
                customer.company = body["company"]
            if "notes" in body:
                customer.notes = body["notes"]
            if "lead_status" in body:
                from src.database.models import LeadStatus
                customer.lead_status = LeadStatus(body["lead_status"])
            if "segment" in body:
                from src.database.models import CustomerSegment
                customer.segment = CustomerSegment(body["segment"])
            
            await session.commit()
            
            return {"success": True, "customer_id": customer_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating customer: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/pipeline")
async def get_pipeline(
    segment: str = None,
    status: str = None,
    min_score: int = None
):
    """Get sales pipeline."""
    sales_service = get_sales_service()
    
    filters = {}
    if segment:
        filters["segment"] = segment
    if status:
        filters["status"] = status
    if min_score:
        filters["min_score"] = min_score
    
    pipeline = await sales_service.get_sales_pipeline(filters)
    
    return {"pipeline": pipeline, "total": len(pipeline)}


@app.get("/api/analytics")
async def get_analytics(days: int = 30):
    """Get business analytics."""
    from src.services.business import get_business_service
    
    try:
        business_service = get_business_service()
        analytics = await business_service.get_business_analytics(days)
        return analytics
    except Exception as e:
        logger.error(f"Error getting analytics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analytics/top-customers")
async def get_top_customers(limit: int = 10, by: str = "score"):
    """Get top customers by various metrics."""
    from src.services.business import get_business_service
    
    try:
        business_service = get_business_service()
        customers = await business_service.get_top_customers(limit, by)
        return {"customers": customers, "total": len(customers)}
    except Exception as e:
        logger.error(f"Error getting top customers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/followups")
async def get_followups_needed(days_inactive: int = 3):
    """Get customers needing follow-up."""
    from src.services.business import get_business_service
    
    try:
        business_service = get_business_service()
        customers = await business_service.get_customers_needing_followup(days_inactive)
        return {"customers": customers, "total": len(customers)}
    except Exception as e:
        logger.error(f"Error getting follow-ups: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/business/operational-update")
async def log_operational_update(request: Request):
    """Log an operational update."""
    from src.services.business import get_business_service
    
    try:
        body = await request.json()
        business_service = get_business_service()
        result = await business_service.log_operational_update(
            update_type=body.get("type", "general"),
            description=body.get("description", ""),
            metadata=body.get("metadata")
        )
        return result
    except Exception as e:
        logger.error(f"Error logging update: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/export/customers")
async def export_customers(
    segment: str = None,
    status: str = None,
    min_score: int = None
):
    """Export customer data."""
    from src.services.business import get_business_service
    
    try:
        business_service = get_business_service()
        filters = {}
        if segment:
            filters["segment"] = segment
        if status:
            filters["status"] = status
        if min_score:
            filters["min_score"] = min_score
        
        customers = await business_service.export_customer_data(filters)
        return {"customers": customers, "total": len(customers)}
    except Exception as e:
        logger.error(f"Error exporting customers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/payments/create-link")
async def create_payment_link(request: Request):
    """Create a payment link for a customer."""
    from src.services.payment import get_payment_service
    
    try:
        body = await request.json()
        
        if not body.get("customer_id"):
            raise HTTPException(status_code=400, detail="customer_id is required")
        if not body.get("amount"):
            raise HTTPException(status_code=400, detail="amount is required")
        
        payment_service = get_payment_service()
        result = await payment_service.create_payment_link(
            customer_id=body["customer_id"],
            amount=float(body["amount"]),
            currency=body.get("currency", "USD"),
            description=body.get("description", "Payment"),
            expires_in_hours=body.get("expires_in_hours", 24)
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating payment link: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sales/{customer_id}/close")
async def close_deal(customer_id: str, request: Request):
    """Close a deal."""
    from src.services.sales import get_sales_service
    
    try:
        body = await request.json() if request.method == "POST" else {}
        notes = body.get("notes")
        
        sales_service = get_sales_service()
        result = await sales_service.close_deal(customer_id, notes)
        
        return result
        
    except Exception as e:
        logger.error(f"Error closing deal: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# 📢 BROADCAST SYSTEM - Admin endpoints for mass messaging
# =============================================================================

@app.post("/api/broadcast/send")
async def broadcast_message(request: Request):
    """
    Send a broadcast message to all users via Telegram.
    
    Requires ADMIN_DASHBOARD_TOKEN in Authorization header.
    
    Body:
        message: str - The message to send (supports Markdown)
        target: str - "all" or "premium" (default: "all")
    """
    from config.settings import get_settings
    
    # Verify admin token
    settings = get_settings()
    auth_header = request.headers.get("Authorization", "")
    expected_token = f"Bearer {settings.admin_dashboard_token}"
    
    if auth_header != expected_token:
        raise HTTPException(status_code=401, detail="Unauthorized - Invalid admin token")
    
    try:
        body = await request.json()
        message = body.get("message", "").strip()
        target = body.get("target", "all")  # "all" or "premium"
        
        if not message:
            raise HTTPException(status_code=400, detail="Message cannot be empty")
        
        # Import subscription manager and telegram bot
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))
        from subscription_manager import SubscriptionManager
        
        # Get users to send to
        sub_manager = SubscriptionManager()
        
        if target == "premium":
            user_ids = sub_manager.get_premium_users()
        else:
            user_ids = sub_manager.get_all_users()
        
        if not user_ids:
            return {
                "success": True,
                "sent": 0,
                "message": "No users to send to"
            }
        
        # Send via Telegram
        sent_count = 0
        failed_count = 0
        
        try:
            import requests
            
            for user_id in user_ids:
                try:
                    # Escape markdown for Telegram
                    escaped_message = message.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[")
                    
                    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
                    payload = {
                        "chat_id": user_id,
                        "text": escaped_message,
                        "parse_mode": "MarkdownV2"
                    }
                    
                    response = requests.post(url, json=payload, timeout=10)
                    
                    if response.status_code == 200 and response.json().get("ok"):
                        sent_count += 1
                    else:
                        failed_count += 1
                        logger.warning(f"Failed to send to {user_id}: {response.text[:100]}")
                        
                except Exception as e:
                    failed_count += 1
                    logger.error(f"Error sending to {user_id}: {e}")
            
        except ImportError:
            logger.error("requests library not available for Telegram API calls")
        
        logger.info(f"Broadcast completed: {sent_count} sent, {failed_count} failed")
        
        return {
            "success": True,
            "sent": sent_count,
            "failed": failed_count,
            "total_users": len(user_ids),
            "target": target
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Broadcast error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/broadcast/stats")
async def broadcast_stats(request: Request):
    """Get broadcast statistics."""
    from config.settings import get_settings
    
    # Verify admin token
    settings = get_settings()
    auth_header = request.headers.get("Authorization", "")
    expected_token = f"Bearer {settings.admin_dashboard_token}"
    
    if auth_header != expected_token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from subscription_manager import SubscriptionManager
    
    sub_manager = SubscriptionManager()
    all_users = sub_manager.get_all_users()
    premium_users = sub_manager.get_premium_users()
    
    return {
        "total_users": len(all_users),
        "premium_users": len(premium_users),
        "free_users": len(all_users) - len(premium_users)
    }


# =============================================================================
# 🏠 ADMIN DASHBOARD API
# =============================================================================

@app.get("/api/admin/stats")
async def admin_stats(request: Request):
    """Get comprehensive admin statistics."""
    from config.settings import get_settings
    
    # Verify admin token
    settings = get_settings()
    auth_header = request.headers.get("Authorization", "")
    expected_token = f"Bearer {settings.admin_dashboard_token}"
    
    if auth_header != expected_token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from subscription_manager import SubscriptionManager
    
    sub_manager = SubscriptionManager()
    all_users = sub_manager.get_all_users()
    premium_users = sub_manager.get_premium_users()
    
    # Get database stats
    try:
        from src.database.connection import get_db_context
        from sqlalchemy import select, func
        from src.database.models import Customer
        
        async with get_db_context() as session:
            total_customers = await session.scalar(select(func.count(Customer.id)))
    except Exception:
        total_customers = 0
    
    return {
        "bot_users": {
            "total": len(all_users),
            "premium": len(premium_users),
            "free": len(all_users) - len(premium_users)
        },
        "database_customers": total_customers,
        "tier_distribution": {
            "free": len(all_users) - len(premium_users),
            "premium": len(premium_users)
        }
    }


@app.get("/api/admin/users")
async def admin_list_users(
    request: Request,
    limit: int = 50,
    offset: int = 0
):
    """List all users with their subscription status."""
    from config.settings import get_settings
    
    # Verify admin token
    settings = get_settings()
    auth_header = request.headers.get("Authorization", "")
    expected_token = f"Bearer {settings.admin_dashboard_token}"
    
    if auth_header != expected_token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from subscription_manager import SubscriptionManager
    
    sub_manager = SubscriptionManager()
    
    with sqlite3.connect(sub_manager.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT user_id, tier, daily_transcriptions, total_transcriptions, 
                   tier_expiration, created_at
            FROM users
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        ''', (limit, offset))
        
        rows = cursor.fetchall()
        
        cursor.execute('SELECT COUNT(*) FROM users')
        total = cursor.fetchone()[0]
    
    users = [
        {
            "user_id": row[0],
            "tier": row[1],
            "daily_transcriptions": row[2],
            "total_transcriptions": row[3],
            "tier_expiration": row[4],
            "created_at": row[5]
        }
        for row in rows
    ]
    
    return {
        "users": users,
        "total": total,
        "limit": limit,
        "offset": offset
    }


@app.get("/api/sales/{customer_id}/summary")
async def get_customer_sales_summary(customer_id: str):
    """Get sales summary for a customer."""
    from src.services.sales import get_sales_service
    
    try:
        sales_service = get_sales_service()
        result = await sales_service.get_customer_sales_summary(customer_id)
        
        if not result.get("success"):
            raise HTTPException(status_code=404, detail="Customer not found")
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting customer summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Error handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler."""
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)}
    )


def configure_logging():
    """Configure application logging."""
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level=settings.log_level
    )
    logger.add(
        "logs/vocalizebot_{time}.log",
        rotation="1 day",
        retention="7 days",
        level="INFO"
    )


if __name__ == "__main__":
    import uvicorn
    
    configure_logging()
    
    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower()
    )
