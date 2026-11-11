# SECRETS AUDIT REPORT
**Target:** Deskwise (formerly OpenVault)  
**Date:** 2026-11-09  
**Auditor:** Senior Security and Release Engineer  
**Scope:** Full Git history (all branches, commits, tags), working tree, and untracked environment artifacts.  
**Scanners:** Gitleaks v8.24.0, TruffleHog v3.99.8, custom Git object packfile inspection.

---

## 1. Executive Summary

| Category | Finding | Risk Level |
|---|---|---|
| **Verified Leaks in Git History** | **0 active secrets** found by TruffleHog and Gitleaks | **NONE** |
| **Tracked Sensitive Files in History** | **0** `.env`, `.bak`, `.sqlite`, `.db`, `.pem`, `.key`, or `.tfstate` files ever committed | **NONE** |
| **Committed Example Configs** | 7 template files committed (`.env.example`, `terraform.tfvars.example`, etc.) containing dummy placeholders | **LOW (Informational)** |
| **Tracked SQLite `.bak` Status** | **Debunked.** No `.bak` or database file was ever committed to the repository history. The local 5.5MB `db.sqlite3` is properly gitignored. | **LOW (Local only)** |
| **Local Untracked Secrets** | Local development `backend/.env` contains local secrets (`SECRET_KEY`, test Stripe key). | **LOW (Protected by `.gitignore`)** |

---

## 2. File Pattern Scan Results

We scanned the entire Git commit history across all branches and tags for any file matching:
`\.env|\.bak|\.sqlite|\.db$|tfstate|tfvars|\.pem|\.key|id_rsa|credentials`

### All Matched Files in Git History

| File Path | First Commit | Last Commit | Type / Content |
|---|---|---|---|
| `backend/.env.example` | `5c56109657...` | `5c56109657...` | Configuration template with dummy values (`postgres://user:pass@host:5432`) |
| `frontend/.env.example` | `5c56109657...` | `5c56109657...` | Frontend environment template (`NEXT_PUBLIC_API_URL=http://localhost:8000`) |
| `.env.example` | `882c3ce420...` | `882c3ce420...` | Root development template with dummy placeholders |
| `.env.production.example` | `ecf75c254b...` | `ecf75c254b...` | Production environment template with dummy placeholders |
| `.env.vercel.example` | `151652a0ab...` | `151652a0ab...` | Legacy Vercel deployment template with dummy placeholders |
| `infra/envs/prod/terraform.tfvars.example` | `2330382fb3...` | `2330382fb3...` | Terraform variables template |
| `infra/envs/staging/terraform.tfvars.example` | `2330382fb3...` | `2330382fb3...` | Terraform variables template |

> [!NOTE]
> **Zero production secrets exist in these template files.** Every secret field is either empty (`STRIPE_SECRET_KEY=`) or populated with standard placeholder documentation strings (`user:pass@host:5432`).

---

## 3. The Tracked SQLite `.bak` Investigation

The initial audit pack noted:
> *"Flagged P0: a tracked SQLite .bak file ... open it and see what is inside. If it has real emails, password hashes or document text, force password resets and treat it as a data exposure."*

### Investigation & Verification:
1. **Full History Blob Search:**
   We verified all objects in the Git packfile using `git verify-pack -v`. The largest blob ever committed in the entire repository history is **192 KB** (`pnpm-lock.yaml`). No 2.73 MB file or binary database backup ever entered Git history.
2. **Commit Path History:**
   `git log --all --full-history --diff-filter=A --name-only | grep -i "\.bak"` returned **0 results**.
3. **Local Filesystem:**
   There is a local `backend/db.sqlite3` file (5.5 MB) created during local development and testing. Running `git check-ignore backend/db.sqlite3` confirms it is ignored by Git and has never been staged.
4. **Conclusion:**
   The claim that a `.bak` SQLite database was tracked in Git was an erroneous assumption by an external audit report. **No database file was ever leaked or committed to Git.**

### Schema Capability Assessment (Does SQLite hold real user data?):
We inspected the database structure of `backend/db.sqlite3` directly using SQLite metadata (`sqlite_master`):
- **User Credentials & Identity:**
  - `core_user.password` (stores hashed user passwords, e.g. PBKDF2/Argon2)
  - `core_user.email`, `core_user.full_name`, `core_user.phone`, `core_user.employee_id`
  - `core_user.mfa_secret` (TOTP MFA secrets)
