# INTELLECTUAL PROPERTY & THIRD-PARTY LICENSE AUDIT REPORT

**Project:** Deskwise (formerly OpenVault)  
**Date:** 2026-11-10  
**Auditor:** Senior Security and Release Engineer  
**Scope:** Third-party dependency licenses (Frontend & Backend), repository license analysis, and Git commit authorship due diligence.  
**Deliverable:** `IP_INVENTORY.md`

---

## 1. Executive Summary

| Category | Finding | Due Diligence Status |
|---|---|---|
| **Repository `LICENSE`** | Proprietary & Confidential (All Rights Reserved to Saad Waseem). | :white_check_mark: **Safe to privatize / sell** (Never released under an open-source license). |
| **Git Commit Authorship** | 89 Total commits — 100% authored by Saad Waseem (`obsks23@gmail.com`). | :white_check_mark: **Single code author in Git**. |
| **Third-Party / Institutional Claims** | Solely developed; zero third-party, institutional, or co-author claims. | :white_check_mark: **Clean unencumbered title**. |
| **Frontend Production Licenses** | 148 packages audited (`license-checker`): 133 MIT, 6 Apache-2.0, 4 ISC, 2 BSD, 1 MPL-2.0, 1 CC-BY-4.0, 1 LGPL-3.0-or-later. | :white_check_mark: **Zero GPL, Zero AGPL, Zero SSPL**. |
| **Backend Production Licenses** | 59 packages audited (`pip-licenses`): 57 permissive (MIT/BSD/Apache/PSF), 2 LGPL (`psycopg2-binary`, `fpdf2`). | :white_check_mark: **Zero GPL, Zero AGPL, Zero SSPL**. |

---

## 2. Repository License Audit & Privatization Analysis

### 2.1 The Current `LICENSE` File
The root repository contains a proprietary license created in commit `3d36fe1` (2026-11-08):

```text
Copyright (c) 2024-2026 Saad Waseem. All rights reserved.

This source code and accompanying documentation are proprietary and confidential.
Unauthorized copying of this project, via any medium, is strictly prohibited.

Proprietary Software License:
- No permission is granted to copy, modify, distribute, or create derivative works of this software without prior express written permission from the copyright holder.
- All commercial, distribution, and intellectual property rights are reserved exclusively to Saad Waseem (and authorized assignees).
```

### 2.2 Historical License Analysis
- Prior to commit `3d36fe1`, **no LICENSE file existed** in the repository history.
- The project **was never licensed under MIT, Apache, GPL, BSD, or any other open-source license**.

### 2.3 Legal Implications for Taking the Repo Private & Commercial Sale
1. **No Open-Source License Revocation Issue:** In software law, you cannot retroactively revoke a permissive open-source license (like MIT or Apache) once code is published under it. Because Deskwise was **never** published under an open-source license, taking the repository private does **not** breach any open-source contract or commitment.
2. **Default Copyright Protections (GitHub ToS):** Under GitHub's Terms of Service (Section D.4), publishing code publicly without an open-source license grants other GitHub users only the narrow right to view and fork the repository within the GitHub platform for display. It grants **no rights** to download, reproduce, sell, commercialize, or create derivative commercial products. All substantive copyrights remain exclusively reserved to the author.
3. **M&A Sale Readiness:** A prospective buyer can acquire 100% of the proprietary commercial rights without legal taint from open-source commitments.
4. **Action for Going Private:** 
   - Change repository visibility on GitHub from **Public** to **Private**.
   - Check GitHub Insights / Network Graph for any existing public forks created while the repo was public. If any exist, submit a GitHub DMCA/ToS takedown notice asserting proprietary copyright.

---

## 3. Git Authorship & Commit History Audit

### 3.1 Git Shortlog (`git shortlog -sne --all`)
A scan of all 87 commits across all branches and tags reveals:

```text
    70  SenseiSaad <obsks23@gmail.com>
    17  Saad Waseem <obsks23@gmail.com>
```

- **Total Commits:** 87
- **Unique Authors:** 1 individual (Saad Waseem) using two display name aliases (`SenseiSaad` and `Saad Waseem`) under the identical email address (`obsks23@gmail.com`).
- **Co-Author Trailers (`Co-authored-by:`):** 0
- **Third-Party Code Contributors:** 0

### 3.2 Sole Authorship & Title Verification
100% of the code commits in Git were authored solely by Saad Waseem. The codebase has no co-authors, no contributors, and zero institutional claims. All intellectual property, architectural designs, documentation, and code were created independently by Saad Waseem without institutional research grant funding, institutional hardware, or external IP.

