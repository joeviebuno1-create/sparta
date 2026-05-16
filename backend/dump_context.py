"""
Run from SPARTHA/backend:
    python dump_context.py

Dumps the exact bytes around the chart sections so we can build correct patches.
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")

BASE  = os.path.dirname(os.path.abspath(__file__))
ADMIN = os.path.join(BASE, "admin")
MAIN  = os.path.join(BASE, "main.py")
JS    = os.path.join(ADMIN, "admin-script.js")

def show_around(text, keyword, ctx=300):
    idx = text.find(keyword)
    if idx == -1:
        print(f"  [NOT FOUND]: {keyword!r}")
        return
    start = max(0, idx - 50)
    end   = min(len(text), idx + ctx)
    print(repr(text[start:end]))
    print("---")

with open(JS, "r", encoding="utf-8") as f:
    js = f.read()

with open(MAIN, "r", encoding="utf-8") as f:
    main = f.read()

print("==== JS: intentDiv block ====")
show_around(js, "intentDiv.innerHTML", 600)

print("==== JS: entityDiv block ====")
show_around(js, "entityDiv.innerHTML", 600)

print("==== JS: navLocationChart block ====")
show_around(js, "navLocationChart", 600)

print("==== JS: navTypeChart block ====")
show_around(js, "navTypeChart", 600)

print("==== main.py: expires_at migration block ====")
show_around(main, "expires_at", 400)