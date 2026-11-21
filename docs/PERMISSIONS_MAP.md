# Deskwise Permissions & Endpoint Map (Phase A Audit)

This document maps **every** HTTP route in `backend/config/urls.py` and `backend/core/urls.py`, plus WebSocket routes in `backend/config/asgi.py` / `backend/core/ws.py`.
It records the pre-hardening baseline (flagged gaps) and tracks migration to the canonical `core.access.decide()` + `core.access.accessible_documents_qs()` engine.

---

## 1. Root & Django Admin Routes (`backend/config/urls.py`)

| Route | Methods | View | Who May Call | Pre-Hardening Check | Central Function? | Flags / Notes |
|---|---|---|---|---|---|---|
| `/` | GET | `config.views.landing` | Public | None | N/A | Static landing HTML. |
| `/admin/mfa-enroll/` | GET, POST | `core.mfa_admin.admin_mfa_enroll` | Django `is_staff` session | `_guard` | N/A | **FLAG (F-16):** Add rate limit on TOTP verification attempts. |
| `/admin/mfa-verify/` | GET, POST | `core.mfa_admin.admin_mfa_verify` | Django `is_staff` session | `_guard` | N/A | **FLAG (F-16):** Add rate limit on 6-digit TOTP attempts. |
| `/admin/` | Any | `admin.site.urls` | `is_staff` + `AdminMFAMiddleware` | Session + MFA | N/A | **FLAG (F-13):** `AuditLogAdmin` permits edit/delete; `AskLogAdmin` exposes raw tenant `question` text. |

---

## 2. Ops, Auth & Session Routes (`/api/...`)

| Route | Methods | View | Who May Call | Pre-Hardening Check | Central Function? | Flags / Notes |
|---|---|---|---|---|---|---|
| `/api/health` | GET | `views.health` | Public | `AllowAny`, `auth=[]` | N/A | Health probe. |
| `/api/health/live` | GET | `views.health_live` | Public | `AllowAny`, `auth=[]` | N/A | Liveness probe. |
| `/api/cron/maintenance` | GET, POST | `views.cron_maintenance` | Vercel Cron (`CRON_SECRET`) | HMAC Bearer check | N/A | Protected by `CRON_SECRET`. |
| `/api/auth/register` | POST | `views.register_company` | Public (RL 5/600s) | `AllowAny` | N/A | **FLAG (F-14):** Sets auth cookies even if `REQUIRE_EMAIL_VERIFICATION=True`. |
| `/api/auth/login` | POST | `views.login` | Public (RL 8/60s) | `AllowAny` + `is_active` + email verif + platform MFA | N/A | Add failed/successful login audit entries (F-13). |
| `/api/auth/mfa/activate` | POST | `views.mfa_activate` | Public w/ signed challenge | Signed token + TOTP | N/A | Platform admin MFA activation. |
| `/api/auth/mfa/verify` | POST | `views.mfa_verify` | Public w/ signed challenge | Signed token + TOTP | N/A | Platform admin MFA login. |
| `/api/auth/mfa/setup` | POST | `views.mfa_setup` | Platform admin | `IsAuthenticated` + `_is_platform_level` | N/A | Platform admin MFA re-enrollment. |
| `/api/auth/logout` | POST | `views.logout` | Public / cookie | Blacklists refresh token | N/A | Also clears auth cookies. |
| `/api/auth/logout-all` | POST | `views.logout_all` | Authenticated user | `IsAuthenticated` + bumps `token_version` | N/A | **FLAG (F-12):** Open WebSockets don't re-check `token_version` after connect. |
| `/api/auth/refresh` | POST | `views.refresh` | Cookie (RL 30/60s) | Blacklist + `token_version` | N/A | Clean. |
| `/api/auth/me` | GET | `views.me` | Authenticated user | `IsAuthenticated` | N/A | Clean; returns explicit `clearance`. |
| `/api/auth/update-me` | PATCH | `views.update_me` | Authenticated user | Whitelisted profile fields | N/A | Rejects/ignores `role`, `clearance`, `department`, `is_dept_admin`, `company`, `is_platform_admin`, `email_verified`, `token_version`. |
| `/api/auth/request-verification` | POST | `views.request_verification` | Public (RL 5/600s) | Non-enumerating | N/A | Clean. |
| `/api/auth/verify` | POST | `views.verify_email` | Public (RL 10/60s) | Signed token | N/A | Clean. |
| `/api/auth/forgot-password` | POST | `views.forgot_password` | Public (RL 5/600s) | Non-enumerating | N/A | Clean. |
| `/api/auth/reset-password` | POST | `views.reset_password` | Public (RL 10/60s) | Signed token + bumps `token_version` | N/A | Clean. |

