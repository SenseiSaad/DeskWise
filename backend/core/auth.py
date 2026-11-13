"""Authentication helpers: HttpOnly cookie sessions on top of SimpleJWT.

The JWT access token lives in an HttpOnly, SameSite=Lax cookie so XSS in the
frontend can no longer exfiltrate it, and a separate refresh-token cookie plus
/api/auth/refresh lets sessions renew without re-login. The Authorization
header still works for scripts/tests. SameSite=Lax also blocks CSRF: browsers
do not attach the cookie to cross-site POSTs.
"""
from django.conf import settings
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import RefreshToken


def revoke_user_refresh_tokens(user):
    """Blacklist every outstanding refresh token for a user.

    Used after password changes/resets and when an account is deactivated, so a
    stolen token cannot outlive the credential change.
    """
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken, OutstandingToken,
    )
    for outstanding in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=outstanding)

ACCESS_COOKIE = "openvault_access"
REFRESH_COOKIE = "openvault_refresh"


def _cookie_kwargs(max_age):
    secure = getattr(settings, "SESSION_COOKIE_SECURE", False)
    return dict(
        max_age=max_age,
        httponly=True,
        samesite="Lax",
        secure=secure,
        path="/",
    )


def set_auth_cookies(response, user):
    """Attach access + refresh JWT cookies to a DRF Response."""
    refresh = RefreshToken.for_user(user)
    access_lifetime = settings.SIMPLE_JWT.get("ACCESS_TOKEN_LIFETIME")
    refresh_lifetime = settings.SIMPLE_JWT.get("REFRESH_TOKEN_LIFETIME")
    access_max_age = max(1, int(access_lifetime.total_seconds()))
    refresh_max_age = max(1, int(refresh_lifetime.total_seconds()))
    response.set_cookie(ACCESS_COOKIE, str(refresh.access_token), **_cookie_kwargs(access_max_age))
    # Refresh token outlives the access token (SimpleJWT default 7 days).
    response.set_cookie(REFRESH_COOKIE, str(refresh), **_cookie_kwargs(refresh_max_age))
    return response


def clear_auth_cookies(response):
    for name in (ACCESS_COOKIE, REFRESH_COOKIE):
        response.delete_cookie(name, path="/")
    return response


class CookieJWTAuthentication(JWTAuthentication):
    """Read the JWT from the HttpOnly cookie first, then the header."""

    def authenticate(self, request):
        raw = request.COOKIES.get(ACCESS_COOKIE)
        if raw:
            validated = self.get_validated_token(raw)
            return self.get_user(validated), validated
        return super().authenticate(request)
