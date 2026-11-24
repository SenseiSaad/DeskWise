# Authentication audit: cookies, CSRF, refresh, logout, OAuth, verification, reset, rate limiting

**Scope:** `backend/core/auth.py`, `core/mfa.py`, `core/mfa_admin.py`, `core/ratelimit.py`, `core/middleware.py`, `core/ws.py` (WebSocket auth), `core/models.py` (`User`, `OneTimeToken`), `core/serializers.py` (register/login/invite), the auth views in `core/views.py` (`register_company` … `onboard_company`, `users` POST), and `config/settings.py` (JWT, cookies, CORS, hosts, cache).
**Method:** I read the code statically and ran the local test suite. Nothing was run against the live site.
**Date:** 2026-11-24. **Commit:** `0d876f3` plus uncommitted working-tree changes from steps 1, 3 and 4.
**Line numbers** refer to the code *before* the fixes in this step.

Severity scale (same as `authorization.md`): **P0** = cross-tenant exposure or takeover with no privileges. **P1** = account takeover or escalation from a reachable position. **P2** = a broken invariant or a control that needs a precondition to bypass. **P3** = defence-in-depth.

Regression tests for this step: `backend/tests/test_authn_audit_findings.py`.

---

## 1. Summary

| ID | Sev | Finding | Where | Status |
|---|---|---|---|---|
| AUTHN-01 | **P1** | Google sign-in links by email, not by Google `sub`, and signs in to an existing *unverified* password account (account pre-hijack) | `core/views.py:873-886` | **fixed** (model change approved: `User.google_sub`, migration `0030`) |
| AUTHN-02 | P2 | No per-account login lockout: the limiter is keyed on IP+email, so guessing spread across IPs is unlimited | `views.py:443`, `ratelimit.py:61-67` | **fixed** |
| AUTHN-03 | P2 | MFA challenge has no attempt cap (only 10/min per IP), so a 6-digit code is brute-forceable with IP rotation once the password is known | `views.py:511-559`, `mfa.py:63-78` | **fixed** |
| AUTHN-04 | P3 | TOTP replay: the same code is accepted for ~90 s (= H-06) | `mfa.py:51-60`, `mfa_admin.py:82,111` | **fixed** |
| AUTHN-05 | P3 | Other outstanding reset links stay valid after a reset; `OneTimeToken.consume` is read-then-write (= H-10) | `views.py:787-804`, `models.py:300-311` | **fixed** |
| AUTHN-06 | P3 | Logout leaves the access token valid until it expires (≤ 15 min) | `views.py:577-591`, `auth.py:74-88` | **fixed** |
| AUTHN-07 | P3 | Presenting an already-rotated refresh token is just a 401; it doesn't revoke the session family | `views.py:604-637` | **fixed** |
| AUTHN-08 | P3 | Non-ASCII / homograph email addresses are accepted (`ceo@аcme.test`, Cyrillic `а`) | `serializers.py:171,191`, `views.py:864` | **fixed** |
| AUTHN-09 | P3 | `OriginCheckMiddleware` returns an un-rendered DRF `Response`, so a blocked request is a **500**, not a 403 (it still fails closed) | `middleware.py:82-92` | **fixed** |
| AUTHN-10 | P3 | CSRF defence is SameSite=Lax + Origin check; unsafe requests with **no** `Origin` header pass | `middleware.py:68-80` | won't fix (scripts rely on header-less requests; SameSite=Lax covers browsers; revisit if `COOKIE_SAMESITE=None`) |
| AUTHN-11 | P3 | `forgot-password` has no per-account cooldown (only per IP+email), so a victim can be mail-bombed from many IPs | `views.py:763-780` | **fixed** |
| AUTHN-12 | P3 | `reset-password` burns the token *before* validating the new password; a weak password wastes the link | `views.py:793-798` | **fixed** |
| AUTHN-13 | P3 | Refresh cookie has `path=/`, so it's sent on every API request instead of only to `/api/auth/refresh` | `auth.py:42`, `auth.py:62` | **fixed** |
| AUTHN-14 | P3 | Register and admin "add member" say whether an email is already registered (account enumeration) | `views.py:386-391`, `views.py:2303-2308` | won't fix (product choice; login and forgot-password don't leak) |
| AUTHN-15 | P2 | Platform-admin MFA is trust-on-first-use (= H-05) | `views.py:494-503` | open (policy question H-05) |
| AUTHN-16 | P2 | Rate limits / cooldowns lived in per-process memory (useless on Vercel) | `settings.py:195-221` | **fixed in step 4** (production refuses to boot without a shared `CACHE_URL`) |
| AUTHN-17 | P3 | Login limiter key could be dodged by padding the email | `ratelimit.py:61-67` | **fixed in step 4** |
| AUTHN-18 | P2 | Cookies weren't `Secure` unless `COOKIE_SECURE` was set; the production guard needed `ENVIRONMENT=production` | `settings.py:34-37,180` | **fixed in step 4** |
| AUTHN-19 | P2 | Email verification was off by default | `settings.py:326` | **fixed in step 4** (on by default in production) |

