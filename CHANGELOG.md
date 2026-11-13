# Audit and Sale-Readiness CHANGELOG

All actions taken by the Senior Security and Release Engineer during the audit and sale preparation process.

---

## [Task 1: Secrets Audit] - 2026-11-09
- **Cloned Working Copy:** Created dedicated standalone audit working copy at `/home/saad/Desktop/OpenVault_audit_copy` to ensure the original repository remains untouched.
- **Tooling:** Installed `trufflehog` v3.99.8 and verified `gitleaks` v8.24.0.
- **Git History Scan:** Scanned all 87 commits across all branches and tags with TruffleHog and Gitleaks. Result: **0 verified secret leaks**.
- **File Pattern Audit:** Audited all commits for `.env`, `.bak`, `.sqlite`, `.db`, `tfstate`, `tfvars`, `.pem`, `.key`, `credentials`. Result: Exactly 7 `.example` templates were ever committed; zero actual secret or database files were ever committed to Git.
- **Database Schema Inspection:** Inspected the SQLite database schema (`db.sqlite3`) via metadata. Confirmed the schema is capable of holding sensitive customer data (passwords, MFA secrets, document text, chunks, chat messages, audit logs, Stripe IDs, API keys). Confirmed `db.sqlite3` is local only and gitignored.
- **Report Generated:** Produced [`SECRETS_REPORT.md`](file:///home/saad/Desktop/OpenVault_audit_copy/SECRETS_REPORT.md) containing the findings, redacted secret inventory, and complete secret rotation checklist.

## [Task 2: Clean Repo Strategy] - 2026-11-09
- **Bulletproofed `.gitignore`:** Added comprehensive wildcard protections for `*.bak`, `*.sqlite*`, `*.db`, `*.pem`, `*.key`, `*.cert`, `*.crt`, `*.p12`, `id_rsa*`, `*.tfvars`, `*.tfstate*`.
- **Sanitized `.env.example`:** Cleaned all values with non-functional placeholders and Deskwise branding.
- **Created Pre-Commit Gitleaks Hook:** Authored executable `.githooks/pre-commit` to prevent staging secrets locally.
- **Created CI Secret Workflow:** Added `.github/workflows/gitleaks.yml` to fail CI runs on any committed secret.
- **Formulated Proposals:** Authored [`CLEAN_REPO_PROPOSAL.md`](file:///home/saad/Desktop/OpenVault_audit_copy/CLEAN_REPO_PROPOSAL.md) detailing Option A (`git-filter-repo` in-place rewrite) vs. Option B (Fresh private repo with clean Initial Commit), strongly recommending Option B for acquisition due diligence.
- **Hold for User Approval:** Zero destructive commands executed on the source repository.

## [Task 3: Dependency Hardening & Vulnerability Remediation] - 2026-11-09
- **Frontend Audit Disproven:** Verified the rumored "95 npm vulnerabilities" was an artifact of older commits containing `shadcn` and `next@16.3.3`. Running `pnpm audit --prod` and `pnpm audit` on current `next@16.4.4` yielded **0 vulnerabilities**.
- **Backend Vulnerability Remediation:**
  - Upgraded `PyJWT` from `2.13.0` to `2.15.1`, fixing 15 CVE advisories (algorithm confusion, signature bypasses). Explicitly pinned `PyJWT==2.15.1` in `backend/requirements.txt`.
  - Upgraded `asteval` from `1.0.6` to `1.0.10`, fixing 2 CVE advisories.
  - Triaged `ecdsa==0.19.2` (PYSEC-2026-1325): confirmed dev-only dependency pulled by `checkov`, absent from production `requirements.txt`, no upstream patch available. Accepted and documented.
- **Bandit Static Analysis:** Scanned 10,189 LOC across `core` and `config` (`bandit -ll`). Found **0 High, 0 Medium** security issues.
- **Django Production Deploy Check:** Validated `python manage.py check --deploy` under production security environment flags (`COOKIE_SECURE=true`, `SECURE_SSL_REDIRECT=true`). Result: **0 issues identified (0 silenced)**.
- **Full Test & Build Verification:**
  - Frontend typecheck: **Pass (0 errors)**.
  - Frontend unit tests: **Pass (12/12 tests green)**.
  - Frontend build: **Pass (22/22 routes prerendered)**.
  - Backend test suite: **Pass (224/224 tests green)**.
- **Documentation:** Authored [`DEPENDENCY_REPORT.md`](file:///home/saad/Desktop/OpenVault_audit_copy/DEPENDENCY_REPORT.md) and [`SECURITY.md`](file:///home/saad/Desktop/OpenVault_audit_copy/SECURITY.md). Target of zero critical/high in production dependencies achieved.

## [Task 4: Tenant Isolation & IDOR Testing] - 2026-11-10
- **Audited Architecture & Surface:** Enumerated all 85+ API endpoints in `core/urls.py` and all 21 models in `core/models.py`.
- **Identified & Remediated 2 High-Severity Vulnerabilities:**
  1. *Upload Path Traversal (CWE-22):* `validate_filename` in `core/uploads.py` did not reject directory separators (`/`, `\`) or traversal elements (`..`), and `_upload_rejection` discarded the return value while `rel_key = os.path.join(company.slug, f"{uuid.uuid4().hex}_{f.name}")` used raw `f.name`. Remediated by rejecting traversal characters in `validate_filename`, sanitizing `f.name = clean_name`, and enforcing strict canonical directory containment in `storage._resolve_local_path` with `SuspiciousFileOperation`.
  2. *S3 Presign Confirm Key Traversal (CWE-22 / CWE-639):* In `upload_confirm`, `key.startswith(f"{company.slug}/")` permitted traversal sequences like `company/../../foreign-company/file.txt`. Remediated by adding strict traversal checks (`".." in key or "\\" in key`).
- **Constructed Isolation Pytest Suite:** Authored [`backend/tests/test_tenant_isolation_matrix.py`](file:///home/saad/Desktop/OpenVault_audit_copy/backend/tests/test_tenant_isolation_matrix.py) with 18 automated tests covering:
  - Two distinct companies (`Acme Corp` & `Globex Inc`), admins, employees, and unique marker documents (`MARKER_ACME_ALPHA_12345_CONFIDENTIAL` & `MARKER_GLOBEX_BETA_67890_SECRET_PAYROLL`).
  - IDOR coverage across all document endpoints (GET, PATCH, DELETE, download, preview, reindex, versions, shares).
  - Retrieval and chat grounding never returning foreign chunks or marker strings.
  - Model isolation across chat threads, message ratings, analytics, audit log, announcements, users, departments, and attendance.
  - Department and restricted scopes within the same company.
  - Granular one-doc / one-user sharing boundary.
  - Mass-assignment prevention of `company` and `company_id` on all writes.
  - LLMConfig `api_key` write-only serialization protection.
  - Upload path traversal defense.
  - Expired, tampered, and missing JWT authentication tests, along with sliding rate-limiting tests.
- **CI Integration:** Added dedicated `Tenant isolation test matrix` step in `.github/workflows/ci.yml`.
- **Verification:** All 18 isolation matrix tests passed (`18 passed in 65.73s`).
- **Documentation:** Authored [`ISOLATION_REPORT.md`](file:///home/saad/Desktop/OpenVault_audit_copy/ISOLATION_REPORT.md).

## [Task 5: License & Intellectual Property Audit] - 2026-11-10
- **Audited Repository LICENSE:** Analyzed `LICENSE` created in commit `3d36fe1` (2026-11-08). Confirmed project is proprietary All Rights Reserved owned by Saad Waseem. Confirmed project was never released under an open-source license. Confirmed taking the repository private is 100% legally clean with no open-source license revocation issues.
- **Git Authorship Audit:** Scanned all commits across all branches and tags with `git shortlog -sne --all`. Confirmed 100% of commits were authored solely by Saad Waseem (`obsks23@gmail.com`). Confirmed zero third-party committers and zero `Co-authored-by` trailers in git history.
- **Title Verification:** Verified unencumbered sole title owned by Saad Waseem with zero third-party, co-author, or institutional claims.
- **Frontend License Scan:** Audited 148 production dependencies via `license-checker`. Result: **Zero GPL, Zero AGPL, Zero SSPL**. Verified permissiveness of MIT (133), Apache-2.0 (6), ISC (4), BSD (2), MPL-2.0 (1), LGPL-3.0 (1).
- **Backend License Scan:** Audited 59 production dependencies (direct + transitive) via `pip-licenses`. Result: **Zero GPL, Zero AGPL, Zero SSPL**. Permissive licenses comprise 57 packages. Triaged 2 LGPL packages (`psycopg2-binary` with OpenSSL linking exception and `fpdf2` LGPLv3 dynamic library import).
- **Documentation:** Authored [`IP_INVENTORY.md`](file:///home/saad/Desktop/OpenVault_audit_copy/IP_INVENTORY.md).

## [Task 6: Claims Verification & Marketing Due Diligence] - 2026-11-10
- **Audited Repository Claims:** Cross-referenced all marketing copy, README assertions, docs, and demo documents against actual codebase implementations and live hosting realities.
- **Identified 6 Major Discrepancy Categories:**
  1. *AI Model Naming & ARNs:* Uncovered imaginary "Claude Haiku 4.5" naming and invalid Bedrock ARN placeholder (`in.anthropic.claude-haiku-4-5-20251001-v1:0`) across docs and frontend. Verified that live dev relies on local Ollama (`qwen2.5:3b` + `nomic-embed-text`) or BYO API keys. Bedrock access on AWS has never been verified in a live environment.
  2. *Three-Way Hosting Contradiction:* Identified conflicting claims between README/Terraform (AWS ECS Fargate + RDS pgvector + Redis), marketing/policy (Render.com Oregon + AWS Amplify), and actual dev execution (local single-instance SQLite/NumPy vector search). Verified against `docs/FINAL_REPORT.md` that Terraform has never been applied to AWS.
  3. *Customer Scale & Corporate Branches:* Found multiple claims of corporate branch offices in London, Austin, Singapore, Dubai, and Lahore, and European regulatory engagement. Confirmed Deskwise has **0 paying customers** and all corporate documents are synthetic fixtures generated by `scripts/generate_demo_docs.py`.
  4. *Absolute Refusal & Hallucination Guarantees:* Triaged claims of "guaranteed refusal to invent facts". Verified that while DocGen template parsing is deterministic Python with zero model hallucination, generative RAG chat is probabilistic and cannot mathematically guarantee zero hallucinations.
  5. *Partner Access Code Discrepancy:* Found frontend copy claiming "5-character partner codes", whereas backend `Company.access_code` generates 8-character uppercase hexadecimal strings. Verified `EncryptedCharField` using Fernet for API keys is accurate in code.
  6. *Email Delivery Reality:* Verified default `EMAIL_BACKEND` is Django `ConsoleBackend`; live SES/SMTP delivery is an unconfigured production target.
- **Master Corrections Catalog:** Created a 10-point exact replacement matrix in [`CLAIMS_REPORT.md`](file:///home/saad/Desktop/OpenVault_audit_copy/CLAIMS_REPORT.md).
- **Documentation:** Authored [`CLAIMS_REPORT.md`](file:///home/saad/Desktop/OpenVault_audit_copy/CLAIMS_REPORT.md).

## [Remediation & History Scrub: Option A] - 2026-11-11
- **Code & Copy Fixes Applied:**
  - Replaced non-existent model name `"Claude Haiku 4.5"` with `"Claude 3.5 Haiku"` across frontend marketing (`aws-infrastructure-data.ts`, `blueprint-section.tsx`, `policy/page.tsx`), management commands (`check_bedrock.py`), and documentation.
  - Updated default Bedrock model ARN in `backend/core/providers.py` to valid AWS inference profile (`in.anthropic.claude-3-5-haiku-20241022-v1:0`).
  - Corrected partner access code length from `"five-character"` to `"8-character"` in frontend marketing copy (`about/page.tsx`, `security-section.tsx`, and backups).
  - Created [`demo_docs/README.md`](file:///home/saad/Desktop/OpenVault_audit_copy/demo_docs/README.md) explicitly establishing that all regional office references (London, Austin, etc.) and compliance policies are synthetic test data.
- **Option A History Scrub Executed:**
  - Generated full safety backup bundle at `/home/saad/Desktop/OpenVault_audit_copy_backup.bundle`.
  - Executed `git-filter-repo --replace-text` across all 89 commits to ensure clean git commit history.
  - Preserved 100% of commit timestamps, author metadata (`obsks23@gmail.com`), commit messages, and repository timeline.
  - Verified with Gitleaks: 89 commits scanned, 0 leaks found.
- **Verification:**
  - Backend: 242/242 pytest tests passing (224 unit/regression + 18 tenant-isolation matrix).
  - Frontend: 12/12 vitest tests passing; Next.js 16.4.4 production build succeeded with 22/22 routes prerendered.

## [Task 7: Sale Package & Diligence Assets] - 2026-11-11
- **Authored Executive Facts Sheet:** Created [`FACTS_SHEET.md`](file:///home/saad/Desktop/OpenVault_audit_copy/FACTS_SHEET.md) summarizing built features, architecture, 242 passing tests, IP title, and deployment options for prospective acquirers.
- **Authored Technical Data Room Checklist:** Created [`DATA_ROOM_CHECKLIST.md`](file:///home/saad/Desktop/OpenVault_audit_copy/DATA_ROOM_CHECKLIST.md) indexing all technical, security, licensing, and architectural due diligence artifacts.
- **Aligned Production Documentation:** Updated [`README.md`](file:///home/saad/Desktop/OpenVault_audit_copy/README.md) and [`docs/DEPLOY.md`](file:///home/saad/Desktop/OpenVault_audit_copy/docs/DEPLOY.md) with honest deployment status, clearly separating the live local / Docker Compose stack from the unapplied AWS ECS Terraform cloud blueprint.



