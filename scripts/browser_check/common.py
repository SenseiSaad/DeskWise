"""Shared helpers for the workspace browser verification (Playwright).

    python3 -m venv /tmp/pwenv && /tmp/pwenv/bin/pip install playwright
    /tmp/pwenv/bin/python scripts/browser_check/<script>.py

Uses the system Chrome so no browser download is needed. Every page records
console errors, uncaught page errors and HTTP >= 400 responses as evidence.
"""
import json
import os
import re
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get("WEB_URL", "http://localhost:3000")
API = os.environ.get("API_URL", "http://localhost:8000")
EVIDENCE = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "evidence", "workspace-browser")
CHROME = os.environ.get("CHROME_PATH", "/usr/bin/google-chrome")


class Session:
    """One browser context (= one logged-in user) with event capture."""

    def __init__(self, pw, label):
        self.label = label
        self.browser = pw.chromium.launch(executable_path=CHROME, headless=True,
                                          args=["--no-sandbox"])
        self.ctx = self.browser.new_context(viewport={"width": 1440, "height": 900})
        self.page = self.ctx.new_page()
        self.events = []  # (kind, url_or_text)
        self.page.on("console", lambda m: self.events.append(("console." + m.type, m.text))
                     if m.type in ("error", "warning") else None)
        self.page.on("pageerror", lambda e: self.events.append(("pageerror", str(e))))
        self.page.on("response", self._on_response)

    def _on_response(self, r):
        if r.status >= 400:
            self.events.append((f"http{r.status}", f"{r.request.method} {r.url}"))

    def drain(self):
        ev, self.events = self.events, []
        return ev

    def shot(self, name):
        os.makedirs(EVIDENCE, exist_ok=True)
        path = os.path.join(EVIDENCE, f"{self.label}-{name}.png")
        self.page.screenshot(path=path, full_page=True)
        return os.path.relpath(path, os.path.join(EVIDENCE, "..", "..", ".."))

    def close(self):
        self.browser.close()


def login(sess, email, password, role="admin"):
    p = sess.page
    p.goto(f"{BASE}/enterprise?role={role}")
    p.get_by_label("Email", exact=False).first.fill(email)
    p.locator("#signin-password").fill(password)
    p.get_by_role("button", name=re.compile(r"^Sign in")).last.click()
    p.wait_for_url(re.compile(r"/workspace"), timeout=20000)
    p.wait_for_load_state("networkidle")


def api_login_cookie(email, password):
    """Not used for UI checks; handy for seeding via the API."""
    import urllib.request
    req = urllib.request.Request(f"{API}/api/auth/login", method="POST",
                                 data=json.dumps({"email": email, "password": password}).encode(),
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req)


def visible_summary(page):
    """Headings, buttons, inputs and links currently visible: used to map a page."""
    return page.evaluate("""() => {
      const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
      const txt = e => (e.innerText || e.getAttribute('aria-label') || e.placeholder || '').trim().replace(/\\s+/g,' ').slice(0,60);
      const pick = sel => [...document.querySelectorAll(sel)].filter(vis).map(txt).filter(Boolean);
      return {
        title: document.title,
        h: pick('h1,h2,h3').slice(0, 14),
        buttons: pick('button').filter(t => !['English','Log out'].includes(t)).slice(0, 40),
        links: pick('a[href]:not(nav a)').slice(0, 20),
        inputs: [...document.querySelectorAll('input, select, textarea')].filter(vis)
                  .map(e => (e.placeholder || e.id || e.name || e.type)).slice(0, 25),
        main_text_len: document.body.innerText.length,
      };
    }""")


def now():
    return time.strftime("%H:%M:%S")


NOISE = ("_vercel/insights",)  # Vercel analytics beacon: 404s off-Vercel (reported separately)
RESULTS = os.path.join(EVIDENCE, "results.jsonl")


class Runner:
    """Runs named steps; records PASS/FAIL + evidence. A failed step never stops the run."""

    def __init__(self, sess, who):
        self.s, self.who = sess, who

    def step(self, page_name, action, fn, expect_events=()):
        self.s.drain()
        status, detail = "PASS", ""
        try:
            r = fn()
            detail = "" if r is None else str(r)
        except Exception as e:  # noqa: BLE001
            status, detail = "FAIL", (str(e).splitlines() or [""])[0][:300]
        events = [e for e in self.s.drain()
                  if not any(n in e[1] for n in NOISE)
                  and not any(x in e[1] for x in expect_events)
                  and "Failed to load resource" not in e[1]]
        shot = ""
        if status == "FAIL" or os.environ.get("SHOT_ALL"):
            try:
                shot = self.s.shot(f"step-{re.sub(r'[^a-z0-9]+', '-', (page_name + '-' + action).lower())[:60]}")
            except Exception:  # noqa: BLE001
                pass
        rec = {"who": self.who, "page": page_name, "action": action, "status": status,
               "detail": detail, "events": events[:6], "shot": shot}
        os.makedirs(EVIDENCE, exist_ok=True)
        with open(RESULTS, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        flag = {"PASS": "PASS", "FAIL": "FAIL"}[status]
        print(f"[{flag}] {self.who:8} {page_name:11} {action}" + (f"  -> {detail}" if detail else "")
              + (f"  !! {events[:3]}" if events else ""))
        return status == "PASS"
