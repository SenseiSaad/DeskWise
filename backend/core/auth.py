"""Authentication helpers: HttpOnly cookie sessions on top of SimpleJWT.

The JWT access token lives in an HttpOnly, SameSite=Lax cookie so XSS in the
frontend can no longer exfiltrate it, and a separate refresh-token cookie plus
/api/auth/refresh lets sessions renew without re-login. The Authorization
header still works for scripts/tests. SameSite=Lax also blocks CSRF: browsers
do not attach the cookie to cross-site POSTs.
"""
from django.conf import settings
from django.core.cache import cache
from django.db.models import F
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.tokens import RefreshToken


def _deny_key(jti):
    return f"jwt:deny:{jti}"


def _deny_sid_key(sid):
    return f"jwt:deny:sid:{sid}"


def deny_access_token(validated):
    """AUTHN-06 / S7-04: end a session's access tokens now instead of at `exp`.

    Every token minted for one login (and all its refresh rotations) carries
    the same `sid`, so denying the sid also kills access tokens issued earlier
    in the session and copied before a refresh. The `jti` entry additionally
    covers tokens minted before sessions had a sid. Entries live in the shared
    cache just long enough for the longest possible access token."""
    import time
    jti, exp = validated.get("jti"), validated.get("exp")
    if jti and exp:
        ttl = int(exp) - int(time.time())
        if ttl > 0:
            cache.set(_deny_key(jti), 1, ttl + 5)
    sid = validated.get("sid")
    if sid:
        lifetime = settings.SIMPLE_JWT.get("ACCESS_TOKEN_LIFETIME")
        cache.set(_deny_sid_key(sid), 1, int(lifetime.total_seconds()) + 60)


def deny_session(sid):
    """Deny a session by id alone (logout with only a refresh cookie)."""
    if sid:
        lifetime = settings.SIMPLE_JWT.get("ACCESS_TOKEN_LIFETIME")
        cache.set(_deny_sid_key(sid), 1, int(lifetime.total_seconds()) + 60)


def is_access_token_denied(validated):
    jti = validated.get("jti")
    if jti and cache.get(_deny_key(jti)) is not None:
        return True
    sid = validated.get("sid")
    return bool(sid) and cache.get(_deny_sid_key(sid)) is not None


def is_platform_level(user):
    return bool(user and (getattr(user, "is_superuser", False) or getattr(user, "is_platform_admin", False)))


def token_allowed_for_user(validated, user) -> bool:
    """Platform-level accounts may only act with a session that completed
    two-factor sign-in (`mfa` claim). A password-only token minted while the
    account was an ordinary user (and not revoked by promotion) never gains
    platform authority (S7-10)."""
    if is_platform_level(user):
        return bool(validated.get("mfa"))
    return True


def revoke_user_refresh_tokens(user):
    """Blacklist every outstanding refresh token and bump token_version so
    active access tokens and WebSocket sessions are invalidated immediately."""
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken, OutstandingToken,
    )
    type(user).objects.filter(pk=user.pk).update(token_version=F("token_version") + 1)
    user.refresh_from_db(fields=["token_version"])
    for outstanding in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=outstanding)

ACCESS_COOKIE = "openvault_access"
REFRESH_COOKIE = "openvault_refresh"
# AUTHN-13: the long-lived refresh token is only sent to the auth endpoints
# (/api/auth/refresh and /api/auth/logout), not on every API request.
REFRESH_COOKIE_PATH = "/api/auth/"


def _cookie_kwargs(max_age, path="/"):
    secure = getattr(settings, "SESSION_COOKIE_SECURE", False)
    samesite = getattr(settings, "COOKIE_SAMESITE", "Lax")
    # Browsers reject SameSite=None unless Secure=True.
    if str(samesite).lower() == "none" and not secure:
        samesite = "Lax"
    kw = dict(
        max_age=max_age,
        httponly=True,
        samesite=samesite,
        secure=secure,
        path=path,
    )
    domain = getattr(settings, "COOKIE_DOMAIN", None)
    if domain:
        kw["domain"] = domain
    return kw


