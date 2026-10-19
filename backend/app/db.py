"""SQLAlchemy 2.x database connection, session management, and base models."""

from __future__ import annotations

import os
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.config import settings


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy ORM models."""
    pass


def get_engine_args(db_url: str) -> dict:
    """Return appropriate engine arguments depending on DB dialect."""
    args = {}
    if db_url.startswith("sqlite"):
        args["connect_args"] = {"check_same_thread": False}
    else:
        # MySQL or other server DB
        args["pool_pre_ping"] = True
        args["pool_recycle"] = 3600
    return args


def create_db_engine(db_url: str | None = None):
    """Create a SQLAlchemy engine for the specified or configured URL."""
    url = db_url or os.environ.get("DATABASE_URL", settings.DATABASE_URL)
    return create_engine(url, **get_engine_args(url))


engine = create_db_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(target_engine=None) -> None:
    """Initialize database tables according to defined ORM models."""
    from backend.app import models  # noqa: F401 - ensure models are registered
    eng = target_engine or engine
    Base.metadata.create_all(bind=eng)
