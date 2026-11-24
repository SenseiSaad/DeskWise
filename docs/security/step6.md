# Security work overview (steps 1–6)

**Date:** 2026-11-24
**Repo:** OpenVault_clean (Deskwise), branch `main`. All changes are **uncommitted**.
**Rules followed:** local repo only, no probing of the live site, no secrets printed or committed. One model change (`User.google_sub`, migration `0030`) was made in the second pass, after you approved it.

This file summarizes everything done in both passes. The second pass (§7) wrote step 2, fixed its findings, and finished the step-3 follow-ups. The detail lives in the per-step files:

| Step | Topic | Report |
|---|---|---|
| 1 | Authorization (DRF views, querysets, URLs, platform admin, plan limits) | [authorization.md](authorization.md) |
| 2 | Authentication (cookies, CSRF, refresh, OAuth, reset, rate limiting) | [authentication.md](authentication.md) |
| 3 | AI and content (prompt injection, workflows, rendering, keys, uploads, SSRF, ReDoS, error leaks) | [ai-and-content.md](ai-and-content.md) |
| 4 | Deployment hardening (settings, CSP, CORS, Vercel env, R2, Neon, admin, logging, email, secrets in git) | [hardening.md](hardening.md) |
| 5 | Dependency and code scanners plus CI gate | §4 below, and `.github/workflows/security.yml` |
| 6 | This overview | — |

---

## 1. Findings and status

### Step 1: authorization (`authorization.md`)

| ID | Sev | Finding | Status |
|---|---|---|---|
| AUTHZ-12 | P1 | The root/platform admin could read and edit every tenant's content through Django `/admin/` | **fixed** |
| AUTHZ-01 | P1 | A department manager could set a member's password (account takeover) | **fixed** |
| AUTHZ-02 | P2 | A company admin could set a member's password (break-glass bypass, unaudited) | **fixed** |
| AUTHZ-03 | P2 | The platform admin could delete company-less users (NULL-company lookup), unaudited | **fixed** |
| AUTHZ-04 | P2 | The platform admin could onboard itself into a tenant | **fixed** |
| AUTHZ-05 | P2 | A promoted platform admin kept tenant-admin access (analytics, audit, users, team chat) | **fixed** |
| AUTHZ-06 | P2 | Storage quota bypass through old document versions | **fixed** |
| AUTHZ-08 | P3 | An admin could delete a restricted document without break-glass | **fixed** |
| AUTHZ-09 | P3 | "Submit for review" skipped the read check (status change on unreadable restricted docs) | **fixed** |
| AUTHZ-10 | P3 | The effective-access view leaked restricted-doc metadata to dept managers | **fixed** |
| AUTHZ-11 | P3 | Team-chat LLM summaries didn't consume the monthly ask quota | **fixed** |
| (AUTHZ-07) | — | Stripe webhook forgery with an empty secret | **disproved** (`stripe==16` rejects an empty secret) |

No P0 found. There's no cross-tenant IDOR on any ID parameter I traced.

### Step 3: AI and content (`ai-and-content.md`)

| ID | Sev | Finding | Status |
|---|---|---|---|
| AI-01 | P1 | Model output alone could trigger meeting emails and invites to any address | **fixed**: chat intents are signed proposals; they run only on Confirm via `POST /api/workflow/confirm`; the team-chat bot never runs them; same-company recipients only |
| AI-02 | P2 | The outbound LLM client followed redirects (SSRF guard bypass) | **fixed** |
| AI-03 | P2 | Django admin showed decrypted LLM keys, TOTP seeds and password hashes | **fixed** |
| AI-04 | P2 | Presigned upload wasn't size-bound when `size` was omitted, and orphaned objects were never cleaned up | **fixed**: size always signed; expired unconfirmed objects purged by cron/beat; rejected objects deleted at confirm |
| AI-05 | P2 | Quadratic private-key regex (ReDoS) in PII redaction | **fixed** (512 KB: ~80 s extrapolated → 0.09 s) |
| AI-06 | P3 | Raw exception text in client responses | **fixed**: `index_error` is now generic for parser errors; `UploadRejected` text kept |
| AI-07 | P3 | Extension-only type check, and a client-chosen content type | **fixed**: confirm byte-checks a ranged 2 KB GET from R2 |
| AI-08 | P3 | Unbounded OCR (pixels and time) | **fixed** (not run against a real tesseract) |

### Step 2: authentication (`authentication.md`)

