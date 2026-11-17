# Deskwise — Complete Technical Handover, Architecture & Operations Guide

**System:** Deskwise (formerly OpenVault)  
**Version:** 0.1.0-release  
**Primary Architect & Owner:** Saad Waseem (`obsks23@gmail.com`)  
**Target Audience:** Acquiring Engineering Team, CTO, and Lead DevOps Engineers

---

## 1. System Architecture

Deskwise is a multi-tenant enterprise RAG (Retrieval-Augmented Generation) knowledge base, team directory, and document workflow automation platform.

```
                         Internet / Corporate VPN
                                    │
                                    ▼
                     ┌─────────────────────────────┐
                     │     Caddy 2 Reverse Proxy   │ (Auto-HTTPS, HTTP/2)
                     └──────────────┬──────────────┘
                                    │
                  ┌─────────────────┴─────────────────┐
                  ▼                                   ▼
    ┌───────────────────────────┐       ┌───────────────────────────┐
    │    Next.js 16 Frontend    │       │     Django 5.1/5.2 API    │
    │  (React 19, Turbopack,    │       │  (DRF, Gunicorn, Celery)  │
    │   Tailwind CSS, Lucide)   │       │                           │
    └───────────────────────────┘       └─────────────┬─────────────┘
                                                      │
                     ┌────────────────────────────────┼────────────────────────────────┐
                     ▼                                ▼                                ▼
       ┌───────────────────────────┐    ┌───────────────────────────┐    ┌───────────────────────────┐
       │   PostgreSQL 16 Database  │    │       Redis 7 Cache       │    │     LLM Inference Hub     │
       │   (pgvector HNSW index,   │    │   (Rate limits, Celery,   │    │  (AWS Bedrock, Anthropic, │
       │    tenant-isolated schema)│    │    shared session cache)  │    │   Gemini, Ollama, BYO)    │
       └───────────────────────────┘    └───────────────────────────┘    └───────────────────────────┘
```

### Key Technical Decisions:
1. **Dual Database Architecture:**
   * **Development:** Zero-config SQLite database (`SQLITE_PATH=/app/data/db.sqlite3`) with in-memory NumPy cosine similarity fallback.
   * **Production:** PostgreSQL 16 with native `pgvector` HNSW vector indexes (`vector(1024)`) and sub-millisecond similarity queries.
2. **Dual Cache & Rate Limiting:**
   * **Development:** Django LocMem cache.
   * **Production:** Redis 7 with sliding-window IP and tenant rate limiting.
3. **Stateless Media Storage:**
   * Local volume storage (`/app/media`) or Amazon S3 with SSE-KMS and presigned PUT URLs for direct browser uploads.

---

## 2. Complete Environment Variables Catalog

