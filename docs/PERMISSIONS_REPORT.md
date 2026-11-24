# Deskwise Permissions Verification Report

> Generated automatically by `backend/tests/test_permission_matrix.py` on 2026-11-24 15:25:04 UTC.

## Summary

- **Canonical Engine:** `backend/core/access.py` (`decide()` + `accessible_documents_qs()`)
- **Differential Proof:** Verified 100% agreement between `decide()` and `accessible_documents_qs()` across all 13 personas × 45 documents × actions × flags (`test_differential_decide_matches_accessible_documents_qs`).
- **Surface Checks Executed:** 902 HTTP/AI/search/template/team-chat/governance checks across 10 personas and 16 representative canary documents.
- **Canary Leaks Detected:** **0** (PASS)
- **Surfaces Verified:** `/api/documents` (list), `/api/documents/<id>` (detail), `/preview`, `/download`, `/versions`, `/api/search`, `/api/ask` (sources + deterministic `fake` provider answer text), `/api/templates`, `/api/shared-with-me`, `team_chat.room_allowed_doc_ids` (`#General` + `#HR`), `/api/admin/audit`, `/api/admin/analytics`, `/api/admin/governance`, `/api/admin/access/explain`, `/api/admin/members/<id>/effective-access`.

## Persona × Document Matrix

Legend: `R/DL/AI` = Read + Download + AI Searchable · `R/AI(no-DL)` = View/AI only (download disabled) · `R(wip)` = Workspace visible (unapproved/draft/in_review) · `DENY` = Denied (404 / excluded)

| Persona | company_standard_approved | company_internal_approved | company_confidential_approved | company_standard_draft | department_standard_approved | department_internal_approved | department_confidential_approved | department_internal_in_review | finance_dept_internal_approved | eng_dept_internal_approved | restricted_internal_approved | restricted_confidential_approved | template_hr_internal | ext_share_valid | ext_share_viewonly | ext_share_expired |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `hr_viewer` | R/DL/AI | DENY | DENY | DENY | R/DL/AI | DENY | DENY | DENY | DENY | DENY | DENY | DENY | DENY | R/DL/AI | DENY | R/DL/AI |
| `hr_employee` | R/DL/AI | R/DL/AI | DENY | DENY | R/DL/AI | R/DL/AI | DENY | DENY | DENY | DENY | R/DL/AI | DENY | R/DL/AI | R/DL/AI | R/DL/AI | R/DL/AI |
| `hr_manager` | R/DL/AI | R/DL/AI | DENY | DENY | R/DL/AI | R/DL/AI | DENY | R(wip) | DENY | DENY | DENY | DENY | R/DL/AI | R/DL/AI | R/DL/AI | R/DL/AI |
| `finance_employee` | R/DL/AI | R/DL/AI | DENY | DENY | DENY | DENY | DENY | DENY | R/DL/AI | DENY | DENY | R/AI(no-DL) | DENY | R/DL/AI | R/DL/AI | R/DL/AI |
| `finance_manager` | R/DL/AI | R/DL/AI | DENY | DENY | DENY | DENY | DENY | DENY | R/DL/AI | DENY | DENY | DENY | DENY | R/DL/AI | R/DL/AI | R/DL/AI |
| `no_dept_employee` | R/DL/AI | R/DL/AI | DENY | DENY | DENY | DENY | DENY | DENY | DENY | DENY | DENY | DENY | DENY | R/DL/AI | R/DL/AI | R/DL/AI |
| `admin` | R/DL/AI | R/DL/AI | R/DL/AI | R(wip) | R/DL/AI | R/DL/AI | R/DL/AI | R(wip) | R/DL/AI | R/DL/AI | DENY | R/DL/AI | R/DL/AI | R/DL/AI | R/DL/AI | R/DL/AI |
| `ex_employee` | DENY (inactive) | DENY (inactive) | DENY (inactive) | DENY (inactive) | DENY (inactive) | DENY (inactive) | DENY (inactive) | DENY (inactive) | DENY (inactive) | DENY (inactive) | DENY (inactive) | DENY (inactive) | DENY (inactive) | DENY (inactive) | DENY (inactive) | DENY (inactive) |
| `ext_partner` | DENY | DENY | DENY | DENY | DENY | DENY | DENY | DENY | DENY | DENY | DENY | DENY | DENY | R/DL/AI | R/AI(no-DL) | DENY |
| `platform_admin` | DENY (platform) | DENY (platform) | DENY (platform) | DENY (platform) | DENY (platform) | DENY (platform) | DENY (platform) | DENY (platform) | DENY (platform) | DENY (platform) | DENY (platform) | DENY (platform) | DENY (platform) | DENY (platform) | DENY (platform) | DENY (platform) |

## Document Key Legend

- `company_standard_approved`: Company / Standard / Approved
- `company_internal_approved`: Company / Internal / Approved
- `company_confidential_approved`: Company / Confidential / Approved
- `company_standard_draft`: Company / Standard / Draft
- `department_standard_approved`: HR Dept / Standard / Approved
- `department_internal_approved`: HR Dept / Internal / Approved
- `department_confidential_approved`: HR Dept / Confidential / Approved
- `department_internal_in_review`: HR Dept / Internal / In Review
- `finance_dept_internal_approved`: Finance Dept / Internal / Approved
- `eng_dept_internal_approved`: Eng Dept / Internal / Approved
- `restricted_internal_approved`: Restricted (HR emp) / Internal / Approved
- `restricted_confidential_approved`: Restricted (Admin+Grants) / Conf / Approved
- `template_hr_internal`: HR Dept Template / Internal / Approved
- `ext_share_valid`: Ext Share (Valid, DL) / Standard / Approved
- `ext_share_viewonly`: Ext Share (View-Only) / Internal / Approved
- `ext_share_expired`: Ext Share (Expired) / Standard / Approved
