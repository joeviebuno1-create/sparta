"""
Run from SPARTHA/backend:
    python diagnose.py
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")

# 1. Check what columns announcement_popups actually has in the DB
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text
engine = create_engine(os.environ["DATABASE_URL"])

with engine.connect() as conn:
    rows = conn.execute(text(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name='announcement_popups' ORDER BY ordinal_position"
    )).fetchall()
    print("=== announcement_popups columns in DB ===")
    for r in rows:
        print(f"  {r[0]:30s} {r[1]}")

# 2. Try the exact query the admin endpoint runs and print the real error
print("\n=== Simulating admin GET /announcement-popups ===")
try:
    import models
    from database import get_db
    from sqlalchemy.orm import Session
    db = next(get_db())
    popups = db.query(models.AnnouncementPopup).order_by(
        models.AnnouncementPopup.priority.desc(),
        models.AnnouncementPopup.created_at.desc()
    ).all()
    result = [
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
    print(f"  OK - {len(result)} popup(s) returned")
except Exception as e:
    import traceback
    print("  ERROR:")
    traceback.print_exc()