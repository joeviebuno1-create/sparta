import os, sys
sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.abspath(__file__))
JS   = os.path.join(BASE, "admin", "admin-script.js")
MAIN = os.path.join(BASE, "main.py")

with open(JS, "r", encoding="utf-8") as f:
    js = f.read().replace("\r\n", "\n")

with open(MAIN, "r", encoding="utf-8") as f:
    main = f.read().replace("\r\n", "\n")

def show(label, src, keyword, ctx=600):
    idx = src.find(keyword)
    if idx == -1:
        print(f"\n[NOT FOUND] {label}: {keyword!r}")
        return
    print(f"\n==== {label} ====")
    print(repr(src[max(0,idx-30):idx+ctx]))

# 1. Find the success rate element in JS
show("successRate element", js, "successRate")
show("navSuccess", js, "navSuccess")
show("search_success", js, "search_success")

# 2. Find bar track colors still remaining
show("e2e8f0 remaining", js, "e2e8f0")
show("bar gradient intent", js, "c41e3a")
show("bar gradient entity", js, "3b82f6,#1d4ed8")
show("bar gradient purple", js, "7c3aed")

# 3. nav-statistics route in main.py
show("nav-statistics route", main, "nav-statistics")
show("nav_statistics route", main, "nav_statistics")