| Variable | Required | Default | Purpose & Description |
|---|:---:|---|---|
| `SECRET_KEY` | **Yes** | *(None)* | Django primary cryptographic key (session signing, CSRF, and base secret for LLM key derivation). Must be 50+ random chars. |
| `ENVIRONMENT` | No | `development` | `development` or `production`. Controls strict security headers and cookie flags. |
| `DEBUG` | No | `false` | Must always be `false` in production. |
| `ALLOWED_HOSTS` | **Yes** | `localhost,127.0.0.1` | Comma-separated list of valid domain names for the API. |
| `CORS_ALLOWED_ORIGINS`| **Yes** | `http://localhost:3000` | Frontend web origin(s) allowed to make credentialed API requests. |
| `CSRF_TRUSTED_ORIGINS`| No | *(Empty)* | Trusted origins for state-changing browser requests (e.g. `https://app.deskwise.co`). |
| `PUBLIC_BASE_URL` | No | `http://localhost:3000` | Base public URL used for email verification links and Stripe redirect callbacks. |
| `DATABASE_URL` | No | *(None)* | PostgreSQL connection string (e.g. `postgres://user:pass@host:5432/deskwise`). When unset, falls back to SQLite. |
| `CACHE_URL` | No | *(None)* | Redis connection string (e.g. `redis://redis:6379/0`). When unset, falls back to LocMem. |
| `LLM_PROVIDER` | No | `ollama` | Default platform chat LLM: `ollama`, `gemini`, `anthropic`, `bedrock`, `selfhosted`, `fake`. |
| `LLM_KEY_ENCRYPTION_KEY` | No | *(Derived)* | Fernet encryption key used to encrypt BYO LLM keys at rest. When unset, derived from `SECRET_KEY`. |
| `GEMINI_API_KEY` | No | *(Empty)* | Platform Google Gemini API key. |
| `GEMINI_MODEL` | No | `gemini-2.5-flash`| Gemini model name. |
| `ANTHROPIC_API_KEY` | No | *(Empty)* | Platform Anthropic Claude API key. |
| `ANTHROPIC_MODEL` | No | `claude-3-5-haiku-latest` | Claude model name. |
| `BEDROCK_REGION` | No | `ap-south-1` | AWS region for Bedrock inference. |
| `BEDROCK_MODEL` | No | `in.anthropic.claude-3-5-haiku-20241022-v1:0` | AWS Bedrock inference profile ARN. |
| `STRIPE_SECRET_KEY` | No | *(Empty)* | Stripe API secret key (`sk_live_...` or `sk_test_...`). |
| `STRIPE_WEBHOOK_SECRET`| No | *(Empty)* | Stripe webhook signing secret (`whsec_...`). |
| `EMAIL_BACKEND` | No | `console` | `django.core.mail.backends.smtp.EmailBackend` or console. |
| `EMAIL_HOST` | No | *(Empty)* | SMTP host (e.g., `email-smtp.us-east-1.amazonaws.com` for AWS SES). |
| `EMAIL_PORT` | No | `587` | SMTP port (587 for STARTTLS). |
| `EMAIL_HOST_USER` | No | *(Empty)* | SMTP username / SES IAM access key. |
| `EMAIL_HOST_PASSWORD`| No | *(Empty)* | SMTP password / SES secret key. |
| `EMAIL_USE_TLS` | No | `true` | Enable STARTTLS. |
| `DEFAULT_FROM_EMAIL`| No | `Deskwise <no-reply@deskwise.co>` | Sender address for system emails. |
| `SENTRY_DSN` | No | *(Empty)* | Sentry error reporting DSN. |
| `AWS_STORAGE_BUCKET_NAME`| No | *(Empty)* | S3 bucket for uploaded files. When unset, files save to local disk. |
| `NEXT_PUBLIC_API_URL` | **Yes** | `http://localhost:8000` | Backend API URL reachable by the client's browser. |

---

## 3. Required Third-Party Accounts Runbook

1. **AWS Bedrock & SES (Optional for Cloud AI & Emails):**
   * **Bedrock:** Request model access in the AWS Console for Anthropic Claude 3.5 Haiku. Assign the `bedrock:InvokeModelWithResponseStream` IAM permission to the ECS execution role.
   * **SES:** Verify sending domain in AWS SES; create SMTP credentials in SES Console; set `EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD`.
2. **Stripe (Optional for Self-Serve Subscriptions):**
   * Register on Stripe; enable Customer Portal in Settings -> Billing -> Customer Portal.
   * Create Products & Prices for Go ($19/mo) and Plus ($49/mo).
   * Configure Webhook endpoint pointing to `https://<domain>/api/billing/webhook` listening for `checkout.session.completed`, `customer.subscription.deleted`, `customer.subscription.updated`.
3. **Google Calendar Sync (Optional):**
   * In Google Cloud Console, create OAuth 2.0 Credentials; enable Google Calendar API.
4. **Sentry (Optional):**
   * Create a Python (Django) project in Sentry; add `SENTRY_DSN` to `.env`.

---

## 4. Operational Runbooks

