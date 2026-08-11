"""
VocalizeBot - Database Initialization Script
Creates all SQLAlchemy tables in vocalizebot.db
"""
import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.database.connection import init_db, close_db
from loguru import logger


async def main():
    """Initialize the primary database."""
    logger.info("Initializing VocalizeBot database...")
    
    try:
        await init_db()
        logger.info("✅ Database initialized successfully!")
        
        # Verify tables exist
        from sqlalchemy import inspect
        from src.database.connection import engine
        
        async with engine.connect() as conn:
            tables = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_table_names()
            )
            logger.info(f"Tables created: {', '.join(tables)}")
        
        logger.info(f"Database file: {os.path.abspath('vocalizebot.db')}")
        
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        sys.exit(1)
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
