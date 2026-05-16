"""
Fixes:
  1. Adds /api/admin/nav-statistics route to main.py
  2. Adds no-cache headers to admin-script.js route (busts browser cache)

Run from SPARTHA/backend:
    python fix_nav_and_cache.py
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(BASE, "main.py")

with open(MAIN, "r", encoding="utf-8") as f:
    src = f.read().replace("\r\n", "\n")

original = src

# ─────────────────────────────────────────────────────────────
# FIX 1: Add no-cache headers to admin-script.js so the browser
#         always gets the latest version
# ─────────────────────────────────────────────────────────────
OLD_SCRIPT = '@app.get("/admin-script.js")\nasync def serve_admin_script():    return frontend_file("admin-script.js")'
NEW_SCRIPT = '''@app.get("/admin-script.js")
async def serve_admin_script():
    from fastapi.responses import FileResponse
    import os as _os
    path = _os.path.join(BASE_DIR, "admin-script.js")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        }
    )'''

if OLD_SCRIPT in src:
    src = src.replace(OLD_SCRIPT, NEW_SCRIPT)
    print("OK: Added no-cache headers to admin-script.js route")
else:
    print("SKIP: admin-script.js route not found (may already be patched)")

# ─────────────────────────────────────────────────────────────
# FIX 2: Add /api/admin/nav-statistics route
#         (inserted just before the intent health endpoint)
# ─────────────────────────────────────────────────────────────
NAV_STATS_ROUTE = '''

# ── Navigation statistics endpoint ───────────────────────────────────────────

@admin_router.get("/nav-statistics")
def get_nav_statistics(db: Session = Depends(get_db)):
    """
    Returns navigation-specific search statistics:
    - total navigation searches
    - today searches
    - unique locations searched
    - top location
    - top_locations list  (for bar chart)
    - type_breakdown list (for type chart)
    - recent_searches list
    """
    from sqlalchemy import func, cast, Date
    import datetime as _dt

    today = _dt.date.today()

    # All nav search logs (intent = navigation OR entity_name has a value)
    nav_logs = db.query(models.SearchLog).filter(
        models.SearchLog.intent == "navigation"
    ).all()

    total_searches   = len(nav_logs)
    today_searches   = sum(1 for l in nav_logs if l.searched_at and l.searched_at.date() == today)
    unique_locations = len(set(l.entity_name for l in nav_logs if l.entity_name))
    top_location     = None

    # Top locations by entity_name frequency
    from collections import Counter
    name_counts = Counter(l.entity_name for l in nav_logs if l.entity_name)
    top_locs    = [{"name": n, "count": c} for n, c in name_counts.most_common(8)]
    if top_locs:
        top_location = top_locs[0]["name"]

    # Try to join with room_locations for type breakdown
    type_counts: Counter = Counter()
    try:
        loc_rows = db.query(models.RoomLocation).all()
        loc_map  = {l.name.lower(): l.type for l in loc_rows}
        for log in nav_logs:
            if log.entity_name:
                t = loc_map.get(log.entity_name.lower(), "other")
                type_counts[t] += 1
    except Exception:
        pass

    type_breakdown = [{"type": t, "count": c}
                      for t, c in type_counts.most_common()]

    # Recent searches
    recent_logs = sorted(nav_logs, key=lambda l: l.searched_at or _dt.datetime.min, reverse=True)[:20]
    recent_searches = []
    try:
        loc_rows2   = db.query(models.RoomLocation).all()
        loc_detail  = {l.name.lower(): l for l in loc_rows2}
        for log in recent_logs:
            detail = loc_detail.get((log.entity_name or "").lower())
            recent_searches.append({
                "name":        log.entity_name or "—",
                "type":        detail.type     if detail else "—",
                "floor":       detail.floor    if detail else None,
                "building":    detail.building if detail else "—",
                "searched_at": log.searched_at.isoformat() if log.searched_at else None,
            })
    except Exception:
        recent_searches = [{"name": l.entity_name or "—", "type": "—", "floor": None,
                            "building": "—",
                            "searched_at": l.searched_at.isoformat() if l.searched_at else None}
                           for l in recent_logs]

    return {
        "total_searches":    total_searches,
        "today_searches":    today_searches,
        "unique_locations":  unique_locations,
        "top_location":      top_location or "—",
        "top_locations":     top_locs,
        "type_breakdown":    type_breakdown,
        "recent_searches":   recent_searches,
    }

'''

ANCHOR = "\n# ── Intent health endpoint ───────────────────────────────────────────────────"

if "@admin_router.get(\"/nav-statistics\")" in src:
    print("SKIP: /nav-statistics route already exists")
elif ANCHOR in src:
    src = src.replace(ANCHOR, NAV_STATS_ROUTE + ANCHOR)
    print("OK: Added /nav-statistics route to main.py")
else:
    print("WARN: Could not find insertion point for nav-statistics route")
    print("      Manually add the route before the intent health endpoint.")

# ─────────────────────────────────────────────────────────────
# Write back
# ─────────────────────────────────────────────────────────────
if src != original:
    with open(MAIN, "w", encoding="utf-8", newline="") as f:
        f.write(src)
    print("\nSAVED main.py")
else:
    print("\nNo changes written.")

print("\nDone!")
print("-> Restart server:      uvicorn main:app --reload")
print("-> Hard refresh browser: Ctrl+Shift+R  (clears JS cache too)")