---

## 3. Documents, Versions, Presign/Confirm & Search

| Route | Methods | View | Who May Call | Pre-Hardening Check | Central Function? | Flags / Notes |
|---|---|---|---|---|---|---|
| `/api/documents` | GET | `views.documents` | Tenant user | `visible_documents` | **Partial (F-06)** | Admins auto-see restricted docs; grants ignore sensitivity; dept managers see confidential docs. Must expose masked metadata-only rows for admin ungranted restricted docs. |
| `/api/documents/upload` | POST | `views.upload_document` | Employee / Dept Mgr / Admin | `IsEditor` + ad-hoc | **NO (F-08)** | Any employee can set `is_okf=True`, `is_template=True`, arbitrary `department_id`; dept manager can upload `confidential` company-wide. |
| `/api/documents/presign` | POST | `views.upload_presign` | Employee / Dept Mgr / Admin | `IsEditor` + ad-hoc | **NO (F-02)** | No server-side key ownership binding; 900s expiry (should be short, e.g. 300s). |
| `/api/documents/confirm` | POST | `views.upload_confirm` | Employee / Dept Mgr / Admin | `IsEditor` + `key.startswith(slug/)` | **NO (F-02, F-08)** | **CRITICAL:** No key-owner binding or uniqueness check -> intra-tenant S3 key hijacking & deletion (even under `legal_hold`). Repeats F-08 mass assignment. |
| `/api/documents/<pk>` | GET | `views.document_detail` | Users allowed to view doc | `_accessible_doc` | **Partial (F-06)** | Inherits F-06; admin viewing ungranted restricted doc should see limited masked metadata only. |
| `/api/documents/<pk>` | PATCH | `views.document_detail` | Owner-company editors/managers/admins per action matrix | `_is_editor_request` + ad-hoc | **NO (F-03, F-08)** | **CRITICAL:** Missing `doc.company_id == user.company_id` allows external share recipients (and external admins!) to edit/unpublish/toggle `legal_hold` on Company A's docs. Uploader can widen scope/lower sensitivity; colleague can unpublish; `department` scope skips `plan.allow_departments`. |
| `/api/documents/<pk>` | DELETE | `views.document_detail` | Uploader (own), Dept Mgr (dept), Admin (company); blocked by `legal_hold` | `_can_manage_document` | **Partial (F-06)** | Must route through `decide(user, "delete", doc)`. |
| `/api/documents/<pk>/download` | GET | `views.download_document` | Users allowed `download` | `_accessible_doc` + `_can_download` | **Partial (F-06)** | Inconsistent with `/preview` for admins on restricted docs; external downloads ignore sensitivity. |
| `/api/documents/<pk>/preview` | GET | `views.document_preview` | Users allowed `view_ask` | `_accessible_doc` | **Partial (F-06, F-11)** | Lazy fallback caches `preview_text` without computing `contains_pii`; logs external filename in viewer's audit log. |
| `/api/documents/<pk>/reindex` | POST | `views.document_reindex` | Managers/Admins/Uploader | **`_get_doc` (NO ACL!)** | **NO (F-09)** | **IDOR:** Any employee can probe/reindex restricted/confidential docs by ID and receive full serialized doc metadata. |
| `/api/documents/<pk>/versions` | GET | `views.document_versions` | Owner-company users allowed `view_ask` | `_accessible_doc` (incl. external) | **Partial (F-09)** | Leaks historical version filenames/uploader IDs to external share recipients. |
| `/api/documents/<pk>/versions/new` | POST | `views.document_new_version` | Uploader/Manager/Admin per `decide` | **`_get_doc` (NO ACL!)** | **NO (F-04)** | **CRITICAL IDOR:** Any employee can overwrite any company doc (including confidential, restricted, and `legal_hold=True`), bypassing storage quota & approval workflow. |
| `/api/documents/<pk>/review` | POST | `views.document_review` | Dept Mgr (own dept, <= internal) / Admin | `_can_approve_document` | **Partial (F-06)** | Allows `is_dept_admin` to approve `confidential` or `restricted` docs. |
| `/api/documents/<pk>/break-glass` | POST | *(New in Phase B)* | Company Admin only | `decide(user, "break_glass", doc)` | **YES (New)** | Grants audited self-access to a `restricted` doc with mandatory reason. |
| `/api/search` | GET | `views.unified_search` | Tenant user | `visible_documents` + `accessible_rooms_for` | **Partial (F-06, F-12)** | Inherits F-06; team chat hits can show unmasked historical citations. |

