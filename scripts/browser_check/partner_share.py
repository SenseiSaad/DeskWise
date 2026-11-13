"""A second tenant (Partner Co) signs up via the UI, uploads a document and shares it
with ONE employee (Eve) of Browser Test Co using that company's access code."""
import os, re, sys
from playwright.sync_api import sync_playwright, expect
from common import BASE, Session, Runner, login

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
code = sys.argv[1]  # Browser Test Co's company code
PE, PP = "partner@partnerco.test", "Part-ner-Pass!8x"

with sync_playwright() as pw:
    s = Session(pw, "partner"); p = s.page; r = Runner(s, "partner")
    def signup():
        p.goto(f"{BASE}/enterprise?role=admin")
        p.get_by_role("tab", name="Create an organization").click()
        p.locator("#create-company").fill("Partner Co"); p.locator("#create-name").fill("Pat Partner")
        p.locator("#create-email").fill(PE); p.locator("#create-password").fill(PP)
        p.get_by_role("button", name=re.compile("Create organization")).click()
        p.wait_for_url(re.compile("/workspace"), timeout=20000); p.wait_for_load_state("networkidle")
    r.step("overview", "second tenant signs up (Partner Co)", signup)
    def upload():
        p.goto(f"{BASE}/workspace/documents"); p.wait_for_load_state("networkidle")
        p.get_by_role("button", name=re.compile("Upload a document")).click()
        p.locator("#up-file").set_input_files(os.path.join(FIX, "partner-handbook.txt"))
        p.get_by_role("button", name=re.compile(r"^Upload( & index| document| file)?$", re.I)).last.click()
        expect(p.get_by_text(re.compile("Partner Handbook", re.I)).first).to_be_visible(timeout=10000)
        for _ in range(30):
            p.reload(); p.wait_for_load_state("networkidle")
            if p.get_by_text(re.compile("pending", re.I)).count() == 0: break
            p.wait_for_timeout(1500)
    r.step("documents", "partner uploads partner-handbook.txt", upload)
    def share():
        p.get_by_role("button", name=re.compile("Share")).first.click()
        p.get_by_placeholder(re.compile("Company code")).fill(code)
        p.get_by_role("button", name="Find").click()
        expect(p.get_by_text("Browser Test Co").first).to_be_visible(timeout=8000)
        sel = p.locator("select").filter(has=p.locator("option", has_text="Choose employee")).first
        labels = sel.locator("option").all_inner_texts()
        sel.select_option(label=[l for l in labels if "Eve" in l][0])
        with p.expect_response(lambda x: "/shares" in x.url and x.request.method == "POST") as ri:
            p.get_by_role("button", name=re.compile(r"^Share$")).last.click()
        assert ri.value.status < 300, ri.value.status
        expect(p.get_by_text("Access granted.")).to_be_visible(timeout=5000)
        return f"employees listed from other tenant: {labels[1:]}; POST {ri.value.status}"
    r.step("documents", "share one file with Eve of another company (by access code)", share)
    s.close()
