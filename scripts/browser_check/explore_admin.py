"""Step 1: sign up through the UI, then map every workspace page as admin."""
import json
import re
import sys

from playwright.sync_api import sync_playwright

from common import BASE, Session, visible_summary

PAGES = ["", "/chat", "/documents", "/shared", "/attendance", "/members", "/audit", "/usage", "/settings"]
EMAIL, PASSWORD = "admin@browsertest.test", "Br0wser-Test-Pass!7"

with sync_playwright() as pw:
    s = Session(pw, "admin")
    p = s.page
    p.goto(f"{BASE}/enterprise?role=admin")
    p.get_by_role("tab", name="Create an organization").click()
    p.locator("#create-company").fill("Browser Test Co")
    p.locator("#create-name").fill("Alice Admin")
    p.locator("#create-email").fill(EMAIL)
    p.locator("#create-password").fill(PASSWORD)
    s.shot("00-signup-form-filled")
    p.get_by_role("button", name=re.compile("Create organization")).click()
    try:
        p.wait_for_url(re.compile(r"/workspace"), timeout=20000)
        print("SIGNUP: OK ->", p.url)
    except Exception as e:
        print("SIGNUP: FAILED", p.url, str(e)[:100])
        print(p.inner_text("body")[:600])
        s.shot("00-signup-failed")
        sys.exit(1)
    p.wait_for_load_state("networkidle")
    print("events after signup:", s.drain())

    for path in PAGES:
        p.goto(f"{BASE}/workspace{path}")
        p.wait_for_load_state("networkidle")
        p.wait_for_timeout(600)
        name = path.strip("/") or "overview"
        summ = visible_summary(p)
        shot = s.shot(f"01-{name}")
        print(f"\n=== admin /workspace{path}  (url now {p.url.replace(BASE,'')}) ===")
        print(json.dumps(summ, ensure_ascii=False))
        print("events:", s.drain())
    s.close()
