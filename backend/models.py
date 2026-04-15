from sqlalchemy import Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey, JSON, LargeBinary
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime

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
    created_at = Column(DateTime, default=datetime.utcnow)

class History(Base):
    __tablename__ = "histories"
    
    id = Column(Integer, primary_key=True, index=True)
    year = Column(Integer, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Announcement(Base):
    __tablename__ = "announcements"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    category = Column(String, nullable=False)
    date_posted = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

class Intent(Base):
    __tablename__ = "intents"
    
    id = Column(Integer, primary_key=True, index=True)
    intent_type = Column(String, nullable=False)
    keywords = Column(Text, nullable=False)
    response_template = Column(Text, nullable=False)
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
# If you need it later, you can add the Msodel3DUpload class back
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

class AdminCredentials(Base):
    __tablename__ = "admin_credentials"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)  # SHA-256 hash
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
    priority = Column(Integer, default=0)             # higher number = shown first
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)