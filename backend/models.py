from sqlalchemy import Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey, JSON, LargeBinary, text, func
from sqlalchemy.orm import relationship
from database import Base, engine
from datetime import datetime

# ─────────────────────────────────────────────────────────────────────────────
# AUTO-MIGRATION
# Runs once on server start. Safely adds missing columns to existing DB tables.
# To add a new column: 1) update the model class below, 2) add an entry here.
# ─────────────────────────────────────────────────────────────────────────────
_MIGRATIONS = {
    "campus_settings": [
        ("grp", "VARCHAR(50)"),   # group/category column — added retroactively
    ],
    "search_logs": [
        # Backfill NULL searched_at with NOW() for any old rows, then enforce NOT NULL
        # This runs as ALTER TABLE only if column exists but has NULLs
    ],
    "announcement_popups": [
        ("is_archived",  "BOOLEAN DEFAULT FALSE"),
        ("scheduled_at", "TIMESTAMP"),
        ("expires_at",   "TIMESTAMP"),
        ("updated_at",   "TIMESTAMP DEFAULT NOW()"),
    ],
}

def run_migrations():
    try:
        with engine.begin() as conn:
            for table, cols in _MIGRATIONS.items():
                for col, definition in cols:
                    exists = conn.execute(text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name=:t AND column_name=:c"
                    ), {"t": table, "c": col}).fetchone()
                    if not exists:
                        conn.execute(text(
                            f"ALTER TABLE {table} ADD COLUMN {col} {definition}"
                        ))
                        print(f"[models] Added column: {table}.{col}")
        print("[models] Migration check complete.")
    except Exception as e:
        print(f"[models] Migration warning: {e}")

# Run immediately when this module is imported (i.e. every server start)
run_migrations()


class Authority(Base):
    __tablename__ = "authorities"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    position = Column(String, nullable=False)
    department = Column(String, nullable=False)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    office_location = Column(String, nullable=True)
    bio = Column(Text, nullable=True)
    photo = Column(Text, nullable=True)   # base64-encoded image or URL
    created_at = Column(DateTime, default=datetime.utcnow)

