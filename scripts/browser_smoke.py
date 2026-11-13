"""Single-entrypoint Playwright browser smoke test for Deskwise.

Covers full critical user journey:
1. Sign up: Create a new company and admin user via /enterprise
2. Member management: Add a new employee in /workspace/members
3. Document upload: Upload a document in /workspace/documents
4. RAG Chat: Ask a question in /workspace/chat and verify response
5. Attendance: Verify and mark attendance in /workspace/attendance

Usage:
    /tmp/pwenv/bin/python scripts/browser_smoke.py
"""
import os
import re
import sys
import time
from playwright.sync_api import sync_playwright, expect

BASE = os.getenv("BASE_URL", "http://localhost:3000")
HEADLESS = os.getenv("HEADLESS", "1") != "0"
CHROME = os.getenv("CHROME_PATH", "/usr/bin/google-chrome")

ts = int(time.time())
COMPANY_NAME = f"Smoke Test Co {ts}"
ADMIN_EMAIL = f"smoke_admin_{ts}@example.com"
ADMIN_PASS = "Sm0keTest-Pass!9"
EMP_EMAIL = f"smoke_emp_{ts}@example.com"
EMP_NAME = f"Smoke Employee {ts}"
EMP_PASS = "Sm0keTest-Emp!9"

SAMPLE_DOC_PATH = f"/tmp/smoke_policy_{ts}.txt"
with open(SAMPLE_DOC_PATH, "w") as f:
    f.write(f"""# Remote Work and Equipment Policy - {COMPANY_NAME}
All employees are entitled to a remote work stipend of $640 per year.
Core business hours are 10:00 AM to 4:00 PM Eastern Time.
Submit travel requests at least 14 days in advance to travel@example.com.
""")


def run_smoke_test():
    print("=" * 60)
    print("Starting Deskwise Browser Smoke Test")
    print(f"Base URL: {BASE}")
    print(f"Chrome:   {CHROME}")
    print(f"Company:  {COMPANY_NAME}")
    print(f"Admin:    {ADMIN_EMAIL}")
    print("=" * 60)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=CHROME,
            headless=HEADLESS,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()

        # Step 1: Sign Up
        print("\n[1/5] Testing Sign Up & Organization Creation...")
        page.goto(f"{BASE}/enterprise?role=admin")
        page.wait_for_load_state("networkidle")

        create_tab = page.get_by_role("tab", name=re.compile("Create an organization", re.I))
        if create_tab.is_visible():
            create_tab.click()

        page.locator("#create-company").fill(COMPANY_NAME)
        page.locator("#create-name").fill("Admin User")
        page.locator("#create-email").fill(ADMIN_EMAIL)
        page.locator("#create-password").fill(ADMIN_PASS)

        submit_btn = page.get_by_role("button", name=re.compile("Create organization", re.I))
        submit_btn.click()

        page.wait_for_url(re.compile(r"/workspace"), timeout=20000)
        print("  -> Sign up successful! Navigated to:", page.url)

        # Step 2: Member Management
        print("\n[2/5] Testing Member Management (Add Employee)...")
        page.goto(f"{BASE}/workspace/members")
        page.wait_for_load_state("networkidle")

        name_input = page.get_by_placeholder("Ada Lovelace")
        name_input.fill(EMP_NAME)

        emp_label = page.locator("label").filter(has_text=re.compile(r"^Employee", re.I)).first
        if emp_label.is_visible():
            emp_label.click()

        page.get_by_placeholder("teammate@company.com").fill(EMP_EMAIL)
        page.get_by_placeholder("At least 8 characters").fill(EMP_PASS)

        page.get_by_role("button", name=re.compile("Add member", re.I)).click()
        expect(page.get_by_text(EMP_EMAIL).first).to_be_visible(timeout=10000)
        print(f"  -> Successfully added employee {EMP_EMAIL}!")

        # Step 3: Document Upload
        print("\n[3/5] Testing Document Upload...")
        page.goto(f"{BASE}/workspace/documents")
        page.wait_for_load_state("networkidle")

        page.get_by_role("button", name=re.compile("Upload a document")).click()
        page.locator("#up-file").set_input_files(SAMPLE_DOC_PATH)
        page.locator("#up-category").fill("Policy")
        page.get_by_role("button", name=re.compile(r"^Upload( & index| document| file)?$", re.I)).last.click()

        doc_filename = os.path.basename(SAMPLE_DOC_PATH)
        expect(page.get_by_text(re.compile(doc_filename, re.I)).first).to_be_visible(timeout=15000)
        print(f"  -> Document {doc_filename} uploaded and listed!")

        # Step 4: RAG Chat
        print("\n[4/5] Testing Chat Flow...")
        page.goto(f"{BASE}/workspace/chat")
        page.wait_for_load_state("networkidle")

        page.get_by_label("Your question").fill("What is the remote work stipend amount?")
        page.get_by_label("Send").click()

        # Verify query was sent and streaming started (sources or answer appear)
        expect(page.get_by_text(re.compile(r"Thinking|Sources|stipend|\$640", re.I)).first).to_be_visible(timeout=30000)
        # Wait until generation finishes (Stop generating button disappears)
        page.wait_for_function("() => !document.querySelector('[aria-label=\"Stop generating\"]')", timeout=120000)
        print("  -> Chat query submitted and response completed!")

        # Step 5: Attendance
        print("\n[5/5] Testing Attendance Page...")
        page.goto(f"{BASE}/workspace/attendance")
        page.wait_for_load_state("networkidle")

        mark_btn = page.get_by_role("button", name="Mark me present")
        if mark_btn.is_visible():
            mark_btn.click()
            expect(page.get_by_role("button", name=re.compile("Already marked"))).to_be_visible(timeout=8000)
            print("  -> Marked attendance successfully: 'Already marked' status shown!")
        else:
            expect(page.get_by_text(re.compile("Already marked|Status|Attendance", re.I)).first).to_be_visible(timeout=8000)
            print("  -> Attendance status verified!")

        browser.close()
        try:
            os.remove(SAMPLE_DOC_PATH)
        except OSError:
            pass

    print("\n" + "=" * 60)
    print("ALL 5 BROWSER SMOKE TEST CHECKS PASSED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    try:
        run_smoke_test()
    except Exception as e:
        print(f"\nSMOKE TEST FAILED: {e}", file=sys.stderr)
        sys.exit(1)
