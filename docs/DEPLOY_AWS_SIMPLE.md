# Deploying Deskwise on AWS (simplest paid path: Amplify + App Runner + RDS + S3)

This is the hands-off, low-cost AWS path for a live beta. The Terraform suite in
`infra/` is the full enterprise blueprint (ECS Fargate, multi-AZ, ALB); you do
**not** need it for a beta and it costs far more. Use this instead.

Target shape:

| Layer | Service | Why |
|---|---|---|
| Frontend | **AWS Amplify Hosting** | The repo is already configured for it (`next.config.mjs` static export + `pnpm-workspace.yaml` hoisted linker). |
| Backend API | **AWS App Runner** (container from ECR) | Runs the existing `backend/Dockerfile` as-is — ASGI, WebSockets, in-process indexing, no Redis needed at 1 instance. |
| Database | **Amazon RDS for PostgreSQL 16** | Persistent Postgres + `pgvector`. |
| Uploads | **Amazon S3** | App Runner's disk is ephemeral; documents must live in S3. |
| AI | **Google Gemini** | `LLM_PROVIDER=gemini` drives both chat and @DeskWise team chat. |

**Answering your two questions up front:**

* **Do I need to make my GitHub repo public?** No. Amplify and App Runner both
  connect to **private** GitHub repos through an AWS-managed GitHub app
  (Amplify: repository connection; App Runner: a source connection). Keep it
  private.
* **Can I use Elastic Beanstalk instead?** Yes, technically — but it is *more*
  setup here (no push-to-deploy for a private repo without CodePipeline, and you
  still run RDS separately). App Runner runs your existing single container image
  with less wiring, so it is the better fit. See the last section for the EB
  caveat.

App Runner **source-code** deploys are *not* usable for this backend: the
managed Python runtime does not include `tesseract`, `poppler`, `libpq` or
`postgresql-client`, which `backend/Dockerfile` installs. Build the image and
deploy from **ECR**.

## Cost (before AI tokens)

| Item | Est. USD / month |
|---|---:|
| Amplify Hosting | ~$1–3 |
| App Runner (0.25 vCPU / 0.5 GB, 1 instance, light traffic) | ~$5–10 |
| RDS `db.t4g.micro`, 20 GB gp3, single-AZ | ~$13–15 |
| S3 (documents) | ~$1 |
| **Total** | **~$20–30 / month** |

Roughly **$40–60 for two months** — inside your budget. Gemini API usage is
separate and scales with questions asked. You can pause the App Runner service
when nobody is using the beta to save the compute hours.

---

## Step 1 — S3 bucket for uploads

1. S3 → Create bucket (e.g. `deskwise-docs-<something>`), same region as RDS.
2. Keep "Block all public access" **on**. The app uses server-side access only.
3. Note the bucket name and region.

The backend talks to S3 with the **instance role** you attach to App Runner in
Step 4, so no static AWS keys go into any env var.

## Step 2 — RDS PostgreSQL with pgvector

1. RDS → Create database → **PostgreSQL 16**, template **Free tier**.
2. Instance `db.t4g.micro`, 20 GB gp3, **Single-AZ**.
3. **Public access: No.** Put it in the default VPC (or your own), and allow the
   security group that Step 4's VPC connector uses on port 5432.
4. Set a master username/password; store them somewhere safe.
5. After it is available, the database is `postgres`; create a database named
   `openvault` (or use the default). Migrations create the `vector` extension
   for you (the RDS master user has the privilege).

Connection string you will use:
`postgresql://<user>:<password>@<endpoint>:5432/openvault?sslmode=require`

## Step 3 — Build and push the backend image to ECR

```bash
# once
aws ecr create-repository --repository-name deskwise-api --region <region>

# every deploy (from the repo root)
aws ecr get-login-password --region <region> | \
  docker login --username AWS --password-stdin <account-id>.dkr.ecr.<region>.amazonaws.com

docker build -f backend/Dockerfile -t deskwise-api .
docker tag deskwise-api:latest <account-id>.dkr.ecr.<region>.amazonaws.com/deskwise-api:latest
docker push <account-id>.dkr.ecr.<region>.amazonaws.com/deskwise-api:latest
```

The repo also has `.github/workflows/deploy.yml`, which builds and pushes SHA
images with GitHub OIDC — you can adapt it to push this image instead of doing
the manual build.

## Step 4 — App Runner service for the API

1. App Runner → Create service → **Container registry** → Amazon ECR → pick the
   `deskwise-api:latest` image.
2. **Deployment trigger:** Manual (or automatic if you enable it).
3. **Port:** `8000`. **Health check:** HTTP, path `/api/health`
   (`/api/health` is exempt from the HTTPS redirect, so it answers 200 over
   plain HTTP inside the container).
4. **Instance:** 0.25 vCPU / 0.5 GB, min 1 instance.
5. **Instance role:** create a role with S3 access to your bucket
   (`s3:GetObject`,`s3:PutObject`,`s3:DeleteObject`,`s3:HeadObject`,
   `s3:ListBucket`) and CloudWatch Logs write.
