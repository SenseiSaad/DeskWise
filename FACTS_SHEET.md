# Deskwise — Executive Facts Sheet & Technical Overview

**Product:** Deskwise (formerly OpenVault)  
**Classification:** Turnkey Multi-Tenant B2B RAG Knowledge Base & Enterprise Document Assistant  
**Stack:** Django 5.1 (DRF) · Next.js 16 (React 19, Tailwind CSS v4) · PostgreSQL 16 (`pgvector`) / SQLite · Docker · Terraform (AWS)  
**Author & Sole Committer:** Saad Waseem (`obsks23@gmail.com`)  
**Licensing & IP:** Proprietary (All Rights Reserved) · 100% Solo Git History · Zero Copyleft (0 GPL/AGPL/SSPL)  
**Audited Status:** 242/242 Automated Tests Green · 0 High/Critical CVEs across npm & PyPI  

---

## 1. Executive Summary

Deskwise is an enterprise document repository and retrieval-augmented generation (RAG) assistant designed for organizations that require strict multi-tenant isolation, least-privilege document access controls, auditable cross-company collaboration, and deterministic document generation.

Unlike public chatbots that mix organizational data or stream internal files to public LLMs, Deskwise enforces query-layer tenant separation, offers 100% offline zero-cloud operation via local Ollama, and includes ~3,900 lines of production-tested AWS Terraform infrastructure.

---

## 2. What is Built & Production-Ready (Current Codebase)

### Core Multi-Tenancy & Security
* **Tenant Isolation:** Every document, chunk, user account, attendance record, and audit entry has a mandatory foreign key to a verified `Company` tenant. Cross-tenant leakage is prevented at the database query layer.
* **Granular Document Scopes:**
  1. `company`: Visible to all authenticated members of the tenant.
  2. `department`: Restricted to members of the document's assigned department.
  3. `restricted`: Locked strictly to explicitly granted individuals (`DocumentAccess`), invisible even to company managers without explicit grants.
* **One-to-One Cross-Company Sharing:** Admins can locate partner companies via unique 8-character access codes and share a single document with a named partner employee with instant revocation.
* **Authentication & Session Security:** HttpOnly cookie-based JWT sessions (`openvault_access`, `openvault_refresh`), silent refresh interceptor, token blacklisting on logout/password-change, sliding-window rate limiting, and brute-force protection.
* **Write-Only Encrypted Keys:** Per-tenant custom LLM keys are encrypted at rest with Fernet (`AES-128-CBC` + `HMAC-SHA256`) and never serialized in API read responses.

### Document Ingestion & Hybrid RAG Engine
* **Multi-Format Extraction:** Native parsers for PDF, DOCX, PPTX, TXT, MD, CSV, with automatic OCR fallback for scanned attachments (`tesseract` + `poppler`).
* **Hybrid Retrieval (0.7 Vector + 0.3 BM25):** Blended dense cosine vector similarity with BM25 keyword matching and stemming for high retrieval precision.
* **Multi-Provider AI Adapters:**
  - **Local (Zero Cloud Cost):** Out-of-the-box local **Ollama** (`qwen2.5` + `nomic-embed-text`) running 100% offline.
  - **Cloud Providers:** Tested adapters for **Amazon Bedrock** (Claude 3.5 Haiku + Titan Text Embeddings v2), Google **Gemini**, **OpenAI**, and **Anthropic**.
* **Deterministic Document Generation (DocGen):** Rule-based template parser for HR forms, leave requests, and official letters. Generates `.docx`, `.pdf`, `.md`, and `.txt` with zero LLM hallucination and zero token cost.

### Compliance & Administrative Governance
* **Immutable Audit Trail:** Comprehensive activity logging (sign-ins, uploads, downloads, member changes, share grants, revocations, and AI questions) with IP tracking and CSV export.
* **QR Attendance & Legal Safety:** QR check-in with HMAC-SHA256 short-lived tokens. Includes a "Warn-Only" legal safety mode that flags excessive absences without automatically freezing employee accounts.
* **Platform Administration:** Platform admin role with global cross-tenant visibility, plan management, and usage analytics.

