"""Authentication helpers: HttpOnly cookie sessions on top of SimpleJWT.

The JWT access token lives in an HttpOnly, SameSite=Lax cookie so XSS in the
frontend can no longer exfiltrate it, and a separate refresh-token cookie plus
/api/auth/refresh lets sessions renew without re-login. The Authorization
header still works for scripts/tests. SameSite=Lax also blocks CSRF: browsers
do not attach the cookie to cross-site POSTs.
"""
from django.conf import settings
from django.db.models import F
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import RefreshToken


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


def _cookie_kwargs(max_age):
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
        path="/",
    )
    domain = getattr(settings, "COOKIE_DOMAIN", None)
    if domain:
        kw["domain"] = domain
    return kw


def set_auth_cookies(response, user):
    """Attach access + refresh JWT cookies to a DRF Response."""
    refresh = RefreshToken.for_user(user)
    refresh["tv"] = getattr(user, "token_version", 1)
    access = refresh.access_token
    access["tv"] = getattr(user, "token_version", 1)
    access_lifetime = settings.SIMPLE_JWT.get("ACCESS_TOKEN_LIFETIME")
    refresh_lifetime = settings.SIMPLE_JWT.get("REFRESH_TOKEN_LIFETIME")
    access_max_age = max(1, int(access_lifetime.total_seconds()))
    refresh_max_age = max(1, int(refresh_lifetime.total_seconds()))
    response.set_cookie(ACCESS_COOKIE, str(access), **_cookie_kwargs(access_max_age))
    # Refresh token outlives the access token (SimpleJWT default 7 days).
    response.set_cookie(REFRESH_COOKIE, str(refresh), **_cookie_kwargs(refresh_max_age))
    return response


def clear_auth_cookies(response):
    domain = getattr(settings, "COOKIE_DOMAIN", None)
    samesite = getattr(settings, "COOKIE_SAMESITE", "Lax")
    for name in (ACCESS_COOKIE, REFRESH_COOKIE):
        response.delete_cookie(name, path="/", domain=domain, samesite=samesite)
    return response


class CookieJWTAuthentication(JWTAuthentication):
    """Read the JWT from the HttpOnly cookie first, then the header."""

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if "tv" in validated_token and int(validated_token["tv"]) != int(getattr(user, "token_version", 1)):
            raise AuthenticationFailed("Session has been revoked. Please sign in again.")
        return user

    def authenticate(self, request):
        raw = request.COOKIES.get(ACCESS_COOKIE)
        if raw:
            validated = self.get_validated_token(raw)
            return self.get_user(validated), validated
        return super().authenticate(request)
