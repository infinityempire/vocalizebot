"""
VocalizeBot Admin Dashboard - Backend Server
Open Hands Agent | Tal HaTil Empire
"""
import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Optional, List, Any
from collections import deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from loguru import logger
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.database.connection import get_db_context, init_db
from src.database.models import Customer, Message, PaymentLink, Interaction, Base
from src.agents.prompts import SYSTEM_PROMPT
from sqlalchemy import select, func

# Initialize database tables on startup
async def init_database():
    """Initialize the database tables."""
    from src.database.connection import engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialized")

# ============================================================================
# LIVE LOGS MANAGER
# ============================================================================

class LiveLogsManager:
    """Manages live logs broadcast to connected WebSocket clients."""
    
    def __init__(self, max_logs: int = 500):
        self.max_logs = max_logs
        self.logs: deque = deque(maxlen=max_logs)
        self.clients: List[WebSocket] = []
        self._lock = asyncio.Lock()
    
    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket client."""
        await websocket.accept()
        async with self._lock:
            self.clients.append(websocket)
        # Send recent logs to new client
        for log in list(self.logs):
            try:
                await websocket.send_json(log)
            except:
                pass
    
    async def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket client."""
        async with self._lock:
            if websocket in self.clients:
                self.clients.remove(websocket)
    
    async def broadcast(self, log_entry: dict):
        """Broadcast a log entry to all connected clients."""
        async with self._lock:
            self.clients_copy = list(self.clients)
        
        for client in self.clients_copy:
            try:
                await client.send_json(log_entry)
            except:
                async with self._lock:
                    if client in self.clients:
                        self.clients.remove(client)
    
    def add_log(self, level: str, message: str, category: str = "general", metadata: dict = None):
        """Add a log entry to the queue."""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "category": category,
            "message": message,
            "metadata": metadata or {}
        }
        self.logs.append(entry)
        # Schedule broadcast
        asyncio.create_task(self.broadcast(entry))
        return entry

logs_manager = LiveLogsManager()


# ============================================================================
# DATA MODELS
# ============================================================================

class SystemPromptUpdate(BaseModel):
    prompt: str

class UserStats(BaseModel):
    user_id: str
    telegram_id: Optional[str] = None
    telegram_username: Optional[str] = None
    name: Optional[str] = None
    joined_at: Optional[str] = None
    transcription_count: int = 0
    message_count: int = 0
    total_spent: float = 0.0
    is_premium: bool = False

class RevenueStats(BaseModel):
    total_revenue: float
    paid_users: int
    pending_payments: float
    recent_payments: List[dict]
    revenue_by_day: List[dict]

class DashboardStats(BaseModel):
    total_users: int
    active_users_today: int
    total_transcriptions: int
    total_messages: int
    total_revenue: float
    premium_users: int


# ============================================================================
# APP SETUP
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Starting Vocalize Admin Dashboard Server...")
    # Initialize database tables
    await init_database()
    logs_manager.add_log("info", "Dashboard server started", "system")
    yield
    logger.info("Shutting down Vocalize Admin Dashboard Server...")

