"""
DATABASE.PY — NeonDB-safe SQLAlchemy engine
=============================================
NeonDB is a serverless Postgres provider. Connections go to sleep after
~5 minutes of inactivity and return NOT_FOUND errors on the stale socket.

Key settings that prevent this:
- pool_pre_ping=True       — tests each connection before use, discards dead ones
- pool_recycle=300         — recycles connections every 5 min (before NeonDB kills them)
- pool_size=2              — small pool — Railway free tier has limited RAM
- max_overflow=3           — allow brief spikes
- connect_args sslmode     — NeonDB requires SSL
"""

import os
from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set.")

# NeonDB connection URLs sometimes use postgres:// — SQLAlchemy needs postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    # ── NeonDB-critical settings ──────────────────────────────────────────────
    pool_pre_ping=True,        # ping before each use — drops dead connections
    pool_recycle=300,          # recycle every 5 min — NeonDB sleeps at ~5 min
    pool_size=2,               # keep small — Railway free tier RAM is limited
    max_overflow=3,            # allow 3 extra connections during spikes
    pool_timeout=30,           # wait max 30s for a connection
    # ── SSL required by NeonDB ────────────────────────────────────────────────
    connect_args={
        "sslmode": "require",
        "connect_timeout": 10,  # fail fast if NeonDB is waking up
    },
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency — yields a DB session and closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()