6. **VPC connector:** create one in the default VPC using the default (public)
   subnets and attach it. This lets the service reach the private RDS *and*
   still reach the internet for Gemini — the default subnets route out through
   the internet gateway, so you avoid a ~$32/mo NAT gateway.
7. **Environment variables** (see the table below).
8. Deploy. The container entrypoint runs migrations + `seed_plans` on start
   (`AUTO_MIGRATE=true`, the default).

## Step 5 — Frontend on Amplify

1. Amplify → New app → **Host web app** → **GitHub** → authorize AWS's GitHub
   app and pick your **private** repo and branch.
2. Amplify reads the root `amplify.yml` (already added), which builds the
   `frontend` app and publishes the `out/` static export.
3. **Environment variables** (App settings → Environment variables):
   * `NEXT_PUBLIC_API_URL` = your App Runner service URL (`https://...`)
   * `NEXT_PUBLIC_BETA_PROVIDER` = `gemini` (omit or set `off` to re-enable every provider)
4. **Node version:** 22 (App settings → Build image settings).
5. Deploy, then note your Amplify domain (e.g. `https://main.xxxx.amplifyapp.com`).

## Step 6 — Close the loop (CORS/CSRF/hosts)

Set these App Runner env vars to the values from Step 5 and redeploy the API so
the browser is allowed to call it:

```
ALLOWED_HOSTS=<apprunner-host>,<your-api-domain>
CORS_ALLOWED_ORIGINS=https://<amplify-domain>
CSRF_TRUSTED_ORIGINS=https://<amplify-domain>
PUBLIC_BASE_URL=https://<amplify-domain>
```

Then open the Amplify URL, register a company, upload a document, and ask a
question. Indexing runs in-process (no Celery/Redis needed at one instance).

---

## App Runner environment variables

| Variable | Value | Notes |
|---|---|---|
| `ENVIRONMENT` | `production` | Enables strict cookies/headers. |
| `DEBUG` | `false` | |
| `SECRET_KEY` | 50+ random chars | `python -c "import secrets;print(secrets.token_urlsafe(50))"` |
| `LLM_KEY_ENCRYPTION_KEY` | a separate random key | Back it up; losing it orphans stored BYO keys. |
| `ALLOWED_HOSTS` | App Runner host + API domain | |
| `CORS_ALLOWED_ORIGINS` | `https://<amplify-domain>` | |
| `CSRF_TRUSTED_ORIGINS` | `https://<amplify-domain>` | |
| `PUBLIC_BASE_URL` | `https://<amplify-domain>` | |
| `DATABASE_URL` | `postgresql://...?...sslmode=require` | From Step 2. |
| `AWS_STORAGE_BUCKET_NAME` | your bucket | Enables S3 storage. |
| `AWS_S3_REGION_NAME` | your region | |
| `LLM_PROVIDER` | `gemini` | Drives chat **and** team chat. |
| `GEMINI_API_KEY` | your Google AI Studio key | Platform-wide key. |
| `EMBED_PROVIDER` | `gemini` | Gemini embeddings for retrieval. |
| `EMBED_DIM` | `3072` | **Required**: `gemini-embedding-001` returns 3072-dim vectors; the DB vector column is sized from this at migration time. |
| `AUTO_MIGRATE` | `true` | Default; runs migrations + seed_plans on boot. |
| `EMAIL_BACKEND` | console (leave blank) or SMTP | Set SES vars only if you want verification emails. |

> If you ever switch embeddings, set `EMBED_DIM` to the new provider's
> dimension, recreate the vector column, and run
> `manage.py reindex_embeddings --all`.

## Gemini data-use note (what to tell users)

On Gemini's **free tier**, Google may use prompts and uploaded content to improve
its products, and human reviewers may see it. On the **paid tier**, Google does
not. This is surfaced in the app during the beta. Confirm Google's current
Gemini API terms before uploading confidential material, and prefer the paid
tier for production.

## Elastic Beanstalk (if you prefer it)

EB runs the same `backend/Dockerfile` via a `Docker` platform single-instance
environment (use `Dockerrun.aws.json` and the EB CLI, or CodePipeline for
private-repo push-to-deploy). You still create RDS and S3 separately, you add
`.ebextensions` for env vars, and there is no push-from-GitHub for a private
repo without CodePipeline. It is ~$8–12/mo for the instance plus the same RDS
cost, and more wiring than App Runner. If you want EB anyway, this guide's
Steps 1, 2 and 6 are unchanged; replace Step 4 with an EB environment.

## Cheapest possible alternative

If the budget gets tighter, one small EC2 instance (t4g.small) running the
shipped `docker-compose.prod.yml` gives you Postgres + Redis + API + Caddy TLS
on one persistent disk for ~$12–15/mo, with no S3 or VPC connector needed. It is
the least "managed", but it is the simplest thing that works and is what
`docs/DEPLOY.md` documents.
