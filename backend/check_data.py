"""
Run from SPARTHA/backend:
    python check_data.py
"""
import os, sys, json
sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text
engine = create_engine(os.environ["DATABASE_URL"])

with engine.connect() as conn:
    # 1. What does nav-statistics actually return?
    print("=== search_logs (navigation intent) ===")
    rows = conn.execute(text("SELECT COUNT(*) FROM search_logs WHERE intent='navigation'")).fetchone()
    print(f"  navigation logs: {rows[0]}")

    rows = conn.execute(text("SELECT COUNT(*) FROM search_logs")).fetchone()
    print(f"  total logs: {rows[0]}")

    # 2. Room locations count
    print("\n=== room_locations ===")
    rows = conn.execute(text("SELECT COUNT(*) FROM room_locations")).fetchone()
    print(f"  total locations: {rows[0]}")

    rows = conn.execute(text("SELECT type, COUNT(*) as c FROM room_locations GROUP BY type ORDER BY c DESC")).fetchall()
    for r in rows:
        print(f"  {r[0]:20s} {r[1]}")

    # 3. FAQ documents
    print("\n=== faq_documents ===")
    rows = conn.execute(text("SELECT id, title, page_count, is_active FROM faq_documents")).fetchall()
    for r in rows:
        print(f"  id={r[0]} title={r[1][:30]} pages={r[2]} active={r[3]}")

    # 4. Statistics endpoint - what does it return for nav_success_rate?
    print("\n=== statistics endpoint data ===")
    rows = conn.execute(text("SELECT intent, COUNT(*) FROM search_logs GROUP BY intent")).fetchall()
    for r in rows:
        print(f"  intent={r[0]} count={r[1]}")