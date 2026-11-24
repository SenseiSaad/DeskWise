# Deployment hardening

**Date:** 2026-11-24. All changes are uncommitted.
**Targets:** Django API on Vercel (serverless Python), Next.js 16 frontend on Vercel, Neon Postgres, Cloudflare R2.

Nothing here was applied to live infrastructure. Where a change has to happen in a dashboard (Vercel, Neon, R2, Upstash), this doc gives the exact settings and commands.

---

## 1. Code changes made

| Area | Change | File |
|---|---|---|
| Production detection | `IS_PRODUCTION` is now true for `ENVIRONMENT=production` **or** `VERCEL_ENV=production`, and is computed before anything uses it. Before this, a Vercel production deploy without `ENVIRONMENT=production` skipped every guard. | `backend/config/settings.py` |
| Fail-closed production guard | At boot it refuses: `DEBUG=true`; a `SECRET_KEY` shorter than 50 chars or containing `insecure`/`change-me`/`replace`/`example`; `CORS_ALLOW_ALL_ORIGINS` (combined with credentialed cookies it lets any site read API responses); console/locmem/dummy/file email backends unless `RESEND_API_KEY` is set; an in-memory rate-limit cache while `RATELIMIT_ENABLED`. The existing checks stay: insecure cookies, wildcard `ALLOWED_HOSTS`, `LLM_PROVIDER=fake`. The old guard was also skipped whenever `DEBUG=true`. | `settings.py` |
| Cookies | `COOKIE_SECURE` defaults to `true` on Vercel. That also turns on `SECURE_SSL_REDIRECT`, `SECURE_PROXY_SSL_HEADER` and HSTS (1 year, includeSubDomains). Cookies stay HttpOnly and SameSite (from `COOKIE_SAMESITE`). | `settings.py` |
| HSTS preload | Now opt-in (`SECURE_HSTS_PRELOAD=true`). Preload is a long-term commitment for every subdomain, so it shouldn't happen by default. | `settings.py` |
| Email verification | `REQUIRE_EMAIL_VERIFICATION` defaults to `true` in production, and can still be overridden. | `settings.py` |
| Neon | `ssl_require` is set in production. When `DATABASE_URL` uses Neon's pooled host (`-pooler.`), or `DB_POOLED=true`, `DISABLE_SERVER_SIDE_CURSORS=True` is set so `QuerySet.iterator()` (the audit CSV export) works through PgBouncer transaction mode. `CONN_MAX_AGE=0` on Vercel was already in place. | `settings.py` |
| Rate limiting | The store is now enforced to be shared: production refuses to boot with LocMem. Set `CACHE_URL=rediss://default:<token>@<name>.upstash.io:6379` (Upstash's Redis-protocol endpoint). Django's built-in `RedisCache` and the pinned `redis==5.2.1` speak TLS, so no new dependency is needed. The `ip_email` key now strips whitespace as well as lowercasing, so padded variants of one address share one bucket. | `settings.py`, `core/ratelimit.py` |
| Django admin | Mounted only when `ADMIN_ENABLED` is true, which defaults to **false** in production. With `ADMIN_ALLOWED_IPS` set, every `/admin/*` path returns 404 for other client IPs. On Vercel the client IP comes from `X-Forwarded-For`, which Vercel overwrites. The admin itself no longer exposes tenant content or secrets (AUTHZ-12 / AI-03). | `config/urls.py`, `core/mfa_admin.py`, `settings.py` |
| API security headers | New `SecurityHeadersMiddleware`. `/api/*` responses get `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'`. All responses get `Permissions-Policy` and `Cross-Origin-Opener-Policy: same-origin`. `nosniff`, `Referrer-Policy: same-origin` and `X-Frame-Options: DENY` were already set. | `core/middleware.py`, `settings.py` |
| Sentry | Added `max_request_body_size="never"`. Bodies carry passwords, reset tokens, questions and document text. `send_default_pii=False` was already set. | `settings.py` |
| Logs | Email delivery warnings now log a masked recipient (`j***@example.com`). | `core/email_service.py` |

### Frontend CSP: two build modes

The frontend has two build modes, chosen by `BUILD_TARGET`. **They are not equally strong.** The server build is the protected one. The static build is a fallback for hosts that can't run a server.

| | **Server build (default; Vercel, `next start`, Docker)** | **Static export (`BUILD_TARGET=static`, e.g. Amplify)** |
|---|---|---|
| How to build | `pnpm build` (optionally `DOCKER_STANDALONE=true`) | `BUILD_TARGET=static pnpm build` (writes `out/`). The legacy `STATIC_EXPORT=true` still works. |
| Where the CSP comes from | `frontend/proxy.ts`, per request | The static host's header config. For Amplify that's `customHttp.yml` at the repo root. `next.config` `headers()` can't do this: Next applies those from its own server, and a static host never runs it. Next 16 lists both `headers()` and Proxy as unsupported with `output: 'export'`. |
| `script-src` | `'self' 'nonce-<random per request>' 'strict-dynamic'`. Inline scripts run only if they carry the nonce, and only scripts loaded by those trusted scripts are allowed. | `'self' 'unsafe-inline' https://accounts.google.com/gsi/client`. Next's exported HTML embeds inline bootstrap scripts, and a static host can't mint nonces. Without `'unsafe-inline'` the app doesn't run. |
| `unsafe-eval` | Never in production (dev only, which React needs) | Never |
| Effect on injected `<script>`/inline handlers (XSS) | **Blocked**: no nonce. | **Not blocked by CSP.** XSS defence then rests on React escaping and `rehype-sanitize`. |
| `style-src` | `'self' 'unsafe-inline' https://accounts.google.com/gsi/style`. React `style={{}}` attributes need `'unsafe-inline'`, and the nonce is left out on purpose, because a nonce would make browsers ignore `'unsafe-inline'`. | Same |
| `connect-src` | `'self'`, the API origin, and its `ws(s)://` origin (from `NEXT_PUBLIC_API_URL` at build), plus `https://accounts.google.com/gsi/` | `'self' https: wss:`. The file can't read env vars, so **replace it with the exact API origin** to tighten it. |
| Both | `default-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; frame-src https://accounts.google.com/gsi/; img-src 'self' data: blob: https://*.googleusercontent.com; font-src 'self' data:` plus `upgrade-insecure-requests` in production | Same |
| Other headers | `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy`, `COOP: same-origin-allow-popups` (for the Google sign-in popup), HSTS 1 year + includeSubDomains | `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, HSTS |
| Rendering cost | **Every route is dynamic** (`ƒ`). `app/layout.tsx` reads the nonce with `headers()`, which nonces require. That means more function invocations on Vercel than static pages. | Fully static |

Files: `frontend/proxy.ts`, `frontend/app/layout.tsx` (the nonce goes on the inline theme script, and `headers()` is skipped when `BUILD_TARGET=static`), `frontend/next.config.mjs`, `customHttp.yml`, and `amplify.yml` (now builds with `BUILD_TARGET=static`).

**Verified locally (2026-11-24):**
- `pnpm typecheck` passes, and `pnpm test` passes 20 of 20.
- **Server build:** `pnpm build` succeeds, and all 23 routes plus Proxy are `ƒ (Dynamic)`. Served with `pnpm start`:
  - responses carry the CSP and all the headers above;
  - every `<script>` in the HTML has the nonce, and the nonce changes per request;
  - in the browser, the theme script ran, React hydrated, and `/` and `/enterprise/` showed **no CSP violations**;
  - the only script without a nonce is Vercel Analytics, which a trusted script injects at runtime, so `'strict-dynamic'` allows it.
- **Static build:** `BUILD_TARGET=static pnpm build` succeeds (Next warns that middleware is disabled for export, as expected) and the output has no nonces. I served `out/` with the exact headers parsed from `customHttp.yml`: the page hydrated, the theme script ran, and there were **no CSP violations**.
- **Not verified:**
  - Google Sign-In under either CSP: the local builds had no `NEXT_PUBLIC_GOOGLE_CLIENT_ID`, so the GSI script never loaded.
  - That Amplify actually applies `customHttp.yml` for this monorepo app. Check the response headers after the next Amplify deploy, or set the same headers under Amplify console → Hosting → Custom headers.
  - Behaviour on a real Vercel deployment.

---

## 2. Vercel environment variables

**Set on the API project (Production).** Mark every secret as **Sensitive** so it can't be read back from the dashboard.

| Variable | Value / note |
|---|---|
| `SECRET_KEY` | ≥ 50 random chars: `python3 -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `LLM_KEY_ENCRYPTION_KEY` | A separate random value. **Set it before rotating `SECRET_KEY`**; see §5. |
| `DATABASE_URL` | Neon **pooled** connection string (`…-pooler.<region>.aws.neon.tech/…?sslmode=require`). |
| `CACHE_URL` | Upstash `rediss://…` URL. Required in production. |
| `ALLOWED_HOSTS` | The exact API hostnames. `VERCEL_URL` is appended automatically. |
| `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, `FRONTEND_URL` | The exact frontend origin(s), https only. |
| `COOKIE_SAMESITE` | `None` only if the frontend and API are on different sites. Otherwise leave `Lax`. |
| `RESEND_API_KEY`, `DEFAULT_FROM_EMAIL` | Real email delivery. `EMAIL_ASYNC` must stay `false` on Vercel, because daemon threads are frozen after the response. |
| `CRON_SECRET` | Random value. Vercel Cron sends it as `Authorization: Bearer`. |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | Live keys only on Production. Test keys only on Preview. |
| `GEMINI_API_KEY` / `AWS_BEARER_TOKEN_BEDROCK` / `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` | Whichever LLM provider is used. |
| `AWS_STORAGE_BUCKET_NAME`, `AWS_S3_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | R2 token scoped to **one bucket, Object Read & Write**. |
| `SENTRY_DSN` | Optional. |
| `ADMIN_ENABLED` / `ADMIN_ALLOWED_IPS` | Leave unset (admin off) unless you need break-fix access. |
| `DEBUG` | Leave unset. Production refuses `true`. |

Hygiene rules:
- **Preview deployments must not get Production secrets.** Give Preview its own Neon branch, Stripe test keys, a separate R2 bucket and a separate `SECRET_KEY`. Preview deploys are reachable by anyone with the URL unless Vercel Deployment Protection is on, so turn it on.
- **Frontend project:** only `NEXT_PUBLIC_*` values that are genuinely public belong there (`NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_GOOGLE_CLIENT_ID`, `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`, `NEXT_PUBLIC_BETA_PROVIDER`, `NEXT_PUBLIC_RELEASE_STAGE`). Anything with that prefix is compiled into the browser bundle. I checked the code: no secret is read through `NEXT_PUBLIC_*`.
- Pull values with `vercel env pull` only into the git-ignored `.env.local`. `.gitignore` already covers `.env` and `.env.*`.

## 3. Cloudflare R2

The code never issues public or presigned **GET** URLs. All downloads stream through Django after the ACL check. The browser only needs **PUT** through the presigned URL from `/api/documents/presign`.

1. **Keep the bucket private.** In Cloudflare dashboard → R2 → bucket → Settings: *Public access* = **Disabled**, leave *r2.dev subdomain* **Disabled**, and attach **no custom domain**. I haven't verified the current setting; check it.
2. **API token:** R2 → Manage API tokens → *Object Read & Write*, **specific bucket only**, no account-wide admin. Rotate the existing token if it was account-scoped.
3. **CORS** (only what direct upload needs). Save as `r2-cors.json`:

   ```json
   [
     {
       "AllowedOrigins": ["https://YOUR-FRONTEND-DOMAIN"],
       "AllowedMethods": ["PUT"],
       "AllowedHeaders": ["content-type", "content-length"],
       "ExposeHeaders": ["ETag"],
       "MaxAgeSeconds": 3600
     }
   ]
   ```

   Apply it with the AWS CLI against the R2 endpoint:

   ```bash
   aws s3api put-bucket-cors --bucket YOUR_BUCKET --cors-configuration "{\"CORSRules\": $(cat r2-cors.json)}" --endpoint-url https://ACCOUNT_ID.r2.cloudflarestorage.com
   ```

4. **Lifecycle rule** for abandoned direct uploads (AI-04 follow-up). Expire objects that were never confirmed. Confirmed objects keep the same key, so scope the rule narrowly, or add the app-side cleanup task instead. Don't apply a blanket rule to the document prefix.

## 4. Neon

- Use the **pooled** connection string in `DATABASE_URL`. Run migrations (`manage.py migrate`) with the **direct**, non-pooled string, from CI or locally, never from a serverless function.
- The app role should own only the app database. Use a separate role for migrations if you want least privilege.
- Use a branch per Preview environment so preview deploys never touch production data.

## 5. Secrets in git: findings and purge

**Tracked files now:** no `.env`, SQLite, `.bak`, key or credential files are tracked. Only `*.example` templates, `SECRETS_REPORT.md`, `infra/secrets-manifest.yaml` (a manifest of names) and a migration file whose name contains "mfa_secret".

**History (all 192 commits, every branch):**
- No `.env`, SQLite, `.bak`, `.pem` or `.key` file was **ever added**. I checked every `--diff-filter=A` path in history.
- A content scan for AWS, Stripe, Google, GitHub, Slack and Resend key formats, private-key headers and Neon URLs with passwords found only:
  - The AWS **documentation example** key pair (`AKIAIOSFODNN7EXAMPLE` / `wJalrXUtnFEMI…`) in a provider unit test. It isn't a credential.
  - Obvious placeholders and test fixtures (`dev-insecure-secret-change-me`, `sk-SuperSecretToken…`, `stale-…-key-123456`).
  - `infra/envs/{prod,staging}/variables.tf` (commits around `de9e0cd` / `a15bb08` / `e821342`, 2026-11-02/03) assigning values starting with `open…` to `SECRET_KEY`, `EMAIL_HOST_PASSWORD` and `BOOTSTRAP_PLATFORM_ADMIN_PASSWORD`. These look like Secrets Manager **path names** (`openvault/prod/…`), not values. I couldn't read the file directly (the permission classifier blocked it). But **gitleaks 8.24.3 (`gitleaks git . --redact`) over all 192 commits reported "no leaks found"**, and its generic-API-key rule didn't flag these lines.

**No purge is required on current evidence.** If gitleaks or your own check of `variables.tf` finds a real value, purge it like this:

```bash
pip install git-filter-repo
```

```bash
git clone --mirror git@github.com:SenseiSaad/OpenVault.git openvault-purge.git
```

```bash
cd openvault-purge.git && printf 'LITERAL_SECRET_VALUE==>REDACTED\n' > ../replacements.txt && git filter-repo --replace-text ../replacements.txt
```

To drop whole files instead (for example a committed `.env` or `*.sqlite3.bak`):

```bash
git filter-repo --invert-paths --path backend/.env --path-glob '*.sqlite3.bak'
```

```bash
git push --force --mirror
```

After a forced push, every clone and fork must be re-cloned. Ask GitHub Support to purge cached views and PR refs. GitHub keeps PR diffs, which `filter-repo` can't reach. **Purging never un-leaks a secret: rotate first, then purge.**

### Credentials to rotate

On current evidence nothing is confirmed leaked, so **no rotation is mandatory yet.** These are every credential the deployment holds and how to rotate each one. Rotate any that gitleaks flags, and any you've ever pasted into chat, tickets or screenshots.

| Credential | Where | Rotation / side effects |
|---|---|---|
| `SECRET_KEY` | Vercel API env | Signs JWTs, MFA challenges and QR tokens, so rotating logs everyone out. **If `LLM_KEY_ENCRYPTION_KEY` is unset, it also decrypts every stored BYO LLM key and every platform admin's TOTP seed.** Set `LLM_KEY_ENCRYPTION_KEY` to the *current* derived material first, or plan to re-enter the keys and re-enroll MFA. |
| `LLM_KEY_ENCRYPTION_KEY` | Vercel | Re-encrypt: decrypt with the old key and save with the new one. There's no command for this yet. |
| Neon DB password (`DATABASE_URL`) | Neon → Roles → Reset password | Update both the pooled and direct URLs in Vercel and CI. |
| Upstash token (`CACHE_URL`) | Upstash console → Reset password | — |
| R2 access key pair | Cloudflare → R2 → API tokens | Create a bucket-scoped token, swap it in, then delete the old one. |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_BEARER_TOKEN_BEDROCK` | AWS IAM / Bedrock | — |
| `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` | Provider consoles | — |
| `STRIPE_SECRET_KEY` (roll), `STRIPE_WEBHOOK_SECRET` (roll endpoint secret) | Stripe dashboard | — |
| `RESEND_API_KEY` / `EMAIL_HOST_PASSWORD` | Resend / SMTP provider | — |
| `CRON_SECRET` | Vercel | — |
| Google OAuth client secret (if one exists in Google Cloud) | Google Cloud console | `GOOGLE_CLIENT_ID` is public. |
| `GOOGLE_CALENDAR_CREDENTIALS` service-account key | Google Cloud IAM | — |
| `SENTRY_DSN` | Sentry | Low sensitivity. It only allows sending events. |
| Platform admin password + TOTP | `create_platform_admin` / `mfa_setup` | — |
| `DEMO_SEED_PASSWORD`, `BOOTSTRAP_PLATFORM_ADMIN_PASSWORD` | Wherever they were set | One-time seed values. Change the resulting account passwords. |
| GitHub deploy keys / Actions secrets | GitHub settings | Only if any repo secret was ever echoed in a workflow log. |

## 6. Verified locally

- Settings boot as before with no env (dev). A Vercel-production boot with a weak `SECRET_KEY` refuses to start. A complete production env boots with SSL redirect, HSTS and `RedisCache`.
- The backend test suite after these changes: see the session report.
