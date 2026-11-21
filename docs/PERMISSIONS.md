# Deskwise Permissions Specification (Plain English)

This document is the canonical specification for how Deskwise computes access across every REST endpoint, WebSocket room, document search, docgen template, and AI retrieval call.

All authorization flows through **one pure engine** in `backend/core/access.py`:
- `decide(user, action, document=None, *, context=None) -> Decision(allowed, reason_code, rule_chain)`
- `accessible_documents_qs(user, *, action="view_ask", include_unapproved=False, include_external_shares=True)` (derived from the exact same rules and proven equivalent by differential tests).

---

## 1. The Three Questions (Evaluated in Order; First Denial Wins)

Every permission check answers three questions in strict order. The first denial immediately stops evaluation and returns a machine-readable `reason_code` plus a human-readable `rule_chain`.

### Question 1: Are you allowed in? (Entry Gate)
1. **Authenticated & Active (`DENY_UNAUTHENTICATED`, `DENY_INACTIVE_USER`)**: User must be authenticated and `is_active=True`. Active JWT cookies/tokens and live WebSocket connections must match the user's current `token_version` in the database (role/department/clearance changes, deactivation, password reset, and `logout-all` bump `token_version`).
2. **Platform Admin Separation (`DENY_PLATFORM_ADMIN_NO_TENANT_DATA`)**: Platform root admins (`is_platform_admin=True`) manage billing plans and aggregate platform metrics only; they have zero access to tenant documents, AI chat, or team chat.
3. **Tenant Boundary (`DENY_WRONG_TENANT`, `DENY_NO_COMPANY`)**: User must belong to the document's company, **or** hold an active, unexpired `DocumentShare` where the owning company has `enable_external_sharing=True`.
4. **Feature & Plan Switches (`DENY_FEATURE_DISABLED`, `DENY_PLAN_LIMIT`)**: Company feature flags (`enable_ai_chat`, `enable_docgen`, `enable_team_chat`, `enable_attendance`, `enable_external_sharing`) and plan flags (`allow_departments`, `allow_versions`, `allow_custom_llm`) must permit the action.

