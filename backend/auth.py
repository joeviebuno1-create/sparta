from fastapi import HTTPException, status, Request
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "fallback-secret-change-this")
ACCESS_TOKEN_EXPIRE_HOURS = int(os.getenv("ACCESS_TOKEN_EXPIRE_HOURS", 8))


def verify_session(request: Request):
    """
    Read username from Starlette session.
    Session is signed by itsdangerous (via SessionMiddleware) — tamper-proof.
    JavaScript cannot read it — stored in a signed HttpOnly cookie.
    """
    username = request.session.get("username")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )

    # Check session expiry
    expires_at = request.session.get("expires_at")
    if expires_at and datetime.utcnow().isoformat() > expires_at:
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired"
        )

    return username


def create_session(request: Request, username: str):
    """Store username and expiry in the signed session cookie"""
    expires_at = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    request.session["username"] = username
    request.session["expires_at"] = expires_at.isoformat()


def clear_session(request: Request):
    """Clear the session on logout"""
    request.session.clear()