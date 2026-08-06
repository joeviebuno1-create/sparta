from fastapi import HTTPException, status, Request, Depends
import os
import secrets
from dotenv import load_dotenv
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db

load_dotenv()

ACCESS_TOKEN_EXPIRE_HOURS = int(os.getenv("ACCESS_TOKEN_EXPIRE_HOURS", 8))


def verify_session(request: Request, db: Session = Depends(get_db)):
    """
    Verify the signed session cookie AND check that its token still matches
    the current token stored in the database for that admin.

    Why this matters: the cookie alone being validly signed only proves it
    was genuinely issued by this server at some point — it does NOT prove
    it hasn't been logged out or copied elsewhere since. Logging out only
    clears the cookie on the browser that clicked it; a copy of the old
    cookie (grabbed via DevTools, a shared device, etc.) would otherwise
    keep working until its natural expiry. Comparing against a DB-stored
    token that logout actively rotates closes that gap — logout now
    invalidates every copy of the token immediately, everywhere.
    """
    username = request.session.get("username")
    token = request.session.get("token")
    if not username or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )

    # Check session expiry (client-claimed, cheap check before hitting DB)
    expires_at = request.session.get("expires_at")
    if expires_at and datetime.utcnow().isoformat() > expires_at:
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please log in again."
        )

    # Check the token against the database — this is what actually enforces
    # revocation on logout, independent of whatever copies of the cookie
    # might exist elsewhere.
    row = db.execute(
        text("SELECT session_token FROM admin_credentials WHERE username = :u"),
        {"u": username}
    ).fetchone()
    if not row or row[0] != token:
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has been revoked. Please log in again."
        )

    return username


def create_session(request: Request, username: str, db: Session):
    """
    Log in: issue a new random token, store it in both the signed cookie
    and the database, and set expiry. Overwrites any previous token for
    this admin — so logging in on a new device/browser also silently
    revokes any older session for the same account, which is a reasonable
    default for a single-admin panel.
    """
    token = secrets.token_hex(32)
    expires_at = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)

    request.session["username"] = username
    request.session["token"] = token
    request.session["expires_at"] = expires_at.isoformat()

    db.execute(
        text("UPDATE admin_credentials SET session_token = :t WHERE username = :u"),
        {"t": token, "u": username}
    )
    db.commit()


def clear_session(request: Request, db: Session):
    """
    Log out: clear the cookie AND rotate the DB-stored token so any other
    copy of the old token (a different tab, a device that stayed logged
    in, a copied cookie value) is invalidated immediately too — not just
    the browser that clicked Logout.
    """
    username = request.session.get("username")
    if username:
        db.execute(
            text("UPDATE admin_credentials SET session_token = :t WHERE username = :u"),
            {"t": secrets.token_hex(32), "u": username}  # rotate to a fresh, unguessable value
        )
        db.commit()
    request.session.clear()