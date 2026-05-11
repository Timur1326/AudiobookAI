"""
SQLAlchemy database setup: engine, session factory, and declarative base.

Defaults to SQLite for local development; set DATABASE_URL in .env for PostgreSQL.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# Use DATABASE_URL from env if set, otherwise fall back to SQLite for local dev
SQLALCHEMY_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "sqlite:///./storage/audiobook.db"
)

connect_args = {"check_same_thread": False, "timeout": 30} if SQLALCHEMY_DATABASE_URL.startswith("sqlite") else {}

if SQLALCHEMY_DATABASE_URL.startswith("sqlite:///"):
    _db_path = SQLALCHEMY_DATABASE_URL[len("sqlite:///"):]
    os.makedirs(os.path.dirname(os.path.abspath(_db_path)), exist_ok=True)

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args=connect_args)

if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(conn, _):
        """Enable WAL mode for better concurrent read/write performance."""
        conn.execute("PRAGMA journal_mode=WAL")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency that yields a DB session and closes it when done."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()