| ID | Sev | Finding | Status |
|---|---|---|---|
| AUTHN-01 | P1 | Google sign-in linked by email and signed in to unverified password accounts (pre-hijack) | **fixed** (`google_sub`, approved model change) |
| AUTHN-02 | P2 | No per-account login lockout | **fixed** (10 failures / 15 min, shared cache) |
| AUTHN-03 | P2 | No per-challenge MFA attempt cap | **fixed** (burned after 5 wrong codes or 1 success) |
| AUTHN-04 | P3 | TOTP replay (H-06) | **fixed** (last step per user, atomic claim) |
| AUTHN-05 | P3 | Other reset links survive a reset; non-atomic `consume` (H-10) | **fixed** |
| AUTHN-06 | P3 | Logout left the access token valid ≤ 15 min | **fixed** (`jti` denylist until `exp`) |
| AUTHN-07 | P3 | Refresh-token reuse didn't revoke the session family | **fixed** (revoke all, 10 s grace, stale-generation exempt) |
| AUTHN-08 | P3 | Homograph / IDN emails accepted | **fixed** (ASCII-only, no `xn--` labels) |
| AUTHN-09 | P3 | Origin-check block returned a 500 instead of 403 | **fixed** |
| AUTHN-10 | P3 | No-`Origin` unsafe requests pass the Origin check | won't fix (SameSite=Lax covers browsers; scripts rely on it) |
| AUTHN-11 | P3 | Forgot-password has no per-account cooldown | **fixed** |
| AUTHN-12 | P3 | Reset token burned before password validation | **fixed** |
| AUTHN-13 | P3 | Refresh cookie path is `/` | **fixed** (`Path=/api/auth/`, old cookie retired) |
| AUTHN-14 | P3 | Register/invite reveal existing emails | won't fix (product choice) |
| AUTHN-15 | P2 | Root MFA is trust-on-first-use (H-05) | policy question |
| AUTHN-16…19 | — | In-memory limiter, email-padding dodge, non-Secure cookies, verification off by default | **fixed in step 4** |

### Policy questions left open (`authorization.md` §4, H-01…H-13)

These are design decisions rather than confirmed bugs. They weren't changed:
- H-01: any reader-employee can edit a document's description and tags.
- H-02: `mode` lets users pick platform-keyed AI providers.
- H-03: the uploader external-share rule looks inverted.
- H-04: cross-company member directory.
- H-05: platform-admin MFA is trust-on-first-use.
- H-06: TOTP replay. **Now fixed** as AUTHN-04.
- H-08: self-editable HR profile fields.
- H-09: Google auto-linking. **Partly addressed** by AUTHN-01 (`sub` binding); auto-linking of verified accounts is still the question.
- H-10 and H-11: token-consume and plan-limit races. The H-10 token half is **now fixed** as AUTHN-05.
- H-12: admins read every private room.
- H-13: `audit_verify` returns 500 for root. That one is simple, and I can fix it on request.

---

## 2. What changed (by file)

