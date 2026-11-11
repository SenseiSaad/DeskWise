# Security Policy & Vulnerability Management

**Project:** Deskwise  
**Classification:** Proprietary / Pre-Sale  
**Last Audited:** 2026-11-09  

---

## 1. Security Posture Overview

Deskwise enforces enterprise-grade security controls across both the Next.js frontend and Django backend architectures:
- **Zero Critical / Zero High Vulnerabilities:** Both production frontend (`pnpm audit --prod`) and production backend (`pip-audit`) dependencies are verified with 0 known Critical or High vulnerabilities.
- **Zero Leaked Secrets in Git History:** All 87 historical commits and branches have been scanned with TruffleHog and Gitleaks with 0 verified active secrets.
- **Strict Production Deployment Guards:** Django's `check --deploy` runs in CI and refuses startup if `SECRET_KEY` is missing or insecure, or if cookie security flags (`COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_SSL_REDIRECT`) are disabled.
- **Multi-Tenant Isolation:** Complete logical tenant separation at the database ORM layer with strict foreign key binding to `Company`.

---

## 2. Supported Versions

| Version / Branch | Supported | Security Maintenance |
|---|---|---|
| `main` (Deskwise v1.0) | :white_check_mark: Yes | Actively patched |
| Historical prototype tags / branches | :x: No | Deprecated / Archived |

---

## 3. Accepted Dependency Leftovers

During the comprehensive security audit conducted on 2026-11-09, all production dependencies were remediated. One non-production dependency is currently accepted as a documented leftover:

| Package | Environment | Advisory ID | Severity | Technical Rationale & Mitigation |
|---|---|---|---|---|
| `ecdsa==0.19.2` | **Dev / CI Only** (`checkov`) | `PYSEC-2026-1325` | Medium (Timing) | **Scope:** Required exclusively by `checkov` (static Terraform/IaC scanner).<br>**Production Isolation:** Not included in `backend/requirements.txt`, not installed in production Docker containers, and never imported by Django or Gunicorn runtime.<br>**Upstream Status:** No patch has been published upstream by the maintainers.<br>**Risk Assessment:** Zero attack surface in production. |

---

## 4. Security Controls & CI Hardening

Deskwise integrates defensive controls across the development lifecycle:
1. **Pre-Commit Hook:** `.githooks/pre-commit` executes `gitleaks protect --staged` before any commit can be created locally.
2. **CI Secret Scan:** `.github/workflows/gitleaks.yml` scans every push and pull request.
3. **Dependency Scanning:** CI invokes `pip-audit` for Python and `pnpm audit --prod` for Node.js.
4. **Static Code Analysis:** Bandit scans backend codebase (`bandit -ll -r backend/core backend/config`).
5. **Configuration Guard:** `python manage.py check --deploy` ensures compliance with production settings.

---

## 5. Reporting a Vulnerability

We value security disclosures. If you discover a vulnerability in Deskwise:

1. **Do not create a public GitHub issue.**
2. Email the core security team at `security@deskwise.site` with:
   - Description of the vulnerability and potential impact.
   - Proof of Concept (PoC) or step-by-step reproduction instructions.
   - Suggested remediation (if available).
3. The team will acknowledge receipt within 24 hours and provide an estimated remediation timeline.
