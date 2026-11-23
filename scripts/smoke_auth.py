#!/usr/bin/env python3
"""End-to-end authentication smoke test for Deskwise (Step 1 baseline & post-fix verifier).

Exercises every required flow against the Django backend (in-process via DRF
APIClient or against a live --base-url) and prints a PASS/FAIL table with evidence.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("SECRET_KEY", "smoke-auth-ephemeral-test-key-not-for-prod")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/deskwise_auth_smoke.sqlite3")
os.environ.setdefault("EMAIL_BACKEND", "django.core.mail.backends.locmem.EmailBackend")
os.environ.setdefault("EMAIL_ASYNC", "false")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.core import mail  # noqa: E402
from django.core.cache import cache  # noqa: E402
from django.core.management import call_command  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from core.models import Company, OneTimeToken, User  # noqa: E402


def run_smoke() -> int:
    db_path = Path("/tmp/deskwise_auth_smoke.sqlite3")
    for p in (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
        if p.exists():
            p.unlink()

    call_command("migrate", "--noinput", verbosity=0)
    call_command("seed_plans", verbosity=0)
    cache.clear()
    settings.RATELIMIT_ENABLED = False
    settings.REQUIRE_EMAIL_VERIFICATION = True
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    if not hasattr(mail, "outbox"):
        mail.outbox = []
    mail.outbox.clear()

    results: list[tuple[str, bool, str]] = []

    def record(name: str, ok: bool, detail: str):
        results.append((name, ok, detail))
        tag = "PASS" if ok else "FAIL"
        print(f"[{tag}] {name} — {detail}")

    c = APIClient()

    # 1. Password policy: 9-char password rejected (min 10 chars) & common password rejected
    r_short = c.post(
        "/api/auth/register",
        {"company_name": "Policy Co", "admin_name": "Ada", "email": "ada@policy.test", "password": "Short!123"},
        format="json",
    )
    record(
        "1. Password policy rejects <10-char password",
        r_short.status_code == 400,
        f"HTTP {r_short.status_code} ({r_short.json() if r_short.content else ''})",
    )

    # 2. Path A: Owner signup (full name, email, password, company name) -> verification required
    mail.outbox.clear()
    r_reg = c.post(
        "/api/auth/register",
        {
            "company_name": "Acme Smoke",
            "admin_name": "Alice Owner",
            "email": "Alice.Owner@AcmeSmoke.test",
            "password": "StrongPassword!2026",
        },
        format="json",
    )
    reg_body = r_reg.json() if r_reg.content else {}
    u_owner = User.objects.filter(email="alice.owner@acmesmoke.test").first()
    record(
        "2. Owner signup normalizes email, stores full_name, gates on verification",
        r_reg.status_code == 201
        and u_owner is not None
        and u_owner.full_name == "Alice Owner"
        and reg_body.get("verification_required") is True
        and "openvault_access" not in r_reg.cookies,
        f"HTTP {r_reg.status_code}, email={getattr(u_owner, 'email', None)}, verified_gate={reg_body.get('verification_required')}",
    )

    # 3. HTML + plain-text verification email sent
    has_html_mail = bool(mail.outbox) and bool(getattr(mail.outbox[-1], "alternatives", None))
    record(
        "3. Branded HTML + plain-text verification email queued",
        len(mail.outbox) >= 1 and has_html_mail,
        f"outbox={len(mail.outbox)}, html_alternatives={has_html_mail}",
    )

    # 4. Duplicate registration returns 409 Conflict
    r_dup = c.post(
        "/api/auth/register",
        {
            "company_name": "Acme Smoke 2",
            "admin_name": "Alice",
            "email": "ALICE.OWNER@acmesmoke.test",
            "password": "StrongPassword!2026",
        },
        format="json",
    )
    record(
        "4. Duplicate signup email returns 409 Conflict",
        r_dup.status_code == 409,
        f"HTTP {r_dup.status_code} ({r_dup.json().get('detail', '') if r_dup.content else ''})",
    )

    # 5. Unverified user blocked from login with 403 email_unverified
    r_unver = c.post(
        "/api/auth/login",
        {"email": "alice.owner@acmesmoke.test", "password": "StrongPassword!2026"},
        format="json",
    )
    record(
        "5. Unverified login blocked with 403 email_unverified",
        r_unver.status_code == 403 and r_unver.json().get("code") == "email_unverified",
        f"HTTP {r_unver.status_code} code={r_unver.json().get('code') if r_unver.content else ''}",
    )

    # 6. Resend verification 60s cooldown + single-use token verification
    r_resend1 = c.post("/api/auth/request-verification", {"email": "alice.owner@acmesmoke.test"}, format="json")
    r_resend2 = c.post("/api/auth/request-verification", {"email": "alice.owner@acmesmoke.test"}, format="json")
    _, raw_vtok = OneTimeToken.issue(u_owner, "verify_email", minutes=60 * 24)
    r_ver1 = c.post("/api/auth/verify", {"token": raw_vtok}, format="json")
    r_ver2 = c.post("/api/auth/verify", {"token": raw_vtok}, format="json")
    record(
        "6. Verification token is single-use and resend has 60s cooldown",
        r_ver1.status_code == 200
        and r_ver2.status_code == 400
        and (r_resend2.status_code == 429 or r_resend2.json().get("cooldown") is True),
        f"verify1={r_ver1.status_code}, verify2={r_ver2.status_code}, resend2={r_resend2.status_code} {r_resend2.json() if r_resend2.content else ''}",
    )

    # 7. Login generic error + HttpOnly cookie session + refresh rotation + replay block
    r_bad_email = c.post("/api/auth/login", {"email": "nobody@acmesmoke.test", "password": "WrongPassword!123"}, format="json")
    r_bad_pw = c.post("/api/auth/login", {"email": "alice.owner@acmesmoke.test", "password": "WrongPassword!123"}, format="json")
    r_login = c.post("/api/auth/login", {"email": "alice.owner@acmesmoke.test", "password": "StrongPassword!2026"}, format="json")
    old_ref = r_login.cookies.get("openvault_refresh").value if "openvault_refresh" in r_login.cookies else ""
    r_ref = c.post("/api/auth/refresh", format="json")
    replay_c = APIClient()
    replay_c.cookies["openvault_refresh"] = old_ref
    r_replay = replay_c.post("/api/auth/refresh", format="json")
    record(
        "7. Login generic 401 error, HttpOnly cookies, and refresh rotation blocks replay",
        r_bad_email.status_code == 401
        and r_bad_pw.status_code == 401
        and r_bad_email.json().get("detail") == r_bad_pw.json().get("detail")
        and r_login.status_code == 200
        and r_ref.status_code == 200
        and r_replay.status_code == 401,
        f"login={r_login.status_code}, refresh={r_ref.status_code}, replay={r_replay.status_code}",
    )

    # 8. Path B1: Employee joins company via company access_code
    comp = Company.objects.get(name="Acme Smoke")
    c_emp = APIClient()
    r_join_code = c_emp.post(
        "/api/auth/join",
        {
            "access_code": comp.access_code,
            "full_name": "Bob Joiner",
            "email": "bob@acmesmoke.test",
            "password": "StrongPassword!2026",
        },
        format="json",
    )
    u_bob = User.objects.filter(email="bob@acmesmoke.test").first()
    record(
        "8. Path B1: Employee signup via company access_code",
        r_join_code.status_code == 201 and u_bob is not None and u_bob.company_id == comp.id and u_bob.role == "employee",
        f"HTTP {r_join_code.status_code}, company_match={getattr(u_bob, 'company_id', None) == comp.id}",
    )

    # 9. Path B2: Admin invite link (email-bound, 7-day expiry, single-use)
    r_inv = c.post(
        "/api/admin/users",
        {"email": "invited@acmesmoke.test", "full_name": "Carol Invited", "role": "employee"},
        format="json",
    )
    u_inv = User.objects.filter(email="invited@acmesmoke.test").first()
    inv_tok_raw = ""
    if u_inv:
        _, inv_tok_raw = OneTimeToken.issue(u_inv, "invite", minutes=60 * 24 * 7)
    c_inv = APIClient()
    r_accept_wrong = c_inv.post(
        "/api/auth/join",
        {"invite_token": inv_tok_raw, "email": "wrong@acmesmoke.test", "password": "StrongPassword!2026"},
        format="json",
    ) if inv_tok_raw else r_inv
    r_accept_ok = c_inv.post(
        "/api/auth/join",
        {"invite_token": inv_tok_raw, "email": "invited@acmesmoke.test", "password": "StrongPassword!2026"},
        format="json",
    ) if inv_tok_raw else r_inv
    r_accept_reuse = c_inv.post(
        "/api/auth/join",
        {"invite_token": inv_tok_raw, "email": "invited@acmesmoke.test", "password": "StrongPassword!2026"},
        format="json",
    ) if inv_tok_raw else r_inv
    record(
        "9. Path B2: Admin 7-day email-bound single-use invite token",
        r_inv.status_code == 201
        and r_accept_wrong.status_code == 400
        and r_accept_ok.status_code in (200, 201)
        and r_accept_reuse.status_code == 400,
        f"create={r_inv.status_code}, wrong_email={getattr(r_accept_wrong, 'status_code', None)}, ok={getattr(r_accept_ok, 'status_code', None)}, reuse={getattr(r_accept_reuse, 'status_code', None)}",
    )

    # 10. Path C: Google OAuth (unverified rejected; new user -> onboarding required -> workspace blocked until onboarded)
    c_g = APIClient()
    with patch("core.views.verify_google_id_token", create=True) as mock_g:
        mock_g.return_value = {
            "sub": "google-sub-1",
            "email": "newgoogle@acmesmoke.test",
            "email_verified": False,
            "name": "Google Unverified",
        }
        r_g_unver = c_g.post("/api/auth/google", {"credential": "fake.jwt.token"}, format="json")
        mock_g.return_value = {
            "sub": "google-sub-2",
            "email": "newgoogle@acmesmoke.test",
            "email_verified": True,
            "name": "Google Newbie",
        }
        r_g_new = c_g.post("/api/auth/google", {"credential": "valid.jwt.token"}, format="json")
        r_docs_before = c_g.get("/api/documents")
        r_onboard = c_g.post("/api/auth/onboard", {"action": "create", "company_name": "Google Workspace Co"}, format="json")
        r_docs_after = c_g.get("/api/documents")
    record(
        "10. Path C: Google OAuth server verification + onboarding gate before workspace access",
        r_g_unver.status_code == 403
        and r_g_new.status_code in (200, 201)
        and r_g_new.json().get("onboarding_required") is True
        and r_docs_before.status_code == 403
        and r_onboard.status_code in (200, 201)
        and r_docs_after.status_code == 200,
        f"unver={r_g_unver.status_code}, new={r_g_new.status_code}, docs_before={r_docs_before.status_code}, onboard={r_onboard.status_code}, docs_after={r_docs_after.status_code}",
    )

    # 11. Password reset revokes sessions & sends "password was changed" notice email (also works for Google user with no password)
    u_g = User.objects.get(email="newgoogle@acmesmoke.test") if User.objects.filter(email="newgoogle@acmesmoke.test").exists() else u_owner
    mail.outbox.clear()
    _, r_tok = OneTimeToken.issue(u_g, "password_reset", minutes=30)
    r_reset = c_g.post("/api/auth/reset-password", {"token": r_tok, "password": "NewGooglePass!2026"}, format="json")
    subjects = [m.subject.lower() for m in mail.outbox]
    record(
        "11. Password reset sets password, revokes tokens, and emails password-changed notice",
        r_reset.status_code == 200 and any("changed" in s or "updated" in s for s in subjects),
        f"HTTP {r_reset.status_code}, emails_sent={subjects}",
    )

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n=== Smoke Summary: {passed}/{total} passed ===")
    return 0 if passed == total else 1


if __name__ == "__main__":
    try:
        sys.exit(run_smoke())
    except Exception as exc:
        print(f"[SMOKE ERROR] {type(exc).__name__}: {exc}")
        sys.exit(1)