---

## 4. Cross-Company Shares & Directory

| Route | Methods | View | Who May Call | Pre-Hardening Check | Central Function? | Flags / Notes |
|---|---|---|---|---|---|---|
| `/api/documents/<pk>/shares` | GET, POST | `views.document_shares` | Users allowed `share_externally` / grant management | **`_get_doc` (NO ACL!)** | **NO (F-01)** | **CRITICAL IDOR + Self-Grant PrivEsc:** Any employee can view/add shares on any confidential/restricted doc AND share with *themselves* via their own `company.access_code`, bypassing sensitivity! Also lacks `override_clearance` + `reason` enforcement for internal grants and allows sharing `confidential` docs without admin approval. |
| `/api/documents/<pk>/shares/<user_id>` | DELETE | `views.document_share_detail` | Users allowed `share_externally` / grant management | **`_get_doc` (NO ACL!)** | **NO (F-09)** | **IDOR / DoS:** Any employee can delete anyone's share or the uploader's `DocumentAccess` on a restricted doc. |
| `/api/shared-with-me` | GET | `views.shared_with_me` | Tenant user | Ad-hoc `DocumentShare` query | **NO (F-06)** | Must filter through `accessible_documents_qs` / `decide` so clearance & sensitivity apply. |
| `/api/companies/search` | GET | `views.company_search` | Editors/Admins (when sharing enabled) | `IsAuthenticated` + caller flag only | **NO (F-15)** | Does not verify target company has `enable_external_sharing=True`; callable by viewers. |
| `/api/companies/<access_code>/members` | GET | `views.company_members` | Editors/Admins (when sharing enabled) | `IsAuthenticated` + caller flag only | **NO (F-15)** | Exposes target company members even if target has `enable_external_sharing=False`; callable by viewers. |

---

## 5. AI Chat, Conversations, DocGen & Artifacts

| Route | Methods | View | Who May Call | Pre-Hardening Check | Central Function? | Flags / Notes |
|---|---|---|---|---|---|---|
| `/api/ask` | POST | `views.ask` | Tenant user (`enable_ai_chat`) | `accessible_doc_ids` | **Partial (F-06, F-11, F-12)** | Replays stale conversation history after doc revocation; `docgen.DocumentPlan` AttributeError when `enable_docgen=False`; logs raw prompt in `AuditLog`. |
| `/api/docgen` | POST | `views.docgen_generate` | Tenant user (`enable_docgen`) | `collect_uploaded_templates` | **NO (F-11)** | Pulls external shared docs & `include_like` docs bypassing `can_download=False` and PII redaction. |
| `/api/templates` | GET | `views.templates_list` | Tenant user (`enable_docgen`) | `collect_uploaded_templates` | **NO (F-11)** | Includes external shared templates contrary to docstring. |
| `/api/artifacts/from_text` | POST | `views.artifact_from_text` | Tenant user (`enable_docgen`) | Owned by caller | N/A | Add size cap. |
| `/api/artifacts/<pk>` | GET | `views.artifact_detail` | Artifact owner (`enable_docgen`) | `_owned_artifact` | **NO (F-12)** | Must re-check access to `source_template_id` if template was revoked. |
| `/api/artifacts/<pk>/download` | GET | `views.artifact_download` | Artifact owner (`enable_docgen`) | `_owned_artifact` | **NO (F-12)** | Must re-check access to `source_template_id` if template was revoked. |
| `/api/llm-status` | GET | `views.llm_status` | Authenticated user | `IsAuthenticated` | N/A | Clean. |
| `/api/conversations` | GET, POST | `views.conversations` | Tenant user (`enable_ai_chat`) | Own company + own user | N/A | Clean. |
| `/api/conversations/<pk>` | GET, PATCH, DELETE | `views.conversation_detail` | Conversation owner | `user=request.user` | **NO (F-12)** | Must mask assistant messages whose source documents are no longer accessible to the user. |
| `/api/messages/<pk>/rate` | POST | `views.message_rate` | Conversation owner | `conversation__user=request.user` | N/A | Clean. |