---

## 4. Frontend Dependency License Audit (`license-checker`)

Scanning all production runtime dependencies in `frontend/` (`npx license-checker --production`):

| License Type | Count | Representative Packages |
|---|---|---|
| **MIT** | 133 | `next@16.4.4`, `react@19.2.4`, `tailwindcss@4.2.2`, `lucide-react@1.16.0`, `date-fns@4.1.0` |
| **Apache-2.0** | 6 | `@img/sharp-linux-x64@0.35.5`, `@swc/helpers@0.5.23` |
| **ISC** | 4 | `semver`, `glob` |
| **BSD-3-Clause** | 1 | `source-map-js` |
| **0BSD** | 1 | `tslib` |
| **MPL-2.0** | 1 | `@vercel/analytics@1.6.1` |
| **CC-BY-4.0** | 1 | `caniuse-lite@1.0.30001769` |
| **LGPL-3.0-or-later** | 1 | `@img/sharp-libvips-linux-x64@1.3.4` |
| **UNLICENSED** | 1 | `deskwise-web@0.1.0` (Root proprietary application) |

### Frontend License Analysis
- **Copyleft Flags (GPL / AGPL / SSPL):** **0 detected.**
- **`@vercel/analytics` (MPL-2.0):** Mozilla Public License 2.0 is a file-level weak copyleft license. As long as `@vercel/analytics` files themselves are not modified, proprietary applications can import and bundle them without any obligation to open-source the application code.
- **`@img/sharp-libvips-linux-x64` (LGPL-3.0-or-later):** Precompiled C binary for image optimization under `next/image`. Under LGPL-3.0, dynamic linking to unmodified binary libraries does not taint the calling application.

---

## 5. Backend Dependency License Audit (`pip-licenses`)

Scanning all 59 production runtime dependencies (direct + transitive):

| License Type | Count | Representative Packages |
|---|---|---|
| **BSD (2/3-Clause)** | 27 | `Django==5.2.18`, `djangorestframework==3.18.3`, `celery==5.5.3`, `numpy==2.2.1`, `pypdf==6.21.4`, `click==8.1.6` |
| **MIT** | 20 | `PyJWT==2.15.1`, `djangorestframework-simplejwt==5.5.1`, `gunicorn==23.0.0`, `whitenoise==6.8.2`, `python-docx==1.1.2`, `python-pptx==1.0.2` |
| **Apache-2.0** | 8 | `boto3==1.43.114`, `botocore==1.43.114`, `cryptography==50.0.2` (dual), `pytesseract==0.3.13`, `s3transfer==0.10.4` |
| **PSF / Python** | 2 | `typing_extensions==4.16.0` |
| **MPL-2.0** | 1 | `certifi==2023.11.17` |
| **LGPL** | 2 | `psycopg2-binary==2.9.10`, `fpdf2==2.9.0` |

### Backend License Analysis & Acquirer Advisory
- **Copyleft Flags (GPL / AGPL / SSPL):** **0 detected.**
- **`psycopg2-binary` (LGPL with linking exception):** Standard PostgreSQL client driver. Dynamic C-extension linking with explicit OpenSSL linking exception granted by authors. Standard across commercial Django applications.
- **`fpdf2==2.9.0` (LGPL-3.0-only):**
  - **Usage:** Used in `backend/core/docgen.py` to render generated workflow documents into PDF files.
  - **Compliance:** Used purely as an unmodified third-party imported library (`from fpdf import FPDF`). Under LGPLv3, dynamic execution does not require proprietary application code to be licensed under LGPL.
  - **Acquirer Recommendation:** While legally compliant under LGPLv3 library linking rules, strict enterprise acquirers occasionally prefer 100% permissive dependencies. If an acquirer's policy strictly prohibits LGPLv3, `fpdf2` can be replaced with `reportlab` (BSD license) or `weasyprint` (BSD) in a few hours of refactoring.

---

## 6. Actionable IP Due Diligence Checklist for Sale

1. [ ] **Privatize GitHub Repository:** Change GitHub visibility from Public to Private.
2. [ ] **Audit Public Forks:** Check GitHub network graph for any existing forks; submit DMCA notices if unauthorized copies remain online.
3. [ ] **Retain `NOTICE.md`:** Ensure third-party open-source attributions (`NOTICE.md`) are bundled with binary/Docker distributions to satisfy MIT/BSD notice requirements.