class History(Base):
    __tablename__ = "histories"
    
    id = Column(Integer, primary_key=True, index=True)
    year = Column(Integer, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    title_tl = Column(String, nullable=True)        # Filipino translation
    description_tl = Column(Text, nullable=True)    # Filipino translation
    created_at = Column(DateTime, default=datetime.utcnow)

class Announcement(Base):
    __tablename__ = "announcements"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    category = Column(String, nullable=False)
    title_tl = Column(String, nullable=True)        # Filipino translation
    content_tl = Column(Text, nullable=True)        # Filipino translation
    date_posted = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

class Intent(Base):
    __tablename__ = "intents"
    
    id = Column(Integer, primary_key=True, index=True)
    intent_type = Column(String, nullable=False)
    keywords = Column(Text, nullable=False)
    response_template = Column(Text, nullable=False)
    response_template_tl = Column(Text, nullable=True)  # Filipino translation
    created_at = Column(DateTime, default=datetime.utcnow)

class RoomLocation(Base):
    __tablename__ = "room_locations"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    building = Column(String, nullable=False)
    floor = Column(Integer, nullable=False)
    type = Column(String, nullable=False)
    icon = Column(String, nullable=True)
    capacity = Column(Integer, nullable=True)
    description = Column(Text, nullable=True)
    coordinates = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Waypoint(Base):
    __tablename__ = "waypoints"
    
    id = Column(Integer, primary_key=True, index=True)
    waypoint_id = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    pos_x = Column(Float, nullable=False)
    pos_y = Column(Float, nullable=False)
    pos_z = Column(Float, nullable=False)
    is_entrance = Column(Boolean, default=False)
    is_exit = Column(Boolean, default=False)
    is_major_junction = Column(Boolean, default=False)
    floor_level = Column(Integer, default=0)
    marker_color = Column(String, default="#4A90E2")
    marker_size = Column(Float, default=1.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class PathConnection(Base):
    __tablename__ = "path_connections"
    
    id = Column(Integer, primary_key=True, index=True)
    from_waypoint_id = Column(Integer, ForeignKey("waypoints.id"), nullable=False)
    to_waypoint_id = Column(Integer, ForeignKey("waypoints.id"), nullable=False)
    distance = Column(Float, nullable=True)
    is_bidirectional = Column(Boolean, default=True)
    is_stairs = Column(Boolean, default=False)
    is_elevator = Column(Boolean, default=False)
    is_ramp = Column(Boolean, default=False)
    is_outdoor = Column(Boolean, default=False)
    path_color = Column(String, default="#F4D03F")
    path_width = Column(Float, default=1.0)
    is_wheelchair_accessible = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    from_waypoint = relationship("Waypoint", foreign_keys=[from_waypoint_id])
    to_waypoint = relationship("Waypoint", foreign_keys=[to_waypoint_id])

class NavigationRoute(Base):
    __tablename__ = "navigation_routes"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    start_location_id = Column(Integer, ForeignKey("room_locations.id"), nullable=False)
    end_location_id = Column(Integer, ForeignKey("room_locations.id"), nullable=False)
    is_wheelchair_accessible = Column(Boolean, default=False)
    path_color = Column(String, default="#F4D03F")
    waypoints = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    start_location = relationship("RoomLocation", foreign_keys=[start_location_id])
    end_location = relationship("RoomLocation", foreign_keys=[end_location_id])

# ONLY USE map_3d_uploads table (the one that works)
class Map3DUpload(Base):
    """
    3D Map uploads table - map_3d_uploads
    This is the ONLY upload table we use for the admin panel
    """
    __tablename__ = "map_3d_uploads"
    __table_args__ = {'extend_existing': True}
    
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=True)
    original_filename = Column(String, nullable=True)
    file_data = Column(LargeBinary, nullable=False)  # bytea type - stores actual file content
    file_size = Column(Integer, nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow, nullable=True)
    uploaded_by = Column(String, default="Admin", nullable=True)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=True)

# NOTE: model_3d_uploads table exists in your database but is NOT used
# If you need it later, you can add the Model3DUpload class back
class Organization(Base):
    """
    Organization/Department table for organizational chart
    Uses existing org_charts table
    """
    __tablename__ = "org_charts"
    __table_args__ = {'extend_existing': True}
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)
    
    # Relationship to members
    members = relationship("OrganizationMember", back_populates="organization", cascade="all, delete-orphan")

class OrganizationMember(Base):
    """
    Organization members table for organizational chart
    Uses existing org_members table
    """
    __tablename__ = "org_members"
    __table_args__ = {'extend_existing': True}
    
    id = Column(Integer, primary_key=True, index=True)
    org_chart_id = Column(Integer, ForeignKey("org_charts.id"), nullable=False)
    name = Column(String, nullable=False)
    position = Column(String, nullable=False)
    sort_order = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=True)
    
    # Relationship to organization
    organization = relationship("Organization", back_populates="members")

class SearchLog(Base):
    """Tracks every chatbot query for analytics / statistics."""
    __tablename__ = "search_logs"

    id = Column(Integer, primary_key=True, index=True)
    query = Column(Text, nullable=False)
    intent = Column(String, nullable=True)          # detected intent
    entity_name = Column(String, nullable=True)     # top entity (location/person name)
    confidence = Column(Float, nullable=True)
    language = Column(String, default="en")
    searched_at = Column(DateTime, default=datetime.utcnow, server_default=func.now(), nullable=False)


