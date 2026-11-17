"""Authentication: registration, HttpOnly cookies, refresh rotation, logout."""
import pytest
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken, OutstandingToken,
)

from core.models import Company, User

from .conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_register_creates_tenant_and_sets_httponly_cookies(api, register_company):
    resp, _payload = register_company(name="Acme Corp", email="admin@acme.test")
    assert resp.status_code == 201

    company = Company.objects.get(name="Acme Corp")
    admin = User.objects.get(email="admin@acme.test")
    assert admin.company_id == company.id
    assert admin.role == "admin"
    assert company.access_code and len(company.access_code) == 8

    access = resp.cookies["openvault_access"]
    refresh = resp.cookies["openvault_refresh"]
    assert access["httponly"] is True
    assert refresh["httponly"] is True
    assert access["samesite"] == "Lax"
    # Raw tokens only ever live in HttpOnly cookies, never in the JSON body.
    body = resp.content.decode()
    assert access.value not in body
    assert refresh.value not in body
    assert "token" not in resp.json()
    assert "password" not in resp.json()["user"]


def test_me_works_with_cookie_session_and_fails_after_logout(api, register_company):
    register_company(email="admin@acme.test")
    assert api.get("/api/auth/me").status_code == 200
    assert api.post("/api/auth/logout", format="json").status_code == 200
    assert api.get("/api/auth/me").status_code == 401


def test_login_rejects_bad_password(api, register_company):
    register_company(email="admin@acme.test")
    api.post("/api/auth/logout", format="json")
    resp = api.post("/api/auth/login", {"email": "admin@acme.test", "password": "wrong"},
                    format="json")
    assert resp.status_code == 401
    assert "Invalid email or password" in resp.json()["detail"]


def test_weak_passwords_are_rejected(api):
    for weak in ("password", "12345678", "short"):
        resp = api.post("/api/auth/register",
                        {"company_name": "Weak Co", "email": f"w{len(weak)}@x.test",
                         "password": weak}, format="json")
        assert resp.status_code == 400, weak


def test_refresh_rotates_and_blacklists_the_old_token(api, register_company):
    register_company(email="admin@acme.test")
    old_refresh = api.cookies["openvault_refresh"].value
    assert OutstandingToken.objects.count() == 1

    resp = api.post("/api/auth/refresh", format="json")
    assert resp.status_code == 200
    new_refresh = resp.cookies["openvault_refresh"].value
    assert new_refresh != old_refresh

    # The old token was blacklisted during rotation and can no longer be used.
    assert BlacklistedToken.objects.count() == 1
    from rest_framework.test import APIClient
    replay = APIClient()
    replay.cookies["openvault_refresh"] = old_refresh
    assert replay.post("/api/auth/refresh", format="json").status_code == 401


def test_logout_blacklists_the_refresh_token(api, register_company):
    register_company(email="admin@acme.test")
    assert api.post("/api/auth/logout", format="json").status_code == 200
    assert BlacklistedToken.objects.count() == 1
    assert api.post("/api/auth/refresh", format="json").status_code == 401


def test_password_reset_revokes_all_refresh_tokens(api, register_company, make_company,
                                                    make_user):
    register_company(email="admin@acme.test")
    admin = User.objects.get(email="admin@acme.test")
    # A second device issued a refresh token for the same user.
    from rest_framework_simplejwt.tokens import RefreshToken
    RefreshToken.for_user(admin)
    assert api.post("/api/auth/refresh", format="json").status_code == 200
    before = OutstandingToken.objects.filter(user=admin).count()
    assert before >= 2

    from core.models import OneTimeToken
    _, raw = OneTimeToken.issue(admin, "password_reset", minutes=30)
    resp = api.post("/api/auth/reset-password",
                    {"token": raw, "password": "BrandNew!Pass9"}, format="json")
    assert resp.status_code == 200

    blacklisted = BlacklistedToken.objects.filter(token__user=admin).count()
    assert blacklisted == OutstandingToken.objects.filter(user=admin).count()
    # Reset token is single-use.
    again = api.post("/api/auth/reset-password",
                     {"token": raw, "password": "Another!Pass9"}, format="json")
    assert again.status_code == 400


def test_update_me_changes_own_password_and_requires_current(auth_client, make_company,
                                                             make_user):
    company = make_company()
    user = make_user(company, email="me@acme.test", role="admin")
    client = auth_client(user)
    resp = client.patch("/api/auth/update-me",
                        {"new_password": "NewSecret!77"}, format="json")
    assert resp.status_code == 400  # current_password missing
    resp = client.patch("/api/auth/update-me",
                        {"current_password": PASSWORD, "new_password": "NewSecret!77"},
                        format="json")
    assert resp.status_code == 200
    user.refresh_from_db()
    assert user.check_password("NewSecret!77")


