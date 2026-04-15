from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, APIRouter, Request, status
from fastapi.responses import HTMLResponse, StreamingResponse, Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from collections import defaultdict
import time as time_module
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import models
from database import engine, get_db
import io
import os
import bcrypt
import math
import json

# Sentence Transformers for offline semantic search
from sentence_transformers import SentenceTransformer, util
import numpy as np

# Import RAG-based chatbot
from rag_chatbot import process_chat_with_rag

# Import auth helpers
from auth import verify_session, create_session, clear_session

# ============================================
# SECURITY — Rate Limiter + Security Headers
# ============================================

class RateLimiter:
    """Simple in-memory rate limiter per IP address."""
    def __init__(self):
        self.requests = defaultdict(list)

    def is_allowed(self, ip: str, max_requests: int, window_seconds: int) -> bool:
        now = time_module.time()
        # Remove old requests outside the window
        self.requests[ip] = [t for t in self.requests[ip] if now - t < window_seconds]
        if len(self.requests[ip]) >= max_requests:
            return False
        self.requests[ip].append(now)
        return True

rate_limiter = RateLimiter()

class SecurityMiddleware(BaseHTTPMiddleware):
    """Adds security headers and rate limiting to all responses."""
    async def dispatch(self, request: Request, call_next):
        ip = request.client.host if request.client else "unknown"

        # ── Rate limiting ──────────────────────────────────────────────
        # Chat endpoint: 30 requests per minute per IP
        if request.url.path == "/api/chat":
            if not rate_limiter.is_allowed(ip, max_requests=30, window_seconds=60):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests. Please wait a moment before sending again."}
                )

        # Login endpoint: 10 attempts per 5 minutes per IP (brute force protection)
        if request.url.path == "/api/admin/login" and request.method == "POST":
            if not rate_limiter.is_allowed(f"login:{ip}", max_requests=10, window_seconds=300):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many login attempts. Please wait 5 minutes."}
                )

        # General API: 200 requests per minute per IP
        if request.url.path.startswith("/api/"):
            if not rate_limiter.is_allowed(f"api:{ip}", max_requests=200, window_seconds=60):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests. Please slow down."}
                )

        response = await call_next(request)

        # ── Security Headers ───────────────────────────────────────────
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(self), camera=()"
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"

        # Only add HSTS in production (HTTPS)
        is_production = os.getenv("IS_PRODUCTION", "false").lower() == "true"
        if is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response

# ============================================
# Create tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI()

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://192.168.1.37:8000",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "https://1fz5f30f-8000.asse.devtunnels.ms",  # VS Code tunnel
    ],
    allow_origin_regex="https://.*(devtunnels\\.ms|trycloudflare\\.com|ngrok-free\\.app|ngrok\\.io)",
    allow_credentials=True,   # Required for cookies to work
    allow_methods=["*"],
    allow_headers=["*"],
)

# Session middleware — signs cookie with itsdangerous
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", "fallback-secret-change-this"),
    session_cookie="spartha_session",
    max_age=60 * 60 * int(os.getenv("ACCESS_TOKEN_EXPIRE_HOURS", 8)),
    https_only=os.getenv("IS_PRODUCTION", "false").lower() == "true",
    same_site="lax"
)

# Paths relative to SPARTHA root
SPARTHA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Security middleware — rate limiting + security headers
app.add_middleware(SecurityMiddleware)

# Mount static files (GLB models etc) from SPARTHA/static/
app.mount("/static", StaticFiles(directory=os.path.join(SPARTHA_DIR, "static")), name="static")

# Mount images from SPARTHA/images/
app.mount("/images", StaticFiles(directory=os.path.join(SPARTHA_DIR, "images")), name="images")

# Serve admin HTML files directly so cookies work (same origin as API)
BASE_DIR = os.path.join(SPARTHA_DIR, "frontend")  # SPARTHA/frontend/

from fastapi.responses import FileResponse

def frontend_file(filename: str):
    return FileResponse(os.path.join(BASE_DIR, filename))

# ── HTML pages ──────────────────────────────────────────
@app.get("/admin.html",            response_class=HTMLResponse)
async def serve_admin():           return frontend_file("admin.html")