### 4.1 Secret Rotation
* **`SECRET_KEY`:** Follow the zero-downtime rotation guide in [`docs/SECURITY.md`](SECURITY.md#13-safe-secret-rotation-runbook-zero-downtime-re-encryption).
* **Database Password:** Update in PostgreSQL (`ALTER USER openvault WITH PASSWORD 'newpass';`), then update `DATABASE_URL` in `.env` and restart containers.
* **Stripe Secrets:** Rotate in Stripe Dashboard -> Developers -> API Keys; update `STRIPE_SECRET_KEY` in `.env`.

### 4.2 Database Migrations
Migrations run automatically on container startup via `docker-entrypoint.sh`. To run them manually:
```bash
docker compose exec api python manage.py migrate
```

### 4.3 Reindexing Vector Embeddings
If you switch embedding models (e.g. from local nomic-embed to Bedrock Titan):
```bash
docker compose exec api python manage.py reindex_embeddings
```

### 4.4 Backup & Restore
* **PostgreSQL Backup:**
  ```bash
  docker compose exec -T db pg_dump -U openvault openvault | gzip > backups/deskwise_$(date +%F).sql.gz
  ```
* **PostgreSQL Restore:**
  ```bash
  gunzip -c backups/deskwise_YYYY-MM-DD.sql.gz | docker compose exec -T db psql -U openvault openvault
  ```
* **SQLite Backup:**
  ```bash
  sqlite3 data/db.sqlite3 ".backup backups/deskwise_sqlite_$(date +%F).db"
  ```

---

## 5. Deployment Options

### 5.1 Single-Server Production Deployment (Docker Compose)
Best suited for small-to-medium teams (< 5,000 users) on a single $20-40/mo VPS (Hetzner, DigitalOcean, AWS EC2):
* Uses `docker-compose.prod.yml`.
* Bundles PostgreSQL 16 + pgvector, Redis 7, Gunicorn API, Next.js Web, and automated Caddy HTTPS.
* Complete step-by-step onboarding guide in [`docs/DEPLOY.md`](DEPLOY.md).

### 5.2 Enterprise Cloud Deployment (AWS ECS Fargate + RDS)
For enterprise acquirers requiring autoscaling and multi-AZ resilience:
* Infrastructure defined in `infra/` (~3,900 lines of modular Terraform).
* VPC, private subnets, ECS Fargate, RDS PostgreSQL Multi-AZ with pgvector, ElastiCache Redis, ALB, and CloudWatch alarms.
* Validated with Checkov (258 security checks passed).

---

## 6. What is Verified vs What is Not (Brutally Honest Diligence)

| Subsystem / Capability | Verification Status | Exact Evidence & Details |
|---|:---:|---|
| **Unit & Regression Tests** | **VERIFIED (PASS)** | 293 automated backend tests passing (`pytest`, 14 skipped); 20 frontend tests passing (`vitest`). |
| **Tenant Isolation Matrix** | **VERIFIED (PASS)** | 18-case pytest matrix testing IDOR, cross-tenant chunk leakage, rating isolation, and path traversal (`test_tenant_isolation_matrix.py`). |
| **Browser E2E Verification** | **VERIFIED (PASS)** | Automated Playwright suite testing ~50 user actions across Overview, Members, Documents, Chat, Attendance, Shared, Audit, Usage, and Settings. |
| **Local Docker Stack** | **VERIFIED (PASS)** | `docker-compose.yml` builds cleanly; web (port 3000) and api (port 8000) containers healthy. |
| **Single-Host Prod Docker** | **VERIFIED (PASS)** | `docker-compose.prod.yml` configured with Postgres 16, pgvector, Redis, and Caddy TLS. |
| **Vector Search (pgvector)** | **VERIFIED (PASS)** | HNSW index migration and KNN query paths verified (`test_pgvector.py`); SQLite fallback verified. |
| **Code Authorship** | **VERIFIED (PASS)** | 100% of Git commits authored by Saad Waseem (`obsks23@gmail.com`). 0 co-authors. Clean title. |
| **Secrets in Git History** | **VERIFIED (PASS)** | History scrubbed (Option A: 95 commits). Gitleaks scan reports 0 leaks across full history. |
| **Dependency Licenses** | **VERIFIED (PASS)** | 0 GPL, 0 AGPL, 0 SSPL in production dependencies. 2 weak-copyleft LGPL packages documented. |
| **AWS Terraform Deployment** | **UNVERIFIED (CONFIG ONLY)** | Terraform validates (`terraform validate` PASS) and Checkov passes, but has **never been applied to live AWS**. Buyer must provision AWS account. |
| **Live AWS Bedrock / SES** | **UNVERIFIED (CONFIG ONLY)** | Bedrock ARNs and SES SMTP configs are implemented with graceful fallbacks (local Ollama and console email), but have not been tested against a live AWS bill. |
| **Live Stripe Webhooks** | **VERIFIED IN TEST MODE** | Unit tests and mock webhooks pass (`test_billing.py`); live production Stripe charges not processed. |
| **Customer Scale / Revenue** | **HONEST REALITY** | Zero paying customers. All demo company files (`demo_docs/`) are synthetic fixtures. Asking price reflects software asset IP value, not ARR. |
