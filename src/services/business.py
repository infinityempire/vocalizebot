"""
VocalizeBot - Business Management Service
"""
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from loguru import logger

from config.settings import get_settings
from src.database.connection import get_db_context
from src.database.models import Customer, Interaction, LeadStatus, CustomerSegment

settings = get_settings()


class BusinessService:
    """Service for general business management operations."""

    async def log_operational_update(
        self,
        update_type: str,
        description: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Log an operational update.
        
        Args:
            update_type: Type of update (inventory, schedule, announcement, etc.)
            description: Description of the update
            metadata: Additional metadata
            
        Returns:
            Result of logging
        """
        try:
            import json
            
            async with get_db_context() as session:
                # Create a system interaction
                interaction = Interaction(
                    id=f"op_{datetime.utcnow().timestamp()}",
                    customer_id="system",  # System-level interaction
                    interaction_type=f"business_update_{update_type}",
                    description=description,
                    metadata=json.dumps(metadata) if metadata else None
                )
                session.add(interaction)
                await session.commit()
                
                logger.info(f"Operational update logged: {update_type} - {description}")
                
                return {
                    "success": True,
                    "interaction_id": interaction.id,
                    "timestamp": datetime.utcnow().isoformat()
                }
                
        except Exception as e:
            logger.error(f"Error logging operational update: {e}")
            return {"success": False, "error": str(e)}

    async def get_business_analytics(
        self,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Get business analytics summary.
        
        Args:
            days: Number of days to analyze
            
        Returns:
            Analytics summary
        """
        try:
            from sqlalchemy import select, func
            
            since_date = datetime.utcnow() - timedelta(days=days)
            
            async with get_db_context() as session:
                # Total customers
                total_customers_stmt = select(func.count(Customer.id))
                total_customers_result = await session.execute(total_customers_stmt)
                total_customers = total_customers_result.scalar() or 0
                
                # Active customers (interacted in last 7 days)
                week_ago = datetime.utcnow() - timedelta(days=7)
                active_customers_stmt = select(func.count(Customer.id)).where(
                    Customer.last_interaction >= week_ago
                )
                active_customers_result = await session.execute(active_customers_stmt)
                active_customers = active_customers_result.scalar() or 0
                
                # Customers by segment
                segment_counts = {}
                for segment in CustomerSegment:
                    count_stmt = select(func.count(Customer.id)).where(
                        Customer.segment == segment
                    )
                    count_result = await session.execute(count_stmt)
                    segment_counts[segment.value] = count_result.scalar() or 0
                
                # Leads by status
                status_counts = {}
                for status in LeadStatus:
                    count_stmt = select(func.count(Customer.id)).where(
                        Customer.lead_status == status
                    )
                    count_result = await session.execute(count_stmt)
                    status_counts[status.value] = count_result.scalar() or 0
                
                # Average lead score
                avg_score_stmt = select(func.avg(Customer.lead_score))
                avg_score_result = await session.execute(avg_score_stmt)
                avg_score = avg_score_result.scalar() or 0
                
                # New customers in period
                new_customers_stmt = select(func.count(Customer.id)).where(
                    Customer.created_at >= since_date
                )
                new_customers_result = await session.execute(new_customers_stmt)
                new_customers = new_customers_result.scalar() or 0
                
                return {
                    "success": True,
                    "period_days": days,
                    "summary": {
                        "total_customers": total_customers,
                        "active_customers_7d": active_customers,
                        "new_customers_period": new_customers,
                        "average_lead_score": round(float(avg_score), 1)
                    },
                    "segments": segment_counts,
                    "lead_statuses": status_counts,
                    "generated_at": datetime.utcnow().isoformat()
                }
                
        except Exception as e:
            logger.error(f"Error getting business analytics: {e}")
            return {"success": False, "error": str(e)}

    async def get_top_customers(
        self,
        limit: int = 10,
        by: str = "score"
    ) -> List[Dict[str, Any]]:
        """
        Get top customers by various metrics.
        
        Args:
            limit: Number of customers to return
            by: Metric to sort by ("score", "recent", "engagement")
            
        Returns:
            List of top customers
        """
        try:
            from sqlalchemy import select
            
            async with get_db_context() as session:
                query = select(Customer).where(Customer.is_active == True)
                
                if by == "score":
                    query = query.order_by(Customer.lead_score.desc())
                elif by == "recent":
                    query = query.order_by(Customer.last_interaction.desc().nullslast())
                elif by == "engagement":
                    # Engagement measured by lower blackout count and higher score
                    query = query.order_by(Customer.blackout_count.asc(), Customer.lead_score.desc())
                
                query = query.limit(limit)
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
            logger.error(f"Error getting top customers: {e}")
            return []

    async def get_customers_needing_followup(
        self,
        days_inactive: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Get customers who haven't interacted recently and need follow-up.
        
        Args:
            days_inactive: Days of inactivity threshold
            
        Returns:
            List of customers needing follow-up
        """
        try:
            from sqlalchemy import select
            
            cutoff_date = datetime.utcnow() - timedelta(days=days_inactive)
            
            async with get_db_context() as session:
                # Get active leads who haven't interacted recently
                query = select(Customer).where(
                    Customer.is_active == True,
                    Customer.last_interaction <= cutoff_date,
                    Customer.lead_status.in_([
                        LeadStatus.NEW,
                        LeadStatus.CONTACTED,
                        LeadStatus.INTERESTED,
                        LeadStatus.PROPOSAL,
                        LeadStatus.NEGOTIATION
                    ])
                ).order_by(Customer.last_interaction.asc())
                
                result = await session.execute(query)
                customers = result.scalars().all()
                
                return [
                    {
                        "id": c.id,
                        "name": c.name or c.phone or c.instagram_handle,
                        "segment": c.segment.value,
                        "lead_score": c.lead_score,
                        "lead_status": c.lead_status.value,
                        "last_interaction": c.last_interaction.isoformat() if c.last_interaction else None,
                        "days_inactive": (datetime.utcnow() - c.last_interaction).days if c.last_interaction else 999
                    }
                    for c in customers
                ]
                
        except Exception as e:
            logger.error(f"Error getting follow-up customers: {e}")
            return []

    async def bulk_update_segment(
        self,
        customer_ids: List[str],
        new_segment: CustomerSegment
    ) -> Dict[str, Any]:
        """
        Bulk update customer segments.
        
        Args:
            customer_ids: List of customer IDs
            new_segment: New segment to assign
            
        Returns:
            Result of bulk update
        """
        try:
            from sqlalchemy import select
            
            async with get_db_context() as session:
                stmt = select(Customer).where(Customer.id.in_(customer_ids))
                result = await session.execute(stmt)
                customers = result.scalars().all()
                
                updated_count = 0
                for customer in customers:
                    customer.segment = new_segment
                    updated_count += 1
                
                await session.commit()
                
                logger.info(f"Bulk updated {updated_count} customers to segment {new_segment.value}")
                
                return {
                    "success": True,
                    "updated_count": updated_count,
                    "segment": new_segment.value
                }
                
        except Exception as e:
            logger.error(f"Error in bulk segment update: {e}")
            return {"success": False, "error": str(e)}

    async def export_customer_data(
        self,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Export customer data for reporting.
        
        Args:
            filters: Optional filters for export
            
        Returns:
            List of customer records
        """
        try:
            from sqlalchemy import select
            
            async with get_db_context() as session:
                query = select(Customer)
                
                if filters:
                    if filters.get("segment"):
                        query = query.where(Customer.segment == filters["segment"])
                    if filters.get("status"):
                        query = query.where(Customer.lead_status == filters["status"])
                    if filters.get("min_score"):
                        query = query.where(Customer.lead_score >= filters["min_score"])
                
                result = await session.execute(query)
                customers = result.scalars().all()
                
                return [
                    {
                        "id": c.id,
                        "phone": c.phone,
                        "instagram_handle": c.instagram_handle,
                        "name": c.name,
                        "email": c.email,
                        "company": c.company,
                        "segment": c.segment.value,
                        "lead_score": c.lead_score,
                        "lead_status": c.lead_status.value,
                        "created_at": c.created_at.isoformat() if c.created_at else None,
                        "last_interaction": c.last_interaction.isoformat() if c.last_interaction else None
                    }
                    for c in customers
                ]
                
        except Exception as e:
            logger.error(f"Error exporting customer data: {e}")
            return []


# Singleton instance
_business_service: Optional[BusinessService] = None


def get_business_service() -> BusinessService:
    """Get the singleton business service instance."""
    global _business_service
    if _business_service is None:
        _business_service = BusinessService()
    return _business_service