@app.get("/chatbot1.html",         response_class=HTMLResponse)
@app.get("/sparta_chatbot.html",    response_class=HTMLResponse)
async def serve_chatbot():         return frontend_file("sparta_chatbot.html")

@app.get("/campus-navigator1.html",response_class=HTMLResponse)
@app.get("/sparta_campus-navigator.html",response_class=HTMLResponse)
async def serve_navigator():       return frontend_file("sparta_campus-navigator.html")

@app.get("/spartha_main_menu.html",response_class=HTMLResponse)
@app.get("/sparta_main_menu.html",response_class=HTMLResponse)
async def serve_main_menu():       return frontend_file("sparta_main_menu.html")

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
async def serve_admin_script():    return frontend_file("admin-script.js")

@app.get("/chatbot_script.js")
async def serve_chatbot_script():  return frontend_file("chatbot_script.js")

@app.get("/navigation-script.js")
async def serve_nav_script():      return frontend_file("navigation-script.js")

# Load offline ML model (runs once on startup)
print("Loading RAG embedding model... (this may take a moment)")
embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
print("✓ RAG model loaded successfully!")

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

class HistoryCreate(BaseModel):
    year: int
    title: str
    description: str

class AnnouncementCreate(BaseModel):
    title: str
    content: str
    category: str
    date_posted: Optional[datetime] = None

class IntentCreate(BaseModel):
    intent_type: str
    keywords: str
    response_template: str

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

@app.get("/", response_class=HTMLResponse)
async def read_root():
    return """
    <html>
        <head>
            <title>SPARTHA API - RAG ENHANCED</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    max-width: 800px;
                    margin: 50px auto;
                    padding: 20px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                }
                h1 { text-align: center; }
                .card {
                    background: rgba(255, 255, 255, 0.1);
                    backdrop-filter: blur(10px);
                    border-radius: 10px;
                    padding: 20px;
                    margin: 20px 0;
                }
                ul { line-height: 1.8; }
                a { color: #ffd700; text-decoration: none; }
                a:hover { text-decoration: underline; }
                .feature {
                    background: rgba(255, 215, 0, 0.1);
                    padding: 10px;
                    border-radius: 5px;
                    margin: 10px 0;
                }
                .badge {
                    background: #ffd700;
                    color: #764ba2;
                    padding: 5px 10px;
                    border-radius: 15px;
                    font-weight: bold;
                    font-size: 0.8em;
                }
            </style>
        </head>
        <body>
            <h1>🏫 SPARTHA API <span class="badge">RAG ENHANCED</span></h1>
            <div class="card">
                <h2>Smart Path and Resource Tracking Hub for Academia</h2>
                <p>Enhanced chatbot with Database-RAG for accurate, context-aware responses</p>
            </div>
            <div class="card">
                <h3>📍 Available Endpoints:</h3>
                <ul>
                    <li><a href="/docs">/docs</a> - Interactive API Documentation</li>
                    <li><a href="/health">/health</a> - System Health Check</li>
                    <li>POST /api/chat - RAG-Enhanced Chatbot</li>
                    <li>POST /api/admin/login - Admin Login (sets HttpOnly cookie)</li>
                    <li>POST /api/admin/logout - Admin Logout (clears cookie)</li>
                    <li>GET/POST/PUT/DELETE /api/admin/* - Protected Admin Endpoints</li>
                </ul>
            </div>
        </body>
    </html>
    """

# ============================================
# ROUTES - RAG-ENHANCED CHATBOT (PUBLIC)
# ============================================

