"""
VocalizeBot - Payment Service (PayPal Integration)
Open Hands Agent | Tal HaTil Empire
"""
import hashlib
import base64
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from loguru import logger
import httpx

from config.settings import get_settings
from src.database.connection import get_db_context
from src.database.models import PaymentLink as PaymentLinkModel, Customer

settings = get_settings()


class PaymentService:
    """Service for handling payment operations with PayPal."""

    def __init__(self):
        self.paypal_mode = settings.paypal_mode
        self._access_token = None
        self._token_expires = None
        
        if settings.paypal_client_id and settings.paypal_client_secret:
            self.paypal_base_url = "https://api-m.sandbox.paypal.com" if self.paypal_mode == "sandbox" else "https://api-m.paypal.com"
        else:
            logger.warning("PayPal credentials not configured")
            self.paypal_base_url = None

    async def _get_access_token(self) -> Optional[str]:
        """Get PayPal access token."""
        if not settings.paypal_client_id or not settings.paypal_client_secret:
            return None
        
        if self._access_token and self._token_expires and datetime.utcnow() < self._token_expires:
            return self._access_token
        
        try:
            auth = base64.b64encode(
                f"{settings.paypal_client_id}:{settings.paypal_client_secret}".encode()
            ).decode()
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.paypal_base_url}/v1/oauth2/token",
                    headers={"Authorization": f"Basic {auth}"},
                    data={"grant_type": "client_credentials"},
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    self._access_token = data.get("access_token")
                    expires_in = data.get("expires_in", 3600)
                    self._token_expires = datetime.utcnow() + timedelta(seconds=expires_in - 60)
                    return self._access_token
                    
        except Exception as e:
            logger.error(f"Error getting PayPal access token: {e}")
        
        return None

    async def create_payment_link(
        self,
        customer_id: str,
        amount: float,
        currency: str,
        description: str,
        expires_in_hours: int = 24
    ) -> Dict[str, Any]:
        """Create a PayPal payment link for a customer."""
        if not settings.paypal_client_id:
            # Fallback to simple PayPal.me link
            return {
                "success": True,
                "payment_url": f"https://paypal.me/talhatil/{int(amount)}",
                "fallback": True,
                "message": "PayPal link generated"
            }

        try:
            access_token = await self._get_access_token()
            if not access_token:
                return {"success": False, "error": "Failed to authenticate with PayPal"}

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.paypal_base_url}/v2/checkout/orders",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "intent": "CAPTURE",
                        "purchase_units": [{
                            "amount": {
                                "currency_code": currency.upper(),
                                "value": str(amount)
                            },
                            "description": description,
                            "custom_id": customer_id
                        }]
                    },
                    timeout=30.0
                )
                
                if response.status_code in [200, 201]:
                    data = response.json()
                    approval_url = next(
                        (link.get("href") for link in data.get("links", []) 
                         if link.get("rel") == "approve"),
                        None
                    )
                    
                    order_id = data.get("id")
                    expires_at = datetime.utcnow() + timedelta(hours=expires_in_hours)
                    
                    async with get_db_context() as session:
                        db_payment = PaymentLinkModel(
                            id=f"pay_{hashlib.md5(order_id.encode()).hexdigest()[:12]}",
                            customer_id=customer_id,
                            amount=amount,
                            currency=currency.upper(),
                            description=description,
                            stripe_payment_intent_id=order_id,
                            payment_link_url=approval_url,
                            status="pending",
                            expires_at=expires_at
                        )
                        session.add(db_payment)
                        await session.commit()
                    
                    logger.info(f"PayPal payment link created: {approval_url}")
                    
                    return {
                        "success": True,
                        "payment_link_id": db_payment.id,
                        "payment_url": approval_url,
                        "order_id": order_id,
                        "expires_at": expires_at.isoformat()
                    }
                else:
                    logger.error(f"PayPal error: {response.text}")
                    return {"success": False, "error": response.text}
                    
        except Exception as e:
            logger.error(f"Error creating PayPal payment: {e}")
            return {"success": False, "error": str(e)}

    async def create_paypal_link(
        self,
        customer_id: str,
        amount: float,
        currency: str = "USD",
        description: str = "Payment"
    ) -> Dict[str, Any]:
        """Create a simple PayPal.me style link."""
        paypal_link = f"https://paypal.me/talhatil/{int(amount)}"
        
        async with get_db_context() as session:
            db_payment = PaymentLinkModel(
                id=f"pp_{hashlib.md5(str(datetime.utcnow().timestamp()).encode()).hexdigest()[:12]}",
                customer_id=customer_id,
                amount=amount,
                currency=currency.upper(),
                description=description,
                status="pending"
            )
            session.add(db_payment)
            await session.commit()
        
        return {
            "success": True,
            "payment_id": db_payment.id,
            "payment_url": paypal_link,
            "message": "קישור PayPal נוצר בהצלחה"
        }

    async def check_payment_status(self, payment_id: str) -> Dict[str, Any]:
        """Check the status of a payment."""
        async with get_db_context() as session:
            from sqlalchemy import select
            stmt = select(PaymentLinkModel).where(PaymentLinkModel.id == payment_id)
            result = await session.execute(stmt)
            payment = result.scalar_one_or_none()
            
            if not payment:
                return {"success": False, "error": "Payment not found"}
            
            return {
                "success": True,
                "payment_id": payment.id,
                "status": payment.status,
                "amount": payment.amount,
                "currency": payment.currency,
                "created_at": payment.created_at.isoformat() if payment.created_at else None,
                "paid_at": payment.paid_at.isoformat() if payment.paid_at else None
            }

    async def handle_payment_webhook(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle PayPal webhook events."""
        try:
            event_type = event_data.get("event_type")
            resource = event_data.get("resource", {})
            
            order_id = resource.get("id")
            
            async with get_db_context() as session:
                from sqlalchemy import select
                stmt = select(PaymentLinkModel).where(
                    PaymentLinkModel.stripe_payment_intent_id == order_id
                )
                result = await session.execute(stmt)
                payment = result.scalar_one_or_none()
                
                if not payment:
                    return {"success": False, "error": "Payment not found in database"}
                
                if event_type == "PAYMENT.CAPTURE.COMPLETED":
                    payment.status = "paid"
                    payment.paid_at = datetime.utcnow()
                    logger.info(f"Payment completed: {order_id}")
                elif event_type == "PAYMENT.CAPTURE.DENIED":
                    payment.status = "failed"
                    logger.warning(f"Payment denied: {order_id}")
                
                await session.commit()
                
                return {
                    "success": True,
                    "event_type": event_type,
                    "payment_id": payment.id,
                    "new_status": payment.status
                }
                
        except Exception as e:
            logger.error(f"Error handling payment webhook: {e}")
            return {"success": False, "error": str(e)}

    async def get_customer_payments(self, customer_id: str) -> List[Dict[str, Any]]:
        """Get all payments for a customer."""
        async with get_db_context() as session:
            from sqlalchemy import select
            stmt = select(PaymentLinkModel).where(
                PaymentLinkModel.customer_id == customer_id
            ).order_by(PaymentLinkModel.created_at.desc())
            result = await session.execute(stmt)
            payments = result.scalars().all()
            
            return [
                {
                    "id": p.id,
                    "amount": p.amount,
                    "currency": p.currency,
                    "description": p.description,
                    "status": p.status,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                    "paid_at": p.paid_at.isoformat() if p.paid_at else None
                }
                for p in payments
            ]

    async def cancel_payment_link(self, payment_id: str) -> Dict[str, Any]:
        """Cancel a pending payment link."""
        async with get_db_context() as session:
            from sqlalchemy import select
            stmt = select(PaymentLinkModel).where(PaymentLinkModel.id == payment_id)
            result = await session.execute(stmt)
            payment = result.scalar_one_or_none()
            
            if not payment:
                return {"success": False, "error": "Payment not found"}
            
            if payment.status != "pending":
                return {"success": False, "error": f"Cannot cancel payment with status: {payment.status}"}
            
            payment.status = "cancelled"
            await session.commit()
            
            return {
                "success": True,
                "payment_id": payment_id,
                "message": "התשלום בוטל"
            }


_payment_service: Optional[PaymentService] = None


def get_payment_service() -> PaymentService:
    """Get the singleton payment service instance."""
    global _payment_service
    if _payment_service is None:
        _payment_service = PaymentService()
    return _payment_service