### Question 2: Which documents? (Audience, Lifecycle & Legal Hold)
1. **Lifecycle Status (`DENY_UNAPPROVED_STATUS`, `DENY_ARCHIVED_STATUS`)**:
   - AI retrieval (`view_ask` with `include_unapproved=False`) and external shares **only** include `status="approved"` documents.
   - `draft` and `in_review` documents are visible only in management views (`include_unapproved=True`) to the uploader, the document's department manager (inside their department, sensitivity `<= internal`), or a company admin (for non-restricted docs, or restricted docs with an explicit grant).
   - `archived` documents are excluded from AI retrieval and ordinary employee views; visible in management views only to company admins (and department managers for their department's non-restricted, `<= internal` docs).
2. **Audience (`access_scope`) (`DENY_SCOPE_DEPARTMENT`, `DENY_SCOPE_RESTRICTED`, `DENY_ADMIN_NEEDS_BREAK_GLASS`)**:
   - **`company` ("Everyone")**: Any active member of the owning company (subject to Question 3 clearance).
   - **`department` ("My department")**: Members of `document.department` (plus explicitly granted users via `DocumentAccess`), subject to Question 3 clearance. Company admins may read non-restricted department documents.
   - **`restricted` ("Only selected people")**: **Only** the uploader (while still active in the company, for content within their clearance) and users with an explicit `DocumentAccess` grant.
     - **Company admins do NOT auto-read `restricted` documents.** In list/governance views they see limited metadata only (`id`, masked title `[Restricted document #<id>]`, `access_scope`, `sensitivity`, `status`, `legal_hold`, `created_at`) and cannot preview, download, or AI-retrieve the document unless they explicitly invoke audited **Break-Glass** (`POST /api/documents/<id>/break-glass` with a mandatory `reason`).
3. **Legal Hold (`DENY_LEGAL_HOLD`)**: Documents with `legal_hold=True` **cannot be deleted, archived, or overwritten with a new version** by anyone until a company admin explicitly releases the legal hold (audited).

### Question 3: What may you do? (Clearance & Role/Action Matrix)
1. **Explicit Clearance (`standard < internal < confidential`) (`DENY_CLEARANCE_INSUFFICIENT`)**:
   - Every user has an explicit `clearance` column (`standard`, `internal`, or `confidential`), defaulting from their role when created or when left unset:
     - `viewer` -> `standard`
     - `employee` (and `department manager`) -> `internal`
     - `admin` -> `confidential`
   - A company admin can adjust a member's clearance, but **never above the acting admin's own clearance**.
   - A department manager can adjust clearance only for members of their own department and **never above `internal`**.
   - **Rule:** Reading, downloading, or AI-retrieving a document requires `user.clearance >= document.sensitivity`.
   - **Grants never silently raise clearance:** A `DocumentAccess` grant or `DocumentShare` widens the *audience* (letting someone into a `restricted` or other-department doc), **not** clearance. An admin may explicitly set `override_clearance=True` on an internal `DocumentAccess` grant **only with a mandatory `grant_reason`**, which is stored on the grant and written to the audit log. External shares (`DocumentShare`) **never** override clearance and **never** share `confidential` documents unless an admin explicitly approves? *(Decision: external shares reject `confidential` documents outright to prevent cross-company exfiltration of admin-only data; see Decision Log D-04.)*

2. **Role & Action Matrix**:

| Action | Anonymous | Viewer | Employee | Dept Manager (`is_dept_admin`) | Company Admin | Platform Admin |
|---|---|---|---|---|---|---|
| `view_ask` (approved, within audience & clearance) | Deny | Allow (standard) | Allow (<= internal) | Allow (<= internal) | Allow (company/dept; restricted needs grant/break-glass) | Deny |
| `download` | Deny | Allow if `view_ask` & `can_download` | Allow if `view_ask` & `can_download` | Allow if `view_ask` & `can_download` | Allow if `view_ask` & `can_download` | Deny |
| `upload` | Deny | Deny | Allow (<= internal; own dept or company; no `is_okf`/`is_template`) | Allow (<= internal; own dept only for dept scope; no `is_okf`/`is_template`) | Allow (all scopes/sensitivities, `is_okf`, `is_template`) | Deny |
| `edit_metadata` (title/desc/tags/category) | Deny | Deny | Allow on readable own-company docs (uploader/colleague); **not** external docs | Allow on own dept (<= internal) & own uploads | Allow on own-company docs (non-restricted or granted) | Deny |
| `change_scope_sensitivity` | Deny | Deny | Uploader **only** and **only MORE restrictive** (`company->dept->restricted`, `standard->internal`); cannot widen, lower sensitivity, or set `confidential` | Own dept docs (`<= internal`) & own uploads; cannot set `confidential` or modify `restricted` ungranted docs | Full control (own company; restricted requires grant/break-glass) | Deny |
| `approve` / `reject` | Deny | Deny | Deny (cannot self-approve) | Own dept docs (`<= internal`, non-restricted); cannot self-approve if `require_doc_approval` | All own-company docs (non-restricted or granted) | Deny |
| `archive` | Deny | Deny | Deny | Own dept docs (`<= internal`, non-restricted, no `legal_hold`) | Own-company docs (no `legal_hold`) | Deny |
| `delete` | Deny | Deny | Uploader's own doc only (no `legal_hold`) | Own dept docs (`<= internal`, non-restricted) or own upload (no `legal_hold`) | Own-company docs (no `legal_hold`) | Deny |
| `share_externally` | Deny | Deny | Deny | Deny | Allow when `enable_external_sharing=True`, `status=approved`, `sensitivity != confidential`, PII override explicit | Deny |
| `manage_grants` (internal `DocumentAccess`) | Deny | Deny | Uploader on own `restricted` doc (no clearance override) | Own dept docs (`<= internal`, non-restricted or granted; no clearance override) | Own-company docs (may use `override_clearance=True` + mandatory `reason`) | Deny |
| `break_glass` | Deny | Deny | Deny | Deny | Own-company `restricted` docs with mandatory `reason` (audited) | Deny |
| `explain_access` | Deny | Deny | Deny | Own dept members & own dept docs only (audited) | Own company members & docs (audited) | Deny |
| `manage_members` / `change_roles` | Deny | Deny | Deny | Own dept non-admin members only (cannot create/promote admins, cannot edit self, cannot move across depts, clearance <= internal) | Own company (cannot demote/delete self or last admin; cannot grant platform admin) | Deny |
| `view_export_audit` | Deny | Deny | Deny | Deny | Allow (own company) | Deny |
| `settings` / `billing` / `llm_config` | Deny | Deny | Deny | Deny | Allow (own company; `llm_config` requires `plan.allow_custom_llm`) | Platform defaults / plans only |

---

## 2. Revocation & AI Security Invariants

1. **Immediate Revocation on Next Request:**
   - Demotion, department change, clearance reduction, deactivation, or `logout-all` immediately bumps `User.token_version` and blacklists all outstanding refresh tokens.
   - Open WebSocket connections re-check `token_version`, `is_active`, `enable_team_chat`, and room membership before delivering broadcasts or accepting actions.
   - Presigned upload URLs use short expiration (`300s` default) and are cryptographically bound to `(user_id, company_id, key)` via a server-side `PendingUpload` record so no user can claim another document's S3 key.
2. **Post-Revocation Chat History Masking:**
   - Assistant `ChatMessage` rows store `source_document_ids` (JSON list of integer IDs) alongside `sources`.
   - Whenever a user loads `GET /api/conversations/<pk>` or continues a conversation via `POST /api/ask`, every prior assistant message referencing a document the user can **no longer** access is masked to `"[This answer referenced a document you no longer have access to.]"` (and its `sources` replaced with `["[Restricted]"]`), and excluded from LLM conversation history so revoked text can never re-enter the prompt!
3. **AI Retrieval Invariants:**
   - Candidate retrieval set, prompt context, returned `sources`, and follow-up history are **always** subsets of `accessible_documents_qs(user, action="view_ask", include_unapproved=False)`.
   - Zero cross-user answer caching.
   - No caller-supplied request field can widen or override the allowed document IDs.
   - In Team Chat rooms, `room_allowed_doc_ids(room)` computes the **exact intersection** of `accessible_documents_qs(member, include_unapproved=False)` across **all** members who can read the room (including `viewer`s in company/department rooms, so `internal` docs never leak to a `viewer` via `@DeskWise`).
   - `docgen` templates only pull from the user's **own company** approved documents that the user can both read and download (`can_download=True`), never unredacted external shares.

---

## 3. Audit Log Guarantees & Honest Limitations

Deskwise's audit log is **tamper-evident and append-only** (not magically "immutable" against a hostile database superuser):
- Every row hashes `hash_version | company_id | actor_id | actor_email | action | outcome | target_type | target_id | detail | ip | created_at | prev_hash` using SHA-256 (`hash_version=2`; legacy `hash_version=1` rows continue to verify without breaking existing chains).
- Updates and deletes are blocked at **both** the Django ORM layer (`AuditLog.save()`, `AuditLogQuerySet.update()`, `delete()`, `bulk_update()`) **and** database triggers (`BEFORE UPDATE` / `BEFORE DELETE` on PostgreSQL and SQLite), with an explicit recorded exception only for whole-company deletion/purge.
- A unique `(company_id, prev_hash)` constraint (for hashed rows) plus serialized per-company locking prevents chain forks.
- **What it guarantees:** Any unauthorized application edit, accidental deletion, or undetected post-hoc row tampering by a rogue operator breaks `verify_chain`.
- **What it does NOT guarantee:** A database superuser with direct SQL root access could drop the trigger, edit a historical row, and recompute every subsequent hash in the chain. For cryptographic proof even against a DB superuser, externally anchor the periodic head hash (`entry_hash`) from the Verification Certificate to an append-only store (e.g. S3 Object Lock or external log sink).

---

## 4. Decision Log

| ID | Topic | Decision | Reasoning |
|---|---|---|---|
| **D-01** | Explicit `User.clearance` | Added `User.clearance` (`standard`, `internal`, `confidential`, nullable -> defaults from role via `effective_clearance(user)`). | Keeps existing user rows & fixtures working cleanly without manual data backfill while allowing admins to explicitly adjust clearance (never above their own). |
| **D-02** | Admin access to `restricted` docs | Admins do **not** auto-read `restricted` docs; list/governance endpoints return masked metadata (`[Restricted document #<id>]`), and admins use audited `POST /api/documents/<id>/break-glass` with mandatory reason to grant themselves access. | Matches README & customer trust model ("restricted means named people only") while preserving audit/legal discovery capability. |
| **D-03** | Grants (`DocumentAccess`) vs clearance | Grants widen audience only; `override_clearance=True` requires company admin + mandatory `grant_reason` (persisted & audited). | Prevents accidental/silent exposure of `confidential` or `internal` docs to lower-clearance users (e.g. `viewer`s). |
| **D-04** | External shares (`DocumentShare`) | Reject `confidential` documents outright; never override clearance; require `status=approved`, `enable_external_sharing=True` on **both** owning and target companies (for directory lookups), and explicit PII override if `contains_pii=True`. | Admin-only `confidential` material should never leave tenant boundaries via ad-hoc sharing. |
| **D-05** | Existing test conflict: `test_security_hardened.py:222` | Existing test `test_scope_change_and_delete_need_admin_or_uploader` asserted that an employee uploader could widen their own `restricted` doc back to `company` (`200`). Under the new Phase B rule (*"uploader may only make their own document MORE restrictive"*), widening requires a manager/admin (`403`). | Strengthening the assertion to `403` for uploader widening (and verifying admin CAN widen) aligns the test with the stricter rule without weakening any security check. Recorded here per Hard Rule 1. |
| **D-06** | Existing test conflict: `test_feature_guards.py:109` & `test_team_chat.py` vs "team chat & attendance off by default" | `test_feature_guards.py:109` explicitly tests `Company.objects.create()` having `enable_attendance=True`, and `test_team_chat.py` expects `enable_team_chat=True` on ORM-created companies. To honor both the Hard Rule (do not break/weaken existing tests) and Phase C ("off by default" for new real workspaces), `POST /api/auth/register` (new SaaS signups), `seed_acl_lab`, and local demo setup default `enable_team_chat=False` and `enable_attendance=False`, and the frontend nav hides both unless explicitly `=== true`. | Preserves all existing unit tests unmodified while ensuring every real user signup and demo starts with Team Chat and Attendance off by default behind their flags. |
| **D-07** | Existing test conflict: `test_enterprise_governance.py:406` | That test simulated raw SQL tampering using `AuditLog.objects.filter(...).update(...)`. Under Phase F, ORM `.update()` AND DB triggers block updates! We will keep `test_enterprise_governance.py` asserting tamper detection by simulating a DB superuser disabling the trigger in SQL for that tamper-detection step, AND add dedicated Phase F tests asserting ORM `.update()`/`.delete()` and raw SQL `UPDATE`/`DELETE` raise errors. | Makes the audit log genuinely append-only while keeping tamper-detection verification tested. |
| **D-08** | Existing test conflict: `test_storage_units.py:36` | Earlier Neon/R2 S3 path-style hardening added `config=Config(...)` to `boto3.client("s3", ...)` when `AWS_S3_ENDPOINT_URL` is set, causing a strict `assert_called_once_with` mismatch in `test_storage_units.py:36`. We will update `test_storage_units.py:36` to assert `config` is a `Config` with `s3v4` + path-style alongside the exact region/endpoint/keys. | Preserves Neon/R2 S3 compatibility and makes the unit test stricter, not weaker. |
| **D-09** | `is_okf` and `is_template` permissions | Restricted to company admins on both upload (`POST /documents/upload`, `/documents/confirm`) and update (`PATCH /documents/<pk>`). | Prevents regular employees from boosting arbitrary docs into every colleague's AI prompt via `is_okf` or exposing files via `is_template`. |
| **D-10** | Deleting a `Department` | `DELETE /api/admin/departments/<pk>` sets `access_scope="restricted"` (fail-closed) instead of `"company"`, resets `is_dept_admin=False` on affected department managers, and bumps their `token_version`. | Fixes critical F-05 bug where deleting a department leaked department docs company-wide. |
