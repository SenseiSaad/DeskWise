"""Admin actions, part A: overview, members, documents."""
import os, re
from playwright.sync_api import sync_playwright, expect
from common import BASE, Session, Runner, login

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
ADMIN = ("admin@browsertest.test", "Br0wser-Test-Pass!7")
EMP = ("eve@browsertest.test", "Eve-Employee-Pass!5")

with sync_playwright() as pw:
    s = Session(pw, "admin"); p = s.page; r = Runner(s, "admin")
    login(s, *ADMIN, role="admin")

    def go(path):
        p.goto(f"{BASE}/workspace{path}"); p.wait_for_load_state("networkidle"); p.wait_for_timeout(400)

    # ---------------- Overview
    go("")
    r.step("overview", "stat cards + company code render", lambda: expect(p.get_by_text(re.compile("Company code"))).to_be_visible())
    def announce():
        p.get_by_role("button", name=re.compile("Post Announcement")).first.click()
        p.get_by_placeholder("e.g. Office Closed on Friday").fill("Office closed Friday")
        p.get_by_placeholder(re.compile("Write the company-wide")).fill("Please work remotely this Friday.")
        p.get_by_role("button", name=re.compile(r"^(Post|Broadcast|Send|Publish)", re.I)).last.click()
        expect(p.get_by_text("Office closed Friday").first).to_be_visible(timeout=8000)
    r.step("overview", "post announcement", announce)
    def quick():
        p.get_by_role("link", name=re.compile("Manage team")).click(); p.wait_for_url(re.compile("/workspace/members"))
    r.step("overview", "quick action 'Manage team' navigates", quick)

    # ---------------- Members
    go("/members")
    def add_member(email, name, pw_, role="Employee"):
        p.get_by_placeholder("Ada Lovelace").fill(name)
        p.locator("label").filter(has_text=re.compile(rf"^{role}")).first.click()
        p.get_by_placeholder("teammate@company.com").fill(email)
        p.get_by_placeholder("At least 8 characters").fill(pw_)
        p.get_by_role("button", name="Add member").click()
        expect(p.get_by_text(email).first).to_be_visible(timeout=8000)
    r.step("members", "add employee Eve", lambda: add_member(EMP[0], "Eve Employee", EMP[1]))
    r.step("members", "add throwaway member", lambda: add_member("temp@browsertest.test", "Temp Person", "Temp-Person-Pass!4"))
    r.step("members", "member count updates to 3", lambda: expect(p.get_by_role("heading", name=re.compile(r"Members \(3\)"))).to_be_visible())
    r.step("members", "Eve listed with role Employee", lambda: expect(p.locator("tbody tr").filter(has_text="eve@browsertest.test").get_by_text("Employee", exact=True)).to_be_visible())
    def edit_member():
        p.locator("tbody tr").filter(has_text="eve@browsertest.test").get_by_title("Edit member").click()
        dlg = p.locator("form").filter(has_text="Full name").last
        sel = dlg.locator("select").first
        sel.select_option(index=2); chosen = sel.evaluate("e => e.options[e.selectedIndex].text")
        with p.expect_response(lambda x: x.request.method in ("PATCH", "PUT") and "/api/admin/users/" in x.url) as ri:
            dlg.get_by_role("button", name=re.compile("Save", re.I)).click()
        assert ri.value.status < 300, ri.value.status
        p.reload(); p.wait_for_load_state("networkidle")
        expect(p.locator("tbody tr").filter(has_text="eve@browsertest.test").get_by_text(chosen)).to_be_visible(timeout=8000)
        return f"title set to {chosen}; persisted after reload (API {ri.value.status})"
    r.step("members", "edit member (job title)", edit_member)
    def remove_member():
        p.locator("tbody tr").filter(has_text="temp@browsertest.test").get_by_title("Remove member").click()
        with p.expect_response(lambda x: x.request.method == "DELETE" and "/api/admin/users/" in x.url) as ri:
            p.get_by_role("dialog").get_by_role("button", name="Remove").click()
        expect(p.get_by_text("temp@browsertest.test")).to_have_count(0, timeout=8000)
        return f"DELETE {ri.value.status}"
    r.step("members", "remove throwaway member (confirm dialog)", remove_member)

    # ---------------- Documents
    go("/documents")
    def upload(fname, expect_name):
        p.get_by_role("button", name=re.compile("Upload a document")).click()
        p.locator("#up-file").set_input_files(os.path.join(FIX, fname))
        p.locator("#up-category").fill("Policy")
        p.get_by_role("button", name=re.compile(r"^Upload( & index| document| file)?$", re.I)).last.click()
        expect(p.get_by_text(re.compile(expect_name, re.I)).first).to_be_visible(timeout=10000)
    r.step("documents", "upload zephyr-policy.txt", lambda: upload("zephyr-policy.txt", "zephyr-policy"))
    def wait_ready():
        for _ in range(40):
            p.reload(); p.wait_for_load_state("networkidle")
            if p.get_by_text(re.compile(r"pending|indexing", re.I)).count() == 0: break
            p.wait_for_timeout(1500)
        expect(p.get_by_text(re.compile(r"failed", re.I))).to_have_count(0)
    r.step("documents", "indexing finishes (no pending/failed badge)", wait_ready)
    r.step("documents", "stats show 1 document", lambda: expect(p.get_by_text("1", exact=True).first).to_be_visible())
    def search():
        box = p.get_by_label("Search documents"); box.fill("zephyr"); p.wait_for_timeout(600)
        expect(p.get_by_text("Zephyr Policy").first).to_be_visible()
        box.fill("nonexistent-xyz"); p.wait_for_timeout(600)
        expect(p.get_by_text("Zephyr Policy")).to_have_count(0); box.fill("")
    r.step("documents", "search filters list", search)
    def preview():
        p.get_by_role("button", name=re.compile("Preview")).first.click()
        expect(p.get_by_text(re.compile("Zephyr-9")).first).to_be_visible(timeout=8000)
        p.keyboard.press("Escape")
        if p.get_by_text(re.compile("Zephyr-9")).count(): p.get_by_role("button", name=re.compile("Close", re.I)).first.click()
    r.step("documents", "preview shows extracted text", preview)
    def download():
        with p.expect_download(timeout=10000) as d:
            p.get_by_role("button", name=re.compile("Download")).first.click()
        return d.value.suggested_filename
    r.step("documents", "download file", download)
    def share_dialog():
        p.get_by_role("button", name=re.compile("Share")).first.click()
        expect(p.get_by_text("Control document access")).to_be_visible(timeout=6000)
        p.get_by_label("Close").first.click()
    r.step("documents", "share dialog opens", share_dialog)
    r.step("documents", "upload throwaway note", lambda: upload("throwaway.txt", "throwaway"))
    def sort_recent():
        names = p.locator("h3, [class*=font-semibold]").filter(has_text=re.compile("^(Throwaway|Zephyr Policy)$")).all_inner_texts()
        assert names and names[0] == "Throwaway", f"order was {names}"
        return f"order: {names}"
    r.step("documents", "'Most recent' sort puts newest upload first", sort_recent)
    def delete_doc():
        title = p.get_by_text("Throwaway", exact=True)
        expect(title).to_be_visible(timeout=10000)  # the list row, not the upload toast
        title.locator("xpath=ancestor::div[.//button[normalize-space()='Delete']][1]").get_by_role("button", name="Delete").click()
        with p.expect_response(lambda x: x.request.method == "DELETE" and "/api/documents/" in x.url) as ri:
            p.get_by_role("dialog").get_by_role("button", name="Delete").click()
        expect(p.get_by_text("Throwaway")).to_have_count(0, timeout=8000)
        expect(p.get_by_text("Zephyr Policy").first).to_be_visible()
        return f"DELETE {ri.value.status}; the other document is untouched"
    r.step("documents", "delete document (confirm dialog)", delete_doc)
    s.close()
