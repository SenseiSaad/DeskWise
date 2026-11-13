# Deskwise — M&A Technical Due Diligence & Data Room Index

This document organizes the complete technical, security, intellectual property, and architectural diligence materials for prospective acquirers of **Deskwise** (formerly OpenVault).

---

## 1. Due Diligence Folder Structure

```
DATA_ROOM/
├── 01_EXECUTIVE_SUMMARY/
│   ├── FACTS_SHEET.md                # One-page executive facts sheet & technical specs
│   └── ARCHITECTURE.md               # Architecture diagrams, trust boundaries, sizing
│
├── 02_SECURITY_AND_AUDITS/
│   ├── SECURITY.md                   # Production security controls, accepted items
│   ├── SECRETS_REPORT.md             # Full git history secrets audit (0 active leaks)
│   ├── DEPENDENCY_REPORT.md          # npm audit, pip-audit, Bandit scan results (0 CVEs)
│   └── ISOLATION_REPORT.md           # 18-case tenant isolation & IDOR penetration test
│
├── 03_INTELLECTUAL_PROPERTY/
│   ├── IP_INVENTORY.md               # Git authorship audit (100% solo commits), licenses
│   └── LICENSE                       # Proprietary All Rights Reserved license
│
├── 04_CODEBASE_AND_TESTS/
│   ├── backend/                      # Django 5.1 + DRF application source
│   ├── frontend/                     # Next.js 16 + React 19 application source
│   ├── tests/                        # 242 automated tests (unit + isolation matrix)
│   └── .github/workflows/            # CI/CD, Gitleaks scanner, isolation test action
│
├── 05_INFRASTRUCTURE_AND_DEPLOY/
│   ├── docker-compose.prod.yml       # Production single-host compose (Postgres+Redis+Caddy)
│   ├── infra/                        # ~3,900 LOC Terraform suite for AWS ECS Fargate
│   ├── docs/DEPLOY.md                # Complete deployment runbooks (local, Docker, AWS)
│   └── docs/FINAL_REPORT.md          # Infrastructure verification & cost model analysis
│
└── 06_MARKETING_AND_DEMO/
    ├── demo_docs/                    # Synthetic policy corpus for testing and demo
    ├── demo_docs/README.md           # Synthetic fixtures notice
    └── scripts/generate_demo_docs.py # Generator script for demo documents
```

---

## 2. Technical Diligence Checklist & Verification Index

| Category | Verification Item | Audit Status | Reference Document |
|---|---|:---:|---|
| **Code Authorship** | 100% of Git commits authored by Saad Waseem (`obsks23@gmail.com`). Zero third-party committers. | **VERIFIED** | [`IP_INVENTORY.md`](IP_INVENTORY.md) |
| **License Compliance** | Zero GPL, AGPL, or SSPL copyleft dependencies in production packages. Proprietary license verified. | **VERIFIED** | [`IP_INVENTORY.md`](IP_INVENTORY.md) |
| **Secrets & Keys** | Full historical git scan (89 commits) with Gitleaks & TruffleHog. Zero active credentials committed. | **VERIFIED** | [`SECRETS_REPORT.md`](SECRETS_REPORT.md) |
| **Dependencies** | `pnpm audit` (0 vulnerabilities); `pip-audit` (`PyJWT==2.15.1`, 0 CVEs); Bandit static analysis (0 High/Medium). | **VERIFIED** | [`DEPENDENCY_REPORT.md`](DEPENDENCY_REPORT.md) |
| **Tenant Isolation** | Automated 18-case pytest matrix testing IDOR, cross-tenant chunk leakage, rating isolation, path traversal. | **VERIFIED (18/18)** | [`ISOLATION_REPORT.md`](ISOLATION_REPORT.md) |
| **Automated Tests** | 242 automated backend tests passing + 12 frontend vitest tests passing in CI. | **VERIFIED (242/242)** | `backend/tests/` |
| **Production Build** | Next.js 16.4.4 Turbopack build succeeds with all 22 static routes prerendered. | **VERIFIED (22/22)** | `frontend/out/` |
| **Infrastructure** | Single-host production Docker Compose tested; AWS ECS Terraform (~3,900 LOC) Checkov-scanned (258 passed, 0 failed). | **VERIFIED** | `infra/`, `docs/FINAL_REPORT.md` |

---

## 3. Pre-Closing Legal Handover Checklist

Prior to asset transfer, the following documents are executed and exchanged:
- [ ] **Asset Purchase Agreement (APA):** Standard Acquire.com / Escrow.com software asset assignment.
- [ ] **GitHub Repository Ownership Transfer:** Transfer of private GitHub repository or bare mirror bundle.
- [ ] **Release of Escrow Funds:** Buyer accepts technical inspection; funds wired to seller.
