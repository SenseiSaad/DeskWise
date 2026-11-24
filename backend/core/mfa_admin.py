"""Django /admin/ two-factor gate for platform-admin accounts.

The API enforces TOTP at /api/auth/login; Django's session-based admin needs
its own second step. AdminMFAMiddleware redirects any authenticated staff
member whose session has not completed the TOTP check to /admin/mfa-verify/
(or a one-time enrollment page when no secret is stored yet). The two views
below are plain Django views with session CSRF, registered before
admin.site.urls so they win the /admin/mfa-* paths.
"""
from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import redirect, render

from . import mfa
from .ratelimit import _client_ip


def _mfa_rate_limited(request, scope: str, limit: int = 8, window: int = 300) -> bool:
    """Rate-limit POST attempts against Django /admin/mfa-* endpoints."""
    from django.conf import settings
    if not getattr(settings, "RATELIMIT_ENABLED", True):
        return False
    key = f"rl:admin_mfa:{scope}:{_client_ip(request)}:{getattr(request.user, 'pk', 'anon')}"
    try:
        count = cache.get(key, 0) + 1
        cache.set(key, count, timeout=window)
        return count > limit
    except Exception:
        return False


class AdminMFAMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if path.startswith("/admin/"):
            from django.conf import settings
            from django.http import Http404
            allowed = getattr(settings, "ADMIN_ALLOWED_IPS", set())
            if allowed and _client_ip(request) not in allowed:
                raise Http404
        if path.startswith("/admin/") and not path.startswith("/admin/mfa"):
            user = getattr(request, "user", None)
            if user and user.is_authenticated and user.is_staff:
                if request.session.get("mfa_admin_ok") != user.pk:
                    if user.mfa_enabled:
                        return redirect(f"/admin/mfa-verify/?next={path}")
                    return redirect("/admin/mfa-enroll/")
        return self.get_response(request)


def _guard(request):
    """Shared gate: only authenticated staff may touch these pages."""
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated and user.is_staff):
        return None, redirect("/admin/login/?next=/admin/")
    return user, None


def _finish(request, next_path):
    target = next_path or "/admin/"
    if not target.startswith("/admin/"):
        target = "/admin/"
    request.session["mfa_admin_ok"] = request.user.pk
    return redirect(target)


def admin_mfa_enroll(request):
    """First-time enrollment: show the secret once, confirm with a live code."""
    user, bounce = _guard(request)
    if bounce:
        return bounce
    error = ""
    if user.mfa_enabled:
        return redirect("/admin/mfa-verify/")
    if request.method == "POST":
        if _mfa_rate_limited(request, "enroll"):
            return HttpResponse("Too many verification attempts. Please wait a few minutes.", status=429)
        secret = request.session.get("mfa_enroll_secret", "")
        if secret and mfa.verify_user_code(user.pk, secret, request.POST.get("code", "")):
            user.mfa_secret = secret
            user.mfa_enabled = True
            user.save(update_fields=["mfa_secret", "mfa_enabled"])
            request.session.pop("mfa_enroll_secret", None)
            return _finish(request, request.GET.get("next"))
        error = "That code did not match. Wait for the next code and try again."
    else:
        secret = mfa.generate_secret()
        request.session["mfa_enroll_secret"] = secret
    return render(request, "core/admin_mfa.html", {
        "mode": "enroll",
        "secret": request.session.get("mfa_enroll_secret", ""),
        "uri": mfa.provisioning_uri(request.session.get("mfa_enroll_secret", ""), user.email),
        "error": error,
    })


def admin_mfa_verify(request):
    """Second step for enrolled accounts: confirm a TOTP code for this session."""
    user, bounce = _guard(request)
    if bounce:
        return bounce
    if not user.mfa_enabled:
        return redirect("/admin/mfa-enroll/")
    error = ""
    if request.method == "POST":
        if _mfa_rate_limited(request, "verify"):
            return HttpResponse("Too many verification attempts. Please wait a few minutes.", status=429)
        if mfa.verify_user_code(user.pk, user.mfa_secret, request.POST.get("code", "")):
            return _finish(request, request.GET.get("next"))
        error = "That code did not match. Wait for the next code and try again."
    return render(request, "core/admin_mfa.html", {"mode": "verify", "error": error})