@app.post("/api/chat")
async def chat(message: ChatMessage, request: Request, db: Session = Depends(get_db)):
    # Input validation
    if not message.message or not message.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    if len(message.message) > 500:
        raise HTTPException(status_code=400, detail="Message too long. Maximum 500 characters.")
    # Sanitize — strip dangerous characters
    clean_message = message.message.strip()

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
        popups = db.query(models.AnnouncementPopup).filter(
            models.AnnouncementPopup.is_active == True
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
    Returns dynamic quick questions built from real database content.
    intent param lets frontend request intent-specific suggestions.
    """
    import random
    questions = []

    try:
        # ── Intent-specific dynamic questions ─────────────────────────
        if intent == 'authority_query':
            # Pick 3 random authorities
            authorities = db.query(models.Authority).all()
            picks = random.sample(authorities, min(3, len(authorities)))
            for auth in picks:
                questions.append({
                    "text": f"👤 Who is {auth.name}?",
                    "query": f"Who is {auth.name}?",
                    "category": "authority"
                })
            questions.append({"text": "🏛️ Who is the Chancellor?", "query": "Who is the chancellor of BSU Lipa?", "category": "authority"})
            questions.append({"text": "👥 All university officials", "query": "Who are all the university officials?", "category": "authority"})

        elif intent == 'location_query':
            # Pick 3 random locations
            locations = db.query(models.RoomLocation).filter(
                ~models.RoomLocation.name.ilike('%emergency%')
            ).all()
            picks = random.sample(locations, min(3, len(locations)))
            for loc in picks:
                questions.append({
                    "text": f"📍 Where is {loc.name}?",
                    "query": f"Where is the {loc.name}?",
                    "category": "location"
                })
            questions.append({"text": "🗺️ Open Campus Navigator", "query": "Show me the campus map", "category": "location"})

        elif intent == 'organization_query':
            # Show all orgs as quick questions
            orgs = db.query(models.Organization).all()
            picks = random.sample(orgs, min(4, len(orgs)))
            for org in picks:
                # Auto-generate acronym
                words = org.name.split()
                acronym = ''.join(w[0].upper() for w in words if w)
                label = acronym if len(acronym) <= 6 else org.name[:20]
                questions.append({
                    "text": f"🎓 {label}",
                    "query": f"Tell me about {org.name} organization",
                    "category": "organization"
                })
            questions.append({"text": "📋 List all organizations", "query": "List all organizations", "category": "organization"})

        elif intent == 'announcement_query':
            # Show latest 4 announcements
            announcements = db.query(models.Announcement).order_by(
                models.Announcement.date_posted.desc()
            ).limit(4).all()
            for ann in announcements:
                title = ann.title if len(ann.title) <= 30 else ann.title[:27] + "..."
                questions.append({
                    "text": f"📢 {title}",
                    "query": f"Tell me about the announcement: {ann.title}",
                    "category": "announcement"
                })

        # ── Fallback — general or empty DB ────────────────────────────
        if not questions:
            questions = [
                {"text": "🎓 Who is the dean?", "query": "Who is the dean?", "category": "authority"},
                {"text": "📍 Where is the library?", "query": "Where is the library?", "category": "location"},
                {"text": "🏛️ BSU Lipa history", "query": "Tell me about BSU Lipa history", "category": "history"},
                {"text": "📢 Latest announcements", "query": "What are the latest announcements?", "category": "announcement"},
            ]

        return questions

    except Exception as e:
        # Return safe fallback on any error
        return [
            {"text": "🎓 Who is the dean?", "query": "Who is the dean?", "category": "authority"},
            {"text": "📍 Where is the library?", "query": "Where is the library?", "category": "location"},
            {"text": "🏛️ BSU Lipa history", "query": "Tell me about BSU Lipa history", "category": "history"},
            {"text": "📢 Latest announcements", "query": "What are the latest announcements?", "category": "announcement"},
        ]

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

    # Store username in signed session cookie — itsdangerous signs it automatically
    create_session(request, credential.username)

    return JSONResponse(content={
        "success": True,
        "message": "Login successful",
        "username": credential.username
    })

@app.post("/api/admin/logout")
async def admin_logout(request: Request):
    """Logout — clears the signed session cookie"""
    clear_session(request)
    return JSONResponse(content={"success": True, "message": "Logged out"})

# ============================================
# PROTECTED ADMIN ENDPOINTS
# All routes below require valid HttpOnly cookie
# ============================================

# --- AUTHORITIES ---

@admin_router.get("/authorities")
async def get_authorities(db: Session = Depends(get_db)):
    return db.query(models.Authority).all()

@admin_router.post("/authorities")
async def create_authority(authority: AuthorityCreate, db: Session = Depends(get_db)):
    db_authority = models.Authority(**authority.dict())
    db.add(db_authority)
    db.commit()
    db.refresh(db_authority)
    return db_authority

@admin_router.put("/authorities/{authority_id}")
async def update_authority(authority_id: int, authority: AuthorityCreate, db: Session = Depends(get_db)):
    db_authority = db.query(models.Authority).filter(models.Authority.id == authority_id).first()
    if not db_authority:
        raise HTTPException(status_code=404, detail="Authority not found")
    for key, value in authority.dict().items():
        setattr(db_authority, key, value)
    db.commit()
    db.refresh(db_authority)
    return db_authority

@admin_router.delete("/authorities/{authority_id}")
async def delete_authority(authority_id: int, db: Session = Depends(get_db)):
    db_authority = db.query(models.Authority).filter(models.Authority.id == authority_id).first()
    if not db_authority:
        raise HTTPException(status_code=404, detail="Authority not found")
    db.delete(db_authority)
    db.commit()
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
    db_history = models.History(**history.dict())
    db.add(db_history)
    db.commit()
    db.refresh(db_history)
    return db_history

@admin_router.post("/history")
async def create_history_singular(history: HistoryCreate, db: Session = Depends(get_db)):
    return await create_history(history, db)

@admin_router.put("/histories/{history_id}")
async def update_history(history_id: int, history: HistoryCreate, db: Session = Depends(get_db)):
    db_history = db.query(models.History).filter(models.History.id == history_id).first()
    if not db_history:
        raise HTTPException(status_code=404, detail="History not found")
    for key, value in history.dict().items():
        setattr(db_history, key, value)
    db.commit()
    db.refresh(db_history)
    return db_history

@admin_router.put("/history/{history_id}")
async def update_history_singular(history_id: int, history: HistoryCreate, db: Session = Depends(get_db)):
    return await update_history(history_id, history, db)

@admin_router.delete("/histories/{history_id}")
async def delete_history(history_id: int, db: Session = Depends(get_db)):
    db_history = db.query(models.History).filter(models.History.id == history_id).first()
    if not db_history:
        raise HTTPException(status_code=404, detail="History not found")
    db.delete(db_history)
    db.commit()
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
    announcement_data = announcement.dict()
    if not announcement_data.get('date_posted'):
        announcement_data['date_posted'] = datetime.utcnow()
    db_announcement = models.Announcement(**announcement_data)
    db.add(db_announcement)
    db.commit()
    db.refresh(db_announcement)
    return db_announcement

@admin_router.put("/announcements/{announcement_id}")
async def update_announcement(announcement_id: int, announcement: AnnouncementCreate, db: Session = Depends(get_db)):
    db_announcement = db.query(models.Announcement).filter(models.Announcement.id == announcement_id).first()
    if not db_announcement:
        raise HTTPException(status_code=404, detail="Announcement not found")
    for key, value in announcement.dict().items():
        setattr(db_announcement, key, value)
    db.commit()
    db.refresh(db_announcement)
    return db_announcement

@admin_router.delete("/announcements/{announcement_id}")
async def delete_announcement(announcement_id: int, db: Session = Depends(get_db)):
    db_announcement = db.query(models.Announcement).filter(models.Announcement.id == announcement_id).first()
    if not db_announcement:
        raise HTTPException(status_code=404, detail="Announcement not found")
    db.delete(db_announcement)
    db.commit()
    return {"message": "Announcement deleted successfully"}

# --- LOCATIONS ---

@admin_router.get("/locations")
async def get_locations(db: Session = Depends(get_db)):
    return db.query(models.RoomLocation).all()

@admin_router.post("/locations")
async def create_location(location: RoomLocationCreate, db: Session = Depends(get_db)):
    location_data = location.dict()
    if location_data.get('coordinates'):
        coords = location_data['coordinates']
        if isinstance(coords, dict):
            location_data['coordinates'] = json.dumps(coords)
    db_location = models.RoomLocation(**location_data)
    db.add(db_location)
    db.commit()
    db.refresh(db_location)
    return db_location

@admin_router.put("/locations/{location_id}")
async def update_location(location_id: int, location: RoomLocationCreate, db: Session = Depends(get_db)):
    db_location = db.query(models.RoomLocation).filter(models.RoomLocation.id == location_id).first()
    if not db_location:
        raise HTTPException(status_code=404, detail="Location not found")
    location_data = location.dict()
    if location_data.get('coordinates'):
        coords = location_data['coordinates']
        if isinstance(coords, dict):
            location_data['coordinates'] = json.dumps(coords)
    for key, value in location_data.items():
        setattr(db_location, key, value)
    db.commit()
    db.refresh(db_location)
    return db_location

@admin_router.delete("/locations/{location_id}")
async def delete_location(location_id: int, db: Session = Depends(get_db)):
    db_location = db.query(models.RoomLocation).filter(models.RoomLocation.id == location_id).first()
    if not db_location:
        raise HTTPException(status_code=404, detail="Location not found")
    db.query(models.NavigationRoute).filter(
        (models.NavigationRoute.start_location_id == location_id) |
        (models.NavigationRoute.end_location_id == location_id)
    ).delete(synchronize_session=False)
    db.delete(db_location)
    db.commit()
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
            'members_count': member_count,
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
        db.delete(db_member)
        db.commit()
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
        db.delete(db_member)
        db.commit()
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
    db.delete(db_org)
    db.commit()
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
            created_at=datetime.utcnow()
        )
        db.add(db_intent)
        db.commit()
        db.refresh(db_intent)
        return {
            "id": db_intent.id,
            "intent_type": db_intent.intent_type,
            "keywords": db_intent.keywords,
            "response_template": db_intent.response_template,
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
        db.commit()
        db.refresh(db_intent)
        return {
            "id": db_intent.id,
            "intent_type": db_intent.intent_type,
            "keywords": db_intent.keywords,
            "response_template": db_intent.response_template,
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
        db.delete(db_intent)
        db.commit()
        return {"message": "Intent deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# --- 3D MAP UPLOAD ---

@admin_router.post("/upload-3d-map")
async def upload_3d_map(
    file: UploadFile = File(...),
    description: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    try:
        file_content = await file.read()
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
        return {
            "message": "3D map uploaded successfully",
            "id": db_upload.id,
            "filename": db_upload.filename,
            "size": db_upload.file_size
        }
    except Exception as e:
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
                "is_active": m.is_active
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
async def get_credentials(db: Session = Depends(get_db)):
    ensure_default_admin(db)
    credential = db.query(models.AdminCredentials).first()
    return {"username": credential.username if credential else "admin"}

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
                "id": p.id,
                "title": p.title,
                "content": p.content,
                "category": p.category,
                "image_data": p.image_data,
                "image_filename": p.image_filename,
                "is_active": p.is_active,
                "priority": p.priority,
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "updated_at": p.updated_at.isoformat() if p.updated_at else None,
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
        popup = models.AnnouncementPopup(
            title=title,
            content=content,
            category=category,
            is_active=(is_active.lower() == "true"),
            priority=priority,
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
    priority: int = Form(0),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    try:
        popup = db.query(models.AnnouncementPopup).filter(models.AnnouncementPopup.id == popup_id).first()
        if not popup:
            raise HTTPException(status_code=404, detail="Popup not found")
        popup.title = title
        popup.content = content
        popup.category = category
        popup.is_active = (is_active.lower() == "true")
        popup.priority = priority
        popup.updated_at = datetime.utcnow()
        if image and image.filename:
            raw = await image.read()
            import base64
            b64 = base64.b64encode(raw).decode("utf-8")
            mime = image.content_type or "image/jpeg"
            popup.image_data = f"data:{mime};base64,{b64}"
            popup.image_filename = image.filename
        db.commit()
        return {"message": "Popup updated successfully"}
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
# HEALTH CHECK (PUBLIC)
# ============================================

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "rag_enabled": True,
        "model_loaded": embedding_model is not None,
        "model_name": "all-MiniLM-L6-v2",
        "version": "2.0-RAG"
    }

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