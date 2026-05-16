"""
Run from SPARTHA/backend:
    python dump_charts.py
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.abspath(__file__))
JS   = os.path.join(BASE, "admin", "admin-script.js")

with open(JS, "r", encoding="utf-8") as f:
    src = f.read()

src = src.replace("\r\n", "\n")

def show(label, keyword, ctx=500):
    idx = src.find(keyword)
    if idx == -1:
        print(f"[NOT FOUND] {keyword!r}")
        return
    print(f"\n==== {label} ====")
    print(repr(src[max(0,idx-30):idx+ctx]))

show("intentDiv", "intentDiv.innerHTML")
show("entityDiv", "entityDiv.innerHTML")
show("navLocationChart innerHTML", "locDiv.innerHTML")
show("navTypeChart innerHTML", "typeDiv.innerHTML")
show("navTypeChart fallback", "navTypeChart').innerHTML = typeArr")
show("navLocationChart fallback", "navLocationChart').innerHTML = topLocs")
show("success rate", "success")
show("nav-statistics endpoint", "nav-statistics")