def test_stale_access_cookie_does_not_block_login_register_refresh_or_logout(
    api, register_company
):
    register_company(name="Stale Co", email="stale@acme.test")
    # Simulate an invalid/rotated-key access cookie still present in the browser.
    api.cookies["openvault_access"] = "invalid.jwt.token"

    bad_pw = api.post(
        "/api/auth/login",
        {"email": "stale@acme.test", "password": "wrong-password"},
        format="json",
    )
    assert bad_pw.status_code == 401
    assert "Invalid email or password" in bad_pw.json()["detail"]

    refreshed = api.post("/api/auth/refresh", format="json")
    assert refreshed.status_code == 200
    assert "openvault_access" in refreshed.cookies

    api.cookies["openvault_access"] = "invalid.jwt.token"
    logged_in = api.post(
        "/api/auth/login",
        {"email": "stale@acme.test", "password": PASSWORD},
        format="json",
    )
    assert logged_in.status_code == 200
    assert api.get("/api/auth/me").status_code == 200

    api.cookies["openvault_access"] = "invalid.jwt.token"
    logged_out = api.post("/api/auth/logout", format="json")
    assert logged_out.status_code == 200


def test_short_access_timeout_cookie_and_refresh_expiry(
    api, settings, monkeypatch, register_company
):
    import copy
    import time
    from datetime import timedelta
    from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

    orig = copy.deepcopy(settings.SIMPLE_JWT)
    try:
        settings.SIMPLE_JWT = {
            **orig,
            "ACCESS_TOKEN_LIFETIME": timedelta(seconds=1),
            "REFRESH_TOKEN_LIFETIME": timedelta(seconds=60),
        }
        monkeypatch.setattr(AccessToken, "lifetime", timedelta(seconds=1))
        monkeypatch.setattr(RefreshToken, "lifetime", timedelta(seconds=60))

        reg_resp, _ = register_company(name="Timeout Co", email="timeout@acme.test")
        assert reg_resp.status_code == 201
        assert int(reg_resp.cookies["openvault_access"]["max-age"]) >= 1
        assert int(reg_resp.cookies["openvault_refresh"]["max-age"]) >= 1

        time.sleep(2)
        # Access token expired -> /me returns 401, while refresh token renews session.
        assert api.get("/api/auth/me").status_code == 401
        ref_resp = api.post("/api/auth/refresh", format="json")
        assert ref_resp.status_code == 200
        assert api.get("/api/auth/me").status_code == 200

        # Expired refresh token -> /refresh returns 401 and clears cookies.
        settings.SIMPLE_JWT = {
            **orig,
            "ACCESS_TOKEN_LIFETIME": timedelta(seconds=1),
            "REFRESH_TOKEN_LIFETIME": timedelta(seconds=1),
        }
        monkeypatch.setattr(AccessToken, "lifetime", timedelta(seconds=1))
        monkeypatch.setattr(RefreshToken, "lifetime", timedelta(seconds=1))
        login_resp = api.post(
            "/api/auth/login",
            {"email": "timeout@acme.test", "password": PASSWORD},
            format="json",
        )
        assert login_resp.status_code == 200
        time.sleep(2)
        expired_ref = api.post("/api/auth/refresh", format="json")
        assert expired_ref.status_code == 401
        assert "Session expired" in expired_ref.json()["detail"]
    finally:
        settings.SIMPLE_JWT = orig


def test_email_case_insensitive_login_and_duplicate_workspace_block(api):
    reg = api.post(
        "/api/auth/register",
        {
            "company_name": "Case Test Co",
            "admin_name": "Case Admin",
            "email": "Alice.Smith@CaseCo.test",
            "password": PASSWORD,
        },
        format="json",
    )
    assert reg.status_code == 201
    api.post("/api/auth/logout", format="json")

    # Login with different casing succeeds.
    login_resp = api.post(
        "/api/auth/login",
        {"email": "alice.smith@caseco.test", "password": PASSWORD},
        format="json",
    )
    assert login_resp.status_code == 200

    # Re-using the same email for a second workspace is rejected clearly.
    dup = api.post(
        "/api/auth/register",
        {
            "company_name": "Second Co",
            "admin_name": "Alice",
            "email": "ALICE.SMITH@caseco.test",
            "password": PASSWORD,
        },
        format="json",
    )
    assert dup.status_code == 400
    assert "unique work email" in dup.json()["detail"].lower()
