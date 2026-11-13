"""Employee (Eve) walkthrough of every workspace page + admin-page access checks."""
import os, re, json
from playwright.sync_api import sync_playwright, expect
from common import BASE, Session, Runner, login

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
EMP = ("eve@browsertest.test", "Eve-Employee-Pass!5")
ADMIN_ONLY = ["/members", "/audit", "/usage", "/settings"]

with sync_playwright() as pw:
    s = Session(pw, "employee"); p = s.page; r = Runner(s, "employee")
    login(s, *EMP, role="employee")
    def go(path):
        p.goto(f"{BASE}/workspace{path}"); p.wait_for_load_state("networkidle"); p.wait_for_timeout(500)

    # sidebar
    go("")
    def nav():
        labels = [t.strip() for t in p.get_by_role("navigation", name="Workspace").locator("a").all_inner_texts()]
        assert labels == ["Overview", "Ask AI", "Documents", "Shared with me", "Attendance"], labels
        return labels
    r.step("overview", "sidebar shows only the 5 employee pages", nav)
    r.step("overview", "page renders for employee", lambda: expect(p.get_by_text(re.compile("Welcome back, Eve", re.I))).to_be_visible())
    r.step("overview", "admin 'Post Announcement' hidden", lambda: expect(p.get_by_role("button", name=re.compile("Post Announcement"))).to_have_count(0))
    r.step("overview", "sees admin's announcement", lambda: expect(p.get_by_text("Office closed Friday").first).to_be_visible())

    # documents
    go("/documents")
    r.step("documents", "sees company-wide Zephyr Policy", lambda: expect(p.get_by_text("Zephyr Policy").first).to_be_visible())
    def preview():
        p.get_by_role("button", name=re.compile("Preview")).first.click()
        expect(p.get_by_text(re.compile("Zephyr-9")).first).to_be_visible(timeout=8000)
        p.keyboard.press("Escape")
        if p.get_by_text(re.compile("Zephyr-9")).count(): p.get_by_role("button", name=re.compile("Close", re.I)).first.click()
    r.step("documents", "preview a document", preview)
    def dl():
        with p.expect_download(timeout=10000) as d:
            p.get_by_role("button", name=re.compile("Download")).first.click()
        return d.value.suggested_filename
    r.step("documents", "download a document", dl)
    def own_upload():
        p.get_by_role("button", name=re.compile("Upload a document")).click()
        p.locator("#up-file").set_input_files(os.path.join(FIX, "throwaway.txt"))
        p.get_by_role("button", name=re.compile(r"^Upload( & index| document| file)?$", re.I)).last.click()
        expect(p.get_by_text("Throwaway", exact=True)).to_be_visible(timeout=10000)
    r.step("documents", "employee uploads own document", own_upload)
    def own_delete():
        t = p.get_by_text("Throwaway", exact=True)
        t.locator("xpath=ancestor::div[.//button[normalize-space()='Delete']][1]").get_by_role("button", name="Delete").click()
        with p.expect_response(lambda x: x.request.method == "DELETE" and "/api/documents/" in x.url) as ri:
            p.get_by_role("dialog").get_by_role("button", name="Delete").click()
        return f"DELETE {ri.value.status}"
    r.step("documents", "employee deletes own document", own_delete)

    # chat
    go("/chat")
    def ask(q, pat, src):
        p.get_by_label("Your question").fill(q); p.get_by_label("Send").click()
        expect(p.get_by_text(re.compile(pat)).first).to_be_visible(timeout=150000)
        p.wait_for_function("() => !document.querySelector('[aria-label=\"Stop generating\"]')", timeout=120000)
        expect(p.get_by_text(re.compile(src, re.I)).first).to_be_visible(timeout=10000)
    r.step("chat", "ask about company doc -> cited answer ($640)", lambda: ask("How much is the Zephyr-9 chair stipend?", r"\$?640", "zephyr-policy"))
    p.get_by_role("button", name=re.compile("New chat")).first.click()
    r.step("chat", "ask about doc shared from another tenant -> cited answer ($2250)", lambda: ask("What is the maximum hotel budget for the Quokka-3 summit?", r"2,?250", "partner-handbook"))

    # shared
    go("/shared")
    r.step("shared", "lists the document Partner Co shared with Eve", lambda: expect(p.get_by_text(re.compile("Partner Handbook", re.I)).first).to_be_visible())
    def shared_preview():
        btn = p.get_by_role("button", name=re.compile("Preview|View|Open")).first
        btn.click(); expect(p.get_by_text(re.compile("Quokka-3")).first).to_be_visible(timeout=8000); p.keyboard.press("Escape")
    r.step("shared", "preview the shared document", shared_preview)

    # attendance
    go("/attendance")
    def mark():
        p.get_by_role("button", name="Mark me present").click()
        expect(p.get_by_role("button", name=re.compile("Already marked"))).to_be_visible(timeout=8000)
    r.step("attendance", "Mark me present -> Already marked", mark)

    # admin-only pages by direct URL: UI behaviour + API enforcement
    for path in ADMIN_ONLY:
        def visit(path=path):
            go(path)
            txt = p.locator("body").inner_text()
            headline = {"/members": "Manage your team", "/audit": "Audit trail", "/usage": "Current plan", "/settings": "Settings & plans"}[path]
            rendered = headline.lower() in txt.lower()
            redirected = "/workspace" + path not in p.url
            return f"url={p.url.replace(BASE,'')} admin_ui_rendered={rendered} redirected={redirected}"
        r.step(path.strip("/"), "employee opens admin page by URL", visit)
    for api in ["/api/admin/users", "/api/admin/audit", "/api/admin/usage", "/api/admin/company", "/api/admin/llm-config", "/api/admin/analytics"]:
        def hit(api=api):
            resp = p.request.get(f"{BASE.replace(':3000', ':8000')}{api}")
            assert resp.status in (401, 403), f"employee got HTTP {resp.status}"
            return f"HTTP {resp.status}"
        r.step("api-guard", f"GET {api} refused for employee", hit)
    s.close()
