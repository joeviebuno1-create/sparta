"""
DATABASE.PY — NeonDB-safe SQLAlchemy engine
"""

import os
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DisconnectionError, OperationalError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set.")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_size=2,
    max_overflow=3,
    pool_timeout=30,
    connect_args={
        "sslmode": "require",
        "connect_timeout": 10,
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 3,
    },
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """
    FastAPI dependency — yields a DB session with automatic retry on NeonDB disconnect.
    """
    db = SessionLocal()
    try:
        # Wake NeonDB if sleeping
        db.execute(text("SELECT 1"))
        yield db
    except (DisconnectionError, OperationalError):
        db.rollback()
        db.close()
        # Retry with a fresh connection
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()
    finally:
        try:
            db.close()
        except Exception:
            pass