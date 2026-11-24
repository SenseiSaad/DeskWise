"""Regression tests for docs/security/authentication.md (AUTHN-NN)."""
from __future__ import annotations

import time

import pytest
from django.test import Client
from rest_framework.test import APIClient

from core.models import OneTimeToken, User

from .conftest import PASSWORD

pytestmark = pytest.mark.django_db


def _code(secret, offset=0):
    from core.mfa import _code_at
    return _code_at(secret, int(time.time()) // 30 + offset)


def _root(make_company, make_user, enrolled=True):
    from core import mfa
    user = make_user(make_company("Root AUTHN"), email="root@authn.test", role="admin",
                     is_platform_admin=True, is_superuser=True, is_staff=True)
    if enrolled:
        user.mfa_secret = mfa.generate_secret()
        user.mfa_enabled = True
        user.save(update_fields=["mfa_secret", "mfa_enabled"])
    return user


def _login(client, email, password=PASSWORD, ip="10.0.0.1"):
    return client.post("/api/auth/login", {"email": email, "password": password},
                       format="json", REMOTE_ADDR=ip, HTTP_X_FORWARDED_FOR=ip)


# --------------------------------------------------------------- AUTHN-02
def test_authn02_login_lockout_is_per_account_not_per_ip(api, make_company, make_user):
    make_user(make_company("Lock Co"), email="victim@lock.test")
    for i in range(10):
        bad = _login(api, "victim@lock.test", "wrong-password-x", ip=f"10.1.0.{i}")
        assert bad.status_code == 401
    ok_password_new_ip = _login(api, " Victim@Lock.test ", ip="10.9.9.9")
    assert ok_password_new_ip.status_code == 429, "account not locked after 10 failures from many IPs"
    assert "openvault_access" not in ok_password_new_ip.cookies


def test_authn02_unknown_email_is_counted_the_same_way(api):
    for i in range(10):
        assert _login(api, "nobody@lock.test", "x", ip=f"10.2.0.{i}").status_code == 401
    assert _login(api, "nobody@lock.test", "x", ip="10.2.9.9").status_code == 429


def test_authn02_successful_reset_clears_the_lockout(api, make_company, make_user):
    user = make_user(make_company("Lock Reset Co"), email="reset@lock.test")
    for i in range(10):
        _login(api, user.email, "wrong-password-x", ip=f"10.3.0.{i}")
    _, raw = OneTimeToken.issue(user, "password_reset", minutes=30)
    assert api.post("/api/auth/reset-password", {"token": raw, "password": "Fresh!Pass-2026"},
                    format="json").status_code == 200
    assert _login(api, user.email, "Fresh!Pass-2026").status_code == 200


# --------------------------------------------------------------- AUTHN-03
def test_authn03_mfa_verify_challenge_burned_after_five_wrong_codes(api, make_company, make_user):
    user = _root(make_company, make_user)
    challenge = _login(api, user.email).json()["challenge"]
    for _ in range(5):
        wrong = api.post("/api/auth/mfa/verify", {"challenge": challenge, "code": "000000"}, format="json")
        assert wrong.status_code == 400
    right = api.post("/api/auth/mfa/verify", {"challenge": challenge, "code": _code(user.mfa_secret)},
                     format="json")
    assert right.status_code == 400, "challenge still usable after 5 wrong codes"
    assert "openvault_access" not in api.cookies


def test_authn03_mfa_activate_challenge_burned_after_five_wrong_codes(api, make_company, make_user):
    user = _root(make_company, make_user, enrolled=False)
    body = _login(api, user.email).json()
    for _ in range(5):
        api.post("/api/auth/mfa/activate", {"challenge": body["challenge"], "code": "000000"}, format="json")
    right = api.post("/api/auth/mfa/activate",
                     {"challenge": body["challenge"], "code": _code(body["enrollment"]["secret"])},
                     format="json")
    assert right.status_code == 400
    user.refresh_from_db()
    assert user.mfa_enabled is False


# --------------------------------------------------------------- AUTHN-04
def test_authn04_totp_code_cannot_be_replayed(make_company, make_user):
    user = _root(make_company, make_user)
    code = _code(user.mfa_secret)

    first = APIClient()
    ch1 = _login(first, user.email).json()["challenge"]
    assert first.post("/api/auth/mfa/verify", {"challenge": ch1, "code": code}, format="json").status_code == 200

    second = APIClient()
    ch2 = _login(second, user.email).json()["challenge"]
    replay = second.post("/api/auth/mfa/verify", {"challenge": ch2, "code": code}, format="json")
    assert replay.status_code == 400, "the same TOTP code was accepted twice"
    # The next time step is still accepted.
    nxt = second.post("/api/auth/mfa/verify", {"challenge": ch2, "code": _code(user.mfa_secret, 1)},
                      format="json")
    assert nxt.status_code == 200


# --------------------------------------------------------------- AUTHN-05
def test_authn05_reset_invalidates_other_outstanding_reset_links(api, make_company, make_user):
    user = make_user(make_company("Reset Co"), email="u@reset.test")
    _, older = OneTimeToken.issue(user, "password_reset", minutes=30)
    _, newer = OneTimeToken.issue(user, "password_reset", minutes=30)
    assert api.post("/api/auth/reset-password", {"token": newer, "password": "First!Reset-2026"},
                    format="json").status_code == 200
    stale = api.post("/api/auth/reset-password", {"token": older, "password": "Second!Reset-2026"},
                     format="json")
    assert stale.status_code == 400, "an older reset link still worked after a successful reset"
    user.refresh_from_db()
    assert user.check_password("First!Reset-2026")


def test_authn05_consume_is_a_conditional_update(make_company, make_user, monkeypatch):
    user = make_user(make_company("Consume Co"), email="c@consume.test")
    _, raw = OneTimeToken.issue(user, "password_reset", minutes=30)
    # Simulate the race: both requests passed the Python-side validity check
    # before either wrote used_at.
    monkeypatch.setattr(OneTimeToken, "is_valid", lambda self: True)
    assert OneTimeToken.consume(raw, "password_reset") is not None
    assert OneTimeToken.consume(raw, "password_reset") is None, "one token consumed twice"


# --------------------------------------------------------------- AUTHN-06
def test_authn06_logout_kills_the_access_token_immediately(api, register_company):
    register_company(email="admin@logout-authn.test")
    access = api.cookies["openvault_access"].value
    assert api.post("/api/auth/logout", format="json").status_code == 200

    via_cookie = APIClient()
    via_cookie.cookies["openvault_access"] = access
    assert via_cookie.get("/api/auth/me").status_code == 401, "access cookie still valid after logout"
    via_header = APIClient()
    via_header.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    assert via_header.get("/api/auth/me").status_code == 401


def test_authn06_logout_does_not_end_other_sessions(make_company, make_user):
    user = make_user(make_company("Two Devices Co"), email="two@devices.test")
    laptop, phone = APIClient(), APIClient()
    assert _login(laptop, user.email).status_code == 200
    assert _login(phone, user.email, ip="10.0.0.2").status_code == 200
    laptop.post("/api/auth/logout", format="json")
    assert phone.get("/api/auth/me").status_code == 200


# --------------------------------------------------------------- AUTHN-07
def _age_blacklist(seconds=60):
    from datetime import timedelta

    from django.utils import timezone
    from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
    BlacklistedToken.objects.update(blacklisted_at=timezone.now() - timedelta(seconds=seconds))


def test_authn07_reused_refresh_token_revokes_the_session_family(api, register_company):
    register_company(email="admin@reuse-authn.test")
    stolen = api.cookies["openvault_refresh"].value
    assert api.post("/api/auth/refresh", format="json").status_code == 200  # real user rotates
    _age_blacklist()

    thief = APIClient()
    thief.cookies["openvault_refresh"] = stolen
    assert thief.post("/api/auth/refresh", format="json").status_code == 401
    # The reuse revoked everything, including the real user's rotated session.
    assert api.get("/api/auth/me").status_code == 401
    assert api.post("/api/auth/refresh", format="json").status_code == 401, \
        "rotated session survived refresh-token reuse"


def test_authn07_concurrent_refresh_inside_grace_window_is_not_treated_as_theft(api, register_company):
    register_company(email="admin@grace-authn.test")
    old = api.cookies["openvault_refresh"].value
    assert api.post("/api/auth/refresh", format="json").status_code == 200
    other_tab = APIClient()
    other_tab.cookies["openvault_refresh"] = old
    late = other_tab.post("/api/auth/refresh", format="json")
    # 401, but no cookie clearing and no revocation: the browser may already
    # hold the fresh cookies from the first rotation.
    assert late.status_code == 401
    assert "openvault_refresh" not in late.cookies
    assert api.get("/api/auth/me").status_code == 200
    assert api.post("/api/auth/refresh", format="json").status_code == 200


def test_authn07_old_generation_token_after_reset_does_not_revoke_new_login(api, make_company, make_user):
    user = make_user(make_company("Gen Co"), email="gen@authn.test")
    old_device = APIClient()
    _login(old_device, user.email)
    _, raw = OneTimeToken.issue(user, "password_reset", minutes=30)
    api.post("/api/auth/reset-password", {"token": raw, "password": "Gen!Reset-2026x"}, format="json")
    _age_blacklist()
    new_device = APIClient()
    assert _login(new_device, user.email, "Gen!Reset-2026x").status_code == 200
    assert old_device.post("/api/auth/refresh", format="json").status_code == 401
    assert new_device.get("/api/auth/me").status_code == 200


# --------------------------------------------------------------- AUTHN-08
@pytest.mark.parametrize("email", [
    "ceo@\u0430cme.test",          # Cyrillic a
    "ceo@xn--cme-8cd.test",        # its punycode spelling
    "c\u0435o@acme.test",          # Cyrillic e in the local part
])
def test_authn08_register_rejects_non_ascii_and_punycode_emails(api, email):
    resp = api.post("/api/auth/register",
                    {"company_name": "Homograph Co", "email": email, "password": PASSWORD}, format="json")
    assert resp.status_code == 400, resp.content
    assert not User.objects.filter(email__iexact=email).exists()


def test_authn08_admin_invite_rejects_homograph_email(auth_client, make_company, make_user):
    admin = make_user(make_company("Invite Homograph Co"), email="admin@invite-h.test", role="admin")
    resp = auth_client(admin).post("/api/admin/users", {"email": "ceo@\u0430cme.test"}, format="json")
    assert resp.status_code == 400
    assert not User.objects.filter(email="ceo@\u0430cme.test").exists()


def test_authn08_google_sign_in_rejects_homograph_email(api, monkeypatch):
    monkeypatch.setattr("core.views.verify_google_id_token", lambda _c: {
        "sub": "g-homo", "email": "ceo@\u0430cme.test", "email_verified": True,
    })
    resp = api.post("/api/auth/google", {"credential": "x"}, format="json")
    assert resp.status_code in (400, 403)
    assert not User.objects.filter(email="ceo@\u0430cme.test").exists()


def test_authn08_plain_ascii_still_works(api):
    resp = api.post("/api/auth/register",
                    {"company_name": "Ascii Co", "email": "Ceo@Acme-Ascii.test", "password": PASSWORD},
                    format="json")
    assert resp.status_code == 201


# --------------------------------------------------------------- AUTHN-09
def test_authn09_untrusted_origin_is_a_clean_403():
    client = Client(raise_request_exception=False)
    resp = client.post("/api/auth/logout", HTTP_ORIGIN="https://evil.example")
    assert resp.status_code == 403
    assert resp.json()["detail"].startswith("Request blocked")


# --------------------------------------------------------------- AUTHN-01
def _google(monkeypatch, sub, email, name="G User"):
    monkeypatch.setattr("core.views.verify_google_id_token", lambda _c: {
        "sub": sub, "email": email, "email_verified": True, "name": name,
    })


def test_authn01_google_binds_sub_on_first_login_and_refuses_another_sub(api, make_company, make_user,
                                                                       monkeypatch):
    user = make_user(make_company("Sub Co"), email="owner@sub.test")
    _google(monkeypatch, "sub-owner", "owner@sub.test")
    assert APIClient().post("/api/auth/google", {"credential": "x"}, format="json").status_code == 200
    user.refresh_from_db()
    assert user.google_sub == "sub-owner"
    assert user.check_password(PASSWORD), "a verified account keeps its password"

    _google(monkeypatch, "sub-impostor", "owner@sub.test")
    other = APIClient()
    resp = other.post("/api/auth/google", {"credential": "x"}, format="json")
    assert resp.status_code == 403
    assert "openvault_access" not in resp.cookies


def test_authn01_google_signs_in_by_sub_even_after_email_change(api, make_company, make_user, monkeypatch):
    user = make_user(make_company("Rename Co"), email="old@rename.test")
    _google(monkeypatch, "sub-rename", "old@rename.test")
    APIClient().post("/api/auth/google", {"credential": "x"}, format="json")
    _google(monkeypatch, "sub-rename", "new@rename.test")
    c = APIClient()
    assert c.post("/api/auth/google", {"credential": "x"}, format="json").status_code == 200
    assert c.get("/api/auth/me").json()["id"] == user.id
    assert not User.objects.filter(email="new@rename.test").exists()


def test_authn01_google_does_not_reuse_an_unverified_password_account(api, settings, monkeypatch):
    settings.REQUIRE_EMAIL_VERIFICATION = False
    attacker = APIClient()
    pre = attacker.post("/api/auth/register",
                        {"company_name": "Squat Co", "email": "victim@prehijack.test", "password": PASSWORD},
                        format="json")
    assert pre.status_code == 201
    assert attacker.get("/api/auth/me").status_code == 200

    _google(monkeypatch, "sub-victim", "victim@prehijack.test")
    victim = APIClient()
    assert victim.post("/api/auth/google", {"credential": "x"}, format="json").status_code == 200

    squat = User.objects.get(email="victim@prehijack.test")
    assert not squat.has_usable_password(), "attacker's password survived Google linking"
    assert squat.google_sub == "sub-victim"
    # The attacker's existing session and password are both dead.
    assert attacker.get("/api/auth/me").status_code == 401
    assert attacker.post("/api/auth/refresh", format="json").status_code == 401
    assert _login(APIClient(), "victim@prehijack.test").status_code == 401
    assert victim.get("/api/auth/me").status_code == 200


def test_authn01_new_google_user_is_created_with_sub(api, monkeypatch):
    _google(monkeypatch, "sub-new", "fresh@google-new.test")
    assert api.post("/api/auth/google", {"credential": "x"}, format="json").status_code == 201
    assert User.objects.get(email="fresh@google-new.test").google_sub == "sub-new"


# --------------------------------------------------------------- AUTHN-11
def test_authn11_forgot_password_has_a_per_account_cooldown_without_leaking(api, make_company, make_user,
                                                                            mailoutbox):
    user = make_user(make_company("Forgot Co"), email="u@forgot.test")
    bodies = []
    for i in range(4):
        resp = api.post("/api/auth/forgot-password", {"email": user.email}, format="json",
                        REMOTE_ADDR=f"10.7.0.{i}", HTTP_X_FORWARDED_FOR=f"10.7.0.{i}")
        assert resp.status_code == 200
        bodies.append(resp.json())
    missing = api.post("/api/auth/forgot-password", {"email": "nobody@forgot.test"}, format="json")
    assert missing.status_code == 200
    assert len({str(b) for b in bodies + [missing.json()]}) == 1, "response differs for a throttled account"
    assert len(mailoutbox) == 1, "reset email was sent more than once inside the cooldown"
    assert OneTimeToken.objects.filter(user=user, purpose="password_reset").count() == 1


# --------------------------------------------------------------- AUTHN-12
def test_authn12_weak_password_does_not_burn_the_reset_link(api, make_company, make_user):
    user = make_user(make_company("Weak Reset Co"), email="u@weakreset.test")
    _, raw = OneTimeToken.issue(user, "password_reset", minutes=30)
    weak = api.post("/api/auth/reset-password", {"token": raw, "password": "password"}, format="json")
    assert weak.status_code == 400
    ok = api.post("/api/auth/reset-password", {"token": raw, "password": "Strong!Reset-2026"}, format="json")
    assert ok.status_code == 200, "a rejected weak password consumed the reset link"
    again = api.post("/api/auth/reset-password", {"token": raw, "password": "Another!Reset-2026"},
                     format="json")
    assert again.status_code == 400


# --------------------------------------------------------------- AUTHN-13
def _refresh_morsels(resp):
    return [m for m in resp.cookies.values() if m.key == "openvault_refresh"]


def test_authn13_refresh_cookie_is_scoped_to_the_auth_endpoints(api, register_company):
    resp, _ = register_company(email="admin@path-authn.test")
    scoped = [m for m in _refresh_morsels(resp) if m["max-age"] != 0]
    assert [m["path"] for m in scoped] == ["/api/auth/"]
    assert resp.cookies["openvault_access"]["path"] == "/"
    legacy = [m for m in _refresh_morsels(resp) if m["path"] == "/"]
    assert legacy and all(int(m["max-age"]) == 0 for m in legacy), "old path=/ refresh cookie not retired"


def test_authn13_logout_clears_both_refresh_paths(api, register_company):
    register_company(email="admin@path2-authn.test")
    resp = api.post("/api/auth/logout", format="json")
    paths = {m["path"] for m in _refresh_morsels(resp)}
    assert paths == {"/", "/api/auth/"}
    assert all(int(m["max-age"]) == 0 for m in _refresh_morsels(resp))


def test_authn13_refresh_still_rotates_with_the_scoped_cookie(api, register_company):
    register_company(email="admin@path3-authn.test")
    assert api.post("/api/auth/refresh", format="json").status_code == 200
