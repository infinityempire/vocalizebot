"""
ReplyQ AI Agent - Sales Coordination Service
"""
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from loguru import logger

from config.settings import get_settings
from src.agents.core import get_agent
from src.services.payment import get_payment_service
from src.database.connection import get_db_context
from src.database.models import Customer, LeadStatus, CustomerSegment, Interaction

settings = get_settings()


class SalesService:
    """Service for sales coordination and deal closing."""

    def __init__(self):
        self.payment_service = get_payment_service()

    async def process_sales_intent(
        self,
        customer_id: str,
        message: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process a potential sales opportunity.
        
        Args:
            customer_id: Customer ID
            message: Customer message
            context: Additional context
            
        Returns:
            Sales action and response
        """
        try:
            # Get customer data
            customer = await self._get_customer(customer_id)
            if not customer:
                return {"success": False, "error": "Customer not found"}

            # Analyze sales intent
            agent = get_agent()
            closing_result = await agent.get_closing_recommendation(
                interest_level=context.get("interest_level", "medium"),
                objections_addressed=context.get("objections_addressed", []),
                product_interest=message,
                segment=customer.segment.value
            )

            # Update lead status based on engagement
            new_status = self._determine_lead_status(customer, message)
            await self._update_lead_status(customer_id, new_status)

            # Log interaction
            await self._log_interaction(
                customer_id=customer_id,
                interaction_type="sales_engagement",
                description=f"Sales intent detected: {message[:100]}",
                metadata={"closing_technique": closing_result.get("technique")}
            )

            return {
                "success": True,
                "closing_recommendation": closing_result,
                "lead_status": new_status,
                "actions": self._determine_sales_actions(message, customer.segment.value)
            }

        except Exception as e:
            logger.error(f"Error processing sales intent: {e}")
            return {"success": False, "error": str(e)}

    async def create_sales_payment(
        self,
        customer_id: str,
        amount: float,
        currency: str,
        description: str
    ) -> Dict[str, Any]:
        """
        Create a payment link for a sale.
        
        Args:
            customer_id: Customer ID
            amount: Amount to charge
            currency: Currency code
            description: Sale description
            
        Returns:
            Payment link details
        """
        try:
            # Get customer
            customer = await self._get_customer(customer_id)
            if not customer:
                return {"success": False, "error": "Customer not found"}

            # Create payment link
            payment_result = await self.payment_service.create_payment_link(
                customer_id=customer_id,
                amount=amount,
                currency=currency,
                description=description
            )

            if payment_result.get("success"):
                # Update lead status to negotiation
                await self._update_lead_status(customer_id, LeadStatus.NEGOTIATION)

                # Log the sale
                await self._log_interaction(
                    customer_id=customer_id,
                    interaction_type="payment_sent",
                    description=f"Payment link sent: {amount} {currency} - {description}",
                    metadata={"payment_id": payment_result.get("payment_link_id")}
                )

            return payment_result

        except Exception as e:
            logger.error(f"Error creating sales payment: {e}")
            return {"success": False, "error": str(e)}

    async def close_deal(
        self,
        customer_id: str,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Mark a deal as closed/won.
        
        Args:
            customer_id: Customer ID
            notes: Optional closing notes
            
        Returns:
            Result of closing the deal
        """
        try:
            # Update lead status
            await self._update_lead_status(customer_id, LeadStatus.CLOSED_WON)

            # Log the closed deal
            await self._log_interaction(
                customer_id=customer_id,
                interaction_type="deal_closed",
                description=f"Deal closed successfully. {notes or ''}",
                metadata={"closed_at": datetime.utcnow().isoformat()}
            )

            # Update customer segment if they were a lead
            async with get_db_context() as session:
                from sqlalchemy import select
                stmt = select(Customer).where(Customer.id == customer_id)
                result = await session.execute(stmt)
                customer = result.scalar_one_or_none()
                if customer and customer.segment != CustomerSegment.EXISTING_CUSTOMER:
                    customer.segment = CustomerSegment.EXISTING_CUSTOMER
                    await session.commit()

            return {
                "success": True,
                "message": "Deal closed successfully! 🎉",
                "customer_id": customer_id
            }

        except Exception as e:
            logger.error(f"Error closing deal: {e}")
            return {"success": False, "error": str(e)}

    async def handle_objection(
        self,
        customer_id: str,
        objection: str
    ) -> Dict[str, Any]:
        """
        Handle a sales objection from a customer.
        
        Args:
            customer_id: Customer ID
            objection: The objection raised
            
        Returns:
            Response to the objection
        """
        try:
            customer = await self._get_customer(customer_id)
            if not customer:
                return {"success": False, "error": "Customer not found"}

            agent = get_agent()
            response = await agent.handle_objection(
                objection=objection,
                segment=customer.segment.value,
                product_info="Premium Subscription - Unlimited Transcriptions"
            )

            # Log the objection
            await self._log_interaction(
                customer_id=customer_id,
                interaction_type="objection",
                description=f"Objection raised: {objection}",
                metadata={"response_given": response[:200] if len(response) > 200 else response}
            )

            return {
                "success": True,
                "response": response,
                "objection": objection
            }

        except Exception as e:
            logger.error(f"Error handling objection: {e}")
            return {"success": False, "error": str(e)}

    async def get_sales_pipeline(
        self,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get sales pipeline with customers at different stages.
        
        Args:
            filters: Optional filters (segment, status, etc.)
            
        Returns:
            List of customers in the pipeline
        """
        try:
            async with get_db_context() as session:
                from sqlalchemy import select
                
                query = select(Customer).where(Customer.lead_score > 0)
                
                if filters:
                    if filters.get("segment"):
                        query = query.where(Customer.segment == filters["segment"])
                    if filters.get("status"):
                        query = query.where(Customer.lead_status == filters["status"])
                    if filters.get("min_score"):
                        query = query.where(Customer.lead_score >= filters["min_score"])
                
                query = query.order_by(Customer.lead_score.desc())
                result = await session.execute(query)
                customers = result.scalars().all()
                
                return [
                    {
                        "id": c.id,
                        "name": c.name or c.phone or c.instagram_handle,
                        "segment": c.segment.value,
                        "lead_score": c.lead_score,
                        "lead_status": c.lead_status.value,
                        "last_interaction": c.last_interaction.isoformat() if c.last_interaction else None
                    }
                    for c in customers
                ]

        except Exception as e:
            logger.error(f"Error getting sales pipeline: {e}")
            return []

    async def get_customer_sales_summary(
        self,
        customer_id: str
    ) -> Dict[str, Any]:
        """Get a summary of sales activity for a customer."""
        try:
            async with get_db_context() as session:
                from sqlalchemy import select
                
                # Get customer
                stmt = select(Customer).where(Customer.id == customer_id)
                result = await session.execute(stmt)
                customer = result.scalar_one_or_none()
                
                if not customer:
                    return {"success": False, "error": "Customer not found"}
                
                # Get interactions
                stmt = select(Interaction).where(
                    Interaction.customer_id == customer_id
                ).order_by(Interaction.created_at.desc()).limit(20)
                result = await session.execute(stmt)
                interactions = result.scalars().all()
                
                # Get payments
                payments = await self.payment_service.get_customer_payments(customer_id)
                
                return {
                    "success": True,
                    "customer": {
                        "id": customer.id,
                        "name": customer.name,
                        "segment": customer.segment.value,
                        "lead_score": customer.lead_score,
                        "lead_status": customer.lead_status.value,
                        "created_at": customer.created_at.isoformat() if customer.created_at else None
                    },
                    "interactions": [
                        {
                            "type": i.interaction_type,
                            "description": i.description,
                            "created_at": i.created_at.isoformat() if i.created_at else None
                        }
                        for i in interactions
                    ],
                    "payments": payments,
                    "total_paid": sum(p["amount"] for p in payments if p["status"] == "paid")
                }

        except Exception as e:
            logger.error(f"Error getting customer sales summary: {e}")
            return {"success": False, "error": str(e)}

    # Helper methods
    async def _get_customer(self, customer_id: str) -> Optional[Customer]:
        """Get customer by ID."""
        async with get_db_context() as session:
            from sqlalchemy import select
            stmt = select(Customer).where(Customer.id == customer_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def _update_lead_status(self, customer_id: str, status: LeadStatus):
        """Update customer lead status."""
        async with get_db_context() as session:
            from sqlalchemy import select
            stmt = select(Customer).where(Customer.id == customer_id)
            result = await session.execute(stmt)
            customer = result.scalar_one_or_none()
            if customer:
                customer.lead_status = status
                customer.updated_at = datetime.utcnow()
                await session.commit()

    async def _log_interaction(
        self,
        customer_id: str,
        interaction_type: str,
        description: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Log a customer interaction."""
        import json
        async with get_db_context() as session:
            interaction = Interaction(
                id=f"int_{datetime.utcnow().timestamp()}",
                customer_id=customer_id,
                interaction_type=interaction_type,
                description=description,
                metadata=json.dumps(metadata) if metadata else None
            )
            session.add(interaction)
            await session.commit()

    def _determine_lead_status(self, customer: Customer, message: str) -> LeadStatus:
        """Determine lead status based on conversation."""
        message_lower = message.lower()
        
        # Check for purchase intent keywords
        purchase_keywords = ["buy", "comprar", "want", "quero", "interested", "interessado", "price", "preço"]
        if any(kw in message_lower for kw in purchase_keywords):
            if customer.lead_status == LeadStatus.NEW:
                return LeadStatus.CONTACTED
            elif customer.lead_status in [LeadStatus.CONTACTED, LeadStatus.INTERESTED]:
                return LeadStatus.INTERESTED
        
        # Check for proposal/negotiation keywords
        negotiation_keywords = ["proposal", "proposta", "discuss", "discussão", "details", "detalhes"]
        if any(kw in message_lower for kw in negotiation_keywords):
            return LeadStatus.PROPOSAL
        
        return customer.lead_status

    def _determine_sales_actions(self, message: str, segment: str) -> List[Dict[str, str]]:
        """Determine sales actions based on message content."""
        actions = []
        message_lower = message.lower()
        
        # Check for price inquiries
        if any(kw in message_lower for kw in ["price", "preço", "cost", "custo", "quanto"]):
            actions.append({"type": "provide_quote", "priority": "high"})
        
        # Check for product questions
        if any(kw in message_lower for kw in ["features", "características", "specs", "info"]):
            actions.append({"type": "send_product_info", "priority": "medium"})
        
        # Check for demo requests
        if any(kw in message_lower for kw in ["demo", "trial", "test", "experimentar"]):
            actions.append({"type": "schedule_demo", "priority": "high"})
        
        return actions


# Singleton instance
_sales_service: Optional[SalesService] = None


def get_sales_service() -> SalesService:
    """Get the singleton sales service instance."""
    global _sales_service
    if _sales_service is None:
        _sales_service = SalesService()
    return _sales_service
