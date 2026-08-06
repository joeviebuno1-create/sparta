import os
from dotenv import load_dotenv
load_dotenv()   # loads .env file into os.environ before anything else reads it
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, APIRouter, Request, status
from fastapi.responses import HTMLResponse, StreamingResponse, Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from collections import defaultdict
import time as time_module
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

# ── Cloudinary configuration ─────────────────────────────────────────────────
# Set these in your .env / Railway environment variables:
#   CLOUDINARY_CLOUD_NAME   your cloud name
#   CLOUDINARY_API_KEY      your API key
#   CLOUDINARY_API_SECRET   your API secret
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY    = os.getenv("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "")

def upload_to_cloudinary(raw_bytes: bytes, filename: str, folder: str = "sparta") -> str:
    """
    Upload image bytes to Cloudinary using signed upload.
    Returns the secure_url string, or raises HTTPException on failure.
    """
    import hashlib, time, requests as _req

    if not all([CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET]):
        raise HTTPException(
            status_code=500,
            detail="Cloudinary is not configured. Set CLOUDINARY_CLOUD_NAME, "
                   "CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET in your environment."
        )

    timestamp = int(time.time())
    # params to sign (alphabetical, no file/api_key)
    params_to_sign = f"folder={folder}&timestamp={timestamp}"
    sig = hashlib.sha1(
        f"{params_to_sign}{CLOUDINARY_API_SECRET}".encode("utf-8")
    ).hexdigest()

    upload_url = f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/image/upload"
    resp = _req.post(upload_url, data={
        "api_key":   CLOUDINARY_API_KEY,
        "timestamp": timestamp,
        "signature": sig,
        "folder":    folder,
    }, files={"file": (filename, raw_bytes)}, timeout=30)

    if resp.status_code != 200:
        detail = resp.json().get("error", {}).get("message", "Cloudinary upload failed")
        raise HTTPException(status_code=502, detail=f"Cloudinary: {detail}")

    return resp.json()["secure_url"]
from sqlalchemy import func, text
from pydantic import BaseModel
from typing import List, Optional, Tuple, TYPE_CHECKING
from datetime import datetime
import models
from database import engine, get_db
import io
import os
import bcrypt
import math
import json

# numpy still used elsewhere
import numpy as np

# Import RAG-based chatbot
from rag_chatbot import process_chat_with_rag

# Import FAQ PDF extractor
from pypdf import PdfReader
import io

# Import auth helpers
from auth import verify_session, create_session, clear_session

# ============================================
# SECURITY — Rate Limiter + Security Headers
# ============================================

class RateLimiter:
    """
    Enhanced in-memory rate limiter with:
    - Per-IP sliding window limiting
    - Session-based message flood detection
    - Suspicious pattern detection (repeated identical messages)
    - Automatic IP blocking for severe violators
    - Periodic cleanup to prevent memory growth
    """
    def __init__(self):
        self.requests      = defaultdict(list)   # ip -> [timestamps]
        self.blocked_until = {}                   # ip -> unblock_timestamp
        self.violations    = defaultdict(int)     # ip -> violation count
        self.last_cleanup  = time_module.time()
        self.session_msgs  = defaultdict(list)    # session_id -> [timestamps]
        self.session_hashes= defaultdict(list)    # session_id -> [msg_hashes]

    def _cleanup(self):
        """Remove stale data every 10 minutes to prevent memory growth."""
        now = time_module.time()
        if now - self.last_cleanup < 600:
            return
        cutoff = now - 3600
        for ip in list(self.requests.keys()):
            self.requests[ip] = [t for t in self.requests[ip] if t > cutoff]
            if not self.requests[ip]:
                del self.requests[ip]
        self.blocked_until = {ip: t for ip, t in self.blocked_until.items() if t > now}
        self.last_cleanup = now

    def is_blocked(self, ip: str) -> bool:
        unblock = self.blocked_until.get(ip, 0)
        return time_module.time() < unblock

    def block_ip(self, ip: str, duration_seconds: int = 900):
        """Temporarily block an IP (default 15 minutes)."""
        self.blocked_until[ip] = time_module.time() + duration_seconds
        print(f"[security] Blocked IP {ip} for {duration_seconds}s")

    def is_allowed(self, ip: str, max_requests: int, window_seconds: int) -> bool:
        self._cleanup()
        now = time_module.time()

        # Hard block check
        if self.is_blocked(ip):
            return False

        self.requests[ip] = [t for t in self.requests[ip] if now - t < window_seconds]
        if len(self.requests[ip]) >= max_requests:
            self.violations[ip] += 1
            # Auto-block after 3 consecutive rate limit violations
            if self.violations[ip] >= 3:
                self.block_ip(ip, duration_seconds=900)  # 15 min block
            return False

        self.requests[ip].append(now)
        # Reset violations on clean request
        if self.violations.get(ip, 0) > 0:
            self.violations[ip] = max(0, self.violations[ip] - 1)
        return True

    def is_chat_allowed(self, ip: str, session_id: str, message: str) -> tuple:
        """
        Multi-layer chat spam check. Returns (allowed: bool, reason: str).
        Checks:
          1. IP hard block
          2. Per-IP chat rate (15/min)
          3. Per-session burst rate (5 in 3 seconds)
          4. Repeated identical message spam (same message 5+ times)
        """
        now = time_module.time()
        self._cleanup()

        # 1. IP block check
        if self.is_blocked(ip):
            return False, "Your IP has been temporarily blocked due to abuse. Please try again later."

        # 2. Per-IP rate limit: 20 messages per minute
        self.requests[ip] = [t for t in self.requests[ip] if now - t < 60]
        if len(self.requests[ip]) >= 20:
            self.violations[ip] += 1
            if self.violations[ip] >= 3:
                self.block_ip(ip, 900)
                return False, "Too many requests. Your IP has been temporarily blocked."
            return False, "You are sending messages too fast. Please wait a moment."
        self.requests[ip].append(now)

        # 3. Per-session burst: max 5 messages in 3 seconds
        self.session_msgs[session_id] = [
            t for t in self.session_msgs[session_id] if now - t < 3
        ]
        if len(self.session_msgs[session_id]) >= 5:
            return False, "You are typing too fast. Please slow down."
        self.session_msgs[session_id].append(now)

        # 4. Identical message spam: same message sent 5+ times in 60s
        msg_hash = hash(message.strip().lower())
        self.session_hashes[session_id] = [
            (t, h) for t, h in self.session_hashes[session_id] if now - t < 60
        ]
        same_count = sum(1 for _, h in self.session_hashes[session_id] if h == msg_hash)
        if same_count >= 5:
            return False, "Please avoid sending the same message repeatedly."
        self.session_hashes[session_id].append((now, msg_hash))

        return True, ""

rate_limiter = RateLimiter()

class SecurityMiddleware:
    """
    Pure ASGI middleware — adds security headers and rate limiting.

    Replaces the old BaseHTTPMiddleware implementation which caused
    h11 LocalProtocolError ('Can't send data when our state is ERROR'
    / 'can't handle event type ConnectionClosed when role=SERVER and
    state=SEND_RESPONSE') whenever the client disconnected mid-stream
    or a streaming response was in flight.  A pure ASGI middleware
    intercepts the 'http.response.start' message directly and injects
    headers there, before any bytes are sent, so it is safe for all
    response types including StreamingResponse.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Build a lightweight Request-like view for path / method / client
        path   = scope.get("path", "")
        method = scope.get("method", "")
        client = scope.get("client")
        ip     = client[0] if client else "unknown"

        # ── Rate limiting ──────────────────────────────────────────────
        if path == "/api/chat":
            # Basic IP-level check at middleware — detailed session check in endpoint
            if rate_limiter.is_blocked(ip):
                await self._send_json(
                    send, 429,
                    {"detail": "Your IP has been temporarily blocked due to abuse. Please try again in 15 minutes.",
                     "blocked": True}
                )
                return

        if path == "/api/admin/login" and method == "POST":
            if not rate_limiter.is_allowed(f"login:{ip}", max_requests=10, window_seconds=300):
                await self._send_json(
                    send, 429,
                    {"detail": "Too many login attempts. Please wait 5 minutes."}
                )
                return

        if path.startswith("/api/") and path not in ("/api/chat",):
            if not rate_limiter.is_allowed(f"api:{ip}", max_requests=150, window_seconds=60):
                await self._send_json(
                    send, 429,
                    {"detail": "Too many requests. Please slow down."}
                )
                return

        # ── Security Headers injected into http.response.start ─────────
        is_production = os.getenv("IS_PRODUCTION", "false").lower() == "true"

        # The 3D model routes are large binary assets whose URL already
        # carries a cache-busting ?v= token (see /api/active-3d-model).
        # Blanket no-store on these means every single page load/reload
        # re-downloads the full file (60MB+) — expensive against Neon's
        # free-tier egress cap in particular. Safe to cache long-term here
        # since a new upload always produces a new URL.
        is_model_asset = path == "/api/3d-model-file" or path.startswith("/static/")

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                # Convert existing headers list → dict-like, append ours, convert back
                headers = list(message.get("headers", []))
                cache_header = (
                    b"public, max-age=604800, immutable" if is_model_asset
                    else b"no-store, no-cache, must-revalidate"
                )
                extra = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options",         b"SAMEORIGIN"),
                    (b"x-xss-protection",        b"1; mode=block"),
                    (b"referrer-policy",          b"strict-origin-when-cross-origin"),
                    (b"permissions-policy",       b"geolocation=(), microphone=(self), camera=()"),
                    (b"cache-control",            cache_header),
                ]
                if is_production:
                    extra.append(
                        (b"strict-transport-security", b"max-age=31536000; includeSubDomains")
                    )
                headers.extend(extra)
                message = {**message, "headers": headers}
            await send(message)

        # Run the inner app; if the client disconnects mid-response we
        # catch the resulting exceptions quietly so uvicorn stays clean.
        response_started = False

        async def send_tracking(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send_with_headers(message)

        try:
            await self.app(scope, receive, send_tracking)
        except Exception as exc:
            # If the inner app raised before sending any response,
            # send a clean 500 so ASGI doesn't crash with
            # "ASGI callable returned without starting response".
            import logging as _logging
            _logging.getLogger("uvicorn.error").exception("Unhandled error in request handler")
            if not response_started:
                try:
                    await self._send_json(send, 500, {"detail": "Internal server error"})
                except Exception:
                    pass  # client already disconnected — nothing we can do

    @staticmethod
    async def _send_json(send, status_code: int, body: dict):
        import json as _json
        content = _json.dumps(body).encode()
        await send({
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type",   b"application/json"),
                (b"content-length", str(len(content)).encode()),
            ],
        })
        await send({"type": "http.response.body", "body": content, "more_body": False})

# ============================================
# Create tables
models.Base.metadata.create_all(bind=engine)

# ── Auto-migrate: add new _tl columns if they don't exist yet ──────────────
def _run_migrations():
    """Safely add new columns to existing tables without data loss."""
    from sqlalchemy import text, inspect
    from database import engine as _engine
    inspector = inspect(_engine)
    with _engine.connect() as conn:
        # UserSession table
        try:
            inspector.get_columns('user_sessions')
        except Exception:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS user_sessions (
                    id SERIAL PRIMARY KEY,
                    session_id VARCHAR(64) UNIQUE NOT NULL,
                    started_at TIMESTAMP DEFAULT NOW(),
                    last_active TIMESTAMP DEFAULT NOW(),
                    ended_at TIMESTAMP,
                    query_count INTEGER DEFAULT 0,
                    language VARCHAR(10) DEFAULT 'en',
                    device VARCHAR(100),
                    status VARCHAR(20) DEFAULT 'active',
                    ip_address VARCHAR(45)
                )
            """))
            print("[migration] Created user_sessions table")

        # ── campus_settings table ──────────────────────────────────────
        if 'campus_settings' not in inspector.get_table_names():
            conn.execute(text("""
                CREATE TABLE campus_settings (
                    id         SERIAL PRIMARY KEY,
                    key        VARCHAR(100) UNIQUE NOT NULL,
                    value      TEXT,
                    grp        VARCHAR(50),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))
            defaults = [
                ('university_name',   'Batangas State University — Lipa Campus', 'general'),
                ('tagline',           'Your BSU Lipa Campus Assistant',           'general'),
                ('contact_email',     'admin@bsu.edu.ph',                         'general'),
                ('contact_phone',     '+63 43 757-3000',                          'general'),
                ('chatbot_name',      'SPARTA',                                   'chatbot'),
                ('chatbot_greeting',  'Welcome to SPARTA!',                       'chatbot'),
                ('primary_color',     '#E6392F',                                  'appearance'),
                ('logo_url',          '',                                          'appearance'),
                ('emergency_hotline', '(043) 757-3000',                           'emergency'),
                ('security_office',   '+63 917 123 4567',                         'emergency'),
                ('clinic',            '+63 917 234 5678',                         'emergency'),
                ('fire_dept',         '(043) 757-3001',                           'emergency'),
                ('evacuation_coord',  '+63 917 345 6789',                         'emergency'),
                ('admin_office',      '+63 43 757-3002',                          'emergency'),
                ('assembly_area',     'Open Grounds / Sports Court (East Wing)',  'emergency'),
                ('campus_address',    'Pablo Borbon, Lipa City, Batangas',        'navigation'),
                ('evacuation_steps',  '1. Stay calm and proceed to the nearest emergency exit.\n2. Do not use elevators during emergencies.\n3. Proceed to the designated assembly area at the Open Grounds.\n4. Report to your floor warden for headcount.\n5. Call the emergency hotline if someone needs assistance.', 'emergency'),
            ]
            for key, val, grp in defaults:
                conn.execute(text(
                    "INSERT INTO campus_settings (key, value) VALUES (:k, :v) "
                    "ON CONFLICT (key) DO NOTHING"
                ), {"k": key, "v": val, "g": grp})
            conn.commit()
            print("[migration] Created campus_settings table with defaults")

        # AnnouncementPopup: scheduling + archiving columns
        # Safe for Neon/PostgreSQL — won't error if columns already exist
        for col, definition in [
            ('is_archived', 'BOOLEAN DEFAULT FALSE'),
            ('scheduled_at', 'TIMESTAMP'),
            ('expires_at',   'TIMESTAMP'),
        ]:
            exists = conn.execute(text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='announcement_popups' AND column_name=:col"
            ), {"col": col}).fetchone()
            if not exists:
                conn.execute(text(
                    f"ALTER TABLE announcement_popups ADD COLUMN {col} {definition}"
                ))
                print(f"[migration] Added announcement_popups.{col}")
        print("[migration] announcement_popups scheduling columns: OK")

        # Intent: response_template_tl
        intent_cols = [c['name'] for c in inspector.get_columns('intents')]
        if 'response_template_tl' not in intent_cols:
            conn.execute(text("ALTER TABLE intents ADD COLUMN response_template_tl TEXT"))
            print("[migration] Added intents.response_template_tl")

        # History: title_tl, description_tl
        history_cols = [c['name'] for c in inspector.get_columns('history')]
        if 'title_tl' not in history_cols:
            conn.execute(text("ALTER TABLE history ADD COLUMN title_tl TEXT"))
            print("[migration] Added history.title_tl")
        if 'description_tl' not in history_cols:
            conn.execute(text("ALTER TABLE history ADD COLUMN description_tl TEXT"))
            print("[migration] Added history.description_tl")

        # Announcement: title_tl, content_tl
        ann_cols = [c['name'] for c in inspector.get_columns('announcements')]
        if 'title_tl' not in ann_cols:
            conn.execute(text("ALTER TABLE announcements ADD COLUMN title_tl TEXT"))
            print("[migration] Added announcements.title_tl")
        if 'content_tl' not in ann_cols:
            conn.execute(text("ALTER TABLE announcements ADD COLUMN content_tl TEXT"))
            print("[migration] Added announcements.content_tl")

        conn.commit()

    # Activity logs — created by metadata.create_all; no extra patch needed
    # FAQ Documents — created by metadata.create_all, just patch new cols if needed
    try:
        if inspector.has_table('faq_documents'):
            faq_cols = [c['name'] for c in inspector.get_columns('faq_documents')]
            if 'page_count' not in faq_cols:
                conn.execute(text("ALTER TABLE faq_documents ADD COLUMN page_count INTEGER"))
                print("[migration] Added faq_documents.page_count")
            if 'file_size' not in faq_cols:
                conn.execute(text("ALTER TABLE faq_documents ADD COLUMN file_size INTEGER"))
                print("[migration] Added faq_documents.file_size")
            conn.commit()
    except Exception as faq_err:
        print(f"[migration] faq_documents patch: {faq_err}")

    # ── search_logs.searched_at backfill ──────────────────────────────
    # Backfills any rows where searched_at is NULL (old rows before the
    # column had a server default). Safe to run every startup — only
    # updates rows that actually need it.
    try:
        if inspector.has_table('search_logs'):
            sl_cols = [c['name'] for c in inspector.get_columns('search_logs')]
            if 'searched_at' in sl_cols:
                result = conn.execute(text(
                    "UPDATE search_logs SET searched_at = NOW() WHERE searched_at IS NULL"
                ))
                if result.rowcount:
                    print(f"[migration] Backfilled {result.rowcount} search_logs.searched_at NULLs")
                conn.commit()
    except Exception as sl_err:
        print(f"[migration] search_logs backfill: {sl_err}")

try:
    _run_migrations()
except Exception as _me:
    print(f"[migration] Non-fatal migration warning: {_me}")

# SECURITY: /docs, /redoc, and /openapi.json are disabled by default —
# they publicly expose your entire API surface (every endpoint, including
# admin routes, plus request/response schemas) to any unauthenticated
# visitor, which is real reconnaissance value for an attacker. To enable
# them for local development, set ENABLE_API_DOCS=true in your environment.
_enable_docs = os.getenv("ENABLE_API_DOCS", "false").lower() == "true"
app = FastAPI(
    docs_url="/docs" if _enable_docs else None,
    redoc_url="/redoc" if _enable_docs else None,
    openapi_url="/openapi.json" if _enable_docs else None,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://localhost:5500",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:5500",
        "https://sparta-production-0acb.up.railway.app",
        "https://sparta.help",
        "https://www.sparta.help",
        "https://admin.sparta.help",
    ],
    allow_origin_regex=r"https://.*\.(vercel\.app|devtunnels\.ms|trycloudflare\.com|ngrok-free\.app|ngrok\.io)|http://192\.168\.\d+\.\d+:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Session middleware — signs cookie with itsdangerous
#
# SECURITY: SECRET_KEY must be set as a real environment variable. There is
# intentionally no fallback default here anymore — a hardcoded fallback
# secret sitting in source code (especially if the repo is public on
# GitHub) lets anyone forge their own validly-signed session cookie via
# DevTools (Application → Cookies), granting admin access without ever
# entering a password. If this raises on startup, set SECRET_KEY in
# Railway's Environment Variables — generate one with:
#   python -c "import secrets; print(secrets.token_hex(32))"
_secret_key = os.getenv("SECRET_KEY")
if not _secret_key:
    raise RuntimeError(
        "SECRET_KEY environment variable is not set. Refusing to start with "
        "an insecure fallback secret. Generate one with: "
        "python -c \"import secrets; print(secrets.token_hex(32))\" "
        "and set it in Railway → Variables."
    )

app.add_middleware(
    SessionMiddleware,
    secret_key=_secret_key,
    session_cookie="spartha_session",
    max_age=60 * 60 * int(os.getenv("ACCESS_TOKEN_EXPIRE_HOURS", 8)),  # respects env var
    https_only=True,
    same_site="none",  # ← change "lax" to "none" for cross-domain
)

# Paths relative to backend/ (where main.py lives)
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
SPARTHA_DIR = BACKEND_DIR  # static and images are now inside backend/

# Security middleware — rate limiting + security headers
app.add_middleware(SecurityMiddleware)

# Mount static files (GLB models etc) from backend/static/
if os.path.exists(os.path.join(BACKEND_DIR, "static")):
    app.mount("/static", StaticFiles(directory=os.path.join(BACKEND_DIR, "static")), name="static")

# Mount images from backend/images/
if os.path.exists(os.path.join(BACKEND_DIR, "images")):
    app.mount("/images", StaticFiles(directory=os.path.join(BACKEND_DIR, "images")), name="images")

# Serve admin HTML files directly so cookies work (same origin as API)
BASE_DIR = os.path.join(BACKEND_DIR, "admin")  # backend/admin/

from fastapi.responses import FileResponse

# Admin files live in backend/admin/
# User-facing frontend files live in ../frontend/ (sibling of backend/)
FRONTEND_DIR = os.path.join(os.path.dirname(BACKEND_DIR), "frontend")

# Files that belong to the admin panel (served from backend/admin/)
ADMIN_FILES = {
    "admin.html", "login.html",
    "admin-script.js", "admin-styles.css",
}

def frontend_file(filename: str):
    """Serve a file from the correct directory based on whether it is an
    admin/backend file or a user-facing frontend file."""
    if filename in ADMIN_FILES:
        path = os.path.join(BASE_DIR, filename)      # backend/admin/
    else:
        # Try frontend/ first, then fall back to backend/ and admin/
        candidates = [
            os.path.join(FRONTEND_DIR, filename),    # ../frontend/
            os.path.join(BACKEND_DIR, filename),     # backend/
            os.path.join(BASE_DIR, filename),        # backend/admin/
        ]
        path = next((p for p in candidates if os.path.exists(p)), None)
        if path is None:
            raise HTTPException(status_code=404, detail=f"File not found: {filename}")
        return FileResponse(path)

    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    return FileResponse(path)

# ── HTML pages ──────────────────────────────────────────
@app.get("/admin.html", response_class=HTMLResponse)
@app.get("/admin",     response_class=HTMLResponse)
async def serve_admin(request: Request):
    """Serve admin.html — redirect to /login if session is missing or expired."""
    from fastapi.responses import RedirectResponse as _Redir
    try:
        verify_session(request)   # uses auth.py — checks "username" key + expiry
    except Exception:
        return _Redir(url="/login?next=/admin", status_code=302)
    return frontend_file("admin.html")

@app.get("/login", response_class=HTMLResponse)
async def serve_login(request: Request):
    """Serve login.html — bounce to /admin if already authenticated."""
    from fastapi.responses import RedirectResponse as _Redir
    try:
        verify_session(request)
        return _Redir(url="/admin", status_code=302)   # already logged in
    except Exception:
        pass
    return frontend_file("login.html")

@app.get("/chatbot1.html",         response_class=HTMLResponse)
@app.get("/sparta_chatbot.html",    response_class=HTMLResponse)
async def serve_chatbot():         return frontend_file("sparta_chatbot.html")

@app.get("/campus-navigator1.html",response_class=HTMLResponse)
@app.get("/sparta_campus-navigator.html",response_class=HTMLResponse)
async def serve_navigator():       return frontend_file("sparta_campus-navigator.html")

@app.get("/spartha_main_menu.html",response_class=HTMLResponse)
@app.get("/sparta_main_menu.html",response_class=HTMLResponse)
async def serve_main_menu():       return frontend_file("sparta_main_menu.html")

@app.get("/sparta_about.html",      response_class=HTMLResponse)
async def serve_about():            return frontend_file("sparta_about.html")

@app.get("/how_to_use.html",       response_class=HTMLResponse)
async def serve_how_to_use():      return frontend_file("how_to_use.html")

# ── CSS files ────────────────────────────────────────────
@app.get("/admin-styles.css")
async def serve_admin_styles():    return frontend_file("admin-styles.css")

@app.get("/chatbot_styles.css")
async def serve_chatbot_styles():  return frontend_file("chatbot_styles.css")

@app.get("/navigation-styles.css")
async def serve_nav_styles():      return frontend_file("navigation-styles.css")

# ── JS files ─────────────────────────────────────────────
@app.get("/admin-script.js")
async def serve_admin_script():
    from fastapi.responses import FileResponse as _FR
    import os as _os
    return _FR(
        _os.path.join(BASE_DIR, "admin-script.js"),
        media_type="application/javascript",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0", "Pragma": "no-cache"}
    )

@app.get("/sparta-alert.js")
async def serve_sparta_alert():
    from fastapi.responses import FileResponse as _FR
    import os as _os
    return _FR(
        _os.path.join(BASE_DIR, "sparta-alert.js"),
        media_type="application/javascript",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0", "Pragma": "no-cache"}
    )

@app.get("/chatbot_script.js")
async def serve_chatbot_script():  return frontend_file("chatbot_script.js")

@app.get("/navigation-script.js")
async def serve_nav_script():      return frontend_file("navigation-script.js")

@app.get("/sparta_popup_announcements.js")
async def serve_popup_script(): return frontend_file("sparta_popup_announcements.js")
# Embedding is now handled via Gemini API in embedding_handler.py
embedding_model = None  # kept for API compatibility

# ============================================
# ACTIVITY LOG HELPER
# ============================================

def log_activity(
    db: Session,
    action: str,
    resource: str,
    resource_id: int | None = None,
    detail: str | None = None,
    performed_by: str = "Admin",
):
    """Append a row to activity_logs. Never raises — logging must not break the main flow."""
    try:
        db.add(models.ActivityLog(
            action=action,
            resource=resource,
            resource_id=resource_id,
            detail=detail,
            performed_by=performed_by,
            performed_at=datetime.utcnow(),
        ))
        db.commit()
    except Exception as _log_err:
        print(f"[activity_log] Non-fatal logging error: {_log_err}")
        try:
            db.rollback()
        except Exception:
            pass

# ============================================
# PYDANTIC MODELS
# ============================================

class ChatMessage(BaseModel):
    message: str
    language: Optional[str] = "en-US"

class AuthorityCreate(BaseModel):
    name: str
    position: str
    department: str
    email: Optional[str] = None
    phone: Optional[str] = None
    office_location: Optional[str] = None
    bio: Optional[str] = None
    photo: Optional[str] = None

class HistoryCreate(BaseModel):
    year: int
    title: str
    description: str
    title_tl: Optional[str] = None
    description_tl: Optional[str] = None

class AnnouncementCreate(BaseModel):
    title: str
    content: str
    category: str
    date_posted: Optional[datetime] = None
    title_tl: Optional[str] = None
    content_tl: Optional[str] = None

class IntentCreate(BaseModel):
    intent_type: str
    keywords: str
    response_template: str
    response_template_tl: Optional[str] = None

class CoordinatesSchema(BaseModel):
    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None

class RoomLocationCreate(BaseModel):
    name: str
    building: str
    floor: int
    type: str
    icon: Optional[str] = None
    capacity: Optional[int] = None
    description: Optional[str] = None
    coordinates: Optional[CoordinatesSchema] = None

class NavigationRouteCreate(BaseModel):
    name: str
    type: str
    start_location_id: int
    end_location_id: int
    is_wheelchair_accessible: bool = False
    path_color: str = "#F4D03F"
    waypoints: list

class OrganizationCreate(BaseModel):
    name: str
    description: Optional[str] = None

class OrganizationMemberCreate(BaseModel):
    organization_id: int
    name: str
    position: str

class AdminLoginRequest(BaseModel):
    username: str
    password: str

class AdminCredentialUpdate(BaseModel):
    current_username: str
    current_password: str
    new_username: Optional[str] = None
    new_password: Optional[str] = None

# ============================================
# PROTECTED ADMIN ROUTER
# All routes here require a valid HttpOnly cookie
# ============================================

admin_router = APIRouter(
    prefix="/api/admin",
    dependencies=[Depends(verify_session)]
)

# ============================================
# ROUTES - HOME
# ============================================

@app.get("/")
async def read_root():
    # admin.sparta.help is entirely dedicated to the admin backend — there's
    # no reason for a visitor hitting the bare domain to see anything but
    # the login screen. This used to render a landing page that listed every
    # available endpoint (including admin routes), which is unnecessary
    # information disclosure for an unauthenticated visitor.
    from fastapi.responses import RedirectResponse as _Redir
    return _Redir(url="/login", status_code=302)

# ============================================
# ROUTES - RAG-ENHANCED CHATBOT (PUBLIC)
# ============================================

@app.post("/api/chat")
async def chat(message: ChatMessage, request: Request, db: Session = Depends(get_db)):
    # ── Session tracking ──────────────────────────────────────────────────
    _sid = request.session.get("chatbot_session_id")
    if not _sid:
        import uuid
        _sid = str(uuid.uuid4())
        request.session["chatbot_session_id"] = _sid
        _ua = request.headers.get("user-agent","")[:100]
        _ip = request.client.host if request.client else None
        try:
            db.execute(
                # FIX: Include started_at explicitly so it's never NULL
                text("INSERT INTO user_sessions (session_id, language, device, ip_address, status, started_at, last_active) "
                     "VALUES (:sid, :lang, :dev, :ip, 'active', NOW(), NOW()) ON CONFLICT (session_id) DO NOTHING"),
                {"sid": _sid, "lang": getattr(message, "language", "en") or "en",
                 "dev": _ua, "ip": _ip}
            )
            db.commit()
        except Exception: db.rollback()
    else:
        try:
            db.execute(
                text("UPDATE user_sessions SET last_active=NOW(), query_count=query_count+1, "
                     "status='active' WHERE session_id=:sid"),
                {"sid": _sid}
            )
            db.commit()
        except Exception: db.rollback()
    # ── End session tracking ──────────────────────────────────────────────

    # ── Session hard cap — prevents single session from flooding ─────────────
    try:
        _qc_row = db.execute(
            text("SELECT query_count FROM user_sessions WHERE session_id = :sid"),
            {"sid": _sid}
        ).fetchone()
        if _qc_row and _qc_row[0] and _qc_row[0] > 300:
            raise HTTPException(
                status_code=429,
                detail="Session message limit reached. Please refresh the page to continue."
            )
    except HTTPException:
        raise
    except Exception:
        pass  # non-fatal

    # ── Spam / rate-limit check ──────────────────────────────────────────────
    _client_ip  = request.client.host if request.client else "unknown"
    _session_id = request.session.get("chatbot_session_id", _client_ip)
    _allowed, _deny_reason = rate_limiter.is_chat_allowed(
        _client_ip, _session_id, message.message or ""
    )
    if not _allowed:
        raise HTTPException(
            status_code=429,
            detail=_deny_reason or "Too many requests. Please wait before sending again."
        )

    # ── Input validation ─────────────────────────────────────────────────────
    if not message.message or not message.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    if len(message.message) > 600:
        raise HTTPException(status_code=400, detail="Message too long. Please keep it under 600 characters.")
    if len(message.message.strip()) < 2:
        raise HTTPException(status_code=400, detail="Message too short.")

    # ── Sanitize — strip control characters and excessive whitespace ──────────
    import re as _re
    clean_message = _re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", message.message)
    clean_message = _re.sub(r"\s{10,}", " ", clean_message).strip()
    if not clean_message:
        raise HTTPException(status_code=400, detail="Message contains invalid characters.")

    try:
        result = process_chat_with_rag(
            message=clean_message,
            db=db,
            embedding_model=embedding_model,
            language=message.language
        )
        return {
            "response": result['response'],
            "confidence": result.get('confidence', 0.0),
            "intent": result.get('intent', 'unknown'),
            "suggestions": result.get('suggestions', []),
            "metadata": {
                "rag_enabled": True,
                "context_used": result.get('context_used', 0),
                "entities_found": result.get('entities_found', {})
            }
        }
    except Exception as e:
        print(f"Error in chat endpoint: {e}")
        import traceback
        traceback.print_exc()
        return {
            "response": "I apologize, but I encountered an error processing your request. Please try again or rephrase your question.",
            "confidence": 0.0,
            "intent": "error",
            "suggestions": [
                "Who is the dean of Engineering?",
                "Where is the library?",
                "Show me latest announcements"
            ],
            "metadata": {"rag_enabled": True, "error": str(e)}
        }

# ============================================
# PUBLIC CAMPUS NAVIGATOR ENDPOINTS
# ============================================

@app.get("/room-locations")
@app.get("/api/locations")
async def get_room_locations(db: Session = Depends(get_db)):
    try:
        locations = db.query(models.RoomLocation).all()
        return [
            {
                "id": loc.id,
                "name": loc.name,
                "building": loc.building,
                "floor": loc.floor,
                "type": loc.type,
                "icon": loc.icon,
                "capacity": loc.capacity,
                "description": loc.description,
                "coordinates": loc.coordinates if loc.coordinates else None
            }
            for loc in locations
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/navigation-routes")
@app.get("/api/routes")
async def get_navigation_routes(db: Session = Depends(get_db)):
    try:
        routes = db.query(models.NavigationRoute).all()
        return [
            {
                "id": route.id,
                "name": route.name,
                "type": route.type,
                "start_location_id": route.start_location_id,
                "end_location_id": route.end_location_id,
                "is_wheelchair_accessible": route.is_wheelchair_accessible,
                "path_color": route.path_color,
                "waypoints": route.waypoints if route.waypoints else []
            }
            for route in routes
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# PUBLIC ANNOUNCEMENT POPUPS
# ============================================

@app.get("/api/routes/for-location/{location_id}")
async def get_routes_for_location(location_id: int, db: Session = Depends(get_db)):
    """Get all routes connected to a specific location (public — used by campus navigator)"""
    try:
        routes = db.query(models.NavigationRoute).filter(
            (models.NavigationRoute.start_location_id == location_id) |
            (models.NavigationRoute.end_location_id == location_id)
        ).all()
        return [
            {
                "id": route.id,
                "name": route.name,
                "type": route.type,
                "start_location_id": route.start_location_id,
                "end_location_id": route.end_location_id,
                "is_wheelchair_accessible": route.is_wheelchair_accessible,
                "path_color": route.path_color,
                "waypoints": route.waypoints if route.waypoints else []
            }
            for route in routes
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/announcement-popups")
async def get_active_popups(db: Session = Depends(get_db)):
    try:
        from datetime import datetime as _now_dt
        _now = _now_dt.utcnow()
        popups = db.query(models.AnnouncementPopup).filter(
            models.AnnouncementPopup.is_active == True,
            models.AnnouncementPopup.is_archived == False if hasattr(models.AnnouncementPopup, 'is_archived') else True,
        ).filter(
            (models.AnnouncementPopup.scheduled_at == None) | (models.AnnouncementPopup.scheduled_at <= _now)
        ).filter(
            (models.AnnouncementPopup.expires_at == None) | (models.AnnouncementPopup.expires_at >= _now)
        ).order_by(
            models.AnnouncementPopup.priority.desc(),
            models.AnnouncementPopup.created_at.desc()
        ).all()
        return [
            {
                "id": p.id,
                "title": p.title,
                "content": p.content,
                "category": p.category,
                "image_data": p.image_data,
                "image_filename": p.image_filename,
                "priority": p.priority,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in popups
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/quick-questions")
async def get_quick_questions(intent: str = "general_info", db: Session = Depends(get_db)):
    """
    Returns quick questions built entirely from DB content.
    Response: { "primary": [...], "explore": [...] }

    Startup and college-picker sets are handled by the frontend with hardcoded
    constants and never call this endpoint.
    """
    import random

    def sample(lst, n):
        return random.sample(lst, min(n, len(lst)))

    def truncate(s, n=32):
        return s if len(s) <= n else s[:n - 1] + "…"

    try:
        authorities   = db.query(models.Authority).all()
        locations     = db.query(models.RoomLocation).filter(
                            ~models.RoomLocation.name.ilike('%emergency%')).all()
        orgs          = db.query(models.Organization).all()
        announcements = db.query(models.Announcement).order_by(
                            models.Announcement.date_posted.desc()).limit(20).all()
        histories     = db.query(models.History).order_by(
                            models.History.year.asc()).all()
        # ── Custom intents from DB ────────────────────────────────────────────
        custom_intents = db.query(models.Intent).filter(
                            models.Intent.keywords != None,
                            models.Intent.keywords != '',
                            models.Intent.response_template != None,
                            models.Intent.response_template != ''
                        ).all()

        def authority_qs(n=3):
            return [{"text": f"👤 {truncate(a.name)}", "query": f"Who is {a.name}?", "category": "authority"}
                    for a in sample(authorities, n)]

        def location_qs(n=3):
            return [{"text": f"📍 {truncate(loc.name)}", "query": f"Where is the {loc.name}?", "category": "location"}
                    for loc in sample(locations, n)]

        def org_qs(n=3):
            qs = []
            for org in sample(orgs, n):
                label = truncate(org.name, 26)
                qs.append({"text": f"🎓 {label}", "query": f"Tell me about {org.name}", "category": "organization"})
            return qs

        def announcement_qs(n=3):
            return [{"text": f"📢 {truncate(ann.title)}", "query": f"Tell me about the announcement: {ann.title}", "category": "announcement"}
                    for ann in sample(announcements, n)]

        def history_qs(n=2):
            return [{"text": f"🏛️ {truncate(h.title)}", "query": f"Tell me about {h.title}", "category": "history"}
                    for h in sample(histories, n)]

        def custom_intent_qs(n=2):
            """Build quick question buttons from custom intents in DB."""
            qs = []
            for ci in sample(custom_intents, n):
                # FIX: Label AND query both derived from intent_type so they always match.
                # Old code: label = intent_type ("Second Diploma")
                #            query = first keyword ("lost diploma") ← MISMATCH
                # New code: both use intent_type, query wrapped as natural sentence.
                label = ci.intent_type.replace('_', ' ').title() if ci.intent_type else (
                    ci.keywords.split(',')[0].strip() if ci.keywords else 'Info'
                )
                query = f"Tell me about {label}"
                qs.append({
                    "text": f"💬 {truncate(label, 28)}",
                    "query": query,
                    "category": "custom"
                })
            return qs

        if intent == "authority_query":
            primary = authority_qs(4)
            explore = location_qs(2) + announcement_qs(1) + org_qs(1) + history_qs(1)
            if custom_intents:
                explore += custom_intent_qs(1)

        elif intent in ("location_query", "navigation_query"):
            # Primary: all location suggestions
            primary = location_qs(5)
            primary.append({"text": "🗺️ Campus Navigator", "query": "Where is the main entrance?", "category": "location"})
            # Explore: more locations first, then mix
            explore = location_qs(3) + announcement_qs(1) + authority_qs(1)
            if custom_intents:
                explore += custom_intent_qs(1)

        elif intent == "organization_query":
            primary = org_qs(5)
            if orgs:
                primary.append({"text": "📋 All organizations", "query": "List all student organizations", "category": "organization"})
            explore = org_qs(2) + location_qs(2) + announcement_qs(1)
            if custom_intents:
                explore += custom_intent_qs(1)

        elif intent == "announcement_query":
            primary = announcement_qs(4)
            explore = authority_qs(2) + location_qs(1) + org_qs(1) + history_qs(1)
            if custom_intents:
                explore += custom_intent_qs(1)

        elif intent == "history_query":
            primary = history_qs(min(4, len(histories)))
            explore = authority_qs(2) + location_qs(1) + org_qs(1) + announcement_qs(1)
            if custom_intents:
                explore += custom_intent_qs(1)

        elif intent == "greeting":
            # After a greeting, show a helpful mix of what SPARTA can do
            primary = location_qs(2) + authority_qs(1) + org_qs(1) + announcement_qs(1)
            random.shuffle(primary)
            explore = history_qs(1) + (custom_intent_qs(1) if custom_intents else [])

        else:  # general_info / fallback
            primary = authority_qs(1) + location_qs(1) + org_qs(1) + announcement_qs(1) + history_qs(1)
            if custom_intents:
                primary += custom_intent_qs(min(2, len(custom_intents)))
            random.shuffle(primary)
            explore = []

        random.shuffle(explore)
        return {"primary": primary, "explore": explore[:4]}

    except Exception as e:
        print(f"[quick-questions] Error: {e}")
        return {
            "primary": [
                {"text": "🎓 Who is the dean?",      "query": "Who is the dean?",                   "category": "authority"},
                {"text": "📍 Where is the library?", "query": "Where is the library?",              "category": "location"},
                {"text": "🏛️ BSU Lipa history",      "query": "Tell me about BSU Lipa history",     "category": "history"},
                {"text": "📢 Latest announcements",   "query": "What are the latest announcements?", "category": "announcement"},
            ],
            "explore": []
        }

# ============================================
# ADMIN AUTH ENDPOINTS (PUBLIC - no cookie needed)
# ============================================

def hash_password(password: str) -> str:
    """Hash a password using bcrypt (slow by design — resists brute force)"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against a bcrypt hash"""
    return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))

