"""
VocalizeBot - Payment Service (PayPal Integration)
Open Hands Agent | Tal HaTil Empire
"""
import hashlib
import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from loguru import logger
import httpx

from config.settings import get_settings
from src.database.connection import get_db_context
from src.database.models import (
    PaymentLink as PaymentLinkModel,
    Customer,
    CustomerSegment,
    Interaction,
)

settings = get_settings()


def _utcnow() -> datetime:
    """Timezone-aware UTC ``now()``.

    ``datetime.utcnow()`` was deprecated in Python 3.12 and removed in 3.13.
    It also returns a *naive* datetime which trips Pydantic v2 validators
    on tz-aware ``datetime`` columns. Centralising the call site here keeps
    every entry point in the service in lock-step with the new convention.
    """
    return datetime.now(timezone.utc)


# Operator's actual PayPal.me handle. Kept as a constant so the test suite
# and both fallback paths (``create_payment_link`` / ``create_paypal_link``)
# stay in sync. The historical default of ``paypal.me/talhatil/{int(amount)}``
# was wrong on two counts:
#   1. ``talhatil`` was an internal handle used nowhere else in the project
#      (``auto_renewal.py`` and ``lead_hunt.py`` both use ``talderie``).
#   2. ``int(amount)`` silently truncated fractional cents ($29.50 became
#      $29), so renewals and renewals-failures read different amounts.
DEFAULT_PAYPAL_ME_HANDLE = "talderie"


def _fallback_paypal_url(amount: float) -> str:
    """Build the human-facing PayPal.me URL used when no API creds are set.

    Rounds to two decimals so PayPal.me renders a sensible amount without
    integer drift. Note: Python's ``round`` uses banker's-rounding (half-to-
    even), so 0.5 → 0, 1.5 → 2 — this is exactly what PayPal.me expects but
    docs it here so a contributor doesn't "fix" it to /2.
    """
    amount_str = f"{round(float(amount), 2):.2f}"
    return f"https://www.paypal.me/{DEFAULT_PAYPAL_ME_HANDLE}/{amount_str}"


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

        if self._access_token and self._token_expires and _utcnow() < self._token_expires:
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
                    self._token_expires = _utcnow() + timedelta(seconds=expires_in - 60)
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
            # Fallback to the human-facing PayPal.me link. Both the handle
            # and the rounded-with-cents amount are kept consistent with
            # ``auto_renewal.py`` and ``lead_hunt.py`` (operator's actual
            # PayPal is www.paypal.me/talderie, not ``talhatil``).
            return {
                "success": True,
                "payment_url": _fallback_paypal_url(amount),
                "fallback": True,
                "message": "PayPal link generated",
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
                    expires_at = _utcnow() + timedelta(hours=expires_in_hours)

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
        paypal_link = _fallback_paypal_url(amount)

        async with get_db_context() as session:
            db_payment = PaymentLinkModel(
                id=f"pp_{hashlib.md5(str(_utcnow().timestamp()).encode()).hexdigest()[:12]}",
                customer_id=customer_id,
                amount=amount,
                currency=currency.upper(),
                description=description,
                payment_link_url=paypal_link,
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
                    payment.paid_at = _utcnow()
                    logger.info(f"Payment completed: {order_id}")

                    # ============================================================
                    # AUTO-PROVISION THE CLIENT ACCOUNT
                    # ------------------------------------------------------------
                    # On a successful payment notification the linked customer
                    # account is automatically initialized and created (or
                    # re-activated) in the database — no manual action required.
                    # ============================================================
                    if not payment.customer_id:
                        logger.warning(
                            f"Payment {payment.id} has no customer_id — "
                            "skipping account provisioning"
                        )
                    else:
                        cust_stmt = select(Customer).where(
                            Customer.id == payment.customer_id
                        )
                        cust_result = await session.execute(cust_stmt)
                        customer = cust_result.scalar_one_or_none()

                        if customer is None:
                            customer = Customer(
                                id=payment.customer_id,
                                segment=CustomerSegment.EXISTING_CUSTOMER,
                                lead_score=settings.initial_lead_score,
                                is_active=True,
                            )
                            session.add(customer)
                            logger.info(
                                f"Payment webhook: auto-created client account "
                                f"{customer.id} from successful payment {order_id}"
                            )
                        else:
                            customer.is_active = True
                            customer.segment = CustomerSegment.EXISTING_CUSTOMER
                            logger.info(
                                f"Payment webhook: re-activated client account "
                                f"{customer.id} from successful payment {order_id}"
                            )

                        # Record the payment interaction on the account.
                        # The id is derived from the payment id so webhook
                        # retries (at-least-once delivery) don't create
                        # duplicate interactions or collide on the PK.
                        interaction = Interaction(
                            id=f"int_{payment.id}",
                            customer_id=payment.customer_id,
                            interaction_type="payment",
                            description=(
                                f"Payment completed: {payment.amount} "
                                f"{payment.currency}"
                            ),
                            interaction_metadata=json.dumps({
                                "payment_id": payment.id,
                                "order_id": order_id,
                            }),
                        )
                        await session.merge(interaction)
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
