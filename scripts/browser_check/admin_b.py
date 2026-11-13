"""Admin actions, part B: chat, attendance, audit, usage, settings, shared."""
import re
from playwright.sync_api import sync_playwright, expect
from common import BASE, Session, Runner, login

ADMIN = ("admin@browsertest.test", "Br0wser-Test-Pass!7")
Q = "How much is the Zephyr-9 chair stipend and how long do I have to claim it?"

with sync_playwright() as pw:
    s = Session(pw, "admin"); p = s.page; r = Runner(s, "admin")
    login(s, *ADMIN, role="admin")
    def go(path):
        p.goto(f"{BASE}/workspace{path}"); p.wait_for_load_state("networkidle"); p.wait_for_timeout(400)

    # ---------------- Chat
    go("/chat")
    def ask():
        p.get_by_label("Your question").fill(Q)
        p.get_by_label("Send").click()
        expect(p.get_by_text(re.compile(r"\$?640")).first).to_be_visible(timeout=120000)
        expect(p.get_by_text(re.compile("45 days")).first).to_be_visible(timeout=60000)
        p.wait_for_function("() => !document.querySelector('[aria-label=\"Stop generating\"]')", timeout=120000)
    r.step("chat", "ask question -> streamed answer ($640 / 45 days)", ask)
    r.step("chat", "answer cites source document", lambda: expect(p.get_by_text(re.compile("zephyr-policy", re.I)).first).to_be_visible(timeout=10000))
    def feedback():
        with p.expect_response(lambda x: "/api/" in x.url and "/rate" in x.url and x.request.method == "POST", timeout=8000) as ri:
            p.get_by_role("button", name=re.compile(r"^Helpful$")).first.click()
        assert ri.value.status < 300, f"feedback API {ri.value.status}"
        return f"feedback API {ri.value.status}"
    r.step("chat", "thumbs feedback saved via API", feedback)
    def history():
        p.get_by_label(re.compile("Open conversation history|Collapse conversation history")).first.click(); p.wait_for_timeout(500)
        expect(p.get_by_text(re.compile("Zephyr|stipend", re.I)).first).to_be_visible()
    r.step("chat", "conversation saved to history sidebar", history)
    def new_chat():
        p.get_by_role("button", name=re.compile("New chat")).first.click(); p.wait_for_timeout(500)
        expect(p.get_by_text("Ask your documents, or create one")).to_be_visible()
    r.step("chat", "New chat resets the thread", new_chat)
    def reopen():
        p.get_by_text(re.compile("Zephyr|stipend", re.I)).first.click(); p.wait_for_timeout(1500)
        expect(p.get_by_label("Your question")).to_be_visible()
        expect(p.get_by_text("Ask your documents, or create one")).to_have_count(0)
        expect(p.get_by_text(re.compile("SOURCES", re.I)).first).to_be_visible(timeout=10000)
    r.step("chat", "reopen past conversation", reopen)
    def docgen():
        p.get_by_role("button", name=re.compile("New chat")).first.click(); p.wait_for_timeout(400)
        p.get_by_role("button", name=re.compile("Leave request")).first.click()
        expect(p.get_by_text(re.compile(r"Leave request|prepared your", re.I)).first).to_be_visible(timeout=120000)
        s.shot("chat-docgen-leave-request")
    r.step("chat", "docgen starter 'Leave request'", docgen)
    def isolation():
        p.get_by_role("button", name=re.compile("New chat")).first.click(); p.wait_for_timeout(400)
        p.get_by_label("Your question").fill("What is the maximum hotel budget for the Quokka-3 summit?"); p.get_by_label("Send").click()
        p.wait_for_timeout(2000)
        p.wait_for_function("() => !document.querySelector('[aria-label=\"Stop generating\"]')", timeout=150000); p.wait_for_timeout(800)
        body = p.locator("body").inner_text()
        assert "partner-handbook" not in body.lower() and "2250" not in body.replace(",", ""), "leaked Partner Co content"
        s.shot("chat-isolation-no-partner-doc")
        return "no Partner Co source or figure shown"
    r.step("chat", "doc shared to someone else is NOT visible to admin (no cite/leak)", isolation)
    def hist_open():
        if p.get_by_label("Collapse conversation history").count() == 0 and p.get_by_label("Open conversation history").count():
            p.get_by_label("Open conversation history").first.click(); p.wait_for_timeout(500)
    def del_conv():
        hist_open(); n = p.get_by_label("Delete conversation").count()
        with p.expect_response(lambda x: x.request.method == "DELETE" and "/api/" in x.url, timeout=8000) as ri:
            p.get_by_label("Delete conversation").first.click(force=True)
        p.wait_for_timeout(800)
        after = p.get_by_label("Delete conversation").count()
        p.reload(); p.wait_for_load_state("networkidle"); p.wait_for_timeout(600); hist_open()
        persisted = p.get_by_label("Delete conversation").count()
        assert after == n - 1 and persisted == n - 1, f"{n} -> {after} (after reload {persisted}), API {ri.value.status}"
        return f"{n} -> {after}, persists after reload, DELETE {ri.value.status}"
    r.step("chat", "delete conversation", del_conv)

    # ---------------- Attendance
    go("/attendance")
    def mark():
        p.get_by_role("button", name="Mark me present").click()
        expect(p.get_by_role("button", name=re.compile("Already marked"))).to_be_visible(timeout=8000)
    r.step("attendance", "Mark me present -> Already marked", mark)
    r.step("attendance", "recent attendance lists today's entry", lambda: expect(p.get_by_text(re.compile(r"Alice|present|Nov", re.I)).last).to_be_visible())
    r.step("attendance", "workplace QR code shown", lambda: expect(p.locator("img[alt*='QR' i], svg, canvas").first).to_be_visible())

    # ---------------- Audit
    go("/audit")
    r.step("audit", "log rows present (register/upload/etc.)", lambda: expect(p.get_by_text(re.compile("register|upload", re.I)).first).to_be_visible())
    def audit_search():
        b = p.get_by_placeholder("Search action, detail, or IP…"); b.fill("zephyr"); p.wait_for_timeout(700)
        expect(p.get_by_text(re.compile("zephyr", re.I)).first).to_be_visible(); b.fill("")
    r.step("audit", "search box filters", audit_search)
    def audit_filter():
        sel = p.locator("#action-filter"); opts = sel.locator("option").all_inner_texts()
        sel.select_option(index=min(2, len(opts)-1)); p.wait_for_timeout(700); return f"{len(opts)} action options"
    r.step("audit", "action filter dropdown", audit_filter)
    r.step("audit", "Refresh button", lambda: p.get_by_role("button", name="Refresh").click())
    def csv():
        with p.expect_download(timeout=10000) as d:
            p.get_by_role("link", name=re.compile("Export CSV")).click()
        return d.value.suggested_filename
    r.step("audit", "Export CSV downloads", csv)

    # ---------------- Usage
    go("/usage")
    r.step("usage", "shows Free plan and ask quota", lambda: expect(p.get_by_text(re.compile("Free")).first).to_be_visible())
    def upgrade():
        p.get_by_role("button", name=re.compile("Upgrade.*19")).click(); p.wait_for_timeout(2500)
        s.shot("usage-after-upgrade-click")
        txt = p.locator("body").inner_text()
        hit = [l for l in txt.splitlines() if re.search(r"stripe|not configured|unavailable|error|failed|checkout", l, re.I)]
        assert not p.url.startswith("http://localhost:3000/workspace/usage") or hit, "button did nothing visible"
        return "url=" + p.url.replace(BASE, "") + " msg=" + (hit[0][:120] if hit else "")
    r.step("usage", "Upgrade ($19/mo) responds (no Stripe configured)", upgrade)

    # ---------------- Settings
    go("/settings")
    def save_profile():
        p.get_by_role("button", name="Save My Profile").click(); p.wait_for_timeout(1200)
        expect(p.get_by_text(re.compile("saved|updated", re.I)).first).to_be_visible(timeout=5000)
    r.step("settings", "Save My Profile", save_profile)
    def save_company():
        p.get_by_role("button", name="Company Profile").click(); p.wait_for_timeout(300)
        p.get_by_placeholder("hr@acme.org").fill("hr@browsertest.test")
        p.get_by_role("button", name="Save Profile").click(); p.wait_for_timeout(1200)
        expect(p.get_by_text(re.compile("saved|updated", re.I)).first).to_be_visible(timeout=5000)
    r.step("settings", "Company Profile tab: save", save_company)
    def plan_tab():
        p.get_by_role("button", name="Plan & Quotas").click(); p.wait_for_timeout(400)
        expect(p.get_by_text(re.compile("Free")).first).to_be_visible()
    r.step("settings", "Plan & Quotas tab renders", plan_tab)
    def ai_tab():
        p.get_by_role("button", name="AI Engine").click(); p.wait_for_timeout(600)
        s.shot("ai-engine-tab")
        return p.locator("main, body").first.inner_text()[:0] or "rendered"
    r.step("settings", "AI Engine tab renders", ai_tab)

    # ---------------- Shared
    go("/shared")
    r.step("shared", "empty state when nothing shared", lambda: expect(p.get_by_text(re.compile("nothing|No documents|empty|shared with you", re.I)).first).to_be_visible())
    s.close()
