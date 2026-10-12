"""Database engine and session management."""
from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from config import settings
from logger import get_logger
from storage.models import Base

logger = get_logger("database")

# Create engine
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
    echo=False
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    bind=engine
)

def init_db() -> None:
    """Initialize database tables and apply lightweight additive migrations."""
    try:
        Base.metadata.create_all(bind=engine)
        _migrate_additive()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise


# Columns added after the initial schema: (table, column, DDL type)
_ADDITIVE_COLUMNS = [
    ("users", "password_hash", "VARCHAR(256)"),
    ("users", "role", "VARCHAR(32) DEFAULT 'user'"),
    ("users", "telegram_linked", "BOOLEAN DEFAULT 0"),
    ("servers", "description", "VARCHAR(256)"),
    ("servers", "auto_start", "BOOLEAN DEFAULT 0"),
]

def _migrate_additive() -> None:
    """Add missing columns to tables created by older schema versions.

    Preserves all existing data; never drops or rewrites columns. Larger schema
    changes use new tables, which create_all handles automatically.
    """
    inspector = __import__("sqlalchemy").inspect(engine)
    with engine.begin() as conn:
        for table, column, ddl in _ADDITIVE_COLUMNS:
            if not inspector.has_table(table):
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            if column not in existing:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
                logger.info(f"Migration: added column {table}.{column}")

@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Context manager for database sessions."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

# Auto-initialize database on startup
init_db()