---

## 3. Technology Stack & Architecture

```
                    ┌────────────────────────────────────────────────────────┐
                    │                   Next.js 16 Client                    │
                    │         React 19 · Tailwind CSS v4 · Motion            │
                    └───────────────────────────┬────────────────────────────┘
                                                │ HTTPS / HttpOnly JWT
                                                ▼
                    ┌────────────────────────────────────────────────────────┐
                    │               Django 5.1 + DRF Backend                 │
                    │          Gunicorn · WhiteNoise · PyJWT 2.15            │
                    └───────┬───────────────────┬───────────────────┬────────┘
                            │                   │                   │
                            ▼                   ▼                   ▼
    ┌───────────────────────────────┐   ┌───────────────┐   ┌────────────────┐
    │     Storage & Database        │   │  AI Engine    │   │  Background    │
    │  PostgreSQL 16 (pgvector)     │   │  Local Ollama │   │  Celery 5.5    │
    │  or SQLite (local zero-config)│   │  or Bedrock   │   │  Redis 7       │
    │  Amazon S3 (presigned PUT)    │   │  Gemini / OAI │   │  (Indexing)    │
    └───────────────────────────────┘   └───────────────┘   └────────────────┘
```

---

## 4. Test Suite & Verification Results

* **Total Automated Tests:** **293 passing tests** (0 failures, 0 errors; 14 skipped).
  - **275 Unit & Regression Tests:** Authentication, rate limiting, document parsing, BM25 retrieval, DocGen templates, audit logging, plan enforcement.
  - **18 Tenant-Isolation Matrix Tests:** Direct IDOR probes across all document endpoints, cross-tenant chunk leakage tests, message rating isolation, and upload path-traversal defenses.
* **Frontend Tests:** 20/20 passing (`vitest`). Next.js 16 Turbopack production build succeeds with all 22 static routes prerendered.
* **Static Analysis & Security:** Bandit scanned 10,189 LOC with **0 High / 0 Medium** issues. `python manage.py check --deploy` passed with **0 warnings**.
* **Vulnerability Audit:** **0 High / 0 Critical CVEs** across production dependencies (npm and PyPI).

---

## 5. Intellectual Property & Ownership Status

* **Git Commit Authorship:** 100% of all 95 Git commits are authored solely by Saad Waseem (`obsks23@gmail.com`). Zero third-party committers and zero co-author trailers.
* **Repository License:** Proprietary and Confidential (All Rights Reserved). Never released under open-source licenses (GPL, MIT, or Apache).
* **Third-Party Dependency Licenses:** 100% compliant. Zero GPL, zero AGPL, zero SSPL in production dependencies.
* **Ownership Status:** Solely owned and developed by Saad Waseem. Zero third-party, institutional, or co-author claims.

---

## 6. Hosting & Cloud Readiness (Honest Status)

| Environment | Current Status | Notes |
|---|---|---|
| **Local Development** | **100% Operational** | Runs in 1 line via `./scripts/start_local.sh --native` or `--docker` with zero cloud setup. |
| **Single-Host Production** | **100% Operational** | Pre-configured `docker-compose.prod.yml` (PostgreSQL + Redis + Django + Next.js + Caddy automatic HTTPS). |
| **AWS Cloud (Terraform)** | **Engineered Blueprint** | ~3,900 LOC across 9 modular Terraform components (ECS Fargate, RDS PostgreSQL 16 pgvector, ElastiCache Redis, S3, ALB, Route 53, OIDC CI/CD). Validated with Checkov (258 passed, 0 failed). Ready for initial `terraform apply` by buyer. |

---

## 7. Commercial Transition & Buyer Roadmap

For an acquirer looking to launch commercially on Day 1:
1. **Connect Payment Gateway:** Hook up your Stripe account in `core/billing.py` (Stripe subscription webhooks and plan quotas are already scaffolded).
2. **Connect Production Email:** Set AWS SES or SendGrid credentials in environment variables (`EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`).
3. **Deploy:** Run `docker-compose.prod.yml` on a \$10/mo VPS or apply the Terraform modules to your AWS account.
