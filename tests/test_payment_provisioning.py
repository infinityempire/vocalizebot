"""
VocalizeBot - Payment Webhook Auto-Provisioning Tests
=======================================================

Regression suite for the "payment -> account auto-creation" guarantee:

    On a successful payment notification (``PAYMENT.CAPTURE.COMPLETED``)
    the linked client account is automatically initialized and created
    (or re-activated) in the database, without requiring manual action.

These tests run the real ``handle_payment_webhook`` flow against an
isolated on-disk SQLite database so they exercise the actual SQLAlchemy
round-trips (no mocks of the DB layer).
"""
import os
import asyncio
import tempfile
from contextlib import asynccontextmanager
from unittest.mock import patch

# Force a minimal, deterministic env so the test doesn't accidentally pull
# any real Pydantic ``Settings`` defaults that need an async DB session.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_ENABLED", "false")
os.environ.setdefault("OPENAI_API_KEY", "test-key-for-import-only")


def _make_db_context(engine):
    """Return an ``asynccontextmanager`` bound to the given engine."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def ctx():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    return ctx


class TestPaymentAutoProvisioning:
    """PAYMENT.CAPTURE.COMPLETED must create/activate the client account."""

    async def _run_webhook(self, event_data, engine):
        import src.services.payment as payment_module

        ctx = _make_db_context(engine)
        # Await INSIDE the patch scope — returning an unawaited coroutine here
        # would exit the ``with`` block before the webhook executes, causing it
        # to fall back to the module-level DB engine.
        with patch.object(payment_module, "get_db_context", ctx):
            return await payment_module.get_payment_service().handle_payment_webhook(
                event_data
            )

    def test_payment_completed_creates_new_customer_account(self):
        import src.services.payment as payment_module
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import create_async_engine

        from src.database.models import Base, Customer, PaymentLink as PaymentLinkModel

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}")

        async def scenario():
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            # Seed a payment link for a customer that does NOT exist yet.
            ctx = _make_db_context(engine)
            async with ctx() as session:
                session.add(
                    PaymentLinkModel(
                        id="pay_prov_new",
                        customer_id="cust_new_prov",
                        amount=29.0,
                        currency="USD",
                        description="Premium subscription",
                        stripe_payment_intent_id="ORDER_PROV_NEW",
                        payment_link_url="https://www.paypal.me/talderie/29.00",
                        status="pending",
                    )
                )

            result = await self._run_webhook(
                {
                    "event_type": "PAYMENT.CAPTURE.COMPLETED",
                    "resource": {"id": "ORDER_PROV_NEW"},
                },
                engine,
            )

            assert result["success"] is True
            assert result["new_status"] == "paid"

            # The client account must have been auto-created and active.
            async with ctx() as session:
                cust = (
                    await session.execute(
                        select(Customer).where(Customer.id == "cust_new_prov")
                    )
                ).scalar_one_or_none()
                assert cust is not None, "customer account was not auto-created"
                assert cust.is_active is True
                assert cust.segment.value == "existing_customer"

                # A payment interaction must be logged on the account.
                from src.database.models import Interaction

                interactions = (
                    await session.execute(
                        select(Interaction).where(
                            Interaction.customer_id == "cust_new_prov"
                        )
                    )
                ).scalars().all()
                assert len(interactions) >= 1

        asyncio.run(scenario())
        asyncio.run(engine.dispose())
        os.unlink(tmp.name)

    def test_payment_completed_reactivates_existing_customer(self):
        import src.services.payment as payment_module
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import create_async_engine

        from src.database.models import (
            Base,
            Customer,
            CustomerSegment,
            PaymentLink as PaymentLinkModel,
        )

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}")

        async def scenario():
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            ctx = _make_db_context(engine)
            async with ctx() as session:
                session.add(
                    Customer(
                        id="cust_existing",
                        phone="+972501234567",
                        segment=CustomerSegment.B2C,
                        is_active=False,  # previously deactivated
                    )
                )
                session.add(
                    PaymentLinkModel(
                        id="pay_prov_exist",
                        customer_id="cust_existing",
                        amount=99.0,
                        currency="USD",
                        description="VIP plan",
                        stripe_payment_intent_id="ORDER_PROV_EXIST",
                        payment_link_url="https://www.paypal.me/talderie/99.00",
                        status="pending",
                    )
                )

            result = await self._run_webhook(
                {
                    "event_type": "PAYMENT.CAPTURE.COMPLETED",
                    "resource": {"id": "ORDER_PROV_EXIST"},
                },
                engine,
            )

            assert result["success"] is True

            async with ctx() as session:
                cust = (
                    await session.execute(
                        select(Customer).where(Customer.id == "cust_existing")
                    )
                ).scalar_one()
                assert cust.is_active is True
                assert cust.segment.value == "existing_customer"

        asyncio.run(scenario())
        asyncio.run(engine.dispose())
        os.unlink(tmp.name)

    def test_webhook_retry_does_not_duplicate_interactions(self):
        """PayPal webhooks are at-least-once delivery; a retry of the same
        COMPLETED event must not create a second interaction row."""
        import src.services.payment as payment_module
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import create_async_engine

        from src.database.models import (
            Base,
            Customer,
            Interaction,
            PaymentLink as PaymentLinkModel,
        )

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}")

        async def scenario():
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            ctx = _make_db_context(engine)
            async with ctx() as session:
                session.add(
                    PaymentLinkModel(
                        id="pay_prov_retry",
                        customer_id="cust_retry",
                        amount=29.0,
                        currency="USD",
                        description="Premium subscription",
                        stripe_payment_intent_id="ORDER_PROV_RETRY",
                        payment_link_url="https://www.paypal.me/talderie/29.00",
                        status="pending",
                    )
                )

            event = {
                "event_type": "PAYMENT.CAPTURE.COMPLETED",
                "resource": {"id": "ORDER_PROV_RETRY"},
            }

            # First delivery + one simulated retry
            r1 = await self._run_webhook(event, engine)
            r2 = await self._run_webhook(event, engine)
            assert r1["success"] is True
            assert r2["success"] is True

            async with ctx() as session:
                interactions = (
                    await session.execute(
                        select(Interaction).where(
                            Interaction.customer_id == "cust_retry"
                        )
                    )
                ).scalars().all()
                # Exactly one interaction, not two
                assert len(interactions) == 1, (
                    f"webhook retry created {len(interactions)} interactions"
                )

        asyncio.run(scenario())
        asyncio.run(engine.dispose())
        os.unlink(tmp.name)

    def test_denied_payment_does_not_create_account(self):
        import src.services.payment as payment_module
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import create_async_engine

        from src.database.models import (
            Base,
            Customer,
            PaymentLink as PaymentLinkModel,
        )

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}")

        async def scenario():
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            ctx = _make_db_context(engine)
            async with ctx() as session:
                session.add(
                    PaymentLinkModel(
                        id="pay_prov_denied",
                        customer_id="cust_denied",
                        amount=29.0,
                        currency="USD",
                        description="Premium subscription",
                        stripe_payment_intent_id="ORDER_PROV_DENIED",
                        payment_link_url="https://www.paypal.me/talderie/29.00",
                        status="pending",
                    )
                )

            result = await self._run_webhook(
                {
                    "event_type": "PAYMENT.CAPTURE.DENIED",
                    "resource": {"id": "ORDER_PROV_DENIED"},
                },
                engine,
            )

            assert result["success"] is True
            assert result["new_status"] == "failed"

            async with ctx() as session:
                cust = (
                    await session.execute(
                        select(Customer).where(Customer.id == "cust_denied")
                    )
                ).scalar_one_or_none()
                assert cust is None, "denied payment must NOT create an account"

        asyncio.run(scenario())
        asyncio.run(engine.dispose())
        os.unlink(tmp.name)