class ActivityLog(Base):
    """
    Audit trail for all admin create / update / delete actions.
    Rows are append-only — never updated or deleted by the app.
    """
    __tablename__ = "activity_logs"

    id           = Column(Integer, primary_key=True, index=True)
    action       = Column(String(20), nullable=False)   # "created" | "updated" | "deleted"
    resource     = Column(String(50), nullable=False)   # e.g. "authority", "announcement"
    resource_id  = Column(Integer,  nullable=True)      # PK of the affected row (None for bulk ops)
    detail       = Column(Text,     nullable=True)      # human-readable summary
    performed_by = Column(String,   default="Admin")
    performed_at = Column(DateTime, default=datetime.utcnow, index=True)


class AdminCredentials(Base):
    __tablename__ = "admin_credentials"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)  # SHA-256 hash
    session_token = Column(String, nullable=True)  # current valid session token; rotated on login/logout for real revocation
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class AnnouncementPopup(Base):
    """
    Popup announcements shown on the main menu page.
    Supports text content and an optional image (stored as base64 or URL).
    """
    __tablename__ = "announcement_popups"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=True)
    category = Column(String, nullable=False, default="General")
    image_data = Column(Text, nullable=True)          # base64-encoded image or empty
    image_filename = Column(String, nullable=True)    # original filename for display
    is_active = Column(Boolean, default=True)         # toggle visibility on main menu
    is_archived = Column(Boolean, default=False)      # soft-delete / archive
    priority = Column(Integer, default=0)             # higher number = shown first
    scheduled_at = Column(DateTime, nullable=True)    # null = show immediately
    expires_at = Column(DateTime, nullable=True)      # null = never expires
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class FAQDocument(Base):
    """
    Stores uploaded PDF FAQ documents with their extracted plain text.
    SPARTA's chatbot uses this text as additional context when answering questions.
    """
    __tablename__ = "faq_documents"

    id             = Column(Integer, primary_key=True, index=True)
    title          = Column(String(255), nullable=False)
    filename       = Column(String(255), nullable=False)
    extracted_text = Column(Text, nullable=False)
    file_size      = Column(Integer, nullable=True)
    page_count     = Column(Integer, nullable=True)
    is_active      = Column(Boolean, default=True)
    uploaded_at    = Column(DateTime, default=datetime.utcnow)
    updated_at     = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<FAQDocument id={self.id} title='{self.title}' pages={self.page_count}>"

class UserSession(Base):
    """
    Tracks each chatbot session — created on first message, updated on each query.
    Allows the admin to see usage patterns, session counts, and durations.
    """
    __tablename__ = "user_sessions"

    id           = Column(Integer, primary_key=True, index=True)
    session_id   = Column(String(64), unique=True, nullable=False, index=True)
    started_at   = Column(DateTime, default=datetime.utcnow, index=True)
    last_active  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    ended_at     = Column(DateTime, nullable=True)
    query_count  = Column(Integer, default=0)
    language     = Column(String(10), default="en")   # "en" | "tl"
    device       = Column(String(100), nullable=True) # User-Agent snippet
    status       = Column(String(20), default="active")  # "active" | "ended"
    ip_address   = Column(String(45), nullable=True)

    def duration_str(self) -> str:
        end = self.ended_at or datetime.utcnow()
        secs = int((end - self.started_at).total_seconds())
        if secs < 60:
            return f"{secs}s"
        if secs < 3600:
            return f"{secs//60}m {secs%60}s"
        return f"{secs//3600}h {(secs%3600)//60}m"


class CampusSetting(Base):
    """
    Key-value store for all campus/chatbot settings.
    Each row is one setting: key (string) → value (text).
    Groups: general | chatbot | appearance | navigation | emergency
    """
    __tablename__ = "campus_settings"

    id         = Column(Integer, primary_key=True, index=True)
    key        = Column(String(100), unique=True, nullable=False, index=True)
    value      = Column(Text, nullable=True)
    grp        = Column(String(50), nullable=True)   # general|chatbot|appearance|navigation|emergency
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<CampusSetting {self.key}={self.value[:30] if self.value else None}>"