---

## 6. Team Chat (REST & WebSocket)

| Route | Methods | View / Consumer | Who May Call | Pre-Hardening Check | Central Function? | Flags / Notes |
|---|---|---|---|---|---|---|
| `/api/team-chat/rooms` | GET, POST | `team_chat_views.team_chat_rooms` | Tenant user (`enable_team_chat`); POST = Admin | `_require_company` + `is_company_admin` | N/A | Clean. |
| `/api/team-chat/rooms/<room_id>` | PATCH, DELETE | `team_chat_views.team_chat_room_detail` | Company Admin (`enable_team_chat`) | `is_company_admin` | N/A | Clean. |
| `/api/team-chat/rooms/<room_id>/messages` | GET, POST | `team_chat_views.team_chat_messages` | Room member (`enable_team_chat`); POST = non-viewer | `_get_accessible_room_or_error` | **NO (F-11, F-12)** | `room_allowed_doc_ids` leaks `internal` dept docs to `viewer`s; `referenced_document_id` allows attaching restricted docs in `#General`; `tpl.doc_id` bug (`team_chat.py:892`). |
| `/api/team-chat/rooms/<room_id>/read` | POST | `team_chat_views.team_chat_mark_read` | Room member | `_get_accessible_room_or_error` | N/A | Guard invalid int `last_message_id`. |
| `/api/team-chat/rooms/<room_id>/summarize` | POST | `team_chat_views.team_chat_room_summarize` | Room member (`enable_team_chat` & `enable_ai_chat`) | `_get_accessible_room_or_error` | **NO (F-15)** | Missing rate limit & monthly ask quota enforcement. |
| `/api/team-chat/messages/<msg_id>` | PATCH, DELETE | `team_chat_views.team_chat_message_detail` | Author (edit window) / Admin (delete) | `_get_accessible_message_or_error` | N/A | Avoid storing deleted message body snippet in `AuditLog`. |
| `/api/team-chat/messages/<msg_id>/pin` | POST | `team_chat_views.team_chat_message_pin` | Company Admin / Dept Mgr | `check_pin_permission` | N/A | Clean. |
| `/api/team-chat/messages/<msg_id>/react` | POST | `team_chat_views.team_chat_message_react` | Room participant (non-viewer) | `user_can_post` | N/A | Clean. |
| `WS /ws/team-chat/` | WS | `ws.TeamChatConsumer` | Authenticated tenant user (`enable_team_chat`) | Connect-time JWT + `tv` | **NO (F-12)** | Never re-validates `token_version`, `is_active`, `enable_team_chat`, or room membership on incoming events/broadcasts after connect. |

---

## 7. Workflow, Attendance, Admin, Audit, Billing & Platform Admin

