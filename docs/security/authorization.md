# Authorization audit: DRF views, querysets, URLs

**Scope:** `backend/core/urls.py`, `backend/config/urls.py`, `core/views.py`, `core/team_chat_views.py`, `core/team_chat.py`, `core/ws.py`, `core/access.py`, `core/permissions.py`, `core/serializers.py`, `core/rag.py` (retrieval), `core/docgen.py` (template collection), `core/billing.py`, `core/mfa.py`, `core/mfa_admin.py`, `core/admin.py`, `create_platform_admin`.
**Method:** Static read of every route, plus local pytest reproduction. Nothing was run against the live site.
**Date:** 2026-11-24. **Commit:** `0d876f3` plus the uncommitted working-tree changes to `email_service.py` and `views.py` (login auto-resend). Those changes don't affect any finding here.
**Tests:** `backend/tests/test_authz_audit_findings.py`. There are 11 tests and all 11 fail on current code. Each test describes the secure behaviour, so it should pass once its finding is fixed. Nothing has been fixed yet.

Severity scale: **P0** = cross-tenant data exposure or full takeover with no privileges. **P1** = privilege escalation or bulk exposure of tenant content from a reachable role. **P2** = a broken security invariant, a plan/billing bypass, or exposure that needs a privileged or operator-created precondition. **P3** = defence-in-depth, metadata leaks, or policy inconsistencies.

---

## 1. Summary

| ID | Sev | Title | Test |
|---|---|---|---|
| AUTHZ-12 | **P1** | The root/platform admin can read and edit all tenant content through Django `/admin/` | `test_authz12_…` |
| AUTHZ-01 | **P1** | A department manager can set a member's password and take over the account | `test_authz01_…` |
| AUTHZ-02 | P2 | A company admin can set a member's password directly, which bypasses break-glass and isn't audited as a password change | `test_authz02_…` |
| AUTHZ-03 | P2 | The platform admin can delete any user who has no company, and the deletion isn't audited | `test_authz03_…` |
| AUTHZ-04 | P2 | The platform admin can attach itself to a tenant via `/auth/onboard` | `test_authz04_…` |
| AUTHZ-05 | P2 | A platform admin promoted from a tenant user keeps tenant-admin data access | `test_authz05_…` |
| AUTHZ-06 | P2 | Storage quota bypass: old document versions are never counted | `test_authz06_…` |
| AUTHZ-08 | P3 | An admin can delete a restricted document without break-glass | `test_authz08_…` |
| AUTHZ-09 | P3 | Admins and dept managers can pull an unreadable restricted doc out of approval via `review submit` | `test_authz09_…` |
| AUTHZ-10 | P3 | The effective-access view leaks restricted/confidential doc metadata to dept managers | `test_authz10_…` |
| AUTHZ-11 | P3 | Team-chat room summaries call the LLM without consuming the monthly ask quota | `test_authz11_…` |

There's no AUTHZ-07. It was a suspected Stripe webhook forgery that I disproved (see §4, H-07).

### Fix status (2026-11-24, uncommitted)

