"""Map interactive elements on every workspace page for a given user."""
import json, sys
from playwright.sync_api import sync_playwright
from common import BASE, Session, login, visible_summary

email, password, role, label = sys.argv[1:5]
with sync_playwright() as pw:
    s = Session(pw, label); login(s, email, password, role); s.drain()
    for path in ["", "/chat", "/documents", "/shared", "/attendance", "/members", "/audit", "/usage", "/settings"]:
        s.page.goto(f"{BASE}/workspace{path}"); s.page.wait_for_load_state("networkidle"); s.page.wait_for_timeout(500)
        d = visible_summary(s.page); d.pop("main_text_len"); d.pop("title")
        print(f"\n== {label} /workspace{path} -> {s.page.url.replace(BASE,'')}"); print(json.dumps(d, ensure_ascii=False))
    s.close()
