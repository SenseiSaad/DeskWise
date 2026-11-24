# Engineering & IT Security Standard Operating Procedure (SOP)

**Company:** Northstar Cloud Labs  
**Audience:** Engineering Department · Internal clearance  
**Owner:** Head of Engineering (`eng-lead@northstarlabs.io`)  
**Version:** 2.1 (2026)

---

## 1. Access & Device Security
1. **Mandatory 2FA:** Every engineer must enable hardware key or TOTP 2FA on GitHub, AWS/Cloudflare, Neon, Vercel, and Google Workspace within 24 hours of joining.
2. **Laptop encryption:** Full-disk encryption (FileVault on macOS, LUKS on Linux, BitLocker on Windows) and automatic screen lock after **5 minutes** of idle time are mandatory.
3. **Secrets rule:** Never commit `.env` files, API keys, customer tokens, or database URLs into Git or paste them into Slack/tickets. Rotate any exposed credential within **15 minutes**.

## 2. Pull Requests & Production Deployments
- Every pull request to `main` requires:
  1. All automated CI checks green (`pytest`, `tsc`, `vitest`, secret scan).
  2. At least **1 peer review approval** from another engineer.
- **Deploy window:** Standard production deploys run **Monday–Thursday between 11:00 AM and 5:00 PM PKT**.
- **No Friday deploys** after 2:00 PM PKT without explicit CTO sign-off (hotfixes excluded).
- Database migrations must be backward-compatible with the currently running container revision.

## 3. Incident Response (SEV-1 / SEV-2)
- **SEV-1 (Production down or security issue):** Page the on-call lead immediately (`+92-300-5550199`), open an `#incident-war-room` thread, and post status updates every **20 minutes**.
- **Post-mortem:** Write a blameless 1-page post-mortem within **48 hours** of resolution.