| ID | Status | Change | Test |
|---|---|---|---|
| AUTHZ-12 | **fixed** | `core/admin.py` registers only Plan, Department, Company, User, LLMConfig and Holiday. All tenant-content models are unregistered, including AuditLog and AskLog. UserAdmin excludes `password`/`mfa_secret`, and its tenancy and privilege fields are read-only. | `test_authz12_…`, `test_ai03_…` pass |
| AUTHZ-01 | **fixed** | `user_detail` returns 403 (and audits `DENY_PASSWORD_SET`) whenever `password` is in the PATCH body. Members reset through the existing forgot-password email. The members UI never sends this field on update, so nothing breaks. | `test_authz01_…` passes |
| AUTHZ-02 | **fixed** | Same change as AUTHZ-01. It applies to company admins too. | `test_authz02_…` passes |
| AUTHZ-03 | **fixed** | `user_detail` returns 404 when the caller has no company, so a NULL-company lookup can't happen. | `test_authz03_…` passes |
| AUTHZ-04 | **fixed** | `onboard_company` returns 403 for platform-level users. | `test_authz04_…` passes |
| AUTHZ-05 | **fixed** | `IsAdmin` and `IsAdminOrDeptAdmin` reject platform-level accounts that have a company. `_platform_admin_blocked` does the same. `team_chat.has_company_context` and `_require_company` exclude platform-level accounts, which covers REST and WebSocket. `create_platform_admin --promote` is unchanged: a promoted account now simply gets no tenant rights. | `test_authz05_…` passes |
| AUTHZ-06 | **fixed** | New `_storage_used()` helper in `views.py` adds `DocumentVersion.size`. It's used by all three upload checks and by `/admin/usage`. No model change. | `test_authz06_…` passes |
| AUTHZ-08 | **fixed** | `access.decide("delete")` now applies the same rule as every other admin action: a restricted document needs the uploader, a grant or break-glass (`DENY_ADMIN_NEEDS_BREAK_GLASS`). | `test_authz08_…` passes |
| AUTHZ-09 | **fixed** | `_can_manage_document` (used only by "submit for review", in `document_review` and `document_detail` PATCH) now also requires `decide("view_ask", include_unapproved)`, so an admin without break-glass or a dept manager can't change the status of a restricted document they can't read. | `test_authz09_…` passes |
| AUTHZ-10 | **fixed** | `member_effective_access` skips rows the caller can't read unless the caller is a company admin (admins keep masked rows, by the break-glass design). | `test_authz10_…` passes |
| AUTHZ-11 | **fixed** | `team_chat_room_summarize` writes an `AskLog` via `rag._log_ask` whenever the LLM produced the summary (`mode` isn't `deterministic`), so it counts against `monthly_ask_limit`. | `test_authz11_…` passes |

Full suite after the fixes: everything passes except `tests/test_rag_units.py::test_gemini_and_bedrock_parallel_embed`. That last one already failed in the baseline run before any fix and is unrelated. Three tests in `test_providers_failures.py` were repointed from `urllib.request.urlopen` to `core.providers._NO_REDIRECT_OPENER.open` because of AI-02. They still mock the same transport. `test_security_hardened.py::test_scope_change_and_delete_need_admin_or_uploader` now performs break-glass before the admin deletes the restricted document. Before AUTHZ-08 it expected deletion without break-glass, contradicting its own comment.

**No P0 found.** Specifically, I found no cross-tenant IDOR on any ID parameter, and no way for a normal tenant user to read another company's documents, chunks, conversations or team chat. §3 explains the reasoning. "Not found" means the code paths I read are scoped. It isn't proof. Gaps I didn't cover are listed in §6.

---

## 2. Confirmed findings

### AUTHZ-12 (P1): the platform admin has full tenant read/write through Django admin

- **Where:** `backend/core/admin.py:36-154` (registrations), `backend/config/urls.py` (`path("admin/", admin.site.urls)`), `backend/core/management/commands/create_platform_admin.py:75-83` (creates the root account with `is_staff=True, is_superuser=True`).
- **What:** The API treats root admins as report-only. For example, `access.decide()` returns `DENY_PLATFORM_ADMIN_NO_TENANT_DATA` (`core/access.py:292-297`), and `switch_company` is disabled (`core/views.py:3577`). But the same account is a Django superuser. `ChunkAdmin`, `DocumentAdmin`, `ChatMessageAdmin`, `TeamMessageAdmin`, `DocumentAccessAdmin`, `DocumentShareAdmin`, `UserAdmin` and `LLMConfigAdmin` are registered with default (full) permissions.
- **Exploit:** Anyone holding the root password and TOTP, whether that's a phished operator or a stolen laptop session, opens `/admin/core/chunk/` and reads every tenant's document text, including restricted and confidential chunks. From there they can:
  - read every AI answer (`/admin/core/chatmessage/`) and every team chat message;
  - edit document text or chunks, which poisons RAG answers;
  - create `DocumentAccess` grants;
  - edit any `User`'s `company`, `role`, `clearance` or `is_platform_admin`.

  None of this goes through `audit()`, so tenants' audit chains show nothing. The test reproduces it: it reads the `SALARY-BAND-MARKER` text of a restricted confidential chunk.
- **Fix:** Either unregister tenant-content models (`Chunk`, `Document`, `DocumentVersion`, `ChatConversation`, `ChatMessage`, `TeamMessage`, `TeamRoom`, `DocumentAccess`, `DocumentShare`, `Announcement`, `AttendanceExemption`), or make them read-only, list-only and with content fields excluded. Make `UserAdmin` read-only for `company/role/clearance/is_platform_admin/is_superuser/is_staff/password`. Long-term options: don't mount `/admin/` in production at all, or mount it on a separate host behind network allow-listing. Also make platform admins non-superusers. `IsPlatformAdmin` already accepts `is_platform_admin` alone.

### AUTHZ-01 (P1): a department manager can reset a member's password

- **Where:** `backend/core/views.py:2447-2451` in `user_detail`. The dept-manager branch at `:2352-2357` and `access.decide("change_roles")` (`core/access.py:822-843`) check role, department and clearance changes, but never the `password` field.
- **Exploit:** An HR dept manager sends `PATCH /api/admin/users/<member_id> {"password":"…"}` and gets a 200. They then log in as that member. If an admin gave the member `clearance=confidential`, or the member holds a personal `DocumentAccess` grant on a restricted doc, the manager now has both. The manager couldn't get either through `decide()` (dept managers are capped at `internal`). The audit row says `update_user member@…` with no mention of a password change, because `changes` (`:2457-2469`) doesn't track it. The test reproduces this with a confidential-clearance member who holds a grant on a restricted board-minutes doc.
- **Fix:** Reject `password` in `user_detail` for anyone who isn't a company admin, and preferably for admins too (see AUTHZ-02). Replace it with a "send reset link" action that issues `OneTimeToken(password_reset)` to the member's mailbox. If a direct set has to stay for admins, log `password_set` as its own audit action.

### AUTHZ-02 (P2): a company admin can take over a member's account

- **Where:** `backend/core/views.py:2447-2451`.
- **What:** This is the same code path as AUTHZ-01, but with a company admin. Admins already have broad access, but the restricted-document model specifically says an admin **must** use break-glass with a written reason (`core/access.py:659-670`, `views.py:1515`) to read a restricted doc. Setting the uploader's password and logging in as them gets to the same content, and the only record is `update_user <email>` with no password marker.
- **Fix:** Same as AUTHZ-01. Admins trigger a reset email and never choose the password. Optionally require the admin's own `current_password` and log `password_set` with fail-closed audit.

### AUTHZ-03 (P2): the platform admin can delete users who have no company

- **Where:** `backend/core/views.py:2348`. `User.objects.get(pk=pk, company=request.user.company)`. For a root admin, `company` is `None`, so this becomes `company IS NULL`. `IsAdminOrDeptAdmin` (`core/permissions.py:43-51`) admits platform admins. The non-full-admin guard at `:2352-2357` passes, because both `department_id` values are `None`. `DELETE` returns at `:2367-2379` **before** `access.decide()` is called (decide would have denied a platform admin).
- **Exploit:** The root admin sends `DELETE /api/admin/users/<id>` for any account that hasn't finished onboarding. That includes fresh Google sign-ups (`views.py:893-901`), and any other platform admin whose `role` isn't `admin`. `audit()` returns early when there's no company (`views.py:230-231`), so even with `fail_closed=True` **no audit row is written**.
- **Fix:** Call `_platform_admin_blocked(request)` at the top of `users` and `user_detail`, or use `access.is_company_admin` / `is_dept_manager` as the permission class. Never filter by `company=request.user.company` when that value can be `None`.

### AUTHZ-04 (P2): the platform admin can onboard itself into a tenant

- **Where:** `backend/core/views.py:978-1023` (`onboard_company`). The only check is `if user.company_id:` (`:984`).
- **Exploit:** The root admin sends `POST /api/auth/onboard {"company_name":"X"}`. The account is now `company=X, role=admin`, still with `is_platform_admin=True`. `_platform_admin_blocked` (`views.py:258-274`) only checks `company_id`, so every tenant-admin endpoint that lacks `decide()` now works for the root account. Those are users, audit, analytics, governance, announcements, llm_config (which now edits the company override instead of the platform default), team chat (`team_chat.is_company_admin` treats platform admins as admins, `core/team_chat.py:88-98`), and invites. This breaks the invariant documented at `views.py:3578` ("root admins must never join a tenant"). The company is new and empty, so this alone doesn't expose another tenant's data. Combined with invites, though, it gives a root account a tenant-admin foothold.
- **Fix:** In `onboard_company`, return 403 when `_is_platform_level(user)`. Also make `_platform_admin_blocked` deny any platform-level user regardless of `company_id`.

### AUTHZ-05 (P2): a promoted platform admin keeps its tenant

- **Where:** `backend/core/management/commands/create_platform_admin.py:90-95` (`_promote` sets the flags but leaves `company`). Then every `IsAdmin` view that relies on `company is None` to keep root out: `analytics` (`views.py:3320`, returns member emails and **raw questions**), `audit_log` (`:2638`), `users` (`:2246`, `full_admin` is true via `_is_platform_level`), `company_settings`, `admin_governance`, `llm_config`, plus attendance and announcements.
- **Exploit:** An operator runs `create_platform_admin --promote ops@tenant.com`. That account now reads its old tenant's analytics, including other employees' questions (the test seeds "how do I report harassment by my manager"), the audit log and the member list. It can also edit company settings. This contradicts `platform_reports`' promise of "no member emails or names".
- **Fix:** `_promote` should refuse users with a company, or clear `company`/`department`. Also apply the platform-level deny from AUTHZ-04 to all `IsAdmin` views.

### AUTHZ-06 (P2): storage quota bypass through versions

- **Where:** `backend/core/views.py:1804-1808` (`document_new_version`), and the same `Sum("size")` over `company.documents` at `:1191` and `:1318`. `DocumentVersion` rows keep their `stored_path` and bytes (`:1830-1834`), but their `size` is never added to usage. `usage()` (`:3399`) reports the same undercount.
- **Exploit:** On a 1 MB plan, an admin, or any uploader on a plan with `allow_versions`, uploads a 0.4 MB file and then keeps posting new 0.4 MB versions. Each check sees about 0.8 MB used, so all five succeed. The test ends with 2.4 MB stored against a 1 MB quota, and there's no upper bound. Cost lands on the platform's R2 bill.
- **Fix:** Compute usage as `Sum(Document.size) + Sum(DocumentVersion.size)` for the company in one helper used by all three upload paths and by `usage()`. Alternatively, cap the version count per plan.

### AUTHZ-08 (P3): an admin can delete a restricted document without break-glass

- **Where:** `backend/core/access.py:525-531`. `delete` allows `is_adm` unconditionally. Every other admin action on a restricted doc (scope change `:433`, approve `:486`, archive `:514`, new version `:550`, reindex `:566`, share `:588`, grants `:614`) requires the uploader or a grant first.
- **Exploit:** An admin who can only see "Restricted document #N" (masked metadata, `views.py:164-198`) can `DELETE /api/documents/N`. That destroys the file, its versions and its chunks without ever giving a break-glass reason. Only `legal_hold` stops it.
- **Fix:** Apply the same `restricted and not is_uploader and grant is None` check, returning `DENY_ADMIN_NEEDS_BREAK_GLASS`. If admin deletion of unseen restricted docs is wanted (for retention), require a reason and log it like break-glass.

### AUTHZ-09 (P3): `review submit` skips `decide()`

- **Where:** `backend/core/views.py:1747-1749` (`document_review`) and `:1662-1664` (`document_detail` PATCH status). Both use `_can_manage_document` (`:1713-1723`): admin **or** dept admin of the doc's department **or** uploader. Neither checks read access or break-glass.
- **Exploit:** An admin with no grant, or the HR dept manager, sends `POST /api/documents/<restricted_hr_doc>/review {"action":"submit"}`. An approved restricted doc they can't read drops to `in_review`, which removes it from the owner's search and AI answers (the approved-only surface). The response also returns the full `DocumentSerializer` for a document whose filename is supposed to be masked. The PATCH path is mostly blocked earlier by `edit_metadata` → `_decide_doc_read`. The `/review` path is not.
- **Fix:** Add a `submit` action to `access.decide()`: the uploader, or anyone with `edit_metadata` (read) rights. Route both call sites through it.

### AUTHZ-10 (P3): the effective-access view leaks metadata to dept managers

- **Where:** `backend/core/views.py:2604-2616` (`member_effective_access`).
- **What:** Masked rows still carry `id`, `access_scope`, `sensitivity`, `status` and `department_name`. Admins already see masked restricted metadata by design. Dept managers don't, but this endpoint shows them every restricted or confidential doc their members are granted. The test shows a dept manager learning that a "restricted, confidential" doc exists and is granted to one of their members.
- **Fix:** For non-admin callers, drop rows the caller can't read, and report only a count.

### AUTHZ-11 (P3): room summaries bypass the ask quota

- **Where:** `backend/core/team_chat_views.py:371-389` and `core/team_chat.py:1059+`. The view checks `_plan_quota_exceeded`, but `summarize_room_messages` calls `providers.get_chat_provider(...).stream_chat` (`team_chat.py:1099`) and never writes an `AskLog`. The quota counts `AskLog` (`team_chat.py:832`). `llm_test` (`views.py:3152`) is the same, but it's admin-only and rate-limited.
- **Exploit:** On a plan with `monthly_ask_limit`, any member can call `/summarize` without limit (10/min per user). Each call can send up to 100 messages of transcript to the LLM using the platform's key.
- **Fix:** Log an `AskLog` (or a separate usage row that the quota counts) per summary, using the same `_log_ask` helper.

---

## 3. Endpoint × caller × enforcement

Legend for **Caller gate**:
- **Anon**: no authentication.
- **Auth**: `IsAuthenticated`.
- **Editor**: `IsEditor`, which is role admin or employee, or platform admin.
- **Admin**: `IsAdmin`, which is company admin, superuser or platform admin.
- **Adm/DM**: `IsAdminOrDeptAdmin`.
- **Platform**: `IsPlatformAdmin`.

**Root blocked?** means `_platform_admin_blocked` or `decide()` refuses a company-less root admin. **Scope** is how the queried row is tied to the caller.

| Method & path | Caller gate | Root blocked? | Scope / object check | Role · dept · clearance enforcement | Notes |
|---|---|---|---|---|---|
| GET `/api/health`, `/health/live` | Anon | n/a | none | none | No data |
| GET/POST `/api/cron/maintenance` | Anon + `Bearer CRON_SECRET` (hmac compare) | n/a | global | n/a | Cross-tenant by design. Secret strength not verified |
| POST `/auth/register` | Anon, 5/10 min/IP | n/a | creates company | Serializer has no role/company fields | OK |
| POST `/auth/join` | Anon, 8/5 min/IP | n/a | invite token hash + email match | role set by inviter | Self-join by code disabled. OK |
| POST `/auth/google` | Anon, 10/min/IP | MFA challenge for root | email from verified Google JWT | new user = employee, no company | Links by email to existing accounts (H-09) |
| POST `/auth/onboard` | Auth | **No** | `company_id is None` | caller becomes admin | **AUTHZ-04** |
| POST `/auth/login` | Anon, 8/min/IP+email | root → MFA challenge | n/a | n/a | TOFU enrollment (H-05) |
| POST `/auth/mfa/activate`, `/mfa/verify` | Anon, 10/min/IP | n/a | signed 5-min challenge | n/a | TOTP replay (H-06) |
| POST `/auth/mfa/setup` | Auth | root only | self | n/a | OK |
| POST `/auth/logout`, `/logout-all`, `/refresh` | Anon / Auth / cookie | n/a | own token | `tv` claim checked | OK |
| GET `/auth/me`; PATCH `/auth/update-me` | Auth | n/a | self | role/dept/clearance/flags **not** writable (existing test `test_mass_assignment_…`) | Self-editable `manager/employee_id/join_date` (H-08) |
| POST `/auth/request-verification`, `/verify`, `/forgot-password`, `/reset-password` | Anon, rate-limited | n/a | hashed one-time token | n/a | Non-enumerating responses. Non-atomic consume (H-10) |
| GET `/documents` | Auth | Yes | `accessible_documents_qs(company)` | full ACL; admins also get masked restricted rows | OK |
| POST `/documents/upload`, `/presign`, `/confirm` | Editor | Yes | own company; presign key bound to user (`PendingUpload`) | `decide("upload")`: OKF/template admin-only, confidential admin-only, dept own-only, clearance cap | Count-then-insert race (H-11) |
| GET `/documents/<pk>` | Auth | Yes | `_accessible_doc` (ACL qs incl. external shares) | full ACL | 404 on deny, denial audited |
| PATCH `/documents/<pk>` | Auth | Yes | `_get_doc` (own company) | `edit_metadata` → read ACL; scope/sens via `change_scope_sensitivity`; status via approve/archive/reject; legal hold/OKF/template admin-only | Any reader-employee can edit description/tags (H-01). Status→in_review via `_can_manage_document` (AUTHZ-09) |
| DELETE `/documents/<pk>` | Auth | Yes | `_get_doc` | `decide("delete")` | **AUTHZ-08** |
| GET `/documents/<pk>/download` | Auth | Yes | `_accessible_doc` | `decide("download")` (grant `can_download`, share `can_download`) | OK |
| GET `/documents/<pk>/preview` | Auth | Yes | `_accessible_doc` | read ACL; PII redacted for external | View-only grants can read full text (by design) |
| POST `/documents/<pk>/reindex` | Editor | Yes | `_get_doc` | `decide("reindex")` | OK |
| GET `/documents/<pk>/versions` | Auth | Yes | `_accessible_doc` + own company | read ACL | OK |
| POST `/documents/<pk>/versions/new` | Editor | Yes | `_get_doc` | `decide("new_version")`, plan `allow_versions`, legal hold | **AUTHZ-06** |
| POST `/documents/<pk>/review` | Editor | Yes | `_get_doc` | approve/reject/archive via `decide()`; **submit via `_can_manage_document`** | **AUTHZ-09** |
| POST `/documents/<pk>/break-glass` | Admin | Yes | `_get_doc` | `decide("break_glass")`: admin, restricted, reason ≥5, fail-closed audit | OK |
| GET/POST `/documents/<pk>/shares` | Editor | Yes | `_get_doc` | `manage_grants` (uploader / own-dept DM / admin + break-glass); override_clearance admin + reason; external via `share_externally` + both companies' `enable_external_sharing` + PII gate | Uploader external-share rule is inverted (H-03). Shares without expiry by default |
| DELETE `/documents/<pk>/shares/<user_id>` | Editor | Yes | `_get_doc`, filtered by doc | `manage_grants` | OK |
| GET `/shared-with-me` | Auth | Yes | `shared_with_user=me`, ACL qs | approved, non-confidential, unexpired, owner sharing on | OK |
| GET `/search` | Auth | Yes | `visible_documents`, `accessible_rooms_for`, own artifacts | full ACL | Scans only the latest 150 visible docs (functional, not security) |
| GET `/companies/search`, `/companies/<code>/members` | Editor, 20/min/IP | Yes | 8-char code; target must enable sharing | none on caller | Cross-company directory of names/titles/roles (H-04) |
| POST `/ask` | Auth, 20/min/user | Yes | retrieval = `accessible_doc_ids(user)`; conversation `user=me, company=mine` | full ACL; AI chat flag; monthly quota | `mode` steers platform keys (H-02) |
| POST `/docgen`; GET `/templates`; POST `/artifacts/from_text` | Auth | Yes | templates = `accessible_documents_qs(download, own company)` | docgen flag | OK |
| GET `/artifacts/<pk>`, `/artifacts/<pk>/download` | Auth | Yes | `user=me` + live access to source template | n/a | OK |
| GET `/llm-status` | Auth | No (harmless) | company config | n/a | Exposes provider/model names only |
| GET/POST `/conversations`; GET/PATCH/DELETE `/conversations/<pk>` | Auth | Yes | `user=me` (+company on list) | revoked-source answers masked | OK |
| POST `/messages/<pk>/rate` | Auth | Yes | `conversation__user=me` | n/a | OK |
| GET/POST `/team-chat/rooms` | Auth | Yes (`_require_company`) | `company_id=mine`, `accessible_rooms_for` | create: admin only | Member list (emails) visible to all members |
| PATCH/DELETE `/team-chat/rooms/<id>` | Auth | Yes | room in company + `user_can_access_room` | admin only | OK |
| GET/POST `/team-chat/rooms/<id>/messages`, `/read` | Auth | Yes | room in company + access | post: non-viewer; referenced doc ⊆ room-safe set | Admins read every private room (H-12) |
| POST `/team-chat/rooms/<id>/summarize` | Auth, 10/min/user | Yes | room access | AI flag, quota checked | **AUTHZ-11** |
| PATCH/DELETE `/team-chat/messages/<id>`; POST `/pin`, `/react` | Auth | Yes | msg in company + room access | edit: own + window; delete: own or admin; pin: non-viewer | OK |
| WS `/ws/team-chat` | JWT cookie/Bearer + `tv` + Origin allow-list | Yes (`has_company_context`) | per-event room re-check, live session re-check | same as REST | OK |
| GET `/workflow/forms/<user_id>/<name>` | Auth | Yes | `user_id == me`, basename + realpath confinement | n/a | OK |
| POST `/attendance/scan`; GET `/attendance/me` | Auth | company required | self; QR token bound to company + TTL | attendance flag | OK |
| GET `/attendance/qr` | Admin | company required | own company | n/a | OK |
| GET/POST `/admin/attendance/holidays`; DELETE `…/<pk>` | Admin | GET/POST need company; **DELETE does not** | `company=mine` | n/a | Root can delete platform-wide (`company=NULL`) holidays. Probably intended, not verified |
| GET/POST `/admin/attendance/exemptions`; DELETE `…/<pk>` | Admin | as above | `user__company=mine`; target user in company | n/a | OK |
| POST `/admin/attendance/evaluate` | Admin | company required | own company | n/a | Can deactivate users (freeze). Admin-only |
| GET/POST `/admin/users` | Adm/DM | 400 if no company; **promoted root passes** | `company=mine` (DM: own dept) | `decide("manage_members")`, seat cap | AUTHZ-05 |
| PATCH/DELETE `/admin/users/<pk>` | Adm/DM | **No** | `company=request.user.company` (**NULL for root**) | `decide("change_roles")` for PATCH only; DELETE has a dept/role check only; **password unchecked** | **AUTHZ-01, -02, -03** |
| GET `/admin/access/explain` | Adm/DM | Yes | target user + doc in company | `decide("explain_access")` | Returns rule chain, which can include grant reasons |
| GET `/admin/members/<pk>/effective-access` | Adm/DM | Yes | target in company | `explain_access` | **AUTHZ-10** |
| GET `/admin/audit`, `/admin/audit/verify` | Admin | No (company NULL → empty, or 500 on verify) | `company=mine` | n/a | AUTHZ-05. `audit_verify` 500s for root (H-13) |
| GET `/admin/governance` | Admin | company required | `company=mine` | unreadable docs masked | OK |
| GET/PATCH `/admin/company` | Admin | company required | own company | n/a | Feature flags aren't plan-gated (no plan fields exist for them) |
| GET/POST `/admin/departments`; DELETE `…/<pk>` | Admin | GET/POST need company | `company=mine` | create: plan `allow_departments` | OK |
| GET/POST `/admin/announcements`; DELETE `…/<pk>`; GET `/announcements/<pk>/acks` | Auth (POST: role admin) / Admin | company required (DELETE/acks: NULL lookup → 404) | `company=mine` | n/a | OK |
| POST `/announcements/<pk>/ack` | Auth | company required | `company=mine` | n/a | OK |
| GET `/admin/analytics`, `/admin/usage` | Admin | company required; **promoted root passes** | `company=mine` | unreadable top docs masked | Raw employee questions visible to admins (by design). AUTHZ-05 |
| GET/PUT/DELETE `/admin/llm-config`; POST `/admin/llm-test` | Admin | root → platform row | company override row | write: plan `allow_custom_llm`; `api_key` write-only; `base_url` SSRF-validated | OK |
| GET `/plans` | Anon | n/a | public catalogue | n/a | OK |
| GET `/billing/status` | Auth | n/a | own company; Stripe IDs admin-only | n/a | OK |
| POST `/billing/checkout`, `/billing/portal` | Admin | n/a | own company; redirect allow-list | n/a | OK |
| POST `/billing/webhook` | Anon + Stripe signature | n/a | metadata `company_id` | n/a | See H-07 |
| GET `/admin/reports`, `/admin/companies`; POST `/admin/companies/<pk>/plan` | Platform | n/a | all companies | n/a | `list_companies` returns every tenant's `access_code` |
| POST `/admin/switch-company`, `/admin/detach-company` | Platform | always 403 (dead code below the return) | n/a | n/a | OK |
| `/admin/*` (Django admin) | Django session, `is_staff`, TOTP middleware | **Not blocked** | **none: all tenants** | superuser = everything | **AUTHZ-12** |
| `/admin/mfa-enroll/`, `/admin/mfa-verify/` | staff session, 8 per 5 min | n/a | self | n/a | OK |

### IDOR and predictable IDs

Every primary key is a sequential integer, so IDs are trivially guessable. Every lookup I found is scoped, though:
- by `company=request.user.company`;
- by the canonical ACL queryset;
- by `user=request.user` (conversations, messages, artifacts, workflow forms);
- or by room access (team chat).

Probing an ID returns 404, or 403 for team-chat rooms. The 403 shows that a room ID exists inside your *own* company, which is minor. The only scoping hole is the `company=None` case (AUTHZ-03, AUTHZ-04, AUTHZ-05). Tokens are fine: `secrets.token_urlsafe(32)`, stored as a SHA-256 hash. The company access code is 8 characters from a 36-symbol alphabet.

### Mass assignment

- `RegisterCompanySerializer`, `UserCreateSerializer` and `LoginSerializer` don't declare `is_staff`, `is_superuser`, `is_platform_admin`, `company` or `token_version`, so those can't be set.
- `UserSerializer` is used only for output.
- `update_me` and `user_detail` copy an explicit field allow-list.
- The existing test `tests/test_security_regressions.py::test_mass_assignment_and_dept_manager_privilege_escalation` covers role, clearance, flags and department on `update-me`, and platform/superuser flags on admin PATCH.

The one gap is `password` on admin PATCH (AUTHZ-01 and AUTHZ-02).

### Cross-company one-doc/one-user sharing

- `share_target` resolves the target by access code plus member ID, and uses one error message for every failure, so it can't be used to test whether a member exists.
- The external branch requires:
  - `enable_external_sharing` on both companies;
  - an approved document;
  - sensitivity other than confidential;
  - an admin `allow_pii` confirmation when the doc contains PII;
  - `decide("share_externally")`.
- Recipients pass `_decide_doc_read`'s cross-tenant branch, which allows only `view_ask` and `download`, needs an unexpired share, and checks the recipient's clearance.
- Recipients can't mutate anything, because `_get_doc` is own-company only.

There are two open policy points: H-03, and shares with no expiry by default.

### Platform admin / root account

- **What it can see via the API:** company names, industries, plans, prices, member and document counts, 30-day ask counts and storage per company (`/admin/reports`). It also sees every company's `access_code` (`/admin/companies`). It can change any company's plan, and edit the platform LLM default.
- **What it can see via Django admin:** everything (AUTHZ-12).
- **How it's protected:**
  - created only via a management command, with a DB flag rather than an email;
  - login always requires TOTP (`views.py:484-497`), including through Google sign-in (`:878-890`);
  - Django `/admin/` is gated by `AdminMFAMiddleware`;
  - challenges are signed and expire after 5 minutes.
- **Weaknesses:** enrollment is trust-on-first-use (H-05), TOTP codes can be replayed inside the window (H-06), the account is a full superuser (AUTHZ-12), and the AUTHZ-03, -04 and -05 boundary holes.

### Plan limits

- **Server-enforced:**
  - document count;
  - storage, except versions (AUTHZ-06);
  - seats (the stricter of the company cap and the plan cap);
  - monthly asks on `/ask` and `@DeskWise`, but not summaries (AUTHZ-11);
  - departments (upload, scope change, create);
  - versions;
  - custom LLM.
- **Gaps:** all checks are count-then-insert, so concurrent requests can overshoot (H-11). Feature flags aren't plan-gated because no plan fields exist for them, which is a product decision rather than a bypass.

---

## 4. Hardening notes and open policy questions (no failing test)

These are real observations. Some are intended behaviour that I can't decide on your behalf. Some are race conditions I didn't reproduce.

| ID | Sev | Where | Observation | Suggested action |
|---|---|---|---|---|
| H-01 | P3 | `core/access.py:401-416` | Any employee who can read a company-wide doc can PATCH its `description`, `category` and `tags`. Those fields feed `/search` matching. | Decide whether metadata edits should need the same manage rights as scope changes. |
| H-02 | P3 | `core/views.py:1982-2021`, `providers.py:738,880` | `provider` is rejected unless the company has its own key, because otherwise "a caller could steer shared platform spend". But `mode` (`online`/`gemini`/`bedrock`/`selfhosted`) does the same thing and is open to every user, and the UI exposes it on purpose (`frontend/lib/api.ts:295`). | Make the rule consistent: either allow both, or restrict paid platform modes per plan. |
| H-03 | P3 | `core/access.py:597` | A plain uploader can share **restricted** and **department** docs externally, but **not** company-wide ones. That looks inverted, but I haven't confirmed the intent. | Confirm the intended rule and add it to `decide()` tests. |
| H-04 | P3 | `core/views.py:2850-2860` | Any employee in any company can list the full names, titles and roles of every member of a sharing-enabled company, given its 8-char code. That's rate-limited per IP, not per user. | Per-user rate limit, or require at least a partial name/email match. |
| H-05 | P2 | `core/views.py:486-495` | Root MFA is trust-on-first-use: the first password-only login returns an enrollment secret. Anyone who learns the password before the real owner enrolls can bind their own authenticator. | Have the command print or require the enrollment secret at creation, or verify enrollment out of band. `verify_platform_admin_mfa` exists. Check it runs in deploy (not verified). |
| H-06 | P3 | `core/mfa.py:51-61` | The same TOTP code is accepted for about 90 s with no "last used step" record, so a shoulder-surfed or relayed code can be reused. | Store the last accepted step per user and reject reuse. |
| H-07 | P3 | `core/billing.py:223-234` | I suspected that with `STRIPE_WEBHOOK_SECRET` unset and `ENVIRONMENT≠production` (the shipped defaults are `development`/`staging`), a signature made with an empty key would be accepted. **Disproved locally:** `stripe==16.0.0` raises `SignatureVerificationError("No webhook secret value was provided")`. This is safe only because of library behaviour. | Fail closed in the app when the secret is empty, whatever the environment. Also, `customer.subscription.updated` with `past_due` doesn't downgrade the plan (business intent not verified). |
| H-08 | P3 | `core/views.py:653-665` | Users can set their own `manager`, `employee_id` and `join_date`, which get injected into generated HR forms and letters. | Make them admin-only if generated documents are treated as authoritative. |
| H-09 | P3 | `core/views.py:864-890` | Google sign-in silently links to an existing password account with the same email, and signs in invited users without the invite token. That's acceptable when Google is authoritative for the domain, but tenants can't opt out. Also, `:853` echoes the raw verifier exception to the client. | Per-company "allow Google sign-in" flag. Generic error message. |
| H-10 | P3 | `core/models.py:301-312` | `OneTimeToken.consume` reads and then writes without `select_for_update` or a conditional update, so two parallel requests can both consume one reset or verify token. Not reproduced. | `filter(used_at__isnull=True).update(used_at=now)` and check the row count. |
| H-11 | P3 | `core/views.py:1187, 1314, 2284` | Plan document, storage and seat limits are count-then-insert. Parallel requests can overshoot. Not reproduced. | Check inside a transaction while locking the company row. |
| H-12 | P3 | `core/team_chat.py:119-120` | Company admins can read every private team room, including ones they're not in. This is probably intentional (oversight), but employees aren't told. | Show it in the UI, or audit admin reads of rooms they're not a member of. |
| H-13 | P3 | `core/views.py:2689-2702` | `audit_verify` dereferences `company.id` and returns a 500 for a company-less root admin. | Return 400 like the sibling views. |

**Update (step 2 of the second pass, see `authentication.md`):**
- H-06 is fixed as AUTHN-04.
- The token-consume half of H-10 is fixed as AUTHN-05. The plan-limit half (H-11) is unchanged.
- H-09 is partly addressed by AUTHN-01: accounts are bound to the Google `sub`, a different `sub` is refused, and unverified password accounts lose their password on linking. Silent auto-linking of *verified* accounts and the per-company opt-out are still the open policy question.

---

## 5. Reproducing

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/test_authz_audit_findings.py -q
```

Expected today: **11 failed**. Each failure message names the bypass, for example "root admin read tenant document text" or "dept manager changed a member's password".

## 6. Not verified or out of scope

- Production settings: whether `ENVIRONMENT=production`, `REQUIRE_EMAIL_VERIFICATION`, `ATTENDANCE_QR_REQUIRED` and `STRIPE_WEBHOOK_SECRET` are set on Vercel, and whether `/admin/` is reachable in production. The code mounts it unconditionally.
- The Next.js frontend and its server routes. I read only `frontend/lib/api.ts` for the `mode` question.
- Celery tasks, `seed_*` commands, and the `cron_maintenance` secret's strength.
- The races in H-10 and H-11 aren't reproduced.
- Neon/Postgres row-level security: none is used. Isolation is entirely application-level, so every new query has to remember the company filter.
