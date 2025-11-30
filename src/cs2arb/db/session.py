"""
Database session management for CS2 Arbitrage Bot.

Provides SQLAlchemy engine and session factory.
"""

from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import get_config

# Global engine instance
_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def init_engine(database_url: Optional[str] = None) -> Engine:
    """
    Initialize the SQLAlchemy engine.
    
    Args:
        database_url: Optional database URL override.
        
    Returns:
        The SQLAlchemy engine.
    """
    global _engine, _SessionLocal
    
    if database_url is None:
        config = get_config()
        database_url = config.database_url
    
    _engine = create_engine(
        database_url,
        echo=False,  # Set to True for SQL debugging
        connect_args={"check_same_thread": False},  # SQLite specific
    )
    
    _SessionLocal = sessionmaker(
        bind=_engine,
        autocommit=False,
        autoflush=False,
    )
    
    return _engine


def get_engine() -> Engine:
    """
    Get the global engine instance, initializing if needed.
    
    Returns:
        The SQLAlchemy engine.
    """
    global _engine
    if _engine is None:
        init_engine()
    return _engine


def get_session_factory() -> sessionmaker:
    """
    Get the session factory, initializing if needed.
    
    Returns:
        The sessionmaker instance.
    """
    global _SessionLocal
    if _SessionLocal is None:
        init_engine()
    return _SessionLocal


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Context manager for database sessions.
    
    Provides a session that is automatically committed on success
    or rolled back on exception.
    
    Usage:
        with get_session() as session:
            session.add(some_object)
            # Session is committed automatically
            
    Yields:
        A SQLAlchemy session.
    """
    session_factory = get_session_factory()
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_session() -> Session:
    """
    Create a new session (caller is responsible for closing).
    
    Returns:
        A new SQLAlchemy session.
    """
    session_factory = get_session_factory()
    return session_factory()