def ensure_default_admin(db: Session):
    existing = db.query(models.AdminCredentials).first()
    if not existing:
        default_admin = models.AdminCredentials(
            username="admin",
            password_hash=hash_password("admin123")
        )
        db.add(default_admin)
        db.commit()

@app.post("/api/admin/login")
async def admin_login(login_request: AdminLoginRequest, request: Request, db: Session = Depends(get_db)):
    """Login — verifies credentials and creates a signed session cookie via itsdangerous"""
    ensure_default_admin(db)
    credential = db.query(models.AdminCredentials).filter(
        models.AdminCredentials.username == login_request.username
    ).first()
    if not credential or not verify_password(login_request.password, credential.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # Store username + expiry in signed session cookie (see auth.py)
    create_session(request, credential.username)

    return JSONResponse(content={
        "success": True,
        "message": "Login successful",
        "username": credential.username
    })

@app.post("/api/admin/logout")
async def admin_logout(request: Request):
    """Logout — clears the signed session cookie"""
    clear_session(request)   # clears entire session including "username" and "expires_at"
    from fastapi.responses import RedirectResponse as _Redir
    # Return JSON for API calls; client-side JS will redirect to /login
    return JSONResponse(content={"success": True, "message": "Logged out", "redirect": "/login"})

# ============================================
# PROTECTED ADMIN ENDPOINTS
# All routes below require valid HttpOnly cookie
# ============================================

# --- AUTHORITIES ---

@admin_router.get("/authorities")
async def get_authorities(db: Session = Depends(get_db)):
    authorities = db.query(models.Authority).all()
    return [
        {
            "id": a.id,
            "name": a.name,
            "position": a.position,
            "department": a.department,
            "email": a.email,
            "phone": a.phone,
            "office_location": a.office_location,
            "bio": a.bio,
            "photo": a.photo,  # explicitly included — base64 string
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in authorities
    ]

@admin_router.post("/authorities")
async def create_authority(
    name: str = Form(...),
    position: str = Form(...),
    department: str = Form(...),
    email: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    office_location: Optional[str] = Form(None),
    bio: Optional[str] = Form(None),
    photo_url: Optional[str] = Form(None),   # Cloudinary secure_url from /upload-photo
    db: Session = Depends(get_db)
):
    """Create a new authority. Photo should be pre-uploaded via /upload-photo."""
    # Server-side validation
    if not name or len(name.strip()) < 2:
        raise HTTPException(status_code=422, detail="Name must be at least 2 characters.")
    if not position or len(position.strip()) < 2:
        raise HTTPException(status_code=422, detail="Position must be at least 2 characters.")
    if not department or len(department.strip()) < 2:
        raise HTTPException(status_code=422, detail="Department must be at least 2 characters.")
    if email:
        import re as _re
        if not _re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$", email.strip()):
            raise HTTPException(status_code=422, detail="Invalid email address format.")
    if phone:
        import re as _re2
        _digits = len(_re2.sub(r"[^\d]", "", phone.strip()))
        if _digits < 5 or len(phone.strip()) > 50:
            raise HTTPException(status_code=422, detail="Enter a valid phone number (e.g. (043) 757-3000 loc. 123).")

    db_authority = models.Authority(
        name=name.strip(),
        position=position.strip(),
        department=department.strip(),
        email=email.strip() if email else None,
        phone=phone.strip() if phone else None,
        office_location=office_location.strip() if office_location else None,
        bio=bio.strip() if bio else None,
        photo=photo_url or None,   # Cloudinary URL or None
    )
    db.add(db_authority)
    db.commit()
    db.refresh(db_authority)
    log_activity(db, "created", "authority", db_authority.id,
                 f"Added authority '{db_authority.name}' ({db_authority.position})")
    return {
        "id": db_authority.id, "name": db_authority.name,
        "position": db_authority.position, "department": db_authority.department,
        "email": db_authority.email, "phone": db_authority.phone,
        "photo": db_authority.photo
    }

@admin_router.put("/authorities/{authority_id}")
async def update_authority(
    authority_id: int,
    name: str = Form(...),
    position: str = Form(...),
    department: str = Form(...),
    email: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    office_location: Optional[str] = Form(None),
    bio: Optional[str] = Form(None),
    photo_url: Optional[str] = Form(None),          # new Cloudinary URL (if changed)
    keep_existing_photo: str = Form("true"),         # "true" = don't change existing photo
    db: Session = Depends(get_db)
):
    """Update an authority. Photo is pre-uploaded via /upload-photo."""
    # Server-side validation
    import re as _re
    if not name or len(name.strip()) < 2:
        raise HTTPException(status_code=422, detail="Name must be at least 2 characters.")
    if not position or len(position.strip()) < 2:
        raise HTTPException(status_code=422, detail="Position must be at least 2 characters.")
    if not department or len(department.strip()) < 2:
        raise HTTPException(status_code=422, detail="Department must be at least 2 characters.")
    if email and not _re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$", email.strip()):
        raise HTTPException(status_code=422, detail="Invalid email address format.")
    if phone:
        import re as _re2
        _digits = len(_re2.sub(r"[^\d]", "", phone.strip()))
        if _digits < 5 or len(phone.strip()) > 50:
            raise HTTPException(status_code=422, detail="Enter a valid phone number (e.g. (043) 757-3000 loc. 123).")

    db_authority = db.query(models.Authority).filter(models.Authority.id == authority_id).first()
    if not db_authority:
        raise HTTPException(status_code=404, detail="Authority not found")

    db_authority.name           = name.strip()
    db_authority.position       = position.strip()
    db_authority.department     = department.strip()
    db_authority.email          = email.strip() if email else None
    db_authority.phone          = phone.strip() if phone else None
    db_authority.office_location= office_location.strip() if office_location else None
    db_authority.bio            = bio.strip() if bio else None

    if photo_url:
        db_authority.photo = photo_url   # new Cloudinary URL
    elif keep_existing_photo.lower() != "true":
        db_authority.photo = None        # explicitly cleared

    db.commit()
    db.refresh(db_authority)
    log_activity(db, "updated", "authority", db_authority.id,
                 f"Updated authority '{db_authority.name}'")
    return {
        "id": db_authority.id, "name": db_authority.name,
        "position": db_authority.position, "department": db_authority.department,
        "email": db_authority.email, "phone": db_authority.phone,
        "photo": db_authority.photo
    }

@admin_router.delete("/authorities/{authority_id}")
async def delete_authority(authority_id: int, db: Session = Depends(get_db)):
    db_authority = db.query(models.Authority).filter(models.Authority.id == authority_id).first()
    if not db_authority:
        raise HTTPException(status_code=404, detail="Authority not found")
    name = db_authority.name
    db.delete(db_authority)
    db.commit()
    log_activity(db, "deleted", "authority", authority_id, f"Deleted authority '{name}'")
    return {"message": "Authority deleted successfully"}

# --- HISTORIES ---

@admin_router.get("/histories")
async def get_histories(db: Session = Depends(get_db)):
    try:
        histories = db.query(models.History).order_by(models.History.year).all()
        return [
            {
                "id": h.id,
                "year": h.year,
                "title": h.title,
                "description": h.description,
                "created_at": h.created_at.isoformat() if h.created_at else None
            }
            for h in histories
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@admin_router.get("/history")
async def get_history_singular(db: Session = Depends(get_db)):
    return await get_histories(db)

@admin_router.post("/histories")
async def create_history(history: HistoryCreate, db: Session = Depends(get_db)):
    db_history = models.History(**history.model_dump())
    db.add(db_history)
    db.commit()
    db.refresh(db_history)
    log_activity(db, "created", "history", db_history.id, f"Added history entry '{db_history.title}' ({db_history.year})")
    return db_history

@admin_router.post("/history")
async def create_history_singular(history: HistoryCreate, db: Session = Depends(get_db)):
    return await create_history(history, db)

@admin_router.put("/histories/{history_id}")
async def update_history(history_id: int, history: HistoryCreate, db: Session = Depends(get_db)):
    db_history = db.query(models.History).filter(models.History.id == history_id).first()
    if not db_history:
        raise HTTPException(status_code=404, detail="History not found")
    for key, value in history.model_dump().items():
        setattr(db_history, key, value)
    db.commit()
    db.refresh(db_history)
    log_activity(db, "updated", "history", db_history.id, f"Updated history entry '{db_history.title}' ({db_history.year})")
    return db_history

@admin_router.put("/history/{history_id}")
async def update_history_singular(history_id: int, history: HistoryCreate, db: Session = Depends(get_db)):
    return await update_history(history_id, history, db)

@admin_router.delete("/histories/{history_id}")
async def delete_history(history_id: int, db: Session = Depends(get_db)):
    db_history = db.query(models.History).filter(models.History.id == history_id).first()
    if not db_history:
        raise HTTPException(status_code=404, detail="History not found")
    title = db_history.title
    db.delete(db_history)
    db.commit()
    log_activity(db, "deleted", "history", history_id, f"Deleted history entry '{title}'")
    return {"message": "History deleted successfully"}

@admin_router.delete("/history/{history_id}")
async def delete_history_singular(history_id: int, db: Session = Depends(get_db)):
    return await delete_history(history_id, db)

# --- ANNOUNCEMENTS ---

@admin_router.get("/announcements")
async def get_announcements(db: Session = Depends(get_db)):
    return db.query(models.Announcement).order_by(models.Announcement.date_posted.desc()).all()

@admin_router.post("/announcements")
async def create_announcement(announcement: AnnouncementCreate, db: Session = Depends(get_db)):
    announcement_data = announcement.model_dump()
    if not announcement_data.get('date_posted'):
        announcement_data['date_posted'] = datetime.utcnow()
    db_announcement = models.Announcement(**announcement_data)
    db.add(db_announcement)
    db.commit()
    db.refresh(db_announcement)
    log_activity(db, "created", "announcement", db_announcement.id, f"Posted announcement '{db_announcement.title}'")
    return db_announcement

@admin_router.put("/announcements/{announcement_id}")
async def update_announcement(announcement_id: int, announcement: AnnouncementCreate, db: Session = Depends(get_db)):
    db_announcement = db.query(models.Announcement).filter(models.Announcement.id == announcement_id).first()
    if not db_announcement:
        raise HTTPException(status_code=404, detail="Announcement not found")
    for key, value in announcement.model_dump().items():
        setattr(db_announcement, key, value)
    db.commit()
    db.refresh(db_announcement)
    log_activity(db, "updated", "announcement", db_announcement.id, f"Updated announcement '{db_announcement.title}'")
    return db_announcement

@admin_router.delete("/announcements/{announcement_id}")
async def delete_announcement(announcement_id: int, db: Session = Depends(get_db)):
    db_announcement = db.query(models.Announcement).filter(models.Announcement.id == announcement_id).first()
    if not db_announcement:
        raise HTTPException(status_code=404, detail="Announcement not found")
    title = db_announcement.title
    db.delete(db_announcement)
    db.commit()
    log_activity(db, "deleted", "announcement", announcement_id, f"Deleted announcement '{title}'")
    return {"message": "Announcement deleted successfully"}

# --- LOCATIONS ---

@admin_router.get("/locations")
async def get_locations(db: Session = Depends(get_db)):
    return db.query(models.RoomLocation).all()

@admin_router.post("/locations")
async def create_location(location: RoomLocationCreate, db: Session = Depends(get_db)):
    location_data = location.model_dump()
    if location_data.get('coordinates'):
        coords = location_data['coordinates']
        if isinstance(coords, dict):
            location_data['coordinates'] = json.dumps(coords)
    db_location = models.RoomLocation(**location_data)
    db.add(db_location)
    db.commit()
    db.refresh(db_location)
    log_activity(db, "created", "location", db_location.id, f"Added location '{db_location.name}' ({db_location.building}, Floor {db_location.floor})")
    return {
        "id": db_location.id,
        "name": db_location.name,
        "building": db_location.building,
        "floor": db_location.floor,
        "type": db_location.type,
        "icon": db_location.icon,
        "capacity": db_location.capacity,
        "description": db_location.description,
        "coordinates": db_location.coordinates,
        "created_at": db_location.created_at.isoformat() if db_location.created_at else None,
    }

@admin_router.put("/locations/{location_id}")
async def update_location(location_id: int, location: RoomLocationCreate, db: Session = Depends(get_db)):
    db_location = db.query(models.RoomLocation).filter(models.RoomLocation.id == location_id).first()
    if not db_location:
        raise HTTPException(status_code=404, detail="Location not found")
    location_data = location.model_dump()
    if location_data.get('coordinates'):
        coords = location_data['coordinates']
        if isinstance(coords, dict):
            location_data['coordinates'] = json.dumps(coords)
    for key, value in location_data.items():
        setattr(db_location, key, value)
    db.commit()
    db.refresh(db_location)
    log_activity(db, "updated", "location", db_location.id, f"Updated location '{db_location.name}'")
    return {
        "id": db_location.id,
        "name": db_location.name,
        "building": db_location.building,
        "floor": db_location.floor,
        "type": db_location.type,
        "icon": db_location.icon,
        "capacity": db_location.capacity,
        "description": db_location.description,
        "coordinates": db_location.coordinates,
        "created_at": db_location.created_at.isoformat() if db_location.created_at else None,
    }

@admin_router.delete("/locations/{location_id}")
async def delete_location(location_id: int, db: Session = Depends(get_db)):
    db_location = db.query(models.RoomLocation).filter(models.RoomLocation.id == location_id).first()
    if not db_location:
        raise HTTPException(status_code=404, detail="Location not found")
    name = db_location.name
    db.query(models.NavigationRoute).filter(
        (models.NavigationRoute.start_location_id == location_id) |
        (models.NavigationRoute.end_location_id == location_id)
    ).delete(synchronize_session=False)
    db.delete(db_location)
    db.commit()
    log_activity(db, "deleted", "location", location_id, f"Deleted location '{name}' and its connected routes")
    return {"message": "Location deleted successfully"}

# --- ORGANIZATIONS ---

@admin_router.get("/organizations")
async def get_organizations(db: Session = Depends(get_db)):
    orgs = db.query(models.Organization).all()
    result = []
    for org in orgs:
        member_count = db.query(func.count(models.OrganizationMember.id))\
                        .filter(models.OrganizationMember.org_chart_id == org.id)\
                        .scalar()
        members = db.query(models.OrganizationMember)\
                   .filter(models.OrganizationMember.org_chart_id == org.id)\
                   .order_by(models.OrganizationMember.sort_order)\
                   .all()
        result.append({
            'id': org.id,
            'name': org.name,
            'description': org.description or '',
            'created_at': org.created_at.isoformat() if org.created_at else None,
            'member_count': member_count,   # key JS expects
            'members_count': member_count,  # keep for backward compat
            'members': [
                {
                    'id': m.id,
                    'name': m.name,
                    'position': m.position,
                    'sort_order': m.sort_order or 0
                } for m in members
            ]
        })
    return result

@admin_router.get("/debug/members")
async def debug_members(db: Session = Depends(get_db)):
    all_members = db.query(models.OrganizationMember).all()
    return {
        "total_members": len(all_members),
        "members": [
            {
                "id": m.id,
                "org_chart_id": m.org_chart_id,
                "name": m.name,
                "position": m.position,
                "sort_order": m.sort_order
            }
            for m in all_members
        ]
    }

@admin_router.post("/organizations")
async def create_organization(org: OrganizationCreate, db: Session = Depends(get_db)):
    db_org = models.Organization(
        name=org.name,
        description=org.description,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    db.add(db_org)
    db.commit()
    db.refresh(db_org)
    log_activity(db, "created", "organization", db_org.id, f"Created organization '{db_org.name}'")
    return db_org

@admin_router.put("/organizations/{org_id}")
async def update_organization(org_id: int, org: OrganizationCreate, db: Session = Depends(get_db)):
    db_org = db.query(models.Organization).filter(models.Organization.id == org_id).first()
    if not db_org:
        raise HTTPException(status_code=404, detail="Organization not found")
    db_org.name = org.name
    db_org.description = org.description
    db_org.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_org)
    log_activity(db, "updated", "organization", db_org.id, f"Updated organization '{db_org.name}'")
    return db_org

@admin_router.post("/organization-members")
async def create_organization_member(member: OrganizationMemberCreate, db: Session = Depends(get_db)):
    db_member = models.OrganizationMember(
        org_chart_id=member.organization_id,
        name=member.name,
        position=member.position,
        created_at=datetime.utcnow()
    )
    db.add(db_member)
    db.commit()
    db.refresh(db_member)
    return db_member

@admin_router.get("/organizations/{org_id}/members")
async def get_organization_members(org_id: int, db: Session = Depends(get_db)):
    try:
        org = db.query(models.Organization).filter(models.Organization.id == org_id).first()
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        members = db.query(models.OrganizationMember)\
                    .filter(models.OrganizationMember.org_chart_id == org_id)\
                    .order_by(models.OrganizationMember.sort_order)\
                    .all()
        return [
            {
                "id": m.id,
                "org_chart_id": m.org_chart_id,
                "name": m.name,
                "position": m.position,
                "sort_order": m.sort_order,
                "created_at": m.created_at.isoformat() if m.created_at else None
            }
            for m in members
        ]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@admin_router.post("/organizations/{org_id}/members")
async def add_member_to_organization(org_id: int, member_data: dict, db: Session = Depends(get_db)):
    try:
        org = db.query(models.Organization).filter(models.Organization.id == org_id).first()
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        max_sort = db.query(func.max(models.OrganizationMember.sort_order))\
                    .filter(models.OrganizationMember.org_chart_id == org_id)\
                    .scalar()
        next_sort = (max_sort or 0) + 1
        db_member = models.OrganizationMember(
            org_chart_id=org_id,
            name=member_data.get("name"),
            position=member_data.get("position"),
            sort_order=member_data.get("sort_order", next_sort),
            created_at=datetime.utcnow()
        )
        db.add(db_member)
        db.commit()
        db.refresh(db_member)
        log_activity(db, "created", "member", db_member.id, f"Added member '{db_member.name}' ({db_member.position}) to org ID {org_id}")
        return {
            "id": db_member.id,
            "org_chart_id": db_member.org_chart_id,
            "name": db_member.name,
            "position": db_member.position,
            "sort_order": db_member.sort_order,
            "created_at": db_member.created_at.isoformat() if db_member.created_at else None
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@admin_router.put("/organizations/{org_id}/members/{member_id}")
async def update_organization_member(org_id: int, member_id: int, member_data: dict, db: Session = Depends(get_db)):
    try:
        org = db.query(models.Organization).filter(models.Organization.id == org_id).first()
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        db_member = db.query(models.OrganizationMember).filter(
            models.OrganizationMember.id == member_id,
            models.OrganizationMember.org_chart_id == org_id
        ).first()
        if not db_member:
            raise HTTPException(status_code=404, detail="Member not found")
        if "name" in member_data:
            db_member.name = member_data["name"]
        if "position" in member_data:
            db_member.position = member_data["position"]
        if "sort_order" in member_data:
            db_member.sort_order = member_data["sort_order"]
        db.commit()
        db.refresh(db_member)
        log_activity(db, "updated", "member", db_member.id, f"Updated member '{db_member.name}' ({db_member.position})")
        return {
            "id": db_member.id,
            "org_chart_id": db_member.org_chart_id,
            "name": db_member.name,
            "position": db_member.position,
            "sort_order": db_member.sort_order,
            "created_at": db_member.created_at.isoformat() if db_member.created_at else None
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@admin_router.delete("/organizations/{org_id}/members/{member_id}")
async def delete_organization_member(org_id: int, member_id: int, db: Session = Depends(get_db)):
    try:
        org = db.query(models.Organization).filter(models.Organization.id == org_id).first()
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        db_member = db.query(models.OrganizationMember).filter(
            models.OrganizationMember.id == member_id,
            models.OrganizationMember.org_chart_id == org_id
        ).first()
        if not db_member:
            raise HTTPException(status_code=404, detail="Member not found")
        name = db_member.name
        db.delete(db_member)
        db.commit()
        log_activity(db, "deleted", "member", member_id, f"Deleted member '{name}' from org ID {org_id}")
        return {"message": "Member deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@admin_router.delete("/members/{member_id}")
async def delete_member_by_id(member_id: int, db: Session = Depends(get_db)):
    try:
        db_member = db.query(models.OrganizationMember).filter(
            models.OrganizationMember.id == member_id
        ).first()
        if not db_member:
            raise HTTPException(status_code=404, detail="Member not found")
        name = db_member.name
        org_id = db_member.org_chart_id
        db.delete(db_member)
        db.commit()
        log_activity(db, "deleted", "member", member_id, f"Deleted member '{name}' from org ID {org_id}")
        return {"message": "Member deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@admin_router.delete("/organizations/{org_id}")
async def delete_organization(org_id: int, db: Session = Depends(get_db)):
    db_org = db.query(models.Organization).filter(models.Organization.id == org_id).first()
    if not db_org:
        raise HTTPException(status_code=404, detail="Organization not found")
    name = db_org.name
    db.delete(db_org)
    db.commit()
    log_activity(db, "deleted", "organization", org_id, f"Deleted organization '{name}' and all its members")
    return {"message": "Organization deleted successfully"}

# --- INTENTS ---

@admin_router.get("/intents")
async def get_intents(db: Session = Depends(get_db)):
    try:
        intents = db.query(models.Intent).all()
        return [
            {
                "id": intent.id,
                "intent_type": intent.intent_type,
                "keywords": intent.keywords,
                "response_template": intent.response_template,
                "response_template_tl": getattr(intent, 'response_template_tl', None),
                "created_at": intent.created_at.isoformat() if intent.created_at else None
            }
            for intent in intents
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@admin_router.post("/intents")
async def create_intent(intent_data: dict, db: Session = Depends(get_db)):
    try:
        db_intent = models.Intent(
            intent_type=intent_data.get("intent_type"),
            keywords=intent_data.get("keywords"),
            response_template=intent_data.get("response_template"),
            response_template_tl=intent_data.get("response_template_tl"),
            created_at=datetime.utcnow()
        )
        db.add(db_intent)
        db.commit()
        db.refresh(db_intent)
        log_activity(db, "created", "custom_response", db_intent.id, f"Added custom response '{db_intent.intent_type}'")
        return {
            "id": db_intent.id,
            "intent_type": db_intent.intent_type,
            "keywords": db_intent.keywords,
            "response_template": db_intent.response_template,
            "response_template_tl": getattr(db_intent, 'response_template_tl', None),
            "created_at": db_intent.created_at.isoformat() if db_intent.created_at else None
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@admin_router.put("/intents/{intent_id}")
async def update_intent(intent_id: int, intent_data: dict, db: Session = Depends(get_db)):
    try:
        db_intent = db.query(models.Intent).filter(models.Intent.id == intent_id).first()
        if not db_intent:
            raise HTTPException(status_code=404, detail="Intent not found")
        if "intent_type" in intent_data:
            db_intent.intent_type = intent_data["intent_type"]
        if "keywords" in intent_data:
            db_intent.keywords = intent_data["keywords"]
        if "response_template" in intent_data:
            db_intent.response_template = intent_data["response_template"]
        if "response_template_tl" in intent_data:
            db_intent.response_template_tl = intent_data["response_template_tl"]
        db.commit()
        db.refresh(db_intent)
        log_activity(db, "updated", "custom_response", db_intent.id, f"Updated custom response '{db_intent.intent_type}'")
        return {
            "id": db_intent.id,
            "intent_type": db_intent.intent_type,
            "keywords": db_intent.keywords,
            "response_template": db_intent.response_template,
            "response_template_tl": getattr(db_intent, 'response_template_tl', None),
            "created_at": db_intent.created_at.isoformat() if db_intent.created_at else None
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@admin_router.delete("/intents/{intent_id}")
async def delete_intent(intent_id: int, db: Session = Depends(get_db)):
    try:
        db_intent = db.query(models.Intent).filter(models.Intent.id == intent_id).first()
        if not db_intent:
            raise HTTPException(status_code=404, detail="Intent not found")
        intent_type = db_intent.intent_type
        db.delete(db_intent)
        db.commit()
        log_activity(db, "deleted", "custom_response", intent_id, f"Deleted custom response '{intent_type}'")
        return {"message": "Intent deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# --- 3D MAP UPLOAD ---
# NOTE: the admin UI (admin-script.js handleModel3DUpload) posts to
# "/upload-3d-model" (singular "model"), not "/upload-3d-map" — that
# mismatch was silently breaking every upload (404). Also, uploads
# previously never deactivated older rows, so is_active could end up
# true on more than one row with no defined "current" model.

@admin_router.post("/upload-3d-model")
async def upload_3d_map(
    file: UploadFile = File(...),
    description: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".glb", ".gltf"):
        raise HTTPException(status_code=400, detail="File must be a .glb or .gltf model.")

    MAX_BYTES = 150 * 1024 * 1024  # 150 MB
    try:
        file_content = await file.read()
        if len(file_content) == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")
        if len(file_content) > MAX_BYTES:
            raise HTTPException(status_code=400, detail="File must be under 150 MB.")

        # Only one model should ever be "active" at a time.
        db.query(models.Map3DUpload).filter(models.Map3DUpload.is_active == True).update(
            {models.Map3DUpload.is_active: False}
        )

        db_upload = models.Map3DUpload(
            filename=file.filename,
            original_filename=file.filename,
            file_data=file_content,
            file_size=len(file_content),
            uploaded_at=datetime.utcnow(),
            uploaded_by="Admin",
            description=description,
            is_active=True
        )
        db.add(db_upload)
        db.commit()
        db.refresh(db_upload)
        log_activity(db, "created", "3d_map", db_upload.id, f"Uploaded 3D map '{file.filename}' ({len(file_content) // 1024} KB)")
        return {
            "message": "3D map uploaded successfully",
            "id": db_upload.id,
            "filename": db_upload.filename,
            "size": db_upload.file_size
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"Upload error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@admin_router.get("/3d-maps")
async def get_3d_maps(db: Session = Depends(get_db)):
    maps = db.query(models.Map3DUpload).filter(models.Map3DUpload.is_active == True).all()
    return [
        {
            "id": m.id,
            "filename": m.filename,
            "uploaded_at": m.uploaded_at,
            "description": m.description,
            "size": m.file_size
        } for m in maps
    ]

@admin_router.get("/3d-maps/{map_id}")
async def get_3d_map(map_id: int, db: Session = Depends(get_db)):
    map_file = db.query(models.Map3DUpload).filter(models.Map3DUpload.id == map_id).first()
    if not map_file:
        raise HTTPException(status_code=404, detail="Map not found")
    return StreamingResponse(
        io.BytesIO(map_file.file_data),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={map_file.filename}"}
    )

@admin_router.delete("/3d-maps/{map_id}")
async def delete_3d_map(map_id: int, db: Session = Depends(get_db)):
    map_file = db.query(models.Map3DUpload).filter(models.Map3DUpload.id == map_id).first()
    if not map_file:
        raise HTTPException(status_code=404, detail="Map not found")
    db.delete(map_file)
    db.commit()
    return {"message": "Map deleted successfully"}

@admin_router.post("/3d-maps/{map_id}/activate")
async def activate_3d_map(map_id: int, db: Session = Depends(get_db)):
    map_file = db.query(models.Map3DUpload).filter(models.Map3DUpload.id == map_id).first()
    if not map_file:
        raise HTTPException(status_code=404, detail="Map not found")
    db.query(models.Map3DUpload).filter(models.Map3DUpload.is_active == True).update(
        {models.Map3DUpload.is_active: False}
    )
    map_file.is_active = True
    db.commit()
    log_activity(db, "updated", "3d_map", map_file.id, f"Activated 3D map '{map_file.filename}'")
    return {"message": "Model activated", "id": map_file.id}

@admin_router.get("/model-upload-history")
async def get_model_upload_history(db: Session = Depends(get_db)):
    try:
        maps = db.query(models.Map3DUpload).order_by(
            models.Map3DUpload.uploaded_at.desc()
        ).all()
        return [
            {
                "id": m.id,
                "filename": m.filename,
                "original_filename": m.original_filename,
                "file_size": m.file_size,
                "uploaded_at": m.uploaded_at.isoformat() if m.uploaded_at else None,
                "uploaded_by": m.uploaded_by,
                "description": m.description,
                "is_active": m.is_active,
                "status": "success"  # only successful uploads ever reach this table
            }
            for m in maps
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- ROUTES (NAVIGATION) ---

@admin_router.get("/routes")
async def get_admin_routes(db: Session = Depends(get_db)):
    try:
        routes = db.query(models.NavigationRoute).all()
        result = []
        for route in routes:
            start_loc = db.query(models.RoomLocation).filter(
                models.RoomLocation.id == route.start_location_id
            ).first()
            end_loc = db.query(models.RoomLocation).filter(
                models.RoomLocation.id == route.end_location_id
            ).first()
            result.append({
                "id": route.id,
                "name": route.name,
                "type": route.type,
                "start_location_id": route.start_location_id,
                "start_location_name": start_loc.name if start_loc else "Unknown",
                "end_location_id": route.end_location_id,
                "end_location_name": end_loc.name if end_loc else "Unknown",
                "is_wheelchair_accessible": route.is_wheelchair_accessible,
                "path_color": route.path_color,
                "waypoints": route.waypoints if route.waypoints else [],
                "created_at": route.created_at.isoformat() if route.created_at else None
            })
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@admin_router.post("/routes")
async def create_route(route_data: dict, db: Session = Depends(get_db)):
    try:
        db_route = models.NavigationRoute(
            name=route_data.get("name"),
            type=route_data.get("type", "standard"),
            start_location_id=route_data.get("start_location_id"),
            end_location_id=route_data.get("end_location_id"),
            is_wheelchair_accessible=route_data.get("is_wheelchair_accessible", False),
            path_color=route_data.get("path_color", "#F4D03F"),
            waypoints=route_data.get("waypoints", [])
        )
        db.add(db_route)
        db.commit()
        db.refresh(db_route)
        return {
            "id": db_route.id,
            "name": db_route.name,
            "type": db_route.type,
            "start_location_id": db_route.start_location_id,
            "end_location_id": db_route.end_location_id,
            "is_wheelchair_accessible": db_route.is_wheelchair_accessible,
            "path_color": db_route.path_color,
            "waypoints": db_route.waypoints
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@admin_router.put("/routes/{route_id}")
async def update_route(route_id: int, route_data: dict, db: Session = Depends(get_db)):
    try:
        db_route = db.query(models.NavigationRoute).filter(
            models.NavigationRoute.id == route_id
        ).first()
        if not db_route:
            raise HTTPException(status_code=404, detail="Route not found")
        if "name" in route_data: db_route.name = route_data["name"]
        if "type" in route_data: db_route.type = route_data["type"]
        if "start_location_id" in route_data: db_route.start_location_id = route_data["start_location_id"]
        if "end_location_id" in route_data: db_route.end_location_id = route_data["end_location_id"]
        if "is_wheelchair_accessible" in route_data: db_route.is_wheelchair_accessible = route_data["is_wheelchair_accessible"]
        if "path_color" in route_data: db_route.path_color = route_data["path_color"]
        if "waypoints" in route_data: db_route.waypoints = route_data["waypoints"]
        db.commit()
        db.refresh(db_route)
        return {
            "id": db_route.id,
            "name": db_route.name,
            "type": db_route.type,
            "start_location_id": db_route.start_location_id,
            "end_location_id": db_route.end_location_id,
            "is_wheelchair_accessible": db_route.is_wheelchair_accessible,
            "path_color": db_route.path_color,
            "waypoints": db_route.waypoints
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@admin_router.delete("/routes/{route_id}")
async def delete_route(route_id: int, db: Session = Depends(get_db)):
    try:
        db_route = db.query(models.NavigationRoute).filter(
            models.NavigationRoute.id == route_id
        ).first()
        if not db_route:
            raise HTTPException(status_code=404, detail="Route not found")
        db.delete(db_route)
        db.commit()
        return {"message": "Route deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# --- CREDENTIALS ---

@admin_router.get("/credentials")
async def get_credentials(request: Request, db: Session = Depends(get_db)):
    """
    Returns the current admin username IF the session is valid.
    Used by the frontend as a session liveness check on load.
    Returns 401 if not logged in (expected behaviour — frontend redirects to login).
    NOTE: verify_session is already applied via admin_router Depends,
    so this correctly returns 401 when not authenticated.
    """
    ensure_default_admin(db)
    credential = db.query(models.AdminCredentials).first()
    return {"username": credential.username if credential else "admin"}

# ── Public session-check endpoint (no auth required) ──────────────────────────
# The admin shell JS calls /api/admin/credentials on page load to check if
# already logged in. Since admin_router requires verify_session, it always
# returns 401 on first load (before login). This public endpoint is the
# correct way to do the liveness check without triggering a 401.
@app.get("/api/admin/session-check")
async def session_check(request: Request, db: Session = Depends(get_db)):
    """
    Lightweight session validity check — no 401, just returns is_authenticated.
    Frontend uses this instead of /credentials to avoid spurious 401 logs.
    """
    username = request.session.get("username")
    if not username:
        return {"authenticated": False}
    expires_at = request.session.get("expires_at")
    from datetime import datetime as _dt
    if expires_at and _dt.utcnow().isoformat() > expires_at:
        request.session.clear()
        return {"authenticated": False}
    return {"authenticated": True, "username": username}

@admin_router.put("/credentials")
async def update_credentials(request: AdminCredentialUpdate, db: Session = Depends(get_db)):
    ensure_default_admin(db)
    credential = db.query(models.AdminCredentials).filter(
        models.AdminCredentials.username == request.current_username
    ).first()
    if not credential or not verify_password(request.current_password, credential.password_hash):
        raise HTTPException(status_code=401, detail="Current username or password is incorrect")
    if request.new_username:
        existing = db.query(models.AdminCredentials).filter(
            models.AdminCredentials.username == request.new_username,
            models.AdminCredentials.id != credential.id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Username already taken")
        credential.username = request.new_username
    if request.new_password:
        credential.password_hash = hash_password(request.new_password)
    credential.updated_at = datetime.utcnow()
    db.commit()
    return {"success": True, "message": "Credentials updated successfully"}

# --- ANNOUNCEMENT POPUPS (ADMIN) ---

@admin_router.get("/announcement-popups")
async def admin_get_popups(db: Session = Depends(get_db)):
    try:
        popups = db.query(models.AnnouncementPopup).order_by(
            models.AnnouncementPopup.priority.desc(),
            models.AnnouncementPopup.created_at.desc()
        ).all()
        return [
            {
                "id":             p.id,
                "title":          p.title,
                "content":        p.content,
                "category":       p.category,
                "image_data":     p.image_data,
                "image_filename": p.image_filename,
                "is_active":      p.is_active,
                "is_archived":    getattr(p, "is_archived", False) or False,
                "priority":       p.priority,
                "scheduled_at":   p.scheduled_at.isoformat() if getattr(p, "scheduled_at", None) else None,
                "expires_at":     p.expires_at.isoformat()   if getattr(p, "expires_at",   None) else None,
                "created_at":     p.created_at.isoformat()   if p.created_at else None,
                "updated_at":     p.updated_at.isoformat()   if p.updated_at else None,
            }
            for p in popups
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@admin_router.post("/announcement-popups")
async def create_popup(
    title: str = Form(...),
    content: str = Form(""),
    category: str = Form("General"),
    is_active: str = Form("true"),
    priority: int = Form(0),
    scheduled_at: Optional[str] = Form(None),
    expires_at:   Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    try:
        image_data = None
        image_filename = None
        if image and image.filename:
            raw = await image.read()
            import base64
            b64 = base64.b64encode(raw).decode("utf-8")
            mime = image.content_type or "image/jpeg"
            image_data = f"data:{mime};base64,{b64}"
            image_filename = image.filename

        # Parse datetime strings (ISO format from datetime-local input)
        from datetime import datetime as _dt
        def _parse_dt(s):
            if not s or not s.strip(): return None
            try:
                # Handle both "2025-01-15T10:30" and "2025-01-15T10:30:00"
                return _dt.fromisoformat(s.strip())
            except ValueError:
                return None

        popup = models.AnnouncementPopup(
            title=title,
            content=content,
            category=category,
            is_active=(is_active.lower() == "true"),
            is_archived=False,
            priority=priority,
            scheduled_at=_parse_dt(scheduled_at),
            expires_at=_parse_dt(expires_at),
            image_data=image_data,
            image_filename=image_filename,
        )
        db.add(popup)
        db.commit()
        db.refresh(popup)
        return {"id": popup.id, "message": "Popup announcement created successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@admin_router.put("/announcement-popups/{popup_id}")
async def update_popup(
    popup_id: int,
    title: str = Form(...),
    content: str = Form(""),
    category: str = Form("General"),
    is_active: str = Form("true"),
    is_archived: str = Form("false"),
    priority: int = Form(0),
    scheduled_at: Optional[str] = Form(None),
    expires_at:   Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    try:
        popup = db.query(models.AnnouncementPopup).filter(models.AnnouncementPopup.id == popup_id).first()
        if not popup:
            raise HTTPException(status_code=404, detail="Popup not found")

        from datetime import datetime as _dt
        def _parse_dt(s):
            if not s or not s.strip(): return None
            try: return _dt.fromisoformat(s.strip())
            except ValueError: return None

        popup.title       = title
        popup.content     = content
        popup.category    = category
        popup.is_active   = (is_active.lower() == "true")
        popup.is_archived = (is_archived.lower() == "true")
        popup.priority    = priority
        popup.scheduled_at = _parse_dt(scheduled_at)
        popup.expires_at   = _parse_dt(expires_at)
        popup.updated_at   = datetime.utcnow()

        if image and image.filename:
            raw = await image.read()
            import base64
            b64 = base64.b64encode(raw).decode("utf-8")
            mime = image.content_type or "image/jpeg"
            popup.image_data     = f"data:{mime};base64,{b64}"
            popup.image_filename = image.filename

        db.commit()
        return {"message": "Popup updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@admin_router.patch("/announcement-popups/{popup_id}")
async def patch_popup(popup_id: int, request: Request, db: Session = Depends(get_db)):
    """PATCH endpoint — accepts JSON body for partial updates like archiving."""
    try:
        data  = await request.json()
        popup = db.query(models.AnnouncementPopup).filter(
            models.AnnouncementPopup.id == popup_id).first()
        if not popup:
            raise HTTPException(status_code=404, detail="Popup not found")
        if "is_archived" in data:
            popup.is_archived = bool(data["is_archived"])
        if "is_active" in data:
            popup.is_active   = bool(data["is_active"])
        if "title"   in data: popup.title   = data["title"]
        if "content" in data: popup.content = data["content"]
        popup.updated_at = datetime.utcnow()
        db.commit()
        return {"message": "Popup updated", "id": popup_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@admin_router.patch("/announcement-popups/{popup_id}/toggle")
async def toggle_popup(popup_id: int, db: Session = Depends(get_db)):
    try:
        popup = db.query(models.AnnouncementPopup).filter(models.AnnouncementPopup.id == popup_id).first()
        if not popup:
            raise HTTPException(status_code=404, detail="Popup not found")
        popup.is_active = not popup.is_active
        popup.updated_at = datetime.utcnow()
        db.commit()
        return {"message": f"Popup {'activated' if popup.is_active else 'deactivated'}", "is_active": popup.is_active}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@admin_router.delete("/announcement-popups/{popup_id}")
async def delete_popup(popup_id: int, db: Session = Depends(get_db)):
    try:
        popup = db.query(models.AnnouncementPopup).filter(models.AnnouncementPopup.id == popup_id).first()
        if not popup:
            raise HTTPException(status_code=404, detail="Popup not found")
        db.delete(popup)
        db.commit()
        return {"message": "Popup deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# FAQ DOCUMENTS (ADMIN) — PDF upload & management
# ============================================

def _extract_text_from_pdf(file_bytes: bytes) -> Tuple[str, int]:
    """
    Extract all text from a PDF and return (text, page_count).

    Uses pdfplumber with column-aware extraction:
    - Pages whose content spans two columns (like the Core Values section)
      are split at the vertical midpoint and the left column is read before
      the right column, producing correct reading order.
    - Single-column pages (Q&A sections) are extracted normally.
    - Falls back to pypdf if pdfplumber is unavailable.
    """
    import io as _io

    # ── pdfplumber path (preferred) ──────────────────────────────────────────
    try:
        import pdfplumber  # type: ignore[import-untyped]

        page_texts = []
        with pdfplumber.open(_io.BytesIO(file_bytes)) as pdf:
            page_count = len(pdf.pages)
            for page in pdf.pages:
                width  = page.width
                height = page.height
                mid    = width / 2

                # Heuristic: check if the page has two distinct text columns.
                # We do this by extracting left and right halves and seeing if
                # BOTH have substantial content — if so, it's a 2-column page.
                left_words  = page.within_bbox((0,    0, mid,   height)).extract_words()
                right_words = page.within_bbox((mid,  0, width, height)).extract_words()

                # A column is "substantial" if it has >10 word tokens
                left_sub  = len(left_words)  > 10
                right_sub = len(right_words) > 10

                if left_sub and right_sub:
                    # Check whether the two columns are truly separate columns
                    # (not just a header spanning full width).
                    # We compare the x-positions: real 2-column layout has left
                    # words mostly < mid and right words mostly > mid.
                    left_x_ok  = sum(1 for w in left_words  if float(w['x0']) < mid)  > len(left_words)  * 0.6
                    right_x_ok = sum(1 for w in right_words if float(w['x0']) >= mid) > len(right_words) * 0.6

                    if left_x_ok and right_x_ok:
                        # Genuine 2-column layout — read left then right
                        left_text  = page.within_bbox((0,   0, mid,   height)).extract_text() or ''
                        right_text = page.within_bbox((mid, 0, width, height)).extract_text() or ''
                        page_texts.append(left_text.strip() + '\n' + right_text.strip())
                        continue

                # Default: single-column or full-width content
                text = page.extract_text() or ''
                page_texts.append(text)

        return '\n\n'.join(page_texts), page_count

    except ImportError:
        pass  # fall through to pypdf
    except Exception as exc:
        print(f"[pdf_extract] pdfplumber failed ({exc}), falling back to pypdf")

    # ── pypdf fallback ───────────────────────────────────────────────────────
    try:
        from pypdf import PdfReader
        reader = PdfReader(_io.BytesIO(file_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages), len(reader.pages)
    except Exception as exc:
        raise ValueError(f"PDF text extraction failed: {exc}")

@admin_router.get("/faq-documents")
async def list_faq_documents(db: Session = Depends(get_db)):
    """List all FAQ PDF documents stored in the database."""
    docs = db.query(models.FAQDocument).order_by(
        models.FAQDocument.uploaded_at.desc()
    ).all()
    return [
        {
            "id": d.id,
            "title": d.title,
            "filename": d.filename,
            "page_count": d.page_count,
            "file_size": d.file_size,
            "is_active": d.is_active,
            "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
            "text_preview": (d.extracted_text or "")[:300] + "…" if d.extracted_text else "",
        }
        for d in docs
    ]

@admin_router.post("/faq-documents")
async def upload_faq_document(
    title: str = Form(...),
    pdf: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a PDF and extract its text for use by SPARTA's FAQ chatbot."""
    if not pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    raw = await pdf.read()
    if len(raw) > 10 * 1024 * 1024:  # 10 MB limit
        raise HTTPException(status_code=400, detail="PDF must be under 10 MB.")

    try:
        text, page_count = _extract_text_from_pdf(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if not text.strip():
        raise HTTPException(status_code=422, detail="Could not extract text from this PDF. Make sure it is not scanned/image-only.")

    doc = models.FAQDocument(
        title=title.strip(),
        filename=pdf.filename,
        extracted_text=text,
        file_size=len(raw),
        page_count=page_count,
        is_active=True,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Invalidate RAG cache so new FAQ content is picked up
    from rag_chatbot import invalidate_rag_cache
    from faq_retriever import invalidate_faq_cache
    invalidate_rag_cache('faq_documents', doc.id)
    invalidate_faq_cache()

    return {
        "id": doc.id,
        "message": f"PDF '{pdf.filename}' uploaded successfully ({page_count} pages, {len(text)} characters extracted).",
    }

@admin_router.put("/faq-documents/{doc_id}")
async def update_faq_document(
    doc_id: int,
    title: str = Form(...),
    pdf: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    """Update the title and optionally replace the PDF file."""
    faq = db.query(models.FAQDocument).filter(models.FAQDocument.id == doc_id).first()
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ document not found.")

    faq.title = title.strip()
    faq.updated_at = datetime.utcnow()

    if pdf and pdf.filename:
        if not pdf.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are accepted.")
        raw = await pdf.read()
        try:
            text, page_count = _extract_text_from_pdf(raw)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        faq.extracted_text = text
        faq.filename = pdf.filename
        faq.file_size = len(raw)
        faq.page_count = page_count

    db.commit()
    from rag_chatbot import invalidate_rag_cache
    from faq_retriever import invalidate_faq_cache
    invalidate_rag_cache('faq_documents', doc_id)
    invalidate_faq_cache()
    return {"message": "FAQ document updated successfully."}

@admin_router.patch("/faq-documents/{doc_id}/toggle")
async def toggle_faq_document(doc_id: int, db: Session = Depends(get_db)):
    for attempt in range(2):
        try:
            db.execute(text("SELECT 1"))
            faq = db.query(models.FAQDocument).filter(models.FAQDocument.id == doc_id).first()
            if not faq:
                raise HTTPException(status_code=404, detail="FAQ document not found.")
            faq.is_active = not faq.is_active
            faq.updated_at = datetime.utcnow()
            db.commit()
            return {"is_active": faq.is_active, "message": f"FAQ document {'activated' if faq.is_active else 'deactivated'}."}
        except HTTPException:
            raise
        except Exception as e:
            if attempt == 0:
                db.rollback()
                continue
            raise HTTPException(status_code=503, detail=str(e))

@admin_router.delete("/faq-documents/{doc_id}")
async def delete_faq_document(doc_id: int, db: Session = Depends(get_db)):
    for attempt in range(2):
        try:
            db.execute(text("SELECT 1"))
            faq = db.query(models.FAQDocument).filter(models.FAQDocument.id == doc_id).first()
            if not faq:
                raise HTTPException(status_code=404, detail="FAQ document not found.")
            db.delete(faq)
            db.commit()
            from rag_chatbot import invalidate_rag_cache
            from faq_retriever import invalidate_faq_cache
            invalidate_rag_cache('faq_documents')
            invalidate_faq_cache()
            return {"message": "FAQ document deleted."}
        except HTTPException:
            raise
        except Exception as e:
            if attempt == 0:
                print(f"[delete-faq] DB error, retrying: {e}")
                db.rollback()
                continue
            raise HTTPException(status_code=503, detail=str(e))

# ============================================
# HEALTH CHECK (PUBLIC)
# ============================================


@app.get("/api/3d-model-file")
async def get_active_3d_model_file(db: Session = Depends(get_db)):
    """
    PUBLIC (no auth) — streams the bytes of whichever Map3DUpload row is
    currently marked is_active. This is what the campus navigator actually
    fetches when an admin has uploaded a model via the dashboard. The
    existing /api/admin/3d-maps/{id} route can't be used for this because
    it sits behind admin_router's login requirement, and the navigator is
    a public page.
    """
    map_row = (
        db.query(models.Map3DUpload)
        .filter(models.Map3DUpload.is_active == True)
        .order_by(models.Map3DUpload.uploaded_at.desc())
        .first()
    )
    if not map_row:
        raise HTTPException(status_code=404, detail="No active 3D model uploaded.")
    return StreamingResponse(
        io.BytesIO(map_row.file_data),
        media_type="model/gltf-binary",
        headers={"Content-Disposition": f"inline; filename={map_row.filename or 'model.glb'}"}
    )


@app.get("/api/active-3d-model")
async def get_active_3d_model(db: Session = Depends(get_db)):
    """
    Returns the active 3D campus model path. Priority order:
      1. A model uploaded via the admin dashboard (map_3d_uploads table)
      2. A custom glb_model_url saved directly in campus_settings
      3. The default static file shipped with the app
    """
    try:
        map_row = (
            db.query(models.Map3DUpload)
            .filter(models.Map3DUpload.is_active == True)
            .order_by(models.Map3DUpload.uploaded_at.desc())
            .first()
        )
        if map_row:
            cache_buster = (
                str(int(map_row.uploaded_at.timestamp())) if map_row.uploaded_at else str(map_row.id)
            )
            return {
                "path": f"/api/3d-model-file?v={cache_buster}",
                "source": "admin_upload",
                "cache_buster": cache_buster
            }
    except Exception as e:
        print(f"[active-3d-model] Map3DUpload lookup failed: {e}")

    try:
        row = db.execute(
            text("SELECT value FROM campus_settings WHERE key = 'glb_model_url'")
        ).fetchone()
        if row and row[0] and row[0].startswith("http"):
            # Custom URL saved in settings
            return {
                "path": row[0],
                "source": "settings",
                "cache_buster": None
            }
    except Exception:
        pass

    # Default: serve from /static/ on this same server
    import time as _t
    base_url = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
    if base_url:
        base_url = f"https://{base_url}"
    else:
        base_url = ""  # relative URL — works when frontend is same origin

    default_glb = f"{base_url}/static/batangas_state_university-_the_neu_lipa_map.glb"
    return {
        "path": default_glb,
        "source": "default",
        "cache_buster": str(int(_t.time()))
    }


@app.get("/health")
async def health_check():
    from gemini_handler import GEMINI_ENABLED
    return {
        "status": "healthy",
        "rag_enabled": True,
        "model_loaded": True,
        "model_name": "gemini-embedding-exp-03-07 (API)",
        "gemini_enabled": GEMINI_ENABLED,
        "version": "3.0-Gemini-RAG"
    }

# ============================================
# STATISTICS ENDPOINT (ADMIN)
# ============================================

@admin_router.get("/statistics")
def get_statistics(db: Session = Depends(get_db)):
    from datetime import date, timedelta
    from sqlalchemy import func, text, cast, Date, case

    today_date = date.today()
    yesterday  = today_date - timedelta(days=1)

    # ── Basic counts ────────────────────────────────────────────────
    total = db.query(models.SearchLog).count()
    today = db.query(models.SearchLog).filter(
        cast(models.SearchLog.searched_at, Date) == today_date
    ).count()
    yesterday_count = db.query(models.SearchLog).filter(
        cast(models.SearchLog.searched_at, Date) == yesterday
    ).count()

    # ── Confidence distribution (low / mid / high) ───────────────────
    # low  = confidence < 0.50
    # mid  = 0.50 – 0.79
    # high = >= 0.80
    conf_low  = db.query(models.SearchLog).filter(
        models.SearchLog.confidence < 0.50
    ).count()
    conf_mid  = db.query(models.SearchLog).filter(
        models.SearchLog.confidence >= 0.50,
        models.SearchLog.confidence <  0.80
    ).count()
    conf_high = db.query(models.SearchLog).filter(
        models.SearchLog.confidence >= 0.80
    ).count()

    # ── Fallback rate ────────────────────────────────────────────────
    # A query is a "fallback" if intent == 'general_info' OR confidence < 0.55
    fallback_count = db.query(models.SearchLog).filter(
        (models.SearchLog.intent == 'general_info') |
        (models.SearchLog.confidence < 0.55)
    ).count()
    fallback_rate = round((fallback_count / total * 100), 1) if total else 0.0

    # ── Language split ───────────────────────────────────────────────
    lang_en = db.query(models.SearchLog).filter(
        models.SearchLog.language == 'en'
    ).count()
    lang_tl = db.query(models.SearchLog).filter(
        models.SearchLog.language.in_(['tl', 'fil', 'fi'])
    ).count()

    # ── Daily active users (distinct days with queries, last 7 days) ──
    seven_days_ago = today_date - timedelta(days=7)
    dau_rows = db.query(
        func.count(models.SearchLog.id).label('cnt')
    ).filter(
        cast(models.SearchLog.searched_at, Date) >= seven_days_ago
    ).first()
    dau = round((dau_rows.cnt or 0) / 7) if dau_rows else 0

    # ── Sessions (from user_sessions table if it exists) ─────────────
    try:
        from sqlalchemy import text as _text
        sess_row = db.execute(_text("""
            SELECT
                COUNT(*)                                            AS total,
                COALESCE(AVG(NULLIF(query_count, 0)), 0)            AS avg_q,
                COUNT(*) FILTER (
                    WHERE last_active >= NOW() - INTERVAL '30 minutes'
                )                                                   AS active_now
            FROM user_sessions
        """)).fetchone()
        total_sessions  = int(sess_row[0]) if sess_row else 0
        active_sessions = int(sess_row[2]) if sess_row else 0

        # FIX: query_count is unreliable (NULL/0 for old sessions).
        # Compute queries_per_session from actual search logs ÷ total sessions.
        # Falls back to AVG(query_count) only if no sessions exist yet.
        if total_sessions > 0:
            avg_queries_sess = round(total / total_sessions, 1)
        else:
            avg_queries_sess = round(float(sess_row[1] or 0), 1) if sess_row else 0
    except Exception:
        total_sessions   = 0
        avg_queries_sess = 0
        active_sessions  = 0

    # ── Nav statistics summary for dashboard ─────────────────────────
    try:
        nav_row = db.execute(_text("""
            SELECT
                COUNT(*)                                       AS total,
                COUNT(DISTINCT entity_name)                    AS unique_locs,
                COUNT(*) FILTER (WHERE searched_at::date = CURRENT_DATE) AS today
            FROM search_logs
            WHERE intent = 'navigation_query' OR intent = 'location_query'
        """)).fetchone()
        nav_total_qs   = int(nav_row[0]) if nav_row else 0
        nav_unique_loc = int(nav_row[1]) if nav_row else 0
        nav_today      = int(nav_row[2]) if nav_row else 0
    except Exception:
        nav_total_qs   = 0
        nav_unique_loc = 0
        nav_today      = 0

    # ── Trend % vs yesterday ─────────────────────────────────────────
    if yesterday_count and yesterday_count > 0:
        trend_pct = round((today - yesterday_count) / yesterday_count * 100, 1)
    else:
        trend_pct = 0.0

    # ── Intent breakdown ─────────────────────────────────────────────
    intent_breakdown = db.query(
        models.SearchLog.intent,
        func.count().label('count')
    ).group_by(models.SearchLog.intent).order_by(func.count().desc()).limit(10).all()
    top_intent = intent_breakdown[0][0] if intent_breakdown else None

    # ── Top entities ─────────────────────────────────────────────────
    top_entities = db.query(
        models.SearchLog.entity_name, func.count().label('count')
    ).filter(models.SearchLog.entity_name != None).group_by(
        models.SearchLog.entity_name
    ).order_by(func.count().desc()).limit(10).all()

    # ── Recent queries ───────────────────────────────────────────────
    recent = db.query(models.SearchLog).order_by(
        models.SearchLog.searched_at.desc()
    ).limit(20).all()

    # ── FAQ utilization (top docs referenced via search_logs intent) ──
    try:
        faq_docs = db.query(models.FAQDocument).filter(
            models.FAQDocument.is_active == True
        ).all()
        # Use page_count as a meaningful size metric for the utilization chart
        faq_util = [{"title": d.title[:28], "count": d.page_count or 1}
                    for d in faq_docs[:8]]
    except Exception:
        faq_util = []

    # ── Nav success rate ─────────────────────────────────────────────────────
    nav_total   = db.query(models.SearchLog).filter(
        models.SearchLog.intent.in_(['location_query', 'navigation_query', 'navigation'])
    ).count()
    nav_success = db.query(models.SearchLog).filter(
        models.SearchLog.intent.in_(['location_query', 'navigation_query', 'navigation']),
        models.SearchLog.confidence >= 0.60
    ).count()
    _nav_success_rate = round(nav_success / nav_total, 3) if nav_total > 0 else 0.0

    return {
        "total_queries":          total,
        "queries_today":          today,
        "yesterday_queries":      yesterday_count,
        "trend_pct":              trend_pct,
        "fallback_rate":          fallback_rate,
        "fallback_count":         fallback_count,
        "daily_active_users":     dau,
        "avg_queries_per_session": avg_queries_sess,
        "total_sessions":          total_sessions,
        "active_sessions":         active_sessions,
        "nav_stats": {
            "total_queries":    nav_total_qs,
            "unique_locations": nav_unique_loc,
            "today_queries":    nav_today,
        },
        "avg_confidence":         float(db.query(func.avg(models.SearchLog.confidence)).scalar() or 0),
        "confidence_distribution": {
            "low":  conf_low,
            "mid":  conf_mid,
            "high": conf_high
        },
        "language_split": {
            "english":  lang_en,
            "filipino": lang_tl
        },
        "nav_success_rate":  _nav_success_rate,
        "faq_utilization":   faq_util,
        "top_intent":        top_intent,
        "intent_breakdown":  [{"intent": r[0], "count": r[1]} for r in intent_breakdown],
        "top_entities":      [{"entity": r[0], "count": r[1]} for r in top_entities],
        "recent_queries":    [
            {
                "query":       r.query,
                "intent":      r.intent,
                "confidence":  r.confidence,
                "language":    r.language,
                "searched_at": r.searched_at.isoformat() if r.searched_at else None
            }
            for r in recent
        ]
    }




# ── Heatmap endpoint ─────────────────────────────────────────────────────────

@admin_router.get("/statistics/heatmap")
def get_heatmap(
    from_date: str = None,
    to_date: str = None,
    db: Session = Depends(get_db)
):
    """
    Returns a 24x7 heatmap of query counts by hour (0-23) and day of week (0=Mon..6=Sun).
    Accepts optional from/to date strings (YYYY-MM-DD).
    """
    from datetime import date, timedelta, datetime
    try:
        today = date.today()
        dt_from = datetime.strptime(from_date, "%Y-%m-%d") if from_date else datetime(today.year, today.month, 1)
        dt_to   = datetime.strptime(to_date,   "%Y-%m-%d").replace(hour=23, minute=59, second=59) if to_date else datetime.combine(today, datetime.max.time())

        rows = db.execute(text("""
            SELECT
                EXTRACT(HOUR FROM searched_at)::int      AS hr,
                EXTRACT(DOW  FROM searched_at)::int      AS dow
            FROM search_logs
            WHERE searched_at >= :from_dt
              AND searched_at <= :to_dt
        """), {"from_dt": dt_from, "to_dt": dt_to}).fetchall()

        # DOW in postgres: 0=Sunday..6=Saturday — convert to 0=Mon..6=Sun
        grid = [[0]*7 for _ in range(24)]
        for hr, dow in rows:
            mon_based = (dow - 1) % 7   # Sun(0)->6, Mon(1)->0 ... Sat(6)->5
            if 0 <= hr <= 23 and 0 <= mon_based <= 6:
                grid[hr][mon_based] += 1

        return {"heatmap": grid, "from": str(dt_from.date()), "to": str(dt_to.date()), "total": sum(sum(r) for r in grid)}
    except Exception as e:
        # Return empty grid on error so frontend falls back to synthetic
        return {"heatmap": [[0]*7 for _ in range(24)], "error": str(e)}


# ── Navigation statistics endpoint ───────────────────────────────────────────

@admin_router.get("/nav-statistics")
def get_nav_statistics(db: Session = Depends(get_db)):
    import datetime as _dt
    from collections import Counter

    today = _dt.date.today()
    # FIX: RAG saves intent as "location_query" not "navigation".
    # Previous filter == "navigation" returned 0 rows every time.
    nav_logs = db.query(models.SearchLog).filter(
        models.SearchLog.intent.in_(["location_query", "navigation_query", "navigation"])
    ).all()

    total_searches   = len(nav_logs)
    today_searches   = sum(1 for l in nav_logs if l.searched_at and l.searched_at.date() == today)
    unique_locations = len(set(l.entity_name for l in nav_logs if l.entity_name))

    name_counts  = Counter(l.entity_name for l in nav_logs if l.entity_name)
    top_locs     = [{"name": n, "count": c} for n, c in name_counts.most_common(8)]
    top_location = top_locs[0]["name"] if top_locs else None

    type_counts: Counter = Counter()
    try:
        loc_rows = db.query(models.RoomLocation).all()
        loc_map  = {l.name.lower(): l.type for l in loc_rows}
        for log in nav_logs:
            if log.entity_name:
                type_counts[loc_map.get(log.entity_name.lower(), "other")] += 1
    except Exception:
        pass

    type_breakdown  = [{"type": t, "count": c} for t, c in type_counts.most_common()]
    recent_logs     = sorted(nav_logs, key=lambda l: l.searched_at or _dt.datetime.min, reverse=True)[:20]

    recent_searches = []
    try:
        loc_detail = {l.name.lower(): l for l in db.query(models.RoomLocation).all()}
        for log in recent_logs:
            d = loc_detail.get((log.entity_name or "").lower())
            recent_searches.append({
                "name":        log.entity_name or "—",
                "type":        d.type     if d else "—",
                "floor":       d.floor    if d else None,
                "building":    d.building if d else "—",
                "searched_at": log.searched_at.isoformat() if log.searched_at else None,
            })
    except Exception:
        recent_searches = [{"name": l.entity_name or "—", "type": "—", "floor": None,
                            "building": "—",
                            "searched_at": l.searched_at.isoformat() if l.searched_at else None}
                           for l in recent_logs]

    return {
        "total_searches":   total_searches,
        "today_searches":   today_searches,
        "unique_locations": unique_locations,
        "top_location":     top_location or "—",
        "top_locations":    top_locs,
        "type_breakdown":   type_breakdown,
        "recent_searches":  recent_searches,
    }


# ── Intent health endpoint ───────────────────────────────────────────────────

@admin_router.get("/intents/health")
def get_intent_health(db: Session = Depends(get_db)):
    """
    Per-intent analytics computed from search_logs:
      - triggers     : total times this intent was matched
      - avg_conf     : average confidence when matched (0–100)
      - fallback_pct : % of matches where confidence < 0.55 OR intent == general_info
      - status       : healthy / needswork / highfallback / dead
    """
    from sqlalchemy import func

    rows = db.query(
        models.SearchLog.intent,
        func.count().label('triggers'),
        func.avg(models.SearchLog.confidence).label('avg_conf'),
    ).filter(
        models.SearchLog.intent != None
    ).group_by(
        models.SearchLog.intent
    ).order_by(func.count().desc()).all()

    if not rows:
        return []

    results = []
    for row in rows:
        intent_name = row[0] or 'unknown'
        triggers    = row[1] or 0
        avg_conf    = float(row[2] or 0)

        # Count fallback occurrences for this intent
        # A log entry is a fallback if: intent is general_info, OR confidence < 0.55
        if intent_name == 'general_info':
            fallback_for_intent = triggers   # every general_info hit is a fallback
        else:
            fallback_for_intent = db.query(models.SearchLog).filter(
                models.SearchLog.intent == intent_name,
                models.SearchLog.confidence < 0.55
            ).count()

        fallback_pct = round(fallback_for_intent / triggers * 100) if triggers else 0
        conf_pct     = round(avg_conf * 100)

        # Determine status
        if triggers == 0:
            status = 'dead'
        elif fallback_pct >= 50 or intent_name == 'general_info':
            status = 'highfallback'
        elif fallback_pct >= 20 or conf_pct < 65:
            status = 'needswork'
        else:
            status = 'healthy'

        results.append({
            "name":     intent_name,
            "triggers": triggers,
            "conf":     conf_pct,
            "fallback": fallback_pct,
            "status":   status
        })

    # Also include configured intents that have 0 hits (dead configs)
    try:
        configured_intents = db.query(models.Intent.intent_type).all()
        seen = {r["name"] for r in results}
        for row in configured_intents:
            iname = row[0]
            if iname and iname not in seen:
                results.append({
                    "name": iname, "triggers": 0,
                    "conf": 0, "fallback": 100, "status": "dead"
                })
    except Exception:
        pass

    return results

# ============================================
# ACTIVITY LOGS ENDPOINT (ADMIN)
# ============================================

@admin_router.get("/activity-logs")
def get_activity_logs(
    limit: int = 50,
    resource: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Return the most recent admin activity log entries."""
    try:
        q = db.query(models.ActivityLog).order_by(models.ActivityLog.performed_at.desc())
        if resource:
            q = q.filter(models.ActivityLog.resource == resource)
        logs = q.limit(min(limit, 200)).all()
        return [
            {
                "id":           l.id,
                "action":       l.action,
                "resource":     l.resource,
                "resource_id":  l.resource_id,
                "detail":       l.detail,
                "performed_by": l.performed_by,
                "performed_at": l.performed_at.isoformat() if l.performed_at else None,
            }
            for l in logs
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# MEMBER SHORTCUT — PUT /members/{id}
# (JS calls this from the Edit Member modal)
# ============================================

@admin_router.put("/members/{member_id}")
async def update_member_by_id(member_id: int, member_data: dict, db: Session = Depends(get_db)):
    """Update a member by ID without needing org_id in the URL."""
    try:
        db_member = db.query(models.OrganizationMember).filter(
            models.OrganizationMember.id == member_id
        ).first()
        if not db_member:
            raise HTTPException(status_code=404, detail="Member not found")
        if "name" in member_data:
            db_member.name = member_data["name"]
        if "position" in member_data:
            db_member.position = member_data["position"]
        if "sort_order" in member_data:
            db_member.sort_order = member_data["sort_order"]
        db.commit()
        db.refresh(db_member)
        log_activity(db, "updated", "member", db_member.id, f"Updated member '{db_member.name}' ({db_member.position})")
        return {
            "id": db_member.id,
            "org_chart_id": db_member.org_chart_id,
            "name": db_member.name,
            "position": db_member.position,
            "sort_order": db_member.sort_order,
            "created_at": db_member.created_at.isoformat() if db_member.created_at else None
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# SESSIONS STUB (no DB storage needed)
# ============================================

@admin_router.post("/upload-photo")
async def upload_authority_photo(
    photo: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Receives an image file, validates it, uploads to Cloudinary,
    and returns the secure_url. Keeps Cloudinary secrets server-side.
    """
    # --- validation ---
    ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
    if photo.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid file type '{photo.content_type}'. Only JPG, PNG or WebP are allowed."
        )
    raw = await photo.read()
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Photo exceeds 5MB limit.")
    if len(raw) < 100:
        raise HTTPException(status_code=422, detail="File appears to be empty or corrupt.")

    # --- upload to Cloudinary ---
    secure_url = upload_to_cloudinary(raw, photo.filename or "photo.jpg", folder="sparta/authorities")
    return {"url": secure_url}


@admin_router.get("/sessions")
async def get_sessions(db: Session = Depends(get_db)):
    """Real user session data from user_sessions table."""
    try:
        # FIX: Mark stale sessions as inactive inline before querying.
        # Old code never set status=inactive so ALL sessions showed as active forever.
        # A session is considered inactive if last_active was > 30 minutes ago.
        try:
            db.execute(text("""
                UPDATE user_sessions
                SET status = 'inactive'
                WHERE status = 'active'
                  AND last_active < NOW() - INTERVAL '30 minutes'
            """))
            db.commit()
        except Exception as _ue:
            db.rollback()
            print(f"[sessions] stale-update skipped: {_ue}")

        rows = db.execute(text("""
            SELECT session_id, started_at, last_active, ended_at,
                   query_count, language, device, status, ip_address
            FROM user_sessions
            ORDER BY last_active DESC NULLS LAST
            LIMIT 200
        """)).fetchall()

        sessions = []
        from datetime import datetime as _dt, timezone as _tz
        now = _dt.now(_tz.utc)

        def _to_utc(dt):
            """Normalize a datetime to UTC-aware, handling both naive and aware."""
            if dt is None:
                return None
            if dt.tzinfo is None:
                return dt.replace(tzinfo=_tz.utc)
            return dt.astimezone(_tz.utc)

        # Count actual search logs per session for accurate query counts
        try:
            log_counts = {row[0]: row[1] for row in db.execute(text("""
                SELECT session_id, COUNT(*) FROM search_logs
                WHERE session_id IS NOT NULL
                GROUP BY session_id
            """)).fetchall()}
        except Exception:
            log_counts = {}

        for r in rows:
            started   = _to_utc(r[1])
            last_act  = _to_utc(r[2])
            ended     = _to_utc(r[3])
            q_count   = log_counts.get(r[0], r[4] or 0)  # prefer actual search_logs count
            lang      = r[5] or "en"
            device    = r[6] or "—"
            status    = r[7] or "active"
            ip_addr   = r[8] or "—"

            # FIX: Use last_active as fallback for started if started is NULL (old rows)
            effective_start = started or last_act
            end_time = ended or last_act or now
            if effective_start:
                secs = int((end_time - effective_start).total_seconds())
                secs = max(secs, 0)
                if secs == 0:     dur = "< 1m"
                elif secs < 60:  dur = f"{secs}s"
                elif secs < 3600: dur = f"{secs//60}m {secs%60}s"
                else:             dur = f"{secs//3600}h {(secs%3600)//60}m"
            else:
                dur = "—"

            # FIX: compute active_now from last_active timestamp, not stored status
            # Sessions active within the last 30 minutes are truly "active"
            is_truly_active = (
                last_act is not None and
                (now - last_act).total_seconds() < 1800
            )

            sessions.append({
                "session_id":  r[0],
                # FIX: fall back to last_active if started_at is NULL (old rows)
                "started_at":  (effective_start).isoformat() if effective_start else None,
                "last_active": last_act.isoformat() if last_act else None,
                "duration":    dur,
                "query_count": q_count,
                "language":    lang,
                "device":      device[:60] if device else "—",
                "status":      "active" if is_truly_active else "inactive",
                "ip_address":  ip_addr,
            })

        total  = len(sessions)
        # FIX: active_now = sessions with activity in last 30 min (not stored status)
        active = sum(1 for s in sessions if s["status"] == "active")
        if sessions:
            all_q = [s["query_count"] for s in sessions if s["query_count"]]
            avg_q = round(sum(all_q) / len(all_q), 1) if all_q else 0
        else:
            avg_q = 0

        # Compute avg duration
        dur_secs = []
        for r in rows:
            s = _to_utc(r[1]) or _to_utc(r[2])
            la = _to_utc(r[2])
            if s and la:
                diff = int((la - s).total_seconds())
                if diff > 0:
                    dur_secs.append(diff)
        avg_dur_s = round(sum(dur_secs) / len(dur_secs)) if dur_secs else 0
        if avg_dur_s < 60:   avg_dur_str = f"{avg_dur_s}s"
        elif avg_dur_s < 3600: avg_dur_str = f"{avg_dur_s//60}m {avg_dur_s%60}s"
        else:                avg_dur_str = f"{avg_dur_s//3600}h {(avg_dur_s%3600)//60}m"

        return {
            "total_sessions":       total,
            "active_now":           active,
            "avg_duration":         avg_dur_str,
            "queries_per_session":  avg_q,
            "sessions":             sessions
        }
    except Exception as e:
        print(f"[sessions] Error: {e}")
        return {
            "total_sessions": 0, "active_now": 0,
            "avg_duration": "—", "queries_per_session": 0,
            "sessions": []
        }

@app.get("/campus-info")
async def get_campus_info(db: Session = Depends(get_db)):
    """
    Public endpoint — returns all safe campus settings.
    No auth required. Used by all frontend pages to apply
    general info, branding, chatbot config, and emergency contacts.
    """
    try:
        rows = db.execute(text(
            "SELECT key, value FROM campus_settings "
            "WHERE key NOT IN ('new_password')"
        )).fetchall()
        return {r[0]: r[1] for r in rows}
    except Exception:
        return {}


# ── Campus Settings endpoints ────────────────────────────────────────────────

@admin_router.get("/settings")
def get_settings(db: Session = Depends(get_db)):
    """Return all campus settings as a flat key→value dict."""
    try:
        rows = db.execute(text("SELECT key, value FROM campus_settings")).fetchall()
        result = {r[0]: r[1] for r in rows}
        return {"settings": result, "grouped": {}}
    except Exception as e:
        print(f"[settings] GET error: {e}")
        return {"settings": {}, "grouped": {}}


@admin_router.post("/settings")
async def save_settings(request: Request, db: Session = Depends(get_db)):
    """Upsert campus settings. Body: { key: value, ... }"""
    try:
        payload = await request.json()
        for key, value in payload.items():
            if not isinstance(key, str) or len(key) > 100:
                continue
            # Determine group from key prefix
            grp = 'general'
            if key in ('emergency_hotline','security_office','clinic','fire_dept',
                       'evacuation_coord','admin_office','assembly_area','evacuation_steps'):
                grp = 'emergency'
            elif key in ('chatbot_name','chatbot_greeting','fallback_en','fallback_fil',
                         'confidence_threshold','max_response_length','default_language',
                         'office_hours_message'):
                grp = 'chatbot'
            elif key in ('campus_address','nav_mode','default_floor','building_name',
                         'glb_model_url','google_maps_url'):
                grp = 'navigation'
            elif key in ('primary_color','logo_url','bg_url','avatar_url'):
                grp = 'appearance'

            db.execute(text("""
                INSERT INTO campus_settings (key, value, updated_at)
                VALUES (:k, :v, NOW())
                ON CONFLICT (key) DO UPDATE
                SET value = EXCLUDED.value, updated_at = NOW()
            """), {"k": key, "v": str(value) if value is not None else None})
        db.commit()
        return {"status": "ok", "saved": len(payload)}
    except Exception as e:
        db.rollback()
        print(f"[settings] POST error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@admin_router.post("/upload-logo")
async def upload_logo(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Upload a logo image to Cloudinary and save the URL to campus_settings."""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image (PNG, JPG, SVG, WEBP).")
    if file.size and file.size > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File must be under 5 MB.")
    try:
        raw_bytes = await file.read()
        url = upload_to_cloudinary(raw_bytes, file.filename or "logo.png", folder="sparta/logos")
        # Also persist to settings
        db.execute(text(
            "INSERT INTO campus_settings (key, value, updated_at) VALUES (:k, :v, NOW()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()"
        ), {"k": "logo_url", "v": url})
        db.commit()
        return {"url": url, "secure_url": url}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Logo upload failed: {e}")


def get_campus_setting(db: Session, key: str, default: str = "") -> str:
    """Helper — read one setting from campus_settings."""
    try:
        row = db.execute(
            text("SELECT value FROM campus_settings WHERE key = :k"), {"k": key}
        ).fetchone()
        return row[0] if row and row[0] is not None else default
    except Exception:
        return default


# ============================================
# REGISTER ADMIN ROUTER
# Must be at the bottom after all routes are defined
# ============================================

app.include_router(admin_router)

# ============================================
# RUN SERVER
# ============================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)