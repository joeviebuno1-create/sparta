"""
Run from SPARTHA/backend:
    cd C:\\Users\\joevi\\SPARTHA\\backend
    python apply_fixes.py
"""
import os, re, sys

# Fix Windows console encoding
sys.stdout.reconfigure(encoding="utf-8")

BASE  = os.path.dirname(os.path.abspath(__file__))
ADMIN = os.path.join(BASE, "admin")
MAIN  = os.path.join(BASE, "main.py")
JS    = os.path.join(ADMIN, "admin-script.js")

def read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def write(p, txt):
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(txt)
    print(f"  SAVED -> {p}")

def sub(src, pattern, repl, label="", flags=re.DOTALL):
    new, n = re.subn(pattern, repl, src, flags=flags)
    if n:
        print(f"  OK ({n}x) {label}")
    else:
        print(f"  NOT FOUND -- {label}")
    return new

# ══════════════════════════════════════════════════════════════
#  main.py  --  add updated_at to announcement_popups migration
# ══════════════════════════════════════════════════════════════
print("\n=== main.py ===")
src = read(MAIN)

src = sub(src,
    r"(for col, definition in \[[\s\S]*?'expires_at',\s*'TIMESTAMP'\),)\s*\]:",
    r"\1\n            ('updated_at',   'TIMESTAMP DEFAULT NOW()'),\n        ]:",
    "add updated_at migration"
)

write(MAIN, src)

# ══════════════════════════════════════════════════════════════
#  admin-script.js  --  chart text + SPARTA branding
# ══════════════════════════════════════════════════════════════
print("\n=== admin-script.js ===")
src = read(JS)

# Normalise Windows line endings
src = src.replace("\r\n", "\n")

# 1. All chart label text: dark grey -> visible white
src = sub(src,
    r'font-size:0\.82rem;color:#475569;margin-bottom:3px;',
    r'font-size:0.82rem;color:rgba(255,255,255,0.85);margin-bottom:3px;',
    "all label colours #475569 -> white"
)

# 2. All bar track backgrounds: light grey -> dark transparent
src = sub(src,
    r'background:#e2e8f0;border-radius:99px;height:10px',
    r'background:rgba(255,255,255,0.08);border-radius:99px;height:10px',
    "all bar track #e2e8f0 -> dark"
)

# 3. Intent chart gradient: old red -> SPARTA red/gold
src = sub(src,
    r'background:linear-gradient\(90deg,#c41e3a,#9b1530\)',
    r'background:linear-gradient(90deg,#c93030,#F4D03F)',
    "intent bar gradient"
)

# 4. Entity chart gradient: blue -> SPARTA red/orange
src = sub(src,
    r'background:linear-gradient\(90deg,#3b82f6,#1d4ed8\)',
    r'background:linear-gradient(90deg,#c93030,#e85d04)',
    "entity bar gradient"
)

# 5. Nav location chart gradient: purple -> SPARTA red/gold
src = sub(src,
    r'background:linear-gradient\(90deg,#7c3aed,#5b21b6\)',
    r'background:linear-gradient(90deg,#c93030,#F4D03F)',
    "nav location bar gradient"
)

# 6. Count numbers: plain strong -> gold strong  (all chart blocks)
src = src.replace(
    '><strong>${item.count}</strong>',
    '><strong style="color:#F4D03F;">${item.count}</strong>'
)
print("  OK  count numbers -> gold")

write(JS, src)

print("\nAll done!")
print("-> Restart server: uvicorn main:app --reload")
print("-> Hard refresh browser: Ctrl+Shift+R")