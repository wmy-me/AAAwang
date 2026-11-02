"""Database models and request-scoped connection helpers."""

from life_agent.db.base import Base
from life_agent.db.models import LoginSession, User
from life_agent.db.session import get_db, get_engine

__all__ = ["Base", "LoginSession", "User", "get_db", "get_engine"]
"""Reserved package for database access (not implemented yet)."""