| File | Change | For |
|---|---|---|
| `backend/core/admin.py` | Registers only platform models. User/LLMConfig admin hides secrets and locks privilege fields. | AUTHZ-12, AI-03 |
| `backend/core/permissions.py` | `IsAdmin` and `IsAdminOrDeptAdmin` reject platform-level accounts that are attached to a company | AUTHZ-05 |
| `backend/core/access.py` | `delete` requires break-glass on restricted docs | AUTHZ-08 |
| `backend/core/views.py` | Password-set blocked in `user_detail`; NULL-company guard; platform deny in `onboard_company` and `_platform_admin_blocked`; `_storage_used()` counts versions; review-submit read check; effective-access row filter; presign requires size and signs a server content type; magic-byte check; generic Stripe/Google errors | AUTHZ-01…06, 09, 10; AI-04, 06, 07 |
| `backend/core/team_chat.py`, `team_chat_views.py` | Platform-level accounts excluded from team chat (REST and WebSocket); LLM summaries logged as asks | AUTHZ-05, 11 |
| `backend/core/workflow.py` | Meeting recipients limited to same-company members; no exception text or internal paths in results | AI-01, AI-06 |
| `backend/core/providers.py` | No-redirect opener for every outbound LLM call | AI-02 |
| `backend/core/moderation.py` | Linear private-key block redaction | AI-05 |
| `backend/core/rag.py` | Generic stream error; bounded OCR | AI-06, AI-08 |
| `backend/core/uploads.py` | `content_type_for()`, `validate_magic()` | AI-07 |
| `backend/config/settings.py` | `IS_PRODUCTION` includes `VERCEL_ENV=production`; fail-closed production guard (DEBUG, SECRET_KEY, CORS allow-all, console email, LocMem rate limiting); Secure cookies on Vercel; HSTS preload opt-in; email verification default; Neon SSL and pooled-cursor setting; `ADMIN_ENABLED` / `ADMIN_ALLOWED_IPS`; Sentry body capture off; security-headers middleware | Step 4 |
| `backend/config/urls.py`, `core/mfa_admin.py` | Admin mounted only when enabled; IP allowlist | Step 4 |
| `backend/core/middleware.py` | `SecurityHeadersMiddleware` (API CSP, Permissions-Policy, COOP) | Step 4 |
| `backend/core/ratelimit.py` | Email key stripped before bucketing | Step 2 / 4 |
| `backend/core/email_service.py` | Recipient masked in log lines. This file also has **your own earlier uncommitted change** (login auto-resend and Resend HTTP error logging). | Step 4 |
| `frontend/proxy.ts` (new) | Strict nonce CSP plus security headers (server build) | Step 4 |
| `frontend/app/layout.tsx` | Reads the nonce and puts it on the theme script; skipped for the static build | Step 4 |
| `frontend/next.config.mjs` | `BUILD_TARGET=static` selects the export; the default is now the server build | Step 4 |
| `frontend/lib/api.ts` | Presigned PUT sends the server-signed content type | AI-07 |
| `customHttp.yml` (new), `amplify.yml` | Weaker static-mode CSP and headers for Amplify; build with `BUILD_TARGET=static` | Step 4 |
| `.github/workflows/security.yml` (new) | pip-audit, bandit (high), pnpm audit (high), semgrep (ERROR), gitleaks (full history); weekly schedule | Step 5 |
| `backend/tests/test_authz_audit_findings.py` (new) | 12 tests (AUTHZ-01…06, 08…12, AI-03) | Steps 1/3 |
| `backend/tests/test_ai_content_audit_findings.py` (new) | 7 tests (AI-01, 02, 04…08) | Step 3 |
| `backend/tests/test_providers_failures.py` | 3 mocks repointed from `urllib.request.urlopen` to the no-redirect opener | AI-02 |
| `backend/tests/test_security_hardened.py` | The admin-deletes-restricted-doc assertion now does break-glass first, matching its own comment | AUTHZ-08 |
| `.claude/launch.json` (new) | Local preview servers used for verification. **Don't commit it**: it points at a `/tmp` test script. | — |
| `docs/PERMISSIONS_REPORT.md` | Only the timestamp, regenerated by an existing test. Revert it with `git checkout -- docs/PERMISSIONS_REPORT.md` if you don't want it. | — |

---

## 3. Verification

| Check | Result |
|---|---|
| Backend test suite | First pass: 372 collected, 371 pass, 1 fails. **Second pass (final run): 409 collected: 394 pass, 14 skipped, 1 fails**: the same `test_rag_units.py::test_gemini_and_bedrock_parallel_embed`, which also failed in the baseline run before any change and is unrelated. The full suite was run after the step-2 fixes and again at the end. |
| Audit tests | 12 / 12 (authz file) and 7 / 7 (AI file) pass. AI-01 was also confirmed to **fail** on the pre-fix code. |
| Frontend `pnpm typecheck` and `pnpm test` | Pass (20 / 20), re-run after the chat Confirm card |
| Frontend server build (`pnpm build`) | Succeeds (re-run in the second pass). All routes are dynamic, and Proxy is active. |
| Frontend static build (`BUILD_TARGET=static pnpm build`) | Succeeds and writes `out/` (re-run in the second pass) |
| Browser check, server build (`pnpm start`) | CSP and headers sent; a fresh nonce per request on every script; the theme script runs; React hydrates; **no CSP violations** on `/` and `/enterprise/` |
| Browser check, static build (served with the exact `customHttp.yml` headers) | Hydrates; the theme script runs; **no CSP violations** |
| Settings boot | Dev boot is unchanged. A Vercel-production boot with a weak `SECRET_KEY` refuses to start. A complete production env boots with SSL redirect, HSTS and `RedisCache`. |

## 4. Scanner results (step 5)

