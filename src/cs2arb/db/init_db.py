"""
Database initialization for CS2 Arbitrage Bot.

Creates the SQLite database and all tables.
"""

from pathlib import Path

from ..config import get_config
from ..logging_config import get_logger
from .models import Base
from .session import get_engine, init_engine

logger = get_logger(__name__)


def create_database() -> None:
    """
    Create the database file and all tables.
    
    Creates the data directory if it doesn't exist,
    then creates all SQLAlchemy model tables.
    """
    config = get_config()
    
    # Ensure the data directory exists
    db_path = config.database_file_path
    db_dir = db_path.parent
    
    if not db_dir.exists():
        logger.info(f"Creating database directory: {db_dir}")
        db_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize the engine
    engine = init_engine()
    
    # Create all tables
    logger.info(f"Creating database tables at: {db_path}")
    Base.metadata.create_all(bind=engine)
    
    logger.info("Database initialized successfully!")


def drop_all_tables() -> None:
    """
    Drop all tables in the database.
    
    WARNING: This will delete all data!
    """
    engine = get_engine()
    logger.warning("Dropping all database tables!")
    Base.metadata.drop_all(bind=engine)
    logger.info("All tables dropped.")


def reset_database() -> None:
    """
    Reset the database by dropping and recreating all tables.
    
    WARNING: This will delete all data!
    """
    logger.warning("Resetting database - all data will be lost!")
    drop_all_tables()
    create_database()


if __name__ == "__main__":
    # Allow running directly for testing
    from ..logging_config import setup_logging
    setup_logging()
    create_database()

