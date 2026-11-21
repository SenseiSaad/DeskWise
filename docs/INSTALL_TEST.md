# Deskwise Local Install & Smoke Test Report

This document tracks verification of Deskwise's one-command local setup (`scripts/start_local.sh`, `scripts/start_local.ps1`, `Start Deskwise.bat`, `Start Deskwise.command`) and the 3-persona install verifier (`scripts/verify_install`).

---

## 1. Linux Verification (Host: Ubuntu / x86_64)

### 1.1 Preflight diagnostics (`./scripts/start_local.sh doctor`)
**Status:** VERIFIED (PASS)
- Checked Docker CLI & daemon availability, `docker compose` v2, free ports (`3000`, `8000`, `5432`), and available disk space.

### 1.2 Local Hardened API + Demo Seeder + 3-Persona Verifier
**Status:** VERIFIED (PASS)

Executed against a fresh local hardened Django API container (`LLM_PROVIDER=fake`, retrieval-only `--no-ai` mode, ephemeral SQLite DB) seeded via `python3 manage.py seed_plans && python3 manage.py seed_demo_personas`:

1. **3-Persona Story (`./scripts/verify_install --base-url http://127.0.0.1:18000`)**
   ```text
   [PASS] 1/3 Finance manager opened finance_contract.txt (doc #2)
   [PASS] 2/3 Engineering employee denied finance_contract.txt (404 preview + zero search hits)
   [PASS] 3/3 Admin sees both Finance preview (allowed) and Employee denial (denied) in audit log; hash chain verified (5 entries).
   ```
2. **Black-Box ACL Lab (`python3 scripts/acl_lab_live.py --base-url http://127.0.0.1:18000`)**
   ```text
   === Result: 17/17 checks passed ===
   Cleaned 3/3 documents and 2/2 members.
   ```
3. **Audit Chain CLI (`python3 manage.py verify_audit_chain --all`)**
   ```text
   OK    deskwise-demo: 5 entries verified
   OK    acltest-20261121-9d17: 23 entries verified
   All audit chains valid (28 total entries checked).
   ```

### 1.3 PostgreSQL 16 Real-DB Verification (`pgvector/pgvector:pg16`)
**Status:** VERIFIED (PASS)
- Applied migration `0029_permission_hardening_and_audit_v2` against PostgreSQL 16.
- Confirmed PL/pgSQL `BEFORE UPDATE` and `BEFORE DELETE` triggers reject direct SQL tampering on `core_auditlog`.
- Confirmed `SET_NULL` user deletion preserves `actor_id`/`actor_email` and chain validity.
- Confirmed 50 concurrent multi-threaded audit writes serialize cleanly with zero forks (`valid=True, checked=51`).
- Confirmed explicit `AuditLog.purge_for_company()` works via transaction-local `SET LOCAL` and records an `AuditPurgeRecord`.

### 1.4 Full `docker compose up --build` Cold-Start on Fresh Clone
**Status:** `UNVERIFIED` locally (automated in `.github/workflows/ci.yml` job `local-setup-smoke` on `ubuntu-latest`, which runs `./scripts/start_local.sh doctor`, `docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build`, `seed_demo_personas`, `./scripts/verify_install`, and `./scripts/start_local.sh --stop`).
Note: Frontend production build (`pnpm build`) and backend container startup/migrations/seeder/`verify_install` were each verified independently on this Linux host.

---

## 2. Windows 10 / 11 Manual Test Checklist

**Status:** `UNVERIFIED` (no Windows host available in this Linux workspace).

Run on a clean Windows 10/11 machine with Docker Desktop installed:
1. Clone repo and double-click `Start Deskwise.bat` (or run `powershell -ExecutionPolicy Bypass -File scripts/start_local.ps1 doctor`).
2. Confirm `doctor` reports Docker Desktop running and ports `3000`/`8000` free.
3. Run `powershell -ExecutionPolicy Bypass -File scripts/start_local.ps1 --no-ai` (default mode).
4. Confirm browser opens `http://localhost:3000`, retrieval-only banner displays in Chat, and login table prints the 4 demo personas (`admin`, `finance`, `employee`, `viewer` at `@demo.deskwise.local`).
5. Run `python scripts/verify_install --base-url http://127.0.0.1:8000 --password <printed-password>` and verify all 3 checks pass.
6. Test `scripts/start_local.ps1 --stop` and `scripts/start_local.ps1 --reset`.
7. Test optional `--ai gemini` or `--ai ollama` (never Bedrock).

---

## 3. macOS (Apple Silicon & Intel) Manual Test Checklist

**Status:** `UNVERIFIED` (no macOS host available in this Linux workspace).

Run on a clean macOS machine with Docker Desktop (or OrbStack/Colima) installed:
1. Clone repo and double-click `Start Deskwise.command` in Finder (if Gatekeeper prompts, right-click -> Open, or run `chmod +x "Start Deskwise.command" scripts/start_local.sh`).
2. Run `./scripts/start_local.sh doctor` and verify all prerequisites pass.
3. Run `./scripts/start_local.sh` (defaults to `--no-ai` retrieval-only mode).
4. Confirm `http://localhost:3000` loads, demo persona table prints cleanly, and `./scripts/verify_install --base-url http://127.0.0.1:8000` passes 3/3.
5. Verify `./scripts/start_local.sh --stop` cleanly stops containers and `./scripts/start_local.sh --reset` resets demo data cleanly.
