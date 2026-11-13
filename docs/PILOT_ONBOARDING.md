# Deskwise — Single-Server Pilot Customer Onboarding & Operations Guide

This guide describes how to deploy **Deskwise** on a single low-cost virtual private server ($20–$40/mo on Hetzner, DigitalOcean, or AWS EC2) using `docker-compose.prod.yml`, configure automated HTTPS and backups, and onboard a pilot enterprise customer.

---

## 1. Architecture on Single-Host Production

```
                                  Internet
                                     │
                                     ▼
                     ┌───────────────────────────────┐
                     │      Caddy 2 Reverse Proxy    │ (Ports 80 & 443, Auto-TLS)
                     └───────────────┬───────────────┘
                                     │
                  ┌──────────────────┴──────────────────┐
                  ▼                                     ▼
     ┌────────────────────────┐            ┌────────────────────────┐
     │   Next.js 16 Web UI    │            │     Django 5.1 API     │
     │      (Port 3000)       │            │  (Gunicorn, Port 8000) │
     └────────────────────────┘            └────────────┬───────────┘
                                                        │
                      ┌─────────────────────────────────┴─────────────────┐
                      ▼                                                   ▼
       ┌──────────────────────────────┐                   ┌──────────────────────────────┐
       │   PostgreSQL 16 + pgvector   │                   │        Redis 7 Cache         │
       │    (HNSW Vector Indexing)    │                   │   (Rate limits & Sessions)   │
       └──────────────────────────────┘                   └──────────────────────────────┘
```

---

## 2. Server Provisioning & DNS Prerequisites

1. **Hardware Recommendation:**
   * 2–4 vCPU, 4–8 GB RAM, 40+ GB SSD (e.g. Hetzner CX22/CX32 or DigitalOcean Droplet).
   * OS: Ubuntu 22.04 LTS or 24.04 LTS.
2. **DNS Setup:**
   * Create an `A` record for your application domain (e.g., `app.pilotclient.com`) pointing to the server's public IPv4 address.
   * Verify DNS propagation before starting Caddy:
     ```bash
     dig +short A app.pilotclient.com
     ```
3. **Firewall / Security Group:**
   * Inbound ports open: `22` (SSH), `80` (HTTP for ACME challenges), `443` (HTTPS).

---

## 3. Server Setup & Launch Sequence

```bash
# 1. Install Docker & Compose Plugin
sudo apt-get update && sudo apt-get install -y ca-certificates curl gnupg
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker $USER

# 2. Clone Repository
git clone <repository_url> /opt/deskwise
cd /opt/deskwise

# 3. Configure Production Environment File
cp .env.production.example .env.production
nano .env.production
```

### Production `.env.production` Minimal Template:
```bash
DOMAIN=app.pilotclient.com
ENVIRONMENT=production
DEBUG=false
SECRET_KEY=<generate_with_openssl_rand_hex_32>
POSTGRES_PASSWORD=<generate_with_openssl_rand_hex_24>
CORS_ALLOWED_ORIGINS=https://app.pilotclient.com
ALLOWED_HOSTS=app.pilotclient.com,localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=https://app.pilotclient.com
PUBLIC_BASE_URL=https://app.pilotclient.com

# LLM: Set your model provider (e.g. Gemini, OpenAI, Anthropic, or Ollama)
LLM_PROVIDER=gemini
GEMINI_API_KEY=<your_api_key>
GEMINI_MODEL=gemini-2.5-flash
```

```bash
# 4. Launch the Production Stack
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

---

## 4. Automated Nightly Backup Cron Setup

Create an automated backup script that dumps the PostgreSQL database with vector embeddings and compresses it:

```bash
sudo mkdir -p /var/backups/deskwise
sudo chmod 700 /var/backups/deskwise

# Add cron job to backup daily at 02:00 AM and prune backups older than 14 days
(crontab -l 2>/dev/null; echo "0 2 * * * docker compose -f /opt/deskwise/docker-compose.prod.yml --env-file /opt/deskwise/.env.production exec -T db pg_dump -U openvault openvault | gzip > /var/backups/deskwise/backup_\$(date +\%F).sql.gz && find /var/backups/deskwise -name '*.sql.gz' -mtime +14 -delete") | crontab -
```

---

## 5. Pilot Customer Onboarding Checklist (Step-by-Step)

- [ ] **Step 1: Verify Stack Health**
  ```bash
  curl -I https://app.pilotclient.com/api/health
  # Should return HTTP 200 with {"database": "ready", "status": "healthy"}
  ```
- [ ] **Step 2: Create Pilot Company & First Admin Account**
  Navigate to `https://app.pilotclient.com/enterprise?role=admin` in the browser, click **Create an organization**, enter the client's company name (e.g. `Acme Corp`), and enter the primary client admin's email and password.
- [ ] **Step 3: Retrieve and Record the Company Access Code**
  On the workspace overview page (`/workspace`), record the 8-character company access code (e.g. `K9X2M4LQ`). Provide this code to the client admin for any cross-organization sharing.
- [ ] **Step 4: Seed Initial Knowledge Base (Upload & Index)**
  * Navigate to `/workspace/documents`.
  * Upload 3–5 representative pilot policy documents (PDF, DOCX, or TXT).
  * Confirm all documents show the green `ready` badge and chunk counts are greater than 0.
- [ ] **Step 5: Run Verification Queries in Chat**
  * Navigate to `/workspace/chat`.
  * Ask 2 specific factual questions covered in the uploaded documents.
  * Verify the answer correctly cites the source document and displays the citation tag.
- [ ] **Step 6: Invite Pilot Teammates**
  * In `/workspace/members`, invite 3 pilot team members with appropriate roles (`Editor` or `Employee`).
  * Verify invited employees receive their credentials and can log in at `https://app.pilotclient.com/enterprise?role=employee`.
- [ ] **Step 7: Verify Attendance Tracking (Optional Feature)**
  * Instruct one employee to visit `/workspace/attendance` and click **Mark me present**.
  * Confirm attendance logs reflect the check-in immediately.

---

## 6. Verification Status: What Was Tested vs What Could Not Be Tested

### Tested & Verified Locally:
* `docker-compose.prod.yml` configuration and environment interpolation (100% valid).
* Multi-container orchestration: PostgreSQL 16 + pgvector, Redis 7, Gunicorn API, and Next.js Web containers build and pass healthchecks.
* Automated database migration and vector table creation on container startup.
* End-to-end browser walkthrough (~50 actions) covering the exact UI flows pilot customers will experience.

### Could Not Be Tested Without Live Production Infrastructure:
* **Live Let's Encrypt TLS Certificate Issuance:** Caddy's automated ACME HTTP-01 challenge requires a publicly accessible IPv4 address with public DNS delegation. (Locally, self-signed certificates or plain HTTP were used).
* **Live Transactional Email Sending:** Requires actual AWS SES SMTP credentials or an external SMTP provider. (The default fallback outputs emails to Docker logs).