No P0 found.

### Fix status (2026-11-24, uncommitted)

Every test below is in `backend/tests/test_authn_audit_findings.py` unless stated. For AUTHN-02…09 I wrote the tests before the fixes and ran them against the unfixed code: 15 failed. Five guard-rail tests passed both before and after, because they protect behaviour that must not regress:
- a reset clears the lockout;
- logout doesn't end other devices;
- a stale-generation refresh doesn't revoke the new login;
- a Cyrillic local part (DRF's `EmailField` already rejected it);
- a plain-ASCII register still works. The AUTHN-01 tests were written with the fix. Against the old code they fail by construction: the old code had no `google_sub`, and it left the squatter's password usable.

| ID | Status | Change | Tests |
|---|---|---|---|
| AUTHN-01 | **fixed** | New `User.google_sub` (unique, nullable), migration `0030_user_google_sub` (AddField only). It's read-only in Django admin. `google_auth` looks the user up by `sub` first. On first Google login it binds `sub` to the account with that email. If the email is already bound to a **different** `sub`, it refuses with 403 (audited). If the existing account was **unverified** and had a usable password, it calls `set_unusable_password()`, revokes all sessions, and audits that before signing in. New Google users are created with `sub`. Verified password accounts are still auto-linked and keep their password (that's H-09's policy question). | `test_authn01_*` (4) |
| AUTHN-02 | **fixed** | `ratelimit.login_locked / record_login_failure / clear_login_failures`. These are shared-cache counters keyed on the normalised email only. The defaults are 10 failures per 15 minutes (`LOGIN_LOCKOUT_THRESHOLD`, `LOGIN_LOCKOUT_SECONDS`), which give a 429 with `code=account_locked` and `Retry-After`. Unknown emails are counted the same way. A correct password clears the counter, and so does a successful reset. This runs even when `RATELIMIT_ENABLED=false`. | `test_authn02_*` (3) |
| AUTHN-03 | **fixed** | `mfa.challenge_burned / record_challenge_failure / burn_challenge`, keyed on the SHA-256 of the challenge. Five wrong codes burn the challenge, and so does one success. Challenges now carry a random nonce, so two logins never share a counter. Used by `mfa_verify` and `mfa_activate`. | `test_authn03_*` (2) |
| AUTHN-04 | **fixed** | `mfa.verify_user_code(user_pk, secret, code)`. It rejects any step ≤ the last accepted step for the user, claims the step atomically with `cache.add`, and stores the last step. Used by the API (`mfa_verify`, `mfa_activate`) and the Django-admin gate (`mfa_admin.py`). | `test_authn04_*`. I also updated `tests/test_mfa.py::test_platform_admin_second_login_uses_verify_step`: it reused the activation code for the login, which is now correctly refused, so it uses the next step. |
| AUTHN-05 | **fixed** | `OneTimeToken.consume` claims the token with a conditional `UPDATE … WHERE used_at IS NULL AND expires_at > now`. It covers verify, reset and invite. `reset_password` then marks every other unused `password_reset` token for the user as used. | `test_authn05_*` (2) |
| AUTHN-06 | **fixed** | `auth.deny_access_token()`: logout puts the access token's `jti` in the shared cache until its `exp`. That's the cookie, or the `Authorization` header if there's no cookie. `CookieJWTAuthentication.get_validated_token` (cookie and header) and the WebSocket connect (`ws.py`) refuse denylisted tokens. Only this session ends. Other devices stay signed in; `logout-all` still revokes everything. | `test_authn06_*` (2) |
| AUTHN-07 | **fixed** | `views._refresh_reuse_response()`, run before rotation. It handles three cases: (1) a blacklisted refresh token of the current `tv` generation, presented more than 10 s after it was retired (`REFRESH_REUSE_GRACE_SECONDS`), runs `revoke_user_refresh_tokens` and is audited as `refresh_token_reuse`; (2) inside the grace window, it returns a 401 that does **not** clear cookies and revokes nothing (concurrent tabs); (3) an older generation gets a plain 401. | `test_authn07_*` (3) |
| AUTHN-08 | **fixed** | `serializers.ascii_email_error()` rejects any non-ASCII character and any `xn--` domain label. It's applied to `RegisterCompanySerializer.email` and `UserCreateSerializer.email` (admin invite), and in `google_auth`. | `test_authn08_*` (6) |
| AUTHN-09 | **fixed** | `OriginCheckMiddleware` returns `JsonResponse(…, status=403)`. | `test_authn09_*` |
| AUTHN-10 | won't fix | See §2. | — |
| AUTHN-11 | **fixed** | `forgot_password` sends at most one reset email per account per 60 s and 10 per day (shared cache, keyed on the user, not the IP). A throttled request gets the identical 200 body, so nothing is revealed. | `test_authn11_*` |
| AUTHN-12 | **fixed** | New `OneTimeToken.peek()`. `reset_password` validates the link and the new password first, then consumes the token atomically. A rejected weak password no longer burns the link. | `test_authn12_*` |
| AUTHN-13 | **fixed** | The refresh cookie is set with `Path=/api/auth/`, so it's only sent to `/api/auth/refresh` and `/api/auth/logout`. Every refresh or login also sends an expiry for the old `Path=/` cookie, because browsers would otherwise send both and Django would read the stale one. Logout clears all three. The access cookie stays at `/`. | `test_authn13_*` (3) |

Test infrastructure: `tests/conftest.py` now clears the cache before and after every test, because lockout, MFA and denylist state lives there and test emails and PKs repeat.

**Residual notes:**
- All the new controls depend on the shared cache. In production that's enforced by the boot guard (`CACHE_URL`). If Redis is unreachable, auth requests error rather than silently skipping the checks.
- The lockout lets anyone lock a known email out for 15 minutes. The reset flow still works and clears it.
- An already-open WebSocket isn't closed by a single-session logout. It re-checks `token_version` periodically, which catches logout-all and password changes, but not the per-`jti` denylist. A new connection with the logged-out token is refused.
- The refresh-cookie path change means a user with a pre-change session keeps working: their old `Path=/` cookie is still accepted on the first refresh, which replaces it. A frontend served from a different path prefix than `/api/auth/` would never send the cookie; the code assumes the browser calls `<API_BASE>/api/auth/refresh`, as `frontend/lib/api.ts` does.
- Existing rows with non-ASCII emails aren't touched. Those users can still sign in with a password, but not with Google.

---

## 2. Findings

### AUTHN-01 (P1): Google sign-in links by email and signs in to unverified password accounts

- **Where:** `core/views.py:873-886` (`google_auth`). The account is looked up by `email__iexact`. If it exists, the view flips `email_verified=True` and sets session cookies. The Google `sub` is never stored or compared.
- **Impact (pre-hijack):**
  1. Attacker registers `victim@company.test` with a password. With `REQUIRE_EMAIL_VERIFICATION=false` (the dev/staging default) the attacker is signed in straight away. In production the account just sits unverified.
  2. The real owner later clicks "Sign in with Google". The view finds the attacker's row, marks it verified, and signs the owner in.
  3. The attacker's password still works, so the attacker now shares a verified account with the victim, including whatever company the victim creates or is added to.

  Secondary: because nothing binds the Google identity, if the email on a Google account is ever reassigned (Workspace admin renames a user), the new holder of that address gets the old account.
- **Fix (needs a model change, step 3):** add `User.google_sub` (unique, nullable). Bind it on first Google login; refuse a different `sub` for the same email; when linking to an existing account that was **not** verified, invalidate its password (`set_unusable_password()` and revoke sessions) before signing in.
- **Status:** open, waiting for approval of the model change.

### AUTHN-02 (P2): no per-account login lockout

- **Where:** `views.py:443` uses `rate_limit("login", rate=8, per_seconds=60, key="ip_email")`. The bucket is `"<ip>:<email>"` (`ratelimit.py:61-67`).
- **Impact:** an attacker with many IPs (a botnet or a cloud function fan-out) gets 8 guesses/min **per IP** against one account. Nothing limits the total number of failures for an account.
- **Fix:** a second, IP-independent counter keyed only on the normalised email, in the shared cache. 10 failures in 15 minutes locks sign-in for that email (even with the right password) until the window ends. Unknown emails are counted too, so the response doesn't reveal whether the account exists. A successful password reset clears the counter.
- **Trade-off:** anyone can lock a known email out for 15 minutes by failing 10 times. That's the usual lockout trade-off; the reset flow still works during a lockout.

### AUTHN-03 (P2): no per-challenge attempt cap on MFA

- **Where:** `mfa_verify` and `mfa_activate` (`views.py:511-559`) are limited to 10/min **per IP**. A challenge (`mfa.py:63-78`) is valid for 5 minutes and can be retried any number of times. A new challenge only needs the password.
- **Impact:** given a platform admin's password, the second factor (10⁶ codes, 3 valid at a time) can be brute-forced from enough IPs.
- **Fix:** count wrong codes per challenge in the shared cache (keyed on the SHA-256 of the challenge string). After 5 wrong codes the challenge is burned and even a correct code is refused. A challenge is also burned after one successful use.

### AUTHN-04 (P3): TOTP replay

- **Where:** `mfa.verify_code` (`mfa.py:51-60`), used by the API (`views.py:530,555`) and the Django-admin gate (`mfa_admin.py:82,111`).
- **Impact:** a shoulder-surfed or phished code can be replayed inside the ±1 step window (~90 s).
- **Fix:** store the last accepted time step per user in the shared cache and reject any code whose step is not newer. The per-step claim uses `cache.add`, so two concurrent requests can't both use one code.

### AUTHN-05 (P3): reset tokens not invalidated; non-atomic consume

- **Where:** `reset_password` (`views.py:787-804`) only consumes the presented token. `OneTimeToken.consume` (`models.py:300-311`) does `filter().first()`, `is_valid()`, then `save()`.
- **Impact:** an older reset link sitting in the mailbox (or in a forwarded email) still works for up to 30 minutes after the user already reset. Two parallel requests can both consume one token.
- **Fix:** `consume` marks the row used with a conditional `UPDATE … WHERE used_at IS NULL AND expires_at > now()` and returns the row only if it updated one row. After a successful reset, every other unused `password_reset` token for that user is marked used.

### AUTHN-06 (P3): logout doesn't kill the access token

- **Where:** `logout` (`views.py:577-591`) blacklists the refresh token and clears cookies. The access JWT is self-contained and accepted by `CookieJWTAuthentication` until `exp` (15 minutes by default).
- **Impact:** an access token copied before logout (from a shared machine, a proxy log, or a script using the `Authorization` header) keeps working for up to 15 minutes.
- **Fix:** on logout, put the access token's `jti` in a shared-cache denylist until the token's `exp`, and check the denylist on every request (REST and WebSocket connect). This logs out only that session. `logout-all` still bumps `token_version` for every device.

### AUTHN-07 (P3): refresh-token reuse isn't treated as theft

- **Where:** `refresh` (`views.py:604-637`). Rotation blacklists the old token. Presenting it again is a plain 401.
- **Impact:** if an attacker and the real user both hold one refresh token, whoever refreshes second just gets a 401. Nothing revokes the token the attacker (or the user) got from the first rotation, so a stolen refresh token stays usable for its 7-day life if the thief refreshes first.
- **Fix:** if a correctly signed refresh token is already blacklisted, and its `tv` still matches the user's current `token_version`, revoke all of that user's sessions (`revoke_user_refresh_tokens`). Two guard rails:
  - **Grace window:** if the blacklisting is less than 10 s old, treat it as two tabs refreshing at once. Return 401 without revoking and without clearing the new cookies.
  - **Stale generation:** a token from before a password reset or logout-all (old `tv`) is just a 401. Otherwise an old phone waking up after a reset would log the user out of the new session.
- **Note:** there's no per-login "family" ID in the schema, so the family is "all of this user's sessions". Adding a family ID would need a model change.

### AUTHN-08 (P3): non-ASCII and homograph email addresses

- **Where:** `RegisterCompanySerializer.email` and `UserCreateSerializer.email` are DRF `EmailField`s (`serializers.py:171,191`). Django's validator accepts IDN domains. `google_auth` takes the claim as-is (`views.py:864`).
- **Impact:** `ceo@аcme.test` (Cyrillic `а`) and `ceo@acme.test` are different accounts that look identical in the member list, share dialogs and audit log. An attacker can register a lookalike workspace or get a careless admin to invite a lookalike address.
- **Fix:** reject any address containing non-ASCII characters, and any domain label in punycode (`xn--`), at register, admin invite, and Google sign-in. That blocks both the raw and the punycode spelling of a homograph.
- **Trade-off:** genuine IDN domains (e.g. `müller.de`) can't be used. If you need them, the alternative is: normalise to punycode, reject mixed-script labels, and refuse an address whose skeleton collides with an existing one.

### AUTHN-09 (P3): Origin check returns a 500

- **Where:** `OriginCheckMiddleware` (`middleware.py:82-92`) returns `rest_framework.response.Response` from Django middleware. No renderer is attached, so Django raises `ContentNotRenderedError` and the client gets a 500 HTML page.
- **Impact:** none for security. The view never runs, so it fails closed. But a CSRF block shows up as a server error in logs and Sentry, and a legitimate misconfigured origin is hard to diagnose.
- **Fix:** return `django.http.JsonResponse(..., status=403)`.

### AUTHN-10 (P3): requests without an `Origin` header pass the Origin check

- **Where:** `middleware.py:80` only checks requests that carry `Origin`.
- **Impact:** low. Modern browsers send `Origin` on every cross-origin `fetch` and on cross-site form POSTs, and `SameSite=Lax` keeps the cookies off cross-site POSTs anyway. The residual risk is only when `COOKIE_SAMESITE=None` is configured **and** some old browser omits `Origin`.
- **Recommendation:** keep as is. Scripts and tests rely on header-less requests. If you ever set `COOKIE_SAMESITE=None`, require `Origin` (or a custom header) on unsafe requests that carry the auth cookie.

### AUTHN-11 (P3): forgot-password mail bombing

- **Where:** `forgot_password` (`views.py:763-780`), `rate_limit(... key="ip_email")`.
- **Impact:** from many IPs, an attacker can make the platform send many reset emails to one address (annoyance and sender-reputation risk). No account access.
- **Fix (not applied, not in this step's list):** reuse the 60 s cooldown and daily cap that `request_verification` already has (`views.py:713-735`).

### AUTHN-12 (P3): reset token burned before password validation

- **Where:** `views.py:793-798`. `consume()` runs before `_password_error()`.
- **Impact:** UX. A user who picks a weak password has to request a new link.
- **Fix (not applied):** validate the password first, then consume.

### AUTHN-13 (P3): refresh cookie path

- **Where:** `auth.py:42` sets `path="/"` for both cookies.
- **Impact:** the long-lived refresh token is sent on every API request, so it shows up in more places (proxies, logs, request dumps) than it needs to.
- **Fix (not applied):** set the refresh cookie with `path="/api/auth/"`. This needs a matching change in `clear_auth_cookies`, and the old `/`-path cookie has to be cleared once during migration.

### AUTHN-14 (P3): account enumeration on register and invite

- **Where:** `views.py:386-391` (409 "already registered") and `views.py:2303-2308`.
- **Status:** won't fix. The UX needs it, and both endpoints are rate-limited or need an admin. Login, forgot-password and request-verification return the same response either way.

### AUTHN-15 (P2): platform-admin MFA is trust-on-first-use

Same as `authorization.md` H-05. It's a policy question; see the step-6 list.

---

## 3. Checked and OK

- **JWT cookie flags:** both cookies are `HttpOnly`, `SameSite=Lax` by default, and `Secure` on Vercel or when `COOKIE_SECURE=true`. `SameSite=None` is downgraded to `Lax` unless `Secure` (`auth.py:31-47`). The production guard refuses to boot with insecure cookies (`settings.py:443-447`). Raw tokens are never in JSON bodies (`tests/test_auth.py:14`).
- **JWT validation:** SimpleJWT HS256 with `SECRET_KEY` (≥ 50 chars enforced in production). 15 min access, 7 day refresh, rotation and blacklist after rotation (`settings.py:157-165`). The `tv` claim is checked against `User.token_version` on REST (`auth.py:77-81`), refresh (`views.py:625`) and WebSocket connect (`ws.py:129`).
- **CORS / ALLOWED_HOSTS:** explicit origin list with credentials. `CORS_ALLOW_ALL_ORIGINS` refused in production (`settings.py:431`). `ALLOWED_HOSTS` must be explicit in production (`settings.py:448`). WebSocket Origin is checked against the same lists (`ws.py:56-89`).
- **Password policy:** min 10 chars, common and numeric checks, similarity check (`settings.py:168-174`), enforced on register, invite accept, reset and self-change.
- **Session revocation on credential change:** password reset and self password change call `revoke_user_refresh_tokens` (blacklist all and bump `token_version`) (`views.py:696,802`).
- **Google ID token:** verified against Google JWKS with RS256 only, `aud` = `GOOGLE_CLIENT_ID`, `iss` pinned, `exp` with 30 s leeway (`views.py:807-837`). `email_verified` is required. The error message is generic (step 3).
- **Email verification:** single-use, 24 h, hashed token. Login is gated when `REQUIRE_EMAIL_VERIFICATION` is on, with a 60 s auto-resend cooldown. Resend has a 60 s cooldown and a 10/day cap.
- **Token generation:** `secrets.token_urlsafe(32)` (256 bits). Only the SHA-256 is stored (`models.py:290-298`). The lookup is by hash, so there's no timing oracle on the raw value. TOTP secrets are 160-bit from `secrets`, encrypted at rest. MFA challenges are `TimestampSigner` blobs with a purpose and a 5-minute life.
- **Constant-time comparisons:** TOTP codes (`mfa.py:58`), invite email binding (`views.py:960`), cron bearer secret (`views.py:4238`).
- **Email normalisation:** stored as `strip().lower()` (`models.py:117`). Every lookup uses `email__iexact`. The limiter buckets on the same normalisation.
- **No enumeration** on login, forgot-password or request-verification. Django's `ModelBackend` runs the hasher for unknown users, so timing is similar.

## 4. Not verified

- Behaviour against a real shared cache (Upstash Redis). The lockout, MFA cap, TOTP replay and access-token denylist all depend on it. Tests use LocMem.
- Migration `0030_user_google_sub` against Neon/Postgres. It ran only on the SQLite test database here. It's a nullable unique column, so existing rows get NULL, and Postgres allows many NULLs under a unique constraint.
- Google Sign-In end to end (no client ID locally). The Google tests mock `verify_google_id_token`.
- Whether any production row already has a non-ASCII email. The new check applies to new registrations, invites and Google sign-ins only.
- How the frontend reacts to the new 429 `account_locked` response, beyond showing its `detail` text (it uses the generic error path).