| Scanner | Scope | Result |
|---|---|---|
| pip-audit 2.10.1 | `requirements.txt`, `requirements-optional.txt` | No known vulnerabilities |
| bandit 1.9.4 | `backend/core`, `backend/config` | 0 medium/high |
| pnpm audit | `frontend/pnpm-lock.yaml` | 0 vulnerabilities |
| osv-scanner (cross-check) | `frontend/pnpm-lock.yaml`, 403 packages | 0 vulnerabilities |
| semgrep (p/python, p/django, p/typescript, p/react) | `backend`, `frontend` | 2 WARNING, 0 ERROR: `open-redirect` in `mfa_admin.py:37`, the line numbering before this session's edits (the redirect target is the fixed `/admin/mfa-verify/` path, and `_finish` constrains `next` to `/admin/`, so this looks like a false positive) and `directly-returned-format-string` in `ratelimit.py:67` (a JSON response, not HTML) |
| gitleaks 8.24.3 | All 192 commits | No leaks |

**Where the "95 npm vulnerabilities" most likely come from (second pass).** `main`'s lockfile is clean. But the `test` branch (local and `origin/test`, last commit `6aed506`, 2026-11-04) has a different `frontend/pnpm-lock.yaml`: `next 16.3.3`, `vitest ^3`, 659 packages. `pnpm audit` on that lockfile, extracted to a temp directory, reports **117 advisories: 6 critical, 40 high, 61 moderate, 10 low**:
- The critical ones are three Next.js RCEs (`next/og`, image optimizer, `use cache`, all fixed by `16.4.x`), `proxy-addr`, and two `tinypool` (via vitest 3).
- Most of the rest come from `undici`, `hono`, `next`, `fast-uri`, `ip-address` and `@modelcontextprotocol/sdk`.

Dependabot only scans the repository's **default branch**. If `test` is the default branch on GitHub, or was when the alerts were raised, that lockfile is the likely source. A count of 95 open alerts fits once some alerts are deduplicated or auto-dismissed. The local `infra` branch has 7 moderate. I couldn't read the alerts: `gh` here has an **invalid token** (`gh auth status`).

What I need from you, either of:
- run `gh auth login` (read-only scope is enough) so I can run `gh api repos/SenseiSaad/OpenVault/dependabot/alerts --paginate`, or
- tell me which branch is the GitHub default.

If it's `test`, the fix is to merge or rebase `main`'s lockfile into it (`next 16.4.6`, `vitest ^4`), or make `main` the default. I didn't change the `test` branch.

---

## 5. Still open

1. **Dependabot "95":** see §4. I need a valid `gh` login or the name of the default branch.
2. **Policy questions H-01…H-13** (see §1 and the recommendations given in chat). No code was changed for them.
3. **Not verified on real infrastructure:**
   - Vercel production boot with the new guards;
   - Upstash `rediss://` connectivity. Every new auth control (lockout, MFA cap, TOTP replay, access-token denylist, proposal single-use) relies on the shared cache;
   - Neon pooled connection, and migration `0030_user_google_sub` on Postgres (only run on SQLite here);
   - Google Sign-In under either CSP, and the `sub` binding with real Google tokens (no client ID locally);
   - whether Amplify applies `customHttp.yml`;
   - whether the R2 bucket is private, and the ranged GET and delete against real R2;
   - the chat Confirm card in a browser with a real model reply. The typecheck, unit tests and both builds pass, but no LLM was available locally to produce a proposal.
4. **CI:** `ci.yml`'s pytest job will still fail on `test_rag_units.py::test_gemini_and_bedrock_parallel_embed`. That failure predates this work and is unrelated.

## 6. Before the next production deploy

These env vars must be set on the Vercel API project, or production refuses to boot by design:
- `SECRET_KEY`: at least 50 random characters;
- `CACHE_URL`: an Upstash `rediss://` URL;
- `RESEND_API_KEY`, or a real `EMAIL_BACKEND`;
- explicit `ALLOWED_HOSTS`.

Make sure `DEBUG` and `CORS_ALLOW_ALL_ORIGINS` are not set to `true`. Leave `ADMIN_ENABLED` unset unless you need `/admin/`. Set `LLM_KEY_ENCRYPTION_KEY` **before** you ever rotate `SECRET_KEY`. Full list: [hardening.md](hardening.md) §2 and §5.

**Second pass:** apply migration `0030_user_google_sub` (`python manage.py migrate`) before or with the deploy that ships the new `google_auth`. Without the column, every Google sign-in fails. The column is nullable, so the migration is safe to run first.

---

## 7. Second pass (step 2 written, step-2 fixes, step 3, step-4 follow-ups)

### Changed files