| Route | Methods | View | Who May Call | Pre-Hardening Check | Central Function? | Flags / Notes |
|---|---|---|---|---|---|---|
| `/api/workflow/forms/<user_id>/<name>` | GET | `views.workflow_form_download` | Owner only | `request.user.id == user_id` | N/A | Solid path confinement. |
| `/api/attendance/scan` | POST | `views.attendance_scan` | Tenant user (`enable_attendance`) | Signed QR token | N/A | Clean. |
| `/api/attendance/me` | GET | `views.attendance_me` | Tenant user (`enable_attendance`) | Own records | N/A | Clean. |
| `/api/attendance/qr` | GET | `views.attendance_qr` | **Should be Admin only** | **`IsAuthenticated` (BUG!)** | **NO (F-07)** | **AuthZ Bypass:** Any employee/viewer can generate valid office check-in QR tokens remotely. |
| `/api/admin/attendance/holidays` + `<pk>` | GET, POST, DELETE | `views.admin_holidays` / `detail` | Company Admin (`enable_attendance`) | `IsAdmin` | N/A | Add `_attendance_disabled` to DELETE; guard `company=None`. |
| `/api/admin/attendance/exemptions` + `<pk>` | GET, POST, DELETE | `views.admin_exemptions` / `detail` | Company Admin (`enable_attendance`) | `IsAdmin` | N/A | Add `_attendance_disabled` to DELETE. |
| `/api/admin/attendance/evaluate` | POST | `views.admin_attendance_evaluate` | Company Admin (`enable_attendance`) | `IsAdmin` | N/A | Revoke tokens when auto-freeze deactivates user (F-14). |
| `/api/admin/users` | GET, POST | `views.users` | Admin (company) / Dept Mgr (own dept, <= internal) | `IsAdminOrDeptAdmin` | **Partial (F-06)** | Route through `decide(user, "manage_members")` + clearance validation + audit before/after. |
| `/api/admin/users/<pk>` | PATCH, DELETE | `views.user_detail` | Admin / Dept Mgr (own dept) | `IsAdminOrDeptAdmin` | **Partial (F-14)** | Fix string `"false"` `is_active` parsing; prevent self-edit/last-admin demotion; clear `is_dept_admin` & lower clearance on demotion to viewer; audit before->after. |
| `/api/admin/members/<pk>/effective-access` | GET | *(New in Phase B)* | Admin / Dept Mgr (own dept) | `decide` + `accessible_documents_qs` | **YES (New)** | Returns counts + lists of accessible / downloadable documents. |
| `/api/admin/access/explain` | GET | *(New in Phase B)* | Admin / Dept Mgr (own dept) | `decide(target, action, doc)` | **YES (New)** | Returns decision + plain-English rule chain; every call is audited. |
| `/api/admin/audit` | GET | `views.audit_log` | Company Admin | `IsAdmin` | N/A | **FLAG (F-13):** 5000-row cap, CSV formula injection, restricted filenames & raw prompts in `detail`. |
| `/api/admin/audit/verify` | GET | `views.audit_verify` | Company Admin | `IsAdmin` | N/A | Verification certificate download via `?certificate=1` (also accepts `?download=certificate`; DRF reserves `?format=`). |
| `/api/admin/governance` | GET | `views.admin_governance` | Company Admin | **Ad-hoc raw `Document` filter** | **NO (F-09, F-13)** | Masks filenames of ungranted `restricted` docs. |
| `/api/admin/company` | GET, PATCH | `views.company_settings` | Company Admin | `IsAdmin` | **Partial** | Route through `decide(user, "settings")` + audit before/after diffs. |
| `/api/admin/departments` | GET, POST | `views.departments` | Company Admin | `IsAdmin` + `plan.allow_departments` | N/A | Clean. |
| `/api/admin/departments/<pk>` | DELETE | `views.department_detail` | Company Admin | `IsAdmin` | **NO (F-05)** | **CRITICAL BUG:** Flips deleted dept's docs to `access_scope="company"` instead of `"restricted"`, exposing private/dept docs company-wide! |
| `/api/admin/announcements` + `<pk>` + `/ack` + `/acks` | GET, POST, DELETE | `views.announcements*` | Tenant users (read/ack); Admin (post/delete/acks) | `IsAuthenticated` / `IsAdmin` | N/A | Clean. |
| `/api/admin/analytics` | GET | `views.analytics` | Company Admin | **Ad-hoc `company.documents` & `AskLog`** | **NO (F-13)** | Leaks restricted filenames in `top_documents` and raw unredacted prompts in `unanswered_questions`. |
| `/api/admin/usage` | GET | `views.usage` | Company Admin | `IsAdmin` | N/A | Aggregate counts. |
| `/api/admin/llm-config` + `/llm-test` | GET, PUT, DELETE, POST | `views.llm_config` / `llm_test` | Company Admin (`allow_custom_llm`) / Platform Admin | `IsAdmin` | **Partial** | Fix platform-admin `DELETE` fallthrough; add RL on `llm-test`. |
| `/api/plans` | GET | `views.plans` | Public | `AllowAny` | N/A | Clean. |
| `/api/billing/status` | GET | `views.billing_status` | Tenant user (Stripe IDs -> Admin only) | `IsAuthenticated` | **Partial** | Hide raw `stripe_customer_id`/`stripe_subscription_id` from non-admins. |
| `/api/billing/checkout` + `/portal` | POST | `views.billing_checkout` / `portal` | Company Admin | `IsAdmin` | **Partial (F-15)** | Validate redirect URLs against `PUBLIC_BASE_URL` / trusted origins. |
| `/api/billing/webhook` | POST | `views.billing_webhook` | Stripe webhook | `@csrf_exempt`, `AllowAny` | **NO (F-15)** | Refuse unsigned webhooks when `STRIPE_WEBHOOK_SECRET` is unset unless explicitly running in tests; verify `payment_status == "paid"`. |
| `/api/admin/reports`, `/admin/companies`, `/admin/companies/<pk>/plan` | GET, POST | `views.platform_reports`, `list_companies`, `company_set_plan` | Platform Admin | `IsPlatformAdmin` | N/A | Clean. |
| `/api/admin/switch-company`, `/admin/detach-company` | POST | `views.switch_company`, `detach_company` | Permanently disabled (403) | `IsPlatformAdmin` -> 403 | N/A | Enforces platform-admin zero-access to tenant docs. |