app = FastAPI(
    title="Vocalize Admin Dashboard",
    description="Admin Dashboard for VocalizeBot - User Management, Revenue Tracking, and AI Configuration",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# WEBSOCKET FOR LIVE LOGS
# ============================================================================

@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    """WebSocket endpoint for live logs streaming."""
    await logs_manager.connect(websocket)
    logs_manager.add_log("info", "Client connected to live logs", "system")
    try:
        while True:
            # Keep connection alive, receive any client messages
            data = await websocket.receive_text()
            # Echo back for ping/pong
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        logs_manager.add_log("info", "Client disconnected from live logs", "system")
        await logs_manager.disconnect(websocket)


# ============================================================================
# AUTHENTICATION (Simple token-based)
# ============================================================================

ADMIN_TOKEN = os.environ.get("ADMIN_DASHBOARD_TOKEN", "vocalize-admin-secret-token")

def verify_token(request: Request) -> bool:
    """Verify admin token from request headers."""
    token = request.headers.get("X-Admin-Token")
    return token == ADMIN_TOKEN

@app.middleware
async def auth_middleware(request: Request, call_next):
    """Simple authentication middleware for admin routes."""
    if request.url.path.startswith("/api/") and request.url.path != "/api/login":
        if not verify_token(request):
            return JSONResponse(
                status_code=401,
                content={"error": "Unauthorized", "detail": "Invalid or missing admin token"}
            )
    return await call_next(request)


# ============================================================================
# AUTH ROUTES
# ============================================================================

@app.post("/api/login")
async def login(request: Request):
    """Admin login endpoint."""
    try:
        body = await request.json()
        token = body.get("token")
        
        if token == ADMIN_TOKEN:
            return {"success": True, "token": token, "message": "Login successful"}
        else:
            return {"success": False, "error": "Invalid token"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# DASHBOARD STATS
# ============================================================================

@app.get("/api/dashboard/stats", response_model=DashboardStats)
async def get_dashboard_stats():
    """Get overall dashboard statistics."""
    async with get_db_context() as session:
        # Total users
        total_users_result = await session.execute(select(func.count(Customer.id)))
        total_users = total_users_result.scalar() or 0
        
        # Active users today
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        active_users_result = await session.execute(
            select(func.count(func.distinct(Customer.id)))
            .where(Customer.last_interaction >= today_start)
        )
        active_users_today = active_users_result.scalar() or 0
        
        # Total messages
        total_messages_result = await session.execute(select(func.count(Message.id)))
        total_messages = total_messages_result.scalar() or 0
        
        # Total transcriptions (voice messages)
        total_transcriptions_result = await session.execute(
            select(func.count(Message.id)).where(Message.message_type == "voice")
        )
        total_transcriptions = total_transcriptions_result.scalar() or 0
        
        # Premium users (users with payments)
        premium_users_result = await session.execute(
            select(func.count(func.distinct(PaymentLink.customer_id)))
            .where(PaymentLink.status == "paid")
        )
        premium_users = premium_users_result.scalar() or 0
        
        # Total revenue
        total_revenue_result = await session.execute(
            select(func.sum(PaymentLink.amount)).where(PaymentLink.status == "paid")
        )
        total_revenue = total_revenue_result.scalar() or 0.0
        
        logs_manager.add_log("info", f"Dashboard stats retrieved: {total_users} users, ${total_revenue:.2f} revenue", "dashboard")
        
        return DashboardStats(
            total_users=total_users,
            active_users_today=active_users_today,
            total_transcriptions=total_transcriptions,
            total_messages=total_messages,
            total_revenue=float(total_revenue),
            premium_users=premium_users
        )


# ============================================================================
# USER MANAGEMENT
# ============================================================================

@app.get("/api/users")
async def get_users(
    limit: int = 50,
    offset: int = 0,
    search: str = None,
    sort_by: str = "created_at",
    order: str = "desc"
):
    """Get all users with pagination and search."""
    async with get_db_context() as session:
        query = select(Customer)
        
        if search:
            search_filter = f"%{search}%"
            query = query.where(
                (Customer.name.ilike(search_filter)) |
                (Customer.telegram_username.ilike(search_filter)) |
                (Customer.telegram_id.ilike(search_filter))
            )
        
        # Sorting
        if sort_by == "created_at":
            sort_column = Customer.created_at
        elif sort_by == "lead_score":
            sort_column = Customer.lead_score
        else:
            sort_column = Customer.created_at
        
        if order == "desc":
            query = query.order_by(sort_column.desc())
        else:
            query = query.order_by(sort_column.asc())
        
        query = query.limit(limit).offset(offset)
        result = await session.execute(query)
        customers = result.scalars().all()
        
        # Get counts for each customer
        users_data = []
        for customer in customers:
            # Get message count
            messages_count_result = await session.execute(
                select(func.count(Message.id)).where(Message.conversation_id.in_(
                    select(Customer.id)
                ))
            )
            message_count = messages_count_result.scalar() or 0
            
            # Get transcription count
            transcription_count_result = await session.execute(
                select(func.count(Message.id))
                .where(Message.message_type == "voice")
            )
            transcription_count = transcription_count_result.scalar() or 0
            
            # Get total spent
            total_spent_result = await session.execute(
                select(func.sum(PaymentLink.amount))
                .where(PaymentLink.customer_id == customer.id)
                .where(PaymentLink.status == "paid")
            )
            total_spent = total_spent_result.scalar() or 0.0
            
            # Check if premium
            is_premium = total_spent > 0
            
            users_data.append({
                "id": customer.id,
                "telegram_id": customer.telegram_id,
                "telegram_username": customer.telegram_username,
                "name": customer.name or "Unknown",
                "segment": customer.segment.value if customer.segment else "b2c",
                "lead_score": customer.lead_score,
                "lead_status": customer.lead_status.value if customer.lead_status else "new",
                "joined_at": customer.created_at.isoformat() if customer.created_at else None,
                "last_interaction": customer.last_interaction.isoformat() if customer.last_interaction else None,
                "message_count": message_count,
                "transcription_count": transcription_count,
                "total_spent": float(total_spent),
                "is_premium": is_premium
            })
        
        # Get total count
        count_query = select(func.count(Customer.id))
        if search:
            search_filter = f"%{search}%"
            count_query = count_query.where(
                (Customer.name.ilike(search_filter)) |
                (Customer.telegram_username.ilike(search_filter)) |
                (Customer.telegram_id.ilike(search_filter))
            )
        total_result = await session.execute(count_query)
        total = total_result.scalar() or 0
        
        logs_manager.add_log("info", f"Retrieved {len(users_data)} users (total: {total})", "users")
        
        return {"users": users_data, "total": total, "limit": limit, "offset": offset}


@app.get("/api/users/{user_id}")
async def get_user_details(user_id: str):
    """Get detailed information about a specific user."""
    async with get_db_context() as session:
        # Get customer
        customer_result = await session.execute(
            select(Customer).where(Customer.id == user_id)
        )
        customer = customer_result.scalar_one_or_none()
        
        if not customer:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Get messages
        messages_result = await session.execute(
            select(Message)
            .where(Message.conversation_id == customer.id)
            .order_by(Message.created_at.desc())
            .limit(50)
        )
        messages = messages_result.scalars().all()
        
        # Get payments
        payments_result = await session.execute(
            select(PaymentLink)
            .where(PaymentLink.customer_id == customer.id)
            .order_by(PaymentLink.created_at.desc())
        )
        payments = payments_result.scalars().all()
        
        logs_manager.add_log("info", f"Retrieved details for user {user_id}", "users")
        
        return {
            "customer": {
                "id": customer.id,
                "telegram_id": customer.telegram_id,
                "telegram_username": customer.telegram_username,
                "name": customer.name,
                "email": customer.email,
                "phone": customer.phone,
                "segment": customer.segment.value if customer.segment else "b2c",
                "lead_score": customer.lead_score,
                "lead_status": customer.lead_status.value if customer.lead_status else "new",
                "notes": customer.notes,
                "created_at": customer.created_at.isoformat() if customer.created_at else None,
                "last_interaction": customer.last_interaction.isoformat() if customer.last_interaction else None,
                "is_active": customer.is_active
            },
            "messages": [
                {
                    "id": m.id,
                    "content": m.content[:100] + "..." if len(m.content) > 100 else m.content,
                    "message_type": m.message_type.value if m.message_type else "text",
                    "direction": m.direction.value if m.direction else "inbound",
                    "transcription": m.transcription,
                    "ai_response": m.ai_response,
                    "created_at": m.created_at.isoformat() if m.created_at else None
                }
                for m in messages
            ],
            "payments": [
                {
                    "id": p.id,
                    "amount": float(p.amount),
                    "currency": p.currency,
                    "status": p.status,
                    "description": p.description,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                    "paid_at": p.paid_at.isoformat() if p.paid_at else None
                }
                for p in payments
            ]
        }


# ============================================================================
# REVENUE TRACKING
# ============================================================================

@app.get("/api/revenue", response_model=RevenueStats)
async def get_revenue_stats(days: int = 30):
    """Get revenue statistics for the specified period."""
    async with get_db_context() as session:
        # Total revenue
        total_result = await session.execute(
            select(func.sum(PaymentLink.amount)).where(PaymentLink.status == "paid")
        )
        total_revenue = total_result.scalar() or 0.0
        
        # Paid users count
        paid_users_result = await session.execute(
            select(func.count(func.distinct(PaymentLink.customer_id)))
            .where(PaymentLink.status == "paid")
        )
        paid_users = paid_users_result.scalar() or 0
        
        # Pending payments
        pending_result = await session.execute(
            select(func.sum(PaymentLink.amount)).where(PaymentLink.status == "pending")
        )
        pending_payments = pending_result.scalar() or 0.0
        
        # Recent payments
        recent_result = await session.execute(
            select(PaymentLink)
            .where(PaymentLink.status == "paid")
            .order_by(PaymentLink.paid_at.desc())
            .limit(10)
        )
        recent_payments = recent_result.scalars().all()
        
        # Revenue by day (last N days)
        start_date = datetime.utcnow() - timedelta(days=days)
        daily_revenue = {}
        for i in range(days):
            day = (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
            daily_revenue[day] = 0.0
        
        # Get payments for the period
        period_payments_result = await session.execute(
            select(PaymentLink)
            .where(PaymentLink.status == "paid")
            .where(PaymentLink.paid_at >= start_date)
        )
        period_payments = period_payments_result.scalars().all()
        
        for payment in period_payments:
            if payment.paid_at:
                day = payment.paid_at.strftime("%Y-%m-%d")
                if day in daily_revenue:
                    daily_revenue[day] += float(payment.amount)
        
        revenue_by_day = [
            {"date": date, "revenue": amount}
            for date, amount in sorted(daily_revenue.items())
        ]
        
        logs_manager.add_log("info", f"Revenue stats: ${total_revenue:.2f} total, {paid_users} paying users", "revenue")
        
        return RevenueStats(
            total_revenue=float(total_revenue),
            paid_users=paid_users,
            pending_payments=float(pending_payments),
            recent_payments=[
                {
                    "id": p.id,
                    "customer_id": p.customer_id,
                    "amount": float(p.amount),
                    "currency": p.currency,
                    "paid_at": p.paid_at.isoformat() if p.paid_at else None
                }
                for p in recent_payments
            ],
            revenue_by_day=revenue_by_day
        )


@app.get("/api/revenue/payments")
async def get_all_payments(
    status: str = None,
    limit: int = 50,
    offset: int = 0
):
    """Get all payments with optional status filter."""
    async with get_db_context() as session:
        query = select(PaymentLink).order_by(PaymentLink.created_at.desc())
        
        if status:
            query = query.where(PaymentLink.status == status)
        
        query = query.limit(limit).offset(offset)
        result = await session.execute(query)
        payments = result.scalars().all()
        
        # Get customer names
        payments_data = []
        for payment in payments:
            customer_result = await session.execute(
                select(Customer).where(Customer.id == payment.customer_id)
            )
            customer = customer_result.scalar_one_or_none()
            
            payments_data.append({
                "id": payment.id,
                "customer_id": payment.customer_id,
                "customer_name": customer.name if customer else "Unknown",
                "customer_telegram": customer.telegram_username if customer else None,
                "amount": float(payment.amount),
                "currency": payment.currency,
                "status": payment.status,
                "description": payment.description,
                "created_at": payment.created_at.isoformat() if payment.created_at else None,
                "paid_at": payment.paid_at.isoformat() if payment.paid_at else None
            })
        
        # Count
        count_query = select(func.count(PaymentLink.id))
        if status:
            count_query = count_query.where(PaymentLink.status == status)
        count_result = await session.execute(count_query)
        total = count_result.scalar() or 0
        
        return {"payments": payments_data, "total": total}


# ============================================================================
# AI ENGINE MANAGEMENT
# ============================================================================

@app.get("/api/ai/prompt")
async def get_system_prompt():
    """Get the current system prompt."""
    logs_manager.add_log("info", "System prompt retrieved", "ai")
    return {"prompt": SYSTEM_PROMPT}


@app.post("/api/ai/prompt")
async def update_system_prompt(request: Request):
    """Update the system prompt (in-memory only - needs restart to persist)."""
    try:
        body = await request.json()
        new_prompt = body.get("prompt")
        
        if not new_prompt:
            raise HTTPException(status_code=400, detail="Prompt is required")
        
        # Update the module-level variable
        import src.agents.prompts as prompts_module
        prompts_module.SYSTEM_PROMPT = new_prompt
        
        logs_manager.add_log("warning", "System prompt updated (in-memory)", "ai")
        
        return {
            "success": True,
            "message": "System prompt updated successfully. Note: Changes are in-memory and will be reset on restart.",
            "prompt": new_prompt
        }
    except Exception as e:
        logs_manager.add_log("error", f"Failed to update system prompt: {str(e)}", "ai")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ai/prompt/save")
async def save_system_prompt_to_file(request: Request):
    """Save the system prompt to a file for persistence."""
    try:
        body = await request.json()
        new_prompt = body.get("prompt")
        
        if not new_prompt:
            raise HTTPException(status_code=400, detail="Prompt is required")
        
        # Update the module variable
        import src.agents.prompts as prompts_module
        prompts_module.SYSTEM_PROMPT = new_prompt
        
        # Save to file
        prompts_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "src", "agents", "prompts.py"
        )
        
        # Read current file
        with open(prompts_file, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Find and replace SYSTEM_PROMPT value
        import re
        
        # Pattern to match the SYSTEM_PROMPT assignment
        pattern = r'(SYSTEM_PROMPT\s*=\s*""")[\s\S]*?"""'
        replacement = r'\1' + new_prompt + '\n"""'
        
        new_content = re.sub(pattern, replacement, content, count=1)
        
        # Write back
        with open(prompts_file, "w", encoding="utf-8") as f:
            f.write(new_content)
        
        logs_manager.add_log("success", "System prompt saved to file", "ai")
        
        return {
            "success": True,
            "message": "System prompt saved to file successfully",
            "prompt": new_prompt
        }
    except Exception as e:
        logs_manager.add_log("error", f"Failed to save system prompt: {str(e)}", "ai")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# LIVE LOGS API
# ============================================================================

@app.get("/api/logs")
async def get_logs(limit: int = 100, category: str = None, level: str = None):
    """Get recent logs (REST endpoint)."""
    logs = list(logs_manager.logs)
    
    if category:
        logs = [l for l in logs if l.get("category") == category]
    if level:
        logs = [l for l in logs if l.get("level") == level]
    
    return {"logs": logs[-limit:], "total": len(logs)}


# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "server": "Vocalize Admin Dashboard",
        "version": "1.0.0",
        "connected_clients": len(logs_manager.clients)
    }


# ============================================================================
# SERVE FRONTEND
# ============================================================================

@app.get("/")
async def root():
    """Serve the admin dashboard frontend."""
    frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
    if os.path.exists(frontend_path):
        with open(frontend_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Vocalize Admin Dashboard</h1><p>Frontend not found. Please build the frontend first.</p>")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8080,
        reload=True,
        log_level="info"
    )
