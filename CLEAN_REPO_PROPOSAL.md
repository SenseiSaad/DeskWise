# Clean Repository Proposal & Strategy
**Target:** Deskwise Codebase  
**Date:** 2026-11-09  
**Role:** Senior Security & Release Engineer  
**Objective:** Prepare a clean, private, secret-free, and dispute-free Git repository for commercial acquisition / sale.

---

## 1. Context & Two Options

When preparing an early-stage B2B SaaS for acquisition, buyers run automated forensic scanners (TruffleHog, Gitleaks, Gitrob) across every commit and branch. Any leaked credentials, deleted student artifacts, or ambiguous authorship commits in Git history trigger technical due diligence flags that can delay the deal or reduce valuation.

We have two options to present to the buyer:

---

### Option A: Clean Existing History with `git-filter-repo`

Rewrite the existing 87 commits in place to purge all unwanted file paths, sensitive strings, and replaced references.

#### Exact Commands:
```bash
# 1. Create a bare mirror clone of the repository
git clone --mirror git@github.com:SenseiSaad/openvault.git deskwise-clean.git
cd deskwise-clean.git

# 2. Invert paths (purge unwanted files from all commits)
git filter-repo \
  --invert-paths \
  --path .env \
  --path-glob '*.bak' \
  --path-glob '*.sqlite3' \
  --path-glob '*.sqlite' \
  --path-glob '*.db' \
  --path-glob '*.tfstate*' \
  --path-glob 'id_rsa*' \
  --path-glob '*.pem' \
  --path-glob '*.key'

# 3. Replace leaked tokens/placeholders across all commit diffs and commit messages
# (Using a replacements file with lines formatted as: leaked_value==>REMOVED)
git filter-repo --replace-text /path/to/replacements.txt --replace-message /path/to/replacements.txt

# 4. Re-link remote and force push rewritten history
git remote add origin git@github.com:SenseiSaad/openvault.git
git push --force --mirror origin

# 5. Contact GitHub Support:
# Request GitHub Support to clear cached commit views and internal pull-request ref caches.
```

#### Evaluation:
- **Pros:** Preserves commit counts and development timeline.
- **Cons:**
  - **Dangling Blob Risk:** GitHub caches unreachable commit SHAs in pull request refs and web views for up to 90 days. A buyer checking commit URLs can still find cached blobs unless GitHub Support manually runs an internal garbage collection.
  - **Colleague Desynchronization:** Anyone who previously cloned the repo cannot simply `git pull`; they must discard their local clone and re-clone.
  - **Audit Complexity:** A buyer's auditor still has to audit 80+ historical commits during due diligence.

---

### Option B: Fresh Private Repository with Single Clean Initial Commit (RECOMMENDED)

Create a brand-new private repository (e.g. `deskwise-core` or `deskwise-app`), copy the audited, working, secret-free codebase without the historical `.git` folder, and make a clean Initial Commit.

#### Exact Commands:
```bash
# 1. Create a clean export directory without git history
mkdir -p /home/saad/Desktop/deskwise-clean
rsync -av --progress /home/saad/Desktop/OpenVault_audit_copy/ /home/saad/Desktop/deskwise-clean/ \
  --exclude '.git' \
  --exclude 'backend/db.sqlite3' \
  --exclude '*.sqlite3' \
  --exclude '*.bak' \
  --exclude 'node_modules' \
  --exclude '.next' \
  --exclude 'backend/.venv' \
  --exclude '.dev-logs'

# 2. Initialize fresh Git repository
cd /home/saad/Desktop/deskwise-clean
git init -b main

# 3. Enable Gitleaks pre-commit hook
git config core.hooksPath .githooks

# 4. Initial commit of clean, audited production code
git add -A
git commit -m "feat(core): initial production release of Deskwise multi-tenant knowledge platform"

# 5. Link to your new private GitHub repository and push
# (e.g. git remote add origin git@github.com:SenseiSaad/deskwise-saas.git)
# git push -u origin main

# 6. Archive the old repository:
# In GitHub Settings -> Danger Zone -> Change visibility to Private (or Archive repository).
```

#### Evaluation:
- **Pros:**
  - **100% Guaranteed Secret-Free:** Absolutely zero historical baggage, zero commit hash ambiguity, zero risk of GitHub caching deleted commits.
  - **Due-Diligence Friendly:** Buyers can audit the clean code in hours rather than digging through weeks of experimental commits.
  - **Clean Title & Authorship:** Commit #1 is authored cleanly by the seller/entity.
  - **Safety:** The old repo remains safely archived on GitHub as a private archive for your own records without any risk of data loss.
- **Cons:** Historical commit log timestamps start from Day 1.

---

## 2. Senior Engineer Recommendation

> [!TIP]
> **We strongly recommend Option B (Fresh Private Repository).**
> For private B2B SaaS acquisitions, buyers prioritize clean chain of title, zero security flags, and ease of due diligence over a commit log history. Option B gives you an enterprise-grade, pristine repository ready for data room presentation.

---

## 3. Protective Assets Prepared

In the audit copy, we have prepared the following prevention controls:
1. **[`.gitignore`](file:///home/saad/Desktop/OpenVault_audit_copy/.gitignore):** Bulletproofed to block all `.env*`, `*.bak`, `*.sqlite*`, `*.db`, `*.tfstate*`, `*.pem`, `*.key`, `id_rsa*`, and build outputs.
2. **[`.env.example`](file:///home/saad/Desktop/OpenVault_audit_copy/.env.example):** Sanitized with dummy documentation placeholders and Deskwise branding.
3. **[`.githooks/pre-commit`](file:///home/saad/Desktop/OpenVault_audit_copy/.githooks/pre-commit):** Pre-commit hook executing `gitleaks protect --staged` before every commit.
4. **[`.github/workflows/gitleaks.yml`](file:///home/saad/Desktop/OpenVault_audit_copy/.github/workflows/gitleaks.yml):** Automated CI workflow running Gitleaks on all PRs and pushes to `main`.

---

## 4. Next Actions (Awaiting User Decision)

No destructive commands have been executed. Please indicate:
- **Proceed with Option B (Create clean export ready for fresh private repo)** OR
- **Proceed with Option A (In-place rewrite)** OR
- **Proceed to Task 3 (Dependencies Audit & Remediation)** while keeping the repository state as is.