---

## 8. Post-Hardening Status (Phases B, E, F Complete)

Every endpoint flagged above has been wired to the canonical engine in [`backend/core/access.py`](../backend/core/access.py) (`decide()` and `accessible_documents_qs()`) and verified by `backend/tests/test_permission_matrix.py` and `backend/tests/test_security_regressions.py`:

- **Document CRUD, preview, download, versions, reindex, review, shares, break-glass, presign/confirm, search:** All route through `access.decide()` / `access.accessible_documents_qs()` (`F-01`–`F-09`). `PendingUpload` binds presign keys to the uploader (`F-02`); `storage._resolve_local_path` confines local paths (`F-10`).
- **AI Chat, Conversations, DocGen, Artifacts, Team Chat & WebSockets:** `rag.accessible_documents_qs` delegates directly to `access.accessible_documents_qs`; `rag.filter_conversation_messages_for_user` masks revoked conversation history (`F-12`); `docgen.collect_uploaded_templates` enforces `action="download"`, `include_unapproved=False`, `include_external_shares=False` (`F-11`); `team_chat.room_allowed_doc_ids` derives from `core.access` and excludes `internal` docs when a standard-clearance viewer is in the department (`F-12`); `ws.TeamChatConsumer` re-checks `is_active`, `token_version`, `enable_team_chat`, and room membership on every frame/broadcast (`F-12`).
- **New Explainability & Break-Glass Endpoints:**
  - `POST /api/documents/<pk>/break-glass` (`views.document_break_glass`) — Admin-only, mandatory reason, audited.
  - `GET /api/admin/access/explain` (`views.admin_access_explain`) — Admin or Dept Manager (own dept), returns `Decision(allowed, reason_code, rule_chain)`, audited on every call.
  - `GET /api/admin/members/<pk>/effective-access` (`views.admin_member_effective_access`) — Admin or Dept Manager (own dept), returns counts and accessible/downloadable lists.
- **Audit, Auth, Attendance, Billing & Admin MFA:** `AuditLog` v2 (`F-13`), fail-closed audit on security-sensitive actions, streaming formula-safe CSV export, `?certificate=1` verification certificate, `verify_audit_chain --all`; `/api/attendance/qr` restricted to `IsAdmin` (`F-07`); `DELETE /api/admin/departments/<pk>` sets `access_scope="restricted"` and revokes `is_dept_admin` (`F-05`); `register_company`, `user_detail`, and `attendance.evaluate` auth fixes (`F-14`); Stripe webhook/redirect & directory sharing checks (`F-15`); Django `/admin/mfa-*` rate limits (`F-16`).

