# Deskwise — Third-Party Notices & Attributions

This document lists the third-party open-source libraries incorporated into or used by **Deskwise**, their licenses, and legal compliance notes for commercial acquisition.

All proprietary application source code, architecture, schema, algorithms, and documentation are Copyright (c) 2024-2026 Saad Waseem. All rights reserved.

---

## 1. Backend Runtime Dependencies (`backend/requirements.txt`)

All backend production dependencies use permissive open-source licenses (MIT, BSD, Apache 2.0, PSF), with two LGPL-licensed libraries documented below.

| Package | Version | License | License Category |
|---|---|---|---|
| **Django** | `5.2.18` | BSD-3-Clause | Permissive |
| **djangorestframework** | `3.18.3` | BSD-3-Clause | Permissive |
| **djangorestframework-simplejwt** | `5.5.1` | MIT | Permissive |
| **PyJWT** | `2.15.1` | MIT | Permissive |
| **cryptography** | `50.0.2` | Apache-2.0 / BSD | Permissive |
| **django-cors-headers** | `4.6.0` | MIT | Permissive |
| **numpy** | `2.2.1` | BSD-3-Clause | Permissive |
| **pypdf** | `6.21.4` | BSD-3-Clause | Permissive |
| **python-pptx** | `1.0.2` | MIT | Permissive |
| **python-docx** | `1.1.2` | MIT | Permissive |
| **fpdf2** | `2.9.0` | LGPL-3.0-only | Weak Copyleft (see note below) |
| **python-dotenv** | `1.2.4` | BSD-3-Clause | Permissive |
| **gunicorn** | `23.0.0` | MIT | Permissive |
| **whitenoise** | `6.8.2` | MIT | Permissive |
| **psycopg2-binary** | `2.9.10` | LGPL-3.0 with OpenSSL exception | Weak Copyleft (see note below) |
| **dj-database-url** | `2.3.0` | BSD-2-Clause | Permissive |
| **redis** | `5.2.1` | MIT | Permissive |
| **boto3** | `1.43.114` | Apache-2.0 | Permissive |
| **botocore** | `1.43.114` | Apache-2.0 | Permissive |
| **sentry-sdk** | `2.73.0` | BSD-2-Clause | Permissive |
| **celery** | `5.5.3` | BSD-3-Clause | Permissive |
| **stripe** | `16.0.0` | MIT | Permissive |
| **pytesseract** | `0.3.13` | Apache-2.0 | Permissive |
| **pdf2image** | `1.17.0` | MIT | Permissive |
| **Pillow** | `13.0.0` | HPND (Permissive BSD-style) | Permissive |
| **google-api-python-client** | `2.149.0` | Apache-2.0 | Permissive (Optional) |
| **google-auth** | `2.35.0` | Apache-2.0 | Permissive (Optional) |
| **qrcode** | `7.4.2` | BSD-3-Clause | Permissive (Optional) |

*(Note: Prior draft notices erroneously mentioned `pyotp`, `pydantic`, `openpyxl`, and `pgvector-python`. None of these packages are in the codebase. Vector operations use direct SQL against PostgreSQL `vector` extension or pure NumPy fallback).*

---

## 2. Frontend Runtime Dependencies (`frontend/package.json`)

Audited via `npx license-checker --production` (148 production dependencies):

| License | Package Count | Key Packages |
|---|---|---|
| **MIT** | 133 | `next@16.4.4`, `react@19.2.4`, `react-dom@19.2.4`, `tailwindcss@4.2.2`, `lucide-react@1.16.0`, `date-fns@4.1.0` |
| **Apache-2.0** | 6 | `@img/sharp-linux-x64@0.35.5`, `@swc/helpers@0.5.23` |
| **ISC** | 4 | `semver`, `glob` |
| **BSD-3-Clause** | 1 | `source-map-js` |
| **0BSD** | 1 | `tslib` |
| **MPL-2.0** | 1 | `@vercel/analytics@1.6.1` (Weak copyleft; unmodified module import) |
| **CC-BY-4.0** | 1 | `caniuse-lite@1.0.30001769` |
| **LGPL-3.0-or-later**| 1 | `@img/sharp-libvips-linux-x64@1.3.4` (Precompiled dynamic C binary) |

---

## 3. Copyleft Analysis & Commercial Acquisition Impact

### Strong Copyleft (GPL / AGPL / SSPL): 0%
- **Zero** dependencies in either frontend or backend are licensed under GPL, AGPL, or SSPL.
- No viral copyleft requirements exist that would compel a buyer to publish or disclose proprietary application code.

### Weak Copyleft (LGPL / MPL) Review:
1. **`psycopg2-binary` (LGPL-3.0 with OpenSSL exception):**
   - Standard PostgreSQL database driver for Django.
   - Dynamically linked C extension with an explicit upstream linking exception. Used unmodified. Does not affect proprietary application code.
2. **`fpdf2` (LGPL-3.0-only):**
   - Used in `backend/core/docgen.py` for exporting generated leave requests and HR templates to PDF format.
   - Used purely as an unmodified library via standard Python import (`from fpdf import FPDF`). Under LGPLv3 Section 4, executing or dynamically linking an unmodified library does not convert the host application into a derivative work.
   - *Buyer note:* If an acquirer operates under an internal corporate policy prohibiting any LGPL library, `fpdf2` can be swapped for `reportlab` (BSD) in ~2 hours.
3. **`@vercel/analytics` (MPL-2.0):**
   - Weak file-level copyleft. As long as the package files themselves are unmodified, importing them into proprietary applications is fully permitted without releasing application code.
4. **`@img/sharp-libvips-linux-x64` (LGPL-3.0-or-later):**
   - Pre-built binary dependency used by Next.js for server-side image optimization. Dynamically loaded by the runtime; does not affect application licensing.