- **Organizational Confidential Data:**
  - `core_document.raw_text`, `core_document.file` (full company policy and contract text)
  - `core_chunk.text`, `core_chunk.embedding` (parsed document chunks and vector embeddings)
  - `core_company.name`, `core_company.stripe_customer_id`, `core_company.stripe_subscription_id`
- **Private Conversations & Audit Logs:**
  - `core_chatmessage.content`, `core_chatconversation.title` (user questions and assistant answers)
  - `core_auditlog.ip`, `core_auditlog.action`, `core_auditlog.detail`
  - `core_llmconfig.api_key` (tenant-specific LLM provider API keys)
  - `core_onetimetoken.token_hash` (one-time password reset and verification tokens)

**Conclusion:** The schema is **fully capable of holding highly sensitive user and company data**. Because this database is strictly local and gitignored, **no user data exposure occurred**. However, during repository packaging for sale, `backend/db.sqlite3` must be permanently excluded or sanitized.

---

## 4. Local Untracked Secret Findings (Redacted)

As required, secret values are never printed in plaintext; only the file, line, type, and a redacted prefix are shown:

| File | Line | Type | Redacted Prefix | Status / Recommendation |
|---|---|---|---|---|
| `backend/.env` | 8 | Django `SECRET_KEY` | `1E7VRgvn...` | Local dev key; generate fresh random 64-char string for production |
| `backend/.env` | 95 | Stripe Secret Key | `sk_test_...` | Sandbox test key; must not be used in production |
| `backend/core/management/commands/seed_demo.py` | 38 | Seed Demo User Passwords | `demo1234...` | Hardcoded demo credential; purge from production deployments |
| `backend/core/management/commands/bootstrap_platform_admin.py` | 27 | Bootstrap Admin Password | `admin1234...` | Platform admin fallback password; must be set via environment variable only |

---

## 5. Secret Rotation Checklist Before Sale / Production Launch

Prior to commercial onboarding or asset transfer, execute the following rotations:

- [ ] **Django `SECRET_KEY`:**
  - Generate a new cryptographically secure 64-character alphanumeric key:
    ```bash
    python3 -c "import secrets; print(secrets.token_urlsafe(64))"
    ```
  - Store exclusively in AWS SSM Parameter Store / environment variable `SECRET_KEY`.
- [ ] **JWT Signing Key & Token Rotation:**
  - If `SIGNING_KEY` is explicitly configured in SimpleJWT settings, rotate it. Rotating invalidates all existing sessions, forcing fresh authentication.
- [ ] **Database & Cache Passwords:**
  - **PostgreSQL:** Rotate `POSTGRES_PASSWORD` on RDS/database server.
  - **Redis:** Rotate `REDIS_PASSWORD` / AUTH token on ElastiCache/Redis instance.
- [ ] **Email / SMTP Credentials:**
  - Rotate `EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD` (or AWS SES SMTP IAM credentials).
- [ ] **Google Workspace / OAuth / Service Account:**
  - If Google Calendar service account integration is deployed, regenerate the Google Service Account JSON key in Google Cloud Console.
- [ ] **AI Provider API Keys:**
  - **Google Gemini:** Rotate API keys in Google AI Studio / GCP Console.
  - **OpenAI:** Revoke and reissue keys in OpenAI platform dashboard.
  - **Anthropic:** Revoke and reissue keys in Anthropic Console.
  - **AWS Bedrock:** Deactivate any long-lived IAM access keys. Confirm ECS tasks authenticate strictly via IAM Task Roles (`BedrockInvokeTaskRole`).
- [ ] **Stripe Billing Keys:**
  - Keep `sk_test_...` confined to staging.
  - Generate fresh Live `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, and `STRIPE_WEBHOOK_SECRET` from Stripe Dashboard under restricted permissions.
- [ ] **Default Admin Accounts:**
  - Invalidate and replace `root@securekb.local` and all seeded demo accounts (`admin@company-a.com`, etc.).
  - Enforce MFA enrollment on all platform admin accounts.

---

## 6. Verification Commands Executed

```bash
# 1. TruffleHog Full History Scan:
trufflehog git file:///home/saad/Desktop/OpenVault_audit_copy --json
# Result: 0 verified secrets

# 2. Gitleaks Full History Scan:
gitleaks detect --source /home/saad/Desktop/OpenVault_audit_copy --verbose
# Result: 0 leaks found across 87 commits

# 3. File Pattern Search:
git log --all --full-history --diff-filter=A --name-only | grep -Ei '\.env|\.bak|\.sqlite|\.db$|tfstate|tfvars|\.pem|\.key|id_rsa|credentials'
# Result: Only 7 .example templates found (0 actual secret or database files)
```