def set_auth_cookies(response, user, sid=None, mfa=False):
    """Attach access + refresh JWT cookies to a DRF Response.

    `sid` links a refresh rotation to the session it continues; a new login
    gets a fresh one. `mfa=True` marks a session that completed the TOTP step
    and is carried through every rotation."""
    import uuid
    refresh = RefreshToken.for_user(user)
    refresh["tv"] = getattr(user, "token_version", 1)
    refresh["sid"] = sid or uuid.uuid4().hex
    if mfa:
        refresh["mfa"] = True
    access = refresh.access_token
    access["tv"] = getattr(user, "token_version", 1)
    access["sid"] = refresh["sid"]
    if mfa:
        access["mfa"] = True
    access_lifetime = settings.SIMPLE_JWT.get("ACCESS_TOKEN_LIFETIME")
    refresh_lifetime = settings.SIMPLE_JWT.get("REFRESH_TOKEN_LIFETIME")
    access_max_age = max(1, int(access_lifetime.total_seconds()))
    refresh_max_age = max(1, int(refresh_lifetime.total_seconds()))
    response.set_cookie(ACCESS_COOKIE, str(access), **_cookie_kwargs(access_max_age))
    # Refresh token outlives the access token (SimpleJWT default 7 days).
    response.set_cookie(
        REFRESH_COOKIE, str(refresh), **_cookie_kwargs(refresh_max_age, path=REFRESH_COOKIE_PATH)
    )
    # Retire the pre-AUTHN-13 refresh cookie (path=/). Browsers send both, and
    # Django would read the stale one.
    _expire_legacy_refresh_cookie(response)
    return response


def _expire_legacy_refresh_cookie(response):
    """Emit a second Set-Cookie for the same name with the old path.

    SimpleCookie is keyed by name, so one name can't hold two paths. The
    morsel is stored under an alias key and renamed, so the wire header is
    `openvault_refresh=; Path=/; Max-Age=0`."""
    samesite = getattr(settings, "COOKIE_SAMESITE", "Lax")
    secure = getattr(settings, "SESSION_COOKIE_SECURE", False)
    if str(samesite).lower() == "none" and not secure:
        samesite = "Lax"
    response.cookies["_legacy_" + REFRESH_COOKIE] = ""
    morsel = response.cookies["_legacy_" + REFRESH_COOKIE]
    morsel.set(REFRESH_COOKIE, "", "")
    morsel["path"] = "/"
    morsel["max-age"] = 0
    morsel["expires"] = "Thu, 01 Jan 1970 00:00:00 GMT"
    morsel["httponly"] = True
    morsel["samesite"] = samesite
    if secure:
        morsel["secure"] = True
    domain = getattr(settings, "COOKIE_DOMAIN", None)
    if domain:
        morsel["domain"] = domain


def clear_auth_cookies(response):
    domain = getattr(settings, "COOKIE_DOMAIN", None)
    samesite = getattr(settings, "COOKIE_SAMESITE", "Lax")
    response.delete_cookie(ACCESS_COOKIE, path="/", domain=domain, samesite=samesite)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, domain=domain, samesite=samesite)
    _expire_legacy_refresh_cookie(response)
    return response


class CookieJWTAuthentication(JWTAuthentication):
    """Read the JWT from the HttpOnly cookie first, then the header."""

    def get_validated_token(self, raw_token):
        validated = super().get_validated_token(raw_token)
        if is_access_token_denied(validated):
            raise InvalidToken("Session has ended. Please sign in again.")
        return validated

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if "tv" in validated_token and int(validated_token["tv"]) != int(getattr(user, "token_version", 1)):
            raise AuthenticationFailed("Session has been revoked. Please sign in again.")
        if not token_allowed_for_user(validated_token, user):
            raise AuthenticationFailed("Platform accounts must sign in with two-factor authentication.")
        return user

    def authenticate(self, request):
        raw = request.COOKIES.get(ACCESS_COOKIE)
        if raw:
            validated = self.get_validated_token(raw)
            return self.get_user(validated), validated
        return super().authenticate(request)