| File | Change | For |
|---|---|---|
| `backend/core/models.py` | `User.google_sub` (unique, nullable); `OneTimeToken.consume` uses a conditional UPDATE; `OneTimeToken.peek` | AUTHN-01, 05, 12 |
| `backend/core/migrations/0030_user_google_sub.py` (new) | AddField only. **Approved by you.** | AUTHN-01 |
| `backend/core/admin.py` | `google_sub` read-only | AUTHN-01 |
| `backend/core/views.py` | Login lockout; MFA attempt cap and replay check; reset invalidates sibling tokens and clears lockout; logout denylists the access `jti`; refresh-reuse handling (`_refresh_reuse_response`); Google `sub` binding and pre-hijack guard; ASCII email check in Google; `workflow_confirm` endpoint; confirm byte-check, delete-on-reject; cron purge; generic `index_error` | AUTHN-01…08, AI-01, 04, 06, 07 |
| `backend/core/auth.py` | `deny_access_token` / `is_access_token_denied`; checked in `CookieJWTAuthentication.get_validated_token`. Refresh cookie scoped to `/api/auth/`, legacy `Path=/` cookie retired | AUTHN-06, 13 |
| `backend/core/ws.py` | WebSocket connect refuses denylisted access tokens | AUTHN-06 |
| `backend/core/mfa.py` | `matching_step`, `verify_user_code` (replay), challenge attempt cap and burn; challenge nonce | AUTHN-03, 04 |
| `backend/core/mfa_admin.py` | Admin gate uses `verify_user_code` | AUTHN-04 |
| `backend/core/ratelimit.py` | `login_locked` / `record_login_failure` / `clear_login_failures` | AUTHN-02 |
| `backend/core/serializers.py` | `ascii_email_error`; validator on register and invite email | AUTHN-08 |
| `backend/core/middleware.py` | Origin block returns `JsonResponse` 403 | AUTHN-09 |
| `backend/core/workflow.py` | `build_proposal`, `confirm_proposal`, `ProposalError` | AI-01 |
| `backend/core/rag.py` | Emits `workflow_proposal` instead of running the workflow; `propose_workflows` flag | AI-01 |
| `backend/core/team_chat.py` | Bot calls `stream_answer(..., propose_workflows=False)` | AI-01 |
| `backend/core/urls.py` | `workflow/confirm` | AI-01 |
| `backend/core/storage.py` | `object_head` (ranged GET) | AI-07 |
| `backend/core/tasks.py` | `purge_expired_pending_uploads`; generic `index_error` | AI-04, 06 |
| `backend/core/uploads.py` | `index_error_message` | AI-06 |
| `backend/config/settings.py` | Beat entry for the hourly upload purge | AI-04 |
| `frontend/lib/api.ts` | `WorkflowProposal` type, `workflowApi.confirm` | AI-01 |
| `frontend/lib/workspace-store.tsx` | Stores the `workflow_proposal` event on the message | AI-01 |
| `frontend/app/workspace/chat/page.tsx` | `WorkflowProposalCard` (Confirm / Dismiss) | AI-01 |
| `backend/tests/test_authn_audit_findings.py` (new) | 29 tests (AUTHN-01…13) | Step 2/3 |
| `backend/tests/test_ai_content_audit_findings.py` | +8 tests (AI-01, 04, 06, 07 follow-ups) | Step 4 |
| `backend/tests/conftest.py` | Autouse cache clear before and after each test | Test infra |
| `backend/tests/test_mfa.py` | Login after activation uses the next TOTP step (same-step reuse is now refused) | AUTHN-04 |
| `backend/tests/test_security_regressions.py` | F-02 also mocks `storage.object_head` | AI-07 |
| `docs/security/authentication.md` (new), `ai-and-content.md`, `authorization.md` (§4 update note), this file | Status | — |


---

## 8. Hostile re-review (step 7)

A second reviewer attacked the working tree and found 10 more issues (S7-01…S7-10): MFA challenges that survived password reset and logout-all, a second enrollment that could replace an enabled authenticator, invitations that could overwrite a recovered password, logout that left earlier access tokens alive, the confirm-time filename swap, lost R2 cleanup records, the docgen gate on AI workflows, and two AI-history exposures (template answers and room history), plus promotion upgrading old sessions. All 10 are **fixed** with regression tests. See [`step7.md`](../../step7.md) for details, the behaviour changes after deploying (root admins sign in once more) and what remains unverified.

Backend suite after the fixes: 442 passed, 14 skipped, 1 failed (the same unrelated `test_gemini_and_bedrock_parallel_embed`).
