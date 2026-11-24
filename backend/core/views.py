"""API endpoints. Function-based DRF views kept deliberately simple and flat.

Multi-tenant rule enforced everywhere: a request only ever touches rows where
`company == request.user.company`. Document reads additionally pass the
per-document ACL before metadata, downloads, or RAG retrieval are returned.

Authentication uses HttpOnly JWT cookies (see core.auth); the Authorization
header still works for scripts. Open endpoints are rate-limited (core.ratelimit).
Platform-level authority is the `is_platform_admin` flag — never an email.
"""
import io
import json
import os
import threading
import uuid
from datetime import timedelta

from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q, Avg, Count, Sum
from django.http import StreamingHttpResponse, Http404, FileResponse, JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.text import slugify
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.views.decorators.csrf import csrf_exempt

from django.conf import settings

import logging
logger = logging.getLogger(__name__)

from . import access
from . import rag
from . import providers
from . import moderation
from . import storage
from . import docgen
from . import billing
from . import attendance as attendance_svc
from .auth import (
    set_auth_cookies, clear_auth_cookies, revoke_user_refresh_tokens,
    ACCESS_COOKIE, REFRESH_COOKIE,
)
from .ratelimit import rate_limit
from .uploads import (
    UploadRejected, content_type_for, guard_zip_archive, index_error_message, validate_extension,
    validate_filename, validate_magic,
)
from .models import (
    Announcement, AnnouncementAck, AskLog, AuditLog, ChatConversation, ChatMessage, Company,
    Department, Document, DocumentAccess, DocumentShare, DocumentVersion, LLMConfig, Plan,
    AttendanceRecord, PendingUpload, TeamMessage, UserStrike, User, OneTimeToken, GeneratedArtifact,
)
from .permissions import IsAdmin, IsAdminOrDeptAdmin, IsEditor, IsPlatformAdmin, is_dept_admin, is_platform_admin
from .serializers import (
    AnnouncementSerializer, AskLogSerializer, AuditSerializer, ChatConversationSerializer,
    ChatMessageSerializer, CompanyDirectorySerializer, CompanyProfileSerializer,
    DepartmentSerializer, DocumentSerializer, DocumentVersionSerializer,
    MemberDirectorySerializer, PlanSerializer, UserSerializer,
    RegisterCompanySerializer, LoginSerializer, UserCreateSerializer, AskSerializer,
    DocumentShareSerializer, LLMConfigSerializer,
    AttendanceRecordSerializer, UserStrikeSerializer,
)


def client_ip(request):
    """Caller IP for the audit log — shared trusted-proxy logic with the rate
    limiter, so a client-supplied X-Forwarded-For prefix cannot forge entries."""
    from .ratelimit import _client_ip
    return _client_ip(request)


def _password_error(password, user=None):
    """Return a human-readable policy violation, or None when the password is OK."""
    try:
        validate_password(password, user=user)
    except DjangoValidationError as exc:
        return " ".join(exc.messages)
    return None


def _upload_rejection(f):
    """A 400 Response for rejected uploads, or None when the file is acceptable.

    Cheap checks (name, extension) and the zip-bomb guard run here so a bad
    file never reaches storage; PDF page/text caps are enforced later inside
    extract_text, which is the single path every consumer goes through.
    """
    try:
        clean_name = validate_filename(f.name)
        f.name = clean_name
        validate_extension(f.name)
        validate_magic(f.name, f.read(2048))
        f.seek(0)
        if (f.name or "").lower().endswith((".docx", ".pptx")):
            guard_zip_archive(f.read())
            f.seek(0)
    except UploadRejected as exc:
        return Response({"detail": str(exc)}, status=400)
    return None


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def health(request):
    """Liveness/readiness probe for load balancers and uptime monitors.

    Exercises the two things a broken deployment actually breaks: the database
    (a real query) and document storage (a write/read/delete probe), so an
    instance that cannot serve uploads or downloads leaves rotation."""
    from django.db import connection
    db_ok = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        db_ok = False

    storage_ok = True
    try:
        probe_key = f"_health/{uuid.uuid4().hex}.txt"
        storage.save_bytes(probe_key, b"ok", base_dir=settings.DATA_DIR)
        storage_ok = storage.read_bytes(probe_key, base_dir=settings.DATA_DIR) == b"ok"
        storage.delete(probe_key, base_dir=settings.DATA_DIR)
    except Exception:
        storage_ok = False

    payload = {
        "status": "ok" if (db_ok and storage_ok) else "degraded",
        "db": db_ok,
        "storage": storage_ok,
        "time": timezone.now().isoformat(),
    }
    return JsonResponse(payload, status=200 if (db_ok and storage_ok) else 503)


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def health_live(request):
    """Cheap liveness probe: no database or storage calls, just proves the
    process is alive and answering requests. Used when a fast failover is
    preferred over detailed readiness (the ALB checks /api/health)."""
    return JsonResponse({"status": "ok", "time": timezone.now().isoformat()})


def _parse_bool(val, default: bool = False) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _safe_doc_label(doc: Document) -> str:
    """Never place restricted document filenames in audit trail detail text."""
    if getattr(doc, "access_scope", "") == "restricted":
        return f"doc#{doc.id}"
    return doc.filename


def _masked_doc_payload(doc: Document) -> dict:
    """Limited metadata shown to company admins for ungranted restricted docs."""
    return {
        "id": doc.id,
        "filename": f"Restricted document #{doc.id}",
        "content_type": doc.content_type,
        "size": doc.size,
        "category": doc.category,
        "description": "",
        "downloads": doc.downloads,
        "is_okf": False,
        "num_chunks": doc.num_chunks,
        "access_scope": "restricted",
        "sensitivity": doc.sensitivity,
        "status": doc.status,
        "reviewed_at": doc.reviewed_at.isoformat() if doc.reviewed_at else None,
        "review_note": "",
        "contains_pii": doc.contains_pii,
        "legal_hold": doc.legal_hold,
        "department": doc.department_id,
        "department_name": doc.department.name if doc.department_id and doc.department else None,
        "tags": [],
        "indexing_status": doc.indexing_status,
        "index_error": "",
        "version": doc.version,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
        "company_name": doc.company.name if doc.company_id and doc.company else None,
        "is_template": False,
        "template_type": "",
        "embed_model": "",
        "reindex_required": False,
        "masked": True,
        "requires_break_glass": True,
    }


def _csv_safe(value) -> str:
    """Neutralise spreadsheet formula injection (=, +, -, @, tab, CR)."""
    s = "" if value is None else str(value)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


def audit(
    request,
    action,
    detail="",
    *,
    outcome: str = "allowed",
    target_type: str = "",
    target_id: str = "",
    company=None,
    user=None,
    fail_closed: bool = False,
):
    """Write one tamper-evident audit-trail row for the caller's company.

    Security-sensitive callers pass `fail_closed=True` so any DB/trigger error
    aborts the operation rather than completing unaudited.
    """
    actor = user if user is not None else (
        request.user if getattr(request, "user", None) and request.user.is_authenticated else None
    )
    target_company = company or getattr(actor, "company", None)
    if target_company is None:
        return
    try:
        AuditLog.objects.create(
            company=target_company,
            user=actor,
            actor_id=getattr(actor, "id", None),
            actor_email=getattr(actor, "email", "") or "",
            action=action,
            outcome=outcome,
            target_type=target_type[:40],
            target_id=str(target_id)[:64],
            detail=str(detail or "")[:300],
            ip=client_ip(request) if request is not None else "",
        )
    except Exception:
        logger.exception("AuditLog write failed for action=%s", action)
        if fail_closed:
            raise


def _is_platform_level(user):
    """Platform-level authority: the DB flag or a Django superuser."""
    return bool(
        user and user.is_authenticated and (user.is_superuser or user.is_platform_admin)
    )


def _platform_admin_blocked(request):
    """403 for a platform/root admin trying to touch tenant-scoped data, or an
    authenticated user who has not yet finished company onboarding.
    """
    if _is_platform_level(request.user) and getattr(request.user, "company_id", None):
        # AUTHZ-05: platform-level accounts never act inside a tenant.
        return Response({"detail": "Platform admins cannot access company data."}, status=403)
    if not getattr(request.user, "company_id", None):
        if _is_platform_level(request.user):
            return Response(
                {"detail": "Platform admins cannot access company data. "
                           "Use /api/admin/reports for platform analytics."},
                status=403,
            )
        return Response(
            {"detail": "Please complete onboarding by creating or joining a company.",
             "code": "company_required"},
            status=403,
        )
    return None


def _feature_disabled(request, attr: str, message: str):
    """403 when a company-level feature toggle is disabled."""
    company = getattr(request.user, "company", None)
    if company is not None and not getattr(company, attr, True):
        return Response({"detail": message}, status=403)
    return None


def _attendance_disabled(request):
    """403 when attendance tracking is turned off for the user's company."""
    return _feature_disabled(request, "enable_attendance", "Attendance tracking is disabled for your company.")


def _docgen_disabled(request):
    """403 when document & template generation is turned off for the user's company."""
    return _feature_disabled(request, "enable_docgen", "Document and template generation is disabled for your company.")


def _ai_chat_disabled(request):
    """403 when AI chat is turned off for the user's company."""
    return _feature_disabled(request, "enable_ai_chat", "AI chat is disabled for your company.")


def _external_sharing_disabled(request):
    """403 when cross-company document sharing is turned off for the user's company."""
    return _feature_disabled(request, "enable_external_sharing", "External document sharing is disabled for your company.")


def visible_documents(user):
    """Return only own-company documents the signed-in user is allowed to read."""
    return access.accessible_documents_qs(user, action="view_ask", include_unapproved=True, include_external_shares=False)


def share_target(request):
    """Resolve a registered target user from a company code + member id.

    Uses a single unified error message for missing or mismatched user IDs so
    callers cannot probe whether arbitrary user IDs exist across tenants.
    """
    access_code = (request.data.get("access_code") or "").strip().upper()
    raw_user_id = request.data.get("user_id")
    if raw_user_id is None:
        return None, "A member is required."
    if not access_code:
        # Internal grant inside caller's own company (no access_code required)
        company = getattr(request.user, "company", None)
        if not company:
            return None, "A company code and a member are required."
    else:
        company = Company.objects.filter(access_code__iexact=access_code).first()
        if not company:
            return None, "No registered company uses that access code."
        if company.id != getattr(request.user, "company_id", None) and not getattr(company, "enable_external_sharing", True):
            return None, "No registered company uses that access code."
    try:
        uid = int(raw_user_id)
    except (TypeError, ValueError):
        return None, "That member was not found in the selected company."
    target = (
        User.objects.filter(pk=uid, company=company, is_active=True)
        .exclude(role="public")
        .first()
    )
    if target is None:
        return None, "That member was not found in the selected company."
    return target, None


# ------------------------------------------------------------------ helpers
def _email_user(user, subject, body, html_body=None):
    """Send a transactional email; uses email_service with HTML + plain text, never raises."""
    from . import email_service
    to_email = user.email if hasattr(user, "email") else str(user or "").strip()
    if not to_email:
        return False
    rendered_html = html_body or email_service._render_html_shell(
        subject, body, "", "", "Deskwise notification."
    )
    return email_service._deliver_now(to_email, subject, body, rendered_html)


def _frontend_url(path=""):
    from . import email_service
    return email_service.frontend_url(path)


def _require_email_verification(user):
    """True when the platform is set to gate login on verified email."""
    return settings.REQUIRE_EMAIL_VERIFICATION and not user.email_verified


# -------------------------------------------------------------------- auth
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@rate_limit("register", rate=5, per_seconds=600, key="ip")
def register_company(request):
    """Create a new company and its first admin. Sets auth cookies."""
    s = RegisterCompanySerializer(data=request.data)
    s.is_valid(raise_exception=True)
    d = s.validated_data
    if User.objects.filter(email__iexact=d["email"].strip()).exists():
        return Response(
            {"detail": "This email is already registered to a workspace. Each workspace requires "
                       "a unique work email — try signing in or reset your password."},
            status=409,
        )

    base = slugify(d["company_name"]) or "company"
    slug, n = base, 1
    while Company.objects.filter(slug=slug).exists():
        n += 1
        slug = f"{base}-{n}"

    from django.db import transaction
    with transaction.atomic():
        company = Company.objects.create(
            name=d["company_name"], slug=slug,
            website=d.get("website", ""), contact_email=d.get("contact_email", ""),
            phone=d.get("phone", ""), max_employees=d.get("max_employees"),
            plan=Plan.default(),
            enable_team_chat=False,
            enable_attendance=False,
        )
        user = User.objects.create_user(
            email=d["email"], password=d["password"],
            full_name=d.get("admin_name", ""), title=d.get("admin_title", ""),
            role="admin", company=company,
        )
        AuditLog.objects.create(
            company=company, user=user, action="register", outcome="allowed",
            target_type="company", target_id=str(company.id),
            detail=f"company {company.name}", ip=client_ip(request),
        )

    # Email verification (branded HTML + plain-text template).
    from . import email_service
    tok, raw = OneTimeToken.issue(user, "verify_email", minutes=60 * 24)
    email_service.send_auth_email(
        user,
        "verify",
        company_name=company.name,
        url=_frontend_url("/auth/verify?token=" + raw),
    )
    audit(_as(request, user), "verification_email_sent", target_type="user", target_id=str(user.id))

    if _require_email_verification(user):
        return Response(
            {"user": UserSerializer(user).data, "verification_required": True},
            status=201,
        )
    resp = Response({"user": UserSerializer(user).data}, status=201)
    return set_auth_cookies(resp, user)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@rate_limit("login", rate=8, per_seconds=60, key="ip_email")
def login(request):
    """Enterprise sign-in with email + password. Sets HttpOnly auth cookies.

    Platform-level accounts (root admins) get a mandatory second step: the
    password alone never sets cookies, it returns an `mfa_required` challenge
    that must be completed via /api/auth/mfa/verify (or activated first via
    /api/auth/mfa/activate on first enrollment).
    """
    s = LoginSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    raw_email = s.validated_data["email"].strip()
    from .ratelimit import clear_login_failures, login_locked, record_login_failure
    if login_locked(raw_email):
        resp = Response(
            {"detail": "Too many failed sign-in attempts for this account. "
                       "Try again in 15 minutes or reset your password.",
             "code": "account_locked"},
            status=429,
        )
        resp["Retry-After"] = str(int(getattr(settings, "LOGIN_LOCKOUT_SECONDS", 900)))
        return resp
    canonical_email = (
        User.objects.filter(email__iexact=raw_email).values_list("email", flat=True).first()
        or raw_email.lower()
    )
    user = authenticate(username=canonical_email, password=s.validated_data["password"])
    if user is None:
        record_login_failure(raw_email)
        existing = User.objects.select_related("company").filter(email__iexact=raw_email).first()
        if existing and existing.company_id:
            audit(
                request, "login_failed", "invalid_credentials",
                outcome="denied", target_type="user", target_id=str(existing.id),
                company=existing.company, user=existing,
            )
        return Response({"detail": "Invalid email or password."}, status=401)
    clear_login_failures(raw_email)
    if _require_email_verification(user):
        from django.core.cache import cache
        from . import email_service

        auto_key = f"rl:login_verify_auto:{user.email}"
        if not cache.get(auto_key):
            cache.set(auto_key, 1, timeout=60)
            _, raw_v = OneTimeToken.issue(user, "verify_email", minutes=60 * 24)
            email_service.send_auth_email(
                user,
                "verify",
                company_name=user.company.name if user.company else "your workspace",
                url=_frontend_url("/auth/verify?token=" + raw_v),
            )
        if user.company_id:
            audit(
                request, "login_failed", "email_unverified",
                outcome="denied", target_type="user", target_id=str(user.id),
                company=user.company, user=user,
            )
        return Response({"detail": "Please verify your email before signing in. "
                                   "We have sent a verification link to your inbox (check spam too).",
                         "code": "email_unverified"}, status=403)
    if _is_platform_level(user):
        from . import mfa
        if not user.mfa_enabled:
            secret = mfa.generate_secret()
            return Response({
                "mfa_required": True,
                "enrollment": {
                    "secret": secret,
                    "uri": mfa.provisioning_uri(secret, user.email),
                },
                "challenge": mfa.issue_challenge(user.pk, "enroll", secret=secret),
            })
        return Response({"mfa_required": True,
                         "challenge": mfa.issue_challenge(user.pk, "login")})
    audit(_as(request, user), "login")
    resp = Response({"user": UserSerializer(user).data})
    return set_auth_cookies(resp, user)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@rate_limit("mfa", rate=10, per_seconds=60, key="ip")
def mfa_activate(request):
    """Finish TOTP enrollment: challenge + 6-digit code.

    Two challenge purposes reach this endpoint:
      * "enroll": issued after a password-only login to an account that has no
        authenticator yet. It can ONLY enable MFA on an account where it is
        still off; an account that already has an authenticator rejects it
        (S7-02), so a leftover enrollment cannot replace the owner's device.
      * "rotate": issued by the authenticated /auth/mfa/setup, i.e. someone who
        already completed MFA; it replaces the existing authenticator.
    Both are bound to the user's session generation (S7-01).

    Saving the secret only happens after the authenticator app proves it can
    produce valid codes, so a typo during setup cannot lock the admin out.
    """
    from . import mfa
    raw_challenge = str((request.data or {}).get("challenge") or "")
    purpose = "enroll"
    payload = mfa.read_challenge(raw_challenge, "enroll")
    if not payload:
        purpose = "rotate"
        payload = mfa.read_challenge(raw_challenge, "rotate")
    code = str((request.data or {}).get("code") or "")
    expired = Response({"detail": "This verification session expired. Sign in again."}, status=400)
    if not payload or mfa.challenge_burned(raw_challenge):
        return expired
    try:
        user = User.objects.get(pk=payload.get("u"), is_active=True)
    except User.DoesNotExist:
        return expired
    if not mfa.challenge_is_current(payload, user):
        return expired
    if purpose == "enroll" and user.mfa_enabled:
        return expired
    if purpose == "rotate" and not user.mfa_enabled:
        return expired
    if not mfa.verify_user_code(user.pk, payload.get("s") or "", code):
        mfa.record_challenge_failure(raw_challenge)
        return Response({"detail": "That code did not match. Check your authenticator app."}, status=400)
    mfa.burn_challenge(raw_challenge)
    # Conditional write: of two concurrent enrollments only one can win.
    guard = {"pk": user.pk, "token_version": user.token_version}
    if purpose == "enroll":
        guard["mfa_enabled"] = False
    if not User.objects.filter(**guard).update(mfa_secret=payload["s"], mfa_enabled=True):
        return expired
    user.refresh_from_db(fields=["mfa_secret", "mfa_enabled"])
    audit(_as(request, user), "mfa_enrolled" if purpose == "enroll" else "mfa_rotated")
    resp = Response({"user": UserSerializer(user, context={"request": request}).data})
    return set_auth_cookies(resp, user, mfa=True)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@rate_limit("mfa", rate=10, per_seconds=60, key="ip")
def mfa_verify(request):
    """Complete a platform-admin login: login challenge + TOTP code -> cookies."""
    from . import mfa
    raw_challenge = str((request.data or {}).get("challenge") or "")
    payload = mfa.read_challenge(raw_challenge, "login")
    code = str((request.data or {}).get("code") or "")
    if not payload or mfa.challenge_burned(raw_challenge):
        return Response({"detail": "This verification session expired. Sign in again."}, status=400)
    try:
        user = User.objects.get(pk=payload.get("u"), is_active=True)
    except User.DoesNotExist:
        return Response({"detail": "This verification session expired. Sign in again."}, status=400)
    if not mfa.challenge_is_current(payload, user):
        return Response({"detail": "This verification session expired. Sign in again."}, status=400)
    if not (user.mfa_enabled and mfa.verify_user_code(user.pk, user.mfa_secret, code)):
        mfa.record_challenge_failure(raw_challenge)
        return Response({"detail": "That code did not match. Check your authenticator app."}, status=400)
    mfa.burn_challenge(raw_challenge)
    audit(_as(request, user), "login")
    resp = Response({"user": UserSerializer(user, context={"request": request}).data})
    return set_auth_cookies(resp, user, mfa=True)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def mfa_setup(request):
    """Rotate the TOTP secret for a platform admin (re-enrollment flow)."""
    if not _is_platform_level(request.user):
        return Response({"detail": "Only platform admins can manage two-factor auth."}, status=403)
    from . import mfa
    secret = mfa.generate_secret()
    return Response({
        "secret": secret,
        "uri": mfa.provisioning_uri(secret, request.user.email),
        "challenge": mfa.issue_challenge(request.user.pk, "rotate", secret=secret),
    })


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def logout(request):
    """Clear the auth cookies, revoke the refresh token server-side, and
    denylist this session's access token until it expires (AUTHN-06)."""
    from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
    from rest_framework_simplejwt.exceptions import TokenError
    from .auth import deny_access_token, deny_session
    raw = request.COOKIES.get(REFRESH_COOKIE)
    if raw:
        try:
            refresh_token = RefreshToken(raw)
            # S7-04: the refresh token knows the session id, so access tokens
            # minted earlier in this session (copied before a rotation) die too.
            deny_session(refresh_token.get("sid"))
            refresh_token.blacklist()
        except (TokenError, AttributeError):
            pass
    raw_access = request.COOKIES.get(ACCESS_COOKIE)
    if not raw_access:
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if header.lower().startswith("bearer "):
            raw_access = header[7:].strip()
    if raw_access:
        try:
            deny_access_token(AccessToken(raw_access))
        except TokenError:
            pass
    resp = Response({"ok": True})
    return clear_auth_cookies(resp)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_all(request):
    """Invalidate every active session/token across all devices for the current user."""
    revoke_user_refresh_tokens(request.user)
    audit(request, "logout_all")
    resp = Response({"ok": True})
    return clear_auth_cookies(resp)


def _refresh_reuse_response(request, raw):
    """AUTHN-07: a correctly signed refresh token that is already blacklisted
    means two parties hold it. Revoke every session of that user, unless:

    * it was retired seconds ago (two tabs refreshing at once): a 401 that
      does not clear cookies (they may be the other tab's fresh ones) and
      revokes nothing;
    * it is from an older generation (tv changed by a reset or logout-all): a
      plain 401, so an old device waking up can't kill the new session.

    Returns None when the token isn't a blacklisted refresh token."""
    from rest_framework_simplejwt.exceptions import TokenError
    from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
    from rest_framework_simplejwt.tokens import UntypedToken
    try:
        token = UntypedToken(raw)  # signature + expiry only, no blacklist lookup
    except TokenError:
        return None
    if token.get("token_type") != "refresh" or not token.get("jti"):
        return None
    entry = BlacklistedToken.objects.filter(token__jti=token["jti"]).first()
    if entry is None:
        return None
    grace = int(getattr(settings, "REFRESH_REUSE_GRACE_SECONDS", 10))
    if entry.blacklisted_at > timezone.now() - timedelta(seconds=grace):
        # Don't clear cookies here: they may be the fresh ones from the other tab.
        return Response({"detail": "Session was just refreshed. Retry the request."}, status=401)
    user = User.objects.select_related("company").filter(pk=token.get("user_id"), is_active=True).first()
    if user is not None and int(token.get("tv", user.token_version)) == int(user.token_version):
        revoke_user_refresh_tokens(user)
        logger.warning("Refresh-token reuse detected; revoked all sessions for user %s", user.pk)
        if user.company_id:
            audit(_as(request, user), "refresh_token_reuse", "all sessions revoked",
                  outcome="denied", target_type="user", target_id=str(user.id))
    resp = Response({"detail": "Session expired. Sign in again."}, status=401)
    return clear_auth_cookies(resp)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@rate_limit("refresh", rate=30, per_seconds=60, key="ip")
def refresh(request):
    """Rotate the refresh cookie and issue a fresh access cookie.

    The presented refresh token is blacklisted after a successful rotation, so
    replaying an old token fails. This is what makes "rotating refresh tokens"
    an actual security control rather than a new token with the old one still
    valid.
    """
    from rest_framework_simplejwt.tokens import RefreshToken
    from rest_framework_simplejwt.exceptions import TokenError
    raw = request.COOKIES.get(REFRESH_COOKIE)
    if not raw:
        return Response({"detail": "No refresh token."}, status=401)
    reuse = _refresh_reuse_response(request, raw)
    if reuse is not None:
        return reuse
    try:
        token = RefreshToken(raw)
        token.check_blacklist()
        user = User.objects.get(id=token["user_id"], is_active=True)
        if "tv" in token and int(token["tv"]) != int(getattr(user, "token_version", 1)):
            raise TokenError("Session revoked")
    except (TokenError, User.DoesNotExist, KeyError, ValueError):
        resp = Response({"detail": "Session expired. Sign in again."}, status=401)
        return clear_auth_cookies(resp)
    resp = Response({"ok": True, "user": UserSerializer(user).data})
    set_auth_cookies(resp, user, sid=token.get("sid"), mfa=bool(token.get("mfa")))
    # New cookies exist; retire the old refresh token.
    try:
        token.blacklist()
    except AttributeError:
        pass
    return resp


def _as(request, user):
    """Attach an authenticated user to a raw request so audit() can log it."""
    request.user = user
    return request


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    """Return the signed-in user's own profile (used to hydrate the frontend)."""
    data = UserSerializer(request.user, context={"request": request}).data
    data["direct_upload"] = storage.is_s3_enabled()
    return Response(data)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def update_me(request):
    """Let a user edit their own profile: name, title, reply language, password."""
    user = request.user
    data = request.data
    for field in ("full_name", "title", "manager", "employee_id"):
        if field in data:
            setattr(user, field, str(data.get(field) or "").strip()[:200])
    if "join_date" in data:
        raw = str(data.get("join_date") or "").strip()
        if not raw:
            user.join_date = None
        else:
            from datetime import date as _date
            try:
                user.join_date = _date.fromisoformat(raw)
            except ValueError:
                return Response({"detail": "join_date must be YYYY-MM-DD."}, status=400)
    # role and department are permission boundaries (document access scopes),
    # so they are deliberately NOT self-editable — admins use /admin/users.
    if "language" in data:
        lang = str(data.get("language") or "en").strip().lower()
        allowed_langs = {code for code, _ in User.LANGUAGES}
        if lang not in allowed_langs:
            return Response(
                {"detail": f"language must be one of: {', '.join(sorted(allowed_langs))}."},
                status=400,
            )
        user.language = lang
    new_password = data.get("new_password")
    if new_password:
        current = data.get("current_password") or ""
        if not user.check_password(current):
            return Response({"detail": "Current password is incorrect."}, status=400)
        err = _password_error(new_password, user)
        if err:
            return Response({"detail": err}, status=400)
        user.set_password(new_password)
    user.save()
    if new_password:
        revoke_user_refresh_tokens(user)
    audit(request, "profile_update", "self")
    return Response(UserSerializer(user, context={"request": request}).data)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@rate_limit("verify_request", rate=5, per_seconds=600, key="ip_email")
def request_verification(request):
    """(Re)send the email-verification link for an account with a 60s cooldown and daily cap."""
    from django.core.cache import cache
    from . import email_service

    email = str((request.data or {}).get("email") or "").strip().lower()
    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if user and not user.email_verified:
        cd_key = f"rl:verify_cd:{user.email}"
        day_key = f"rl:verify_day:{user.email}"
        if cache.get(cd_key):
            resp = Response(
                {
                    "detail": "If that account exists, a verification link has been sent.",
                    "cooldown": True,
                    "retry_after": 60,
                },
                status=429,
            )
            resp["Retry-After"] = "60"
            return resp
        daily_sent = int(cache.get(day_key) or 0)
        if daily_sent >= 10:
            resp = Response(
                {"detail": "Daily verification email limit reached. Try again tomorrow."},
                status=429,
            )
            resp["Retry-After"] = "3600"
            return resp
        cache.set(cd_key, 1, timeout=60)
        cache.set(day_key, daily_sent + 1, timeout=86400)
        tok, raw = OneTimeToken.issue(user, "verify_email", minutes=60 * 24)
        email_service.send_auth_email(
            user,
            "verify",
            company_name=user.company.name if user.company else "your workspace",
            url=_frontend_url("/auth/verify?token=" + raw),
        )
    # Same response either way on initial call: never reveal whether an email exists.
    return Response({"detail": "If that account exists, a verification link has been sent."})


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@rate_limit("verify_confirm", rate=10, per_seconds=600, key="ip")
def verify_email(request):
    """Consume a verification token and mark the account verified."""
    raw = str((request.data or {}).get("token") or "")
    tok = OneTimeToken.consume(raw, "verify_email")
    if not tok:
        return Response({"detail": "This verification link is invalid or has expired."}, status=400)
    if not tok.user.email_verified:
        tok.user.email_verified = True
        tok.user.save(update_fields=["email_verified"])
    return Response({"detail": "Email verified. You can sign in now."})


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@rate_limit("forgot", rate=5, per_seconds=600, key="ip_email")
def forgot_password(request):
    """Email a one-time password-reset link (never reveals account existence)."""
    from . import email_service

    from django.core.cache import cache

    email = str((request.data or {}).get("email") or "").strip().lower()
    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if user:
        # AUTHN-11: per-account cooldown and daily cap, independent of the IP.
        # A throttled request gets the same 200 body so nothing is revealed.
        cd_key = f"rl:reset_cd:{user.pk}"
        day_key = f"rl:reset_day:{user.pk}"
        if cache.add(cd_key, 1, timeout=60) and int(cache.get(day_key) or 0) < 10:
            cache.set(day_key, int(cache.get(day_key) or 0) + 1, timeout=86400)
            tok, raw = OneTimeToken.issue(user, "password_reset", minutes=30)
            email_service.send_auth_email(
                user,
                "reset",
                url=_frontend_url("/auth/reset?token=" + raw),
            )
    return Response({"detail": "If that account exists, a reset link has been sent."})


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@rate_limit("reset_confirm", rate=10, per_seconds=600, key="ip")
def reset_password(request):
    """Consume a reset token and set a new password."""
    from . import email_service

    raw = str((request.data or {}).get("token") or "")
    password = str((request.data or {}).get("password") or "")
    # AUTHN-12: validate the new password first; a rejected password must not
    # burn the link. consume() below stays the atomic single-use gate.
    peeked = OneTimeToken.peek(raw, "password_reset")
    if not peeked:
        return Response({"detail": "This reset link is invalid or has expired."}, status=400)
    err = _password_error(password, peeked.user)
    if err:
        return Response({"detail": err}, status=400)
    tok = OneTimeToken.consume(raw, "password_reset")
    if not tok:
        return Response({"detail": "This reset link is invalid or has expired."}, status=400)
    tok.user.set_password(password)
    tok.user.email_verified = True  # a working reset link proves mailbox ownership
    tok.user.save(update_fields=["password", "email_verified"])
    # AUTHN-05: any other reset link still sitting in the mailbox dies with this one.
    # S7-03: an outstanding invitation is also a way to set a password, so a
    # recovery must retire it as well.
    OneTimeToken.objects.filter(
        user=tok.user, purpose__in=("password_reset", "invite"), used_at__isnull=True,
    ).update(used_at=timezone.now())
    revoke_user_refresh_tokens(tok.user)
    from .ratelimit import clear_login_failures
    clear_login_failures(tok.user.email)
    email_service.send_auth_email(tok.user, "password_changed")
    return Response({"detail": "Password updated. You can sign in now."})


def verify_google_id_token(credential: str) -> dict:
    """Cryptographically verify a Google ID token against Google's JWKS.

    Checks RS256 signature, `aud` against `settings.GOOGLE_CLIENT_ID`, `iss`
    (`accounts.google.com` or `https://accounts.google.com`), and `exp` with 30s
    clock-skew leeway. Never trusts client-decoded claims.
    """
    import jwt
    from jwt import PyJWKClient

    client_id = getattr(settings, "GOOGLE_CLIENT_ID", "").strip()
    if not client_id:
        raise ValueError("Google Sign-In is not configured on this server (missing GOOGLE_CLIENT_ID).")
    if not credential or not isinstance(credential, str):
        raise ValueError("Missing Google ID token.")

    jwk_client = PyJWKClient(
        "https://www.googleapis.com/oauth2/v3/certs",
        cache_keys=True,
        lifespan=3600,
    )
    signing_key = jwk_client.get_signing_key_from_jwt(credential)
    claims = jwt.decode(
        credential,
        signing_key.key,
        algorithms=["RS256"],
        audience=client_id,
        issuer=["accounts.google.com", "https://accounts.google.com"],
        leeway=30,
    )
    return claims


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@rate_limit("google_auth", rate=10, per_seconds=60, key="ip")
def google_auth(request):
    """Sign in or sign up with a verified Google ID token (Path C).

    Rules:
      - Google must assert `email_verified == True`.
      - The Google account is identified by `sub` (AUTHN-01). An account
        already bound to a `sub` is signed in by it. Otherwise an account with
        the same email is linked on first use, unless it is bound to a
        different `sub` (403). Linking an unverified password account first
        invalidates that password and its sessions (pre-hijack guard).
      - New user: creates account with unusable password + `email_verified=True`
        and `company=None`, sets session cookies, and returns
        `onboarding_required: True` so the frontend displays the Create/Join screen.
    """
    credential = str((request.data or {}).get("credential") or "").strip()
    if not credential:
        return Response({"detail": "Google credential token is required."}, status=400)
    try:
        claims = verify_google_id_token(credential)
    except Exception as exc:
        logger.info("Google ID token rejected: %s", type(exc).__name__)
        return Response({"detail": "Invalid or expired Google sign-in token."}, status=401)

    email = str(claims.get("email") or "").strip().lower()
    email_verified = claims.get("email_verified") in (True, "true", "True", 1)
    full_name = str(claims.get("name") or "").strip()[:200]
    if not email or not email_verified:
        return Response(
            {"detail": "Your Google account email is not verified by Google."},
            status=403,
        )
    from .serializers import ascii_email_error
    email_err = ascii_email_error(email)
    if email_err:
        return Response({"detail": email_err}, status=400)

    # AUTHN-01: the Google account is identified by `sub`, never by email alone.
    sub = str(claims.get("sub") or "").strip()[:255]
    if not sub:
        return Response({"detail": "Invalid or expired Google sign-in token."}, status=401)

    from django.db import IntegrityError, transaction
    user = User.objects.select_related("company").filter(google_sub=sub).first()
    if user is None:
        user = User.objects.select_related("company").filter(email__iexact=email).first()
        if user is not None and user.google_sub and user.google_sub != sub:
            audit(request, "login_google_denied", "email bound to a different Google account",
                  outcome="denied", target_type="user", target_id=str(user.id), user=user)
            return Response(
                {"detail": "This email is linked to a different Google account. "
                           "Sign in with that account or with your password."},
                status=403,
            )
    created_new = False
    if user is not None:
        if not user.is_active:
            return Response({"detail": "This account has been deactivated. Contact your administrator."}, status=403)
        updates = []
        invalidated_password = False
        if not user.google_sub:
            if not user.email_verified and user.has_usable_password():
                # Pre-hijack guard: nobody proved ownership of this mailbox when
                # the password was set, so that password must not survive the
                # real owner signing in with Google.
                user.set_unusable_password()
                updates.append("password")
                invalidated_password = True
            user.google_sub = sub
            updates.append("google_sub")
        if not user.email_verified:
            user.email_verified = True
            updates.append("email_verified")
        if full_name and not user.full_name:
            user.full_name = full_name
            updates.append("full_name")
        if updates:
            try:
                with transaction.atomic():
                    user.save(update_fields=updates)
            except IntegrityError:
                return Response({"detail": "Google sign-in is already in progress for this account. "
                                           "Try again."}, status=409)
        if invalidated_password:
            revoke_user_refresh_tokens(user)
            audit(request, "google_link_password_invalidated", "unverified password account linked to Google",
                  target_type="user", target_id=str(user.id), user=user)
        if _is_platform_level(user):
            from . import mfa
            if not user.mfa_enabled:
                secret = mfa.generate_secret()
                return Response({
                    "mfa_required": True,
                    "enrollment": {
                        "secret": secret,
                        "uri": mfa.provisioning_uri(secret, user.email),
                    },
                    "challenge": mfa.issue_challenge(user.pk, "enroll", secret=secret),
                })
            return Response({"mfa_required": True, "challenge": mfa.issue_challenge(user.pk, "login")})
    else:
        created_new = True
        user = User(
            email=email,
            full_name=full_name,
            role="employee",
            email_verified=True,
            company=None,
            google_sub=sub,
        )
        user.set_unusable_password()
        try:
            with transaction.atomic():
                user.save()
        except IntegrityError:
            return Response({"detail": "Google sign-in is already in progress for this account. "
                                       "Try again."}, status=409)

    needs_onboarding = not _is_platform_level(user) and user.company_id is None
    if user.company_id:
        audit(_as(request, user), "login_google")
    resp = Response(
        {
            "user": UserSerializer(user).data,
            "onboarding_required": needs_onboarding,
        },
        status=201 if created_new else 200,
    )
    return set_auth_cookies(resp, user)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@rate_limit("join", rate=8, per_seconds=300, key="ip")
def join_company(request):
    """Accept a 7-day email-bound single-use admin invitation token.

    Public self-join via company access_code is intentionally disabled so a
    leaked company code can never let an uninvited person join a workspace.
    """
    import hashlib
    import hmac
    from . import email_service

    data = request.data or {}
    invite_raw = str(data.get("invite_token") or "").strip()
    email = str(data.get("email") or "").strip().lower()
    password = str(data.get("password") or "")
    full_name = str(data.get("full_name") or "").strip()[:200]

    if not invite_raw:
        return Response(
            {"detail": "Joining a workspace requires a personal invitation link from your company administrator."},
            status=400,
        )
    if not email or "@" not in email:
        return Response({"detail": "A valid work email is required."}, status=400)

    token_hash = hashlib.sha256(invite_raw.encode()).hexdigest()
    tok = OneTimeToken.objects.select_related("user", "user__company").filter(
        token_hash=token_hash, purpose="invite"
    ).first()
    if not tok or not tok.is_valid():
        return Response({"detail": "This invitation link is invalid or has expired."}, status=400)
    target_user = tok.user
    if not hmac.compare_digest(target_user.email.lower(), email.lower()):
        return Response(
            {"detail": "This invitation link was issued for a different email address."},
            status=400,
        )
    # S7-03: an invitation only completes a *pending* account (admin-created,
    # no password yet). It is never a way to replace an existing password
    # (e.g. after a recovery), and never a way into a platform-level account,
    # which must go through the TOTP login.
    if _is_platform_level(target_user) or not target_user.is_active or target_user.has_usable_password():
        return Response({"detail": "This invitation link is invalid or has expired."}, status=400)
    err = _password_error(password, target_user)
    if err:
        return Response({"detail": err}, status=400)
    consumed = OneTimeToken.consume(invite_raw, "invite")
    if not consumed:
        return Response({"detail": "This invitation link has already been used."}, status=400)
    target_user.set_password(password)
    target_user.email_verified = True
    if full_name:
        target_user.full_name = full_name
    target_user.save(update_fields=["password", "email_verified", "full_name"])
    # Any session that existed before the password was set is now stale.
    revoke_user_refresh_tokens(target_user)
    if target_user.company_id:
        audit(_as(request, target_user), "invite_accepted", target_user.email)
        email_service.send_auth_email(
            target_user, "welcome", company_name=target_user.company.name
        )
    resp = Response({"user": UserSerializer(target_user).data}, status=200)
    return set_auth_cookies(resp, target_user)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def onboard_company(request):
    """Complete post-Google organization creation (becomes company admin)."""
    from django.db import transaction
    from . import email_service

    user = request.user
    if _is_platform_level(user):
        # AUTHZ-04: platform/root admins must never join a tenant.
        return Response({"detail": "Platform admins cannot create or join a company."}, status=403)
    if user.company_id:
        return Response({"user": UserSerializer(user).data, "onboarding_required": False})

    data = request.data or {}
    full_name = str(data.get("full_name") or "").strip()[:200]
    if full_name and not user.full_name:
        user.full_name = full_name

    company_name = str(data.get("company_name") or "").strip()[:200]
    if not company_name:
        return Response({"detail": "Company name is required."}, status=400)
    base = slugify(company_name) or "company"
    slug, n = base, 1
    while Company.objects.filter(slug=slug).exists():
        n += 1
        slug = f"{base}-{n}"
    with transaction.atomic():
        company = Company.objects.create(
            name=company_name,
            slug=slug,
            plan=Plan.default(),
            enable_team_chat=False,
            enable_attendance=False,
        )
        user.company = company
        user.role = "admin"
        user.save(update_fields=["company", "role", "full_name"])
        AuditLog.objects.create(
            company=company,
            user=user,
            action="register",
            outcome="allowed",
            target_type="company",
            target_id=str(company.id),
            detail=f"company {company.name} (google)",
            ip=client_ip(request),
        )
    email_service.send_auth_email(user, "welcome", company_name=company.name)
    resp = Response({"user": UserSerializer(user).data, "onboarding_required": False}, status=201)
    return set_auth_cookies(resp, user)


# --------------------------------------------------------------- documents
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def documents(request):
    _guard = _platform_admin_blocked(request)
    if _guard:
        return _guard
    """List documents readable by this member. Paginated with ?page=&page_size="""
    # select_related matches DocumentSerializer's FK traversal (company name,
    # department name) so a 200-row page costs 1 query, not 400.
    qs = (visible_documents(request.user)
          .select_related("company", "department")
          .order_by("-created_at"))
    page_data = _paginate(request, qs)
    resp_data = {
        "results": DocumentSerializer(page_data["qs"], many=True).data,
        "count": page_data["count"],
        "page": page_data["page"],
        "pages": page_data["pages"],
    }
    if access.is_company_admin(request.user):
        masked_qs = (
            access.admin_restricted_metadata_qs(request.user)
            .select_related("company", "department")
            .order_by("-created_at")[:100]
        )
        resp_data["restricted_metadata"] = [_masked_doc_payload(d) for d in masked_qs]
    return Response(resp_data)


def _paginate(request, qs, default_page_size=50, max_page_size=200):
    """Minimal pagination helper shared by list endpoints."""
    try:
        page = max(1, int(request.query_params.get("page", 1)))
        page_size = min(max_page_size, max(1, int(request.query_params.get("page_size", default_page_size))))
    except (TypeError, ValueError):
        page, page_size = 1, default_page_size
    count = qs.count()
    pages = max(1, -(-count // page_size))
    return {"qs": qs[(page - 1) * page_size: page * page_size],
            "count": count, "page": page, "pages": pages}


def _storage_used(company):
    """Bytes stored for a company: current files plus retained old versions (AUTHZ-06)."""
    current = company.documents.aggregate(total=Sum("size"))["total"] or 0
    old = DocumentVersion.objects.filter(document__company=company).aggregate(total=Sum("size"))["total"] or 0
    return current + old


def _plan_for(company):
    """The company's plan, guaranteed non-null for limit checks."""
    return company.plan or Plan.default()


def _parse_doc_governance_fields(request, company, *, access_scope: str = "company", department_id=None):
    """Parse sensitivity and approval status for upload_document / upload_confirm."""
    sensitivity = str(request.data.get("sensitivity") or "standard").strip().lower()
    if sensitivity not in {"standard", "internal", "confidential"}:
        return None, None, Response({"detail": "sensitivity must be standard, internal or confidential."}, status=400)
    is_adm = access.is_company_admin(request.user)
    is_own_dept_mgr = bool(
        access.is_dept_manager(request.user)
        and access_scope == "department"
        and department_id
        and int(department_id) == request.user.department_id
    )
    if sensitivity == "confidential" and not is_adm:
        return None, None, Response({"detail": "Only company admins can upload confidential documents."}, status=403)

    can_auto_approve = is_adm or (is_own_dept_mgr and sensitivity != "confidential")
    default_status = (
        "in_review"
        if (getattr(company, "require_doc_approval", False) and not can_auto_approve)
        else "approved"
    )
    doc_status = str(request.data.get("status") or default_status).strip().lower()
    if doc_status not in {"draft", "in_review", "approved"}:
        return None, None, Response({"detail": "status must be draft, in_review or approved."}, status=400)
    if getattr(company, "require_doc_approval", False) and doc_status == "approved" and not can_auto_approve:
        doc_status = "in_review"
    return sensitivity, doc_status, None


@api_view(["POST"])
@permission_classes([IsEditor])
def upload_document(request):
    _guard = _platform_admin_blocked(request)
    if _guard:
        return _guard
    """Upload + index a file. Indexing runs in a background thread so the
    request returns immediately with indexing_status='pending'."""
    f = request.FILES.get("file")
    if not f:
        return Response({"detail": "No file provided."}, status=400)
    max_size = getattr(settings, "DATA_UPLOAD_MAX_MEMORY_SIZE", 50 * 1024 * 1024)
    if f.size > max_size:
        return Response({"detail": f"File too large. Max size is {max_size // (1024*1024)} MB."},
                        status=413)
    rejected = _upload_rejection(f)
    if rejected:
        return rejected

    is_okf = _parse_bool(request.data.get("is_okf"), False)
    access_scope = (request.data.get("access_scope") or "company").strip().lower()
    if access_scope not in {"company", "restricted", "department"}:
        return Response({"detail": "access_scope must be company, department or restricted."},
                        status=400)
    category = request.data.get("category") or "Other"
    description = request.data.get("description") or ""
    tags = str(request.data.get("tags") or "").strip()[:300]
    is_template = _parse_bool(request.data.get("is_template"), False)
    template_type = str(request.data.get("template_type") or "").strip().lower()
    if template_type and template_type not in dict(Document.TEMPLATE_TYPES):
        return Response({"detail": "template_type must be email, form, policy or other."},
                        status=400)
    if is_template and not template_type:
        template_type = "other"

    company = request.user.company
    if company is None:
        return Response(
            {"detail": "Your account is not attached to a company. Platform admins must pick an "
                       "active company (use the company switcher in the sidebar) before uploading."},
            status=400,
        )

    plan = _plan_for(company)
    # Department scope needs a department (default: the uploader's own).
    department = None
    if access_scope == "department":
        dept_id = request.data.get("department_id")
        if dept_id:
            department = Department.objects.filter(pk=dept_id, company=company).first()
            if department is None:
                return Response({"detail": "Pick a valid department in your company."}, status=400)
        if department is None and request.user.department_id:
            department = request.user.department
        if department is None:
            return Response({"detail": "Pick a department (or join one) to use department scope."},
                            status=400)
        if not (plan and plan.allow_departments):
            return Response({"detail": "Department scoping is not part of your current plan."},
                            status=402)

    sensitivity, doc_status, gov_err = _parse_doc_governance_fields(
        request, company, access_scope=access_scope, department_id=department.id if department else None,
    )
    if gov_err:
        return gov_err

    up_dec = access.decide(
        request.user, "upload",
        context={
            "access_scope": access_scope,
            "sensitivity": sensitivity,
            "department_id": department.id if department else None,
            "is_okf": is_okf,
            "is_template": is_template,
        },
    )
    if not up_dec.allowed:
        audit(request, "upload_denied", up_dec.reason_code, outcome="denied")
        code = 402 if up_dec.reason_code == "DENY_PLAN_LIMIT" else 403
        return Response({"detail": up_dec.rule_chain[-1], "reason_code": up_dec.reason_code}, status=code)

    # Plan limits: document count and storage quota (server-enforced).
    if plan:
        if plan.max_documents is not None and company.documents.count() >= plan.max_documents:
            return Response({"detail": f"Plan limit reached ({plan.max_documents} documents). "
                                       "Upgrade your plan to upload more."}, status=402)
        if plan.storage_mb is not None:
            used = _storage_used(company)
            if used + f.size > plan.storage_mb * 1024 * 1024:
                return Response({"detail": "Storage quota for your plan is full. "
                                           "Upgrade to upload more."}, status=402)

    # Django's UploadedFile.name setter silently truncates names to 255 chars,
    # so the raw-length check cannot catch long names here — validate the
    # storage key instead (uuid prefix + slug + name must fit one FS component).
    safe_name = os.path.basename(f.name)
    rel_key = os.path.join(company.slug, f"{uuid.uuid4().hex}_{safe_name}")
    if len(os.path.basename(rel_key)) > 255:
        return Response({"detail": "Filename is too long. Use a name of up to 220 characters."},
                        status=400)
    stored = storage.save_uploaded_file(rel_key, f, base_dir=settings.DATA_DIR)

    from django.db import transaction
    with transaction.atomic():
        doc = Document.objects.create(
            company=company, filename=safe_name, stored_path=stored,
            content_type=content_type_for(safe_name), size=f.size,
            category=category, description=description, tags=tags,
            is_okf=is_okf, access_scope=access_scope, department=department,
            sensitivity=sensitivity, status=doc_status,
            is_template=is_template, template_type=template_type,
            uploaded_by=request.user, indexing_status="pending",
        )
        DocumentAccess.objects.create(document=doc, user=request.user)
        audit(
            request, "upload", _safe_doc_label(doc),
            outcome="allowed", target_type="document", target_id=str(doc.id), fail_closed=True,
        )

    _index_in_background(doc)
    payload = dict(DocumentSerializer(doc).data)
    if getattr(settings, "IS_VERCEL", False) and not storage.is_s3_enabled():
        payload["ephemeral_notice"] = (
            "Beta demo upload (Vercel): uploaded files are capped at 4.5 MB and "
            "automatically deleted after 24 hours. Production deployments connect S3/R2 for permanent storage."
        )
    return Response(payload, status=201)


@api_view(["POST"])
@permission_classes([IsEditor])
def upload_presign(request):
    _guard = _platform_admin_blocked(request)
    if _guard:
        return _guard
    """Return a presigned S3 PUT URL so the browser can upload large files (>4.5 MB)
    directly to S3 without hitting Vercel's serverless request body limit."""
    if not storage.is_s3_enabled():
        return Response({"detail": "Direct S3 upload is not enabled on this server."}, status=400)
    filename = os.path.basename(str(request.data.get("filename") or "").strip())
    if not filename:
        return Response({"detail": "filename is required."}, status=400)
    try:
        filename = validate_filename(filename)
        validate_extension(filename)
    except UploadRejected as exc:
        return Response({"detail": str(exc)}, status=400)
    try:
        size = int(request.data.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    if size <= 0:
        # AI-04: the size is signed into the URL, so it must always be present.
        return Response({"detail": "size (bytes) is required."}, status=400)
    max_size = getattr(settings, "DATA_UPLOAD_MAX_MEMORY_SIZE", 50 * 1024 * 1024)
    if size > max_size:
        return Response({"detail": f"File too large. Max size is {max_size // (1024*1024)} MB."}, status=413)
    company = request.user.company
    if company is None:
        return Response({"detail": "Your account is not attached to a company."}, status=400)
    content_type = content_type_for(filename)
    key = f"{company.slug}/{uuid.uuid4().hex}_{filename}"
    url = storage.generate_presigned_put(key, content_type=content_type, size=size)
    PendingUpload.objects.create(
        company=company,
        user=request.user,
        key=key,
        filename=filename,
        size=max(0, size),
        expires_at=timezone.now() + timedelta(minutes=15),
    )
    return Response({"upload_url": url, "key": key, "filename": filename, "content_type": content_type})


@api_view(["POST"])
@permission_classes([IsEditor])
def upload_confirm(request):
    _guard = _platform_admin_blocked(request)
    if _guard:
        return _guard
    """Confirm a direct-to-S3 upload, create the Document row, and trigger indexing."""
    if not storage.is_s3_enabled():
        return Response({"detail": "Direct S3 upload is not enabled on this server."}, status=400)
    key = str(request.data.get("key") or "").strip().lstrip("/")
    company = request.user.company
    if company is None or not key or ".." in key or "\\" in key or not key.startswith(f"{company.slug}/"):
        return Response({"detail": "Invalid storage key for your company."}, status=400)

    # Server-side key binding: key must match an unconsumed, unexpired PendingUpload issued to this exact user.
    pending = (
        PendingUpload.objects.filter(
            key=key, company=company, user=request.user, consumed=False,
        )
        .filter(expires_at__gt=timezone.now())
        .first()
    )
    if pending is None or Document.objects.filter(stored_path=key).exists():
        audit(request, "upload_confirm_denied", "invalid_or_unowned_key", outcome="denied")
        return Response({"detail": "Upload session expired or storage key is invalid."}, status=403)

    # S7-05: the name (and so the type and byte signature that are checked)
    # is the one authorised at presign time. A client-supplied name here is
    # ignored, so renaming cannot move an object to a weaker type check.
    filename = pending.filename
    try:
        validate_filename(filename)
        validate_extension(filename)
    except UploadRejected as exc:
        return Response({"detail": str(exc)}, status=400)

    real_size = storage.object_size(key)
    if real_size is None:
        return Response({"detail": "Uploaded object not found in storage."}, status=404)

    def _discard(detail, code):
        # AI-04: an object confirm refuses for what it *is* (size, bytes,
        # quota) can never become a document, so it is deleted now rather than
        # left for the expiry sweep. Fixable request-field errors below keep
        # the object so the client can retry before the session expires.
        # S7-06: only burn the pending row once the object is really gone. If
        # the delete failed the row stays (unconsumed, and it expires on its
        # own), so the expiry sweep retries instead of forgetting the object.
        if storage.delete_checked(key):
            PendingUpload.objects.filter(pk=pending.pk).update(consumed=True)
        audit(request, "upload_confirm_rejected", detail[:120], outcome="denied")
        return Response({"detail": detail}, status=code)

    max_size = getattr(settings, "DATA_UPLOAD_MAX_MEMORY_SIZE", 50 * 1024 * 1024)
    if real_size <= 0 or real_size > max_size:
        return _discard("Uploaded object is empty or exceeds the size limit.", 400)

    # AI-07: byte-check the direct upload with a ranged GET of its first 2 KB.
    try:
        validate_magic(filename, storage.object_head(key, 2048))
    except UploadRejected as exc:
        return _discard(str(exc), 400)
    except Exception:
        logger.exception("Could not read the head of uploaded object for confirm")
        return Response({"detail": "The uploaded file could not be verified. Try again."}, status=502)

    size = real_size
    plan = _plan_for(company)
    if plan:
        if plan.max_documents is not None and company.documents.count() >= plan.max_documents:
            return _discard(f"Plan limit reached ({plan.max_documents} documents). "
                            "Upgrade your plan to upload more.", 402)
        if plan.storage_mb is not None:
            used = _storage_used(company)
            if used + size > plan.storage_mb * 1024 * 1024:
                return _discard("Storage quota for your plan is full. Upgrade to upload more.", 402)

    content_type = content_type_for(filename)
    is_okf = _parse_bool(request.data.get("is_okf"), False)
    access_scope = (request.data.get("access_scope") or "company").strip().lower()
    if access_scope not in {"company", "restricted", "department"}:
        return Response({"detail": "access_scope must be company, department or restricted."}, status=400)
    category = request.data.get("category") or "Other"
    description = request.data.get("description") or ""
    tags = str(request.data.get("tags") or "").strip()[:300]
    is_template = _parse_bool(request.data.get("is_template"), False)
    template_type = str(request.data.get("template_type") or "").strip().lower()
    if template_type and template_type not in dict(Document.TEMPLATE_TYPES):
        return Response({"detail": "template_type must be email, form, policy or other."},
                        status=400)
    if is_template and not template_type:
        template_type = "other"

    department = None
    if access_scope == "department":
        dept_id = request.data.get("department_id")
        if dept_id:
            department = Department.objects.filter(pk=dept_id, company=company).first()
            if department is None:
                return Response({"detail": "Pick a valid department in your company."}, status=400)
        if department is None and request.user.department_id:
            department = request.user.department
        if department is None:
            return Response({"detail": "Pick a department (or join one) to use department scope."}, status=400)
        if not (plan and plan.allow_departments):
            return Response({"detail": "Department scoping is not part of your current plan."}, status=402)

    sensitivity, doc_status, gov_err = _parse_doc_governance_fields(
        request, company, access_scope=access_scope, department_id=department.id if department else None,
    )
    if gov_err:
        return gov_err

    up_dec = access.decide(
        request.user, "upload",
        context={
            "access_scope": access_scope,
            "sensitivity": sensitivity,
            "department_id": department.id if department else None,
            "is_okf": is_okf,
            "is_template": is_template,
        },
    )
    if not up_dec.allowed:
        audit(request, "upload_denied", up_dec.reason_code, outcome="denied")
        code = 402 if up_dec.reason_code == "DENY_PLAN_LIMIT" else 403
        return Response({"detail": up_dec.rule_chain[-1], "reason_code": up_dec.reason_code}, status=code)

    from django.db import transaction
    with transaction.atomic():
        locked_pending = (
            PendingUpload.objects.select_for_update()
            .filter(pk=pending.pk, consumed=False)
            .first()
        )
        if locked_pending is None:
            return Response({"detail": "Upload key has already been confirmed."}, status=409)
        locked_pending.consumed = True
        locked_pending.save(update_fields=["consumed"])
        doc = Document.objects.create(
            company=company, filename=filename, stored_path=key,
            content_type=content_type, size=size,
            category=category, description=description, tags=tags,
            is_okf=is_okf, access_scope=access_scope, department=department,
            sensitivity=sensitivity, status=doc_status,
            is_template=is_template, template_type=template_type,
            uploaded_by=request.user, indexing_status="pending",
        )
        DocumentAccess.objects.create(document=doc, user=request.user)
        audit(
            request, "upload", _safe_doc_label(doc),
            outcome="allowed", target_type="document", target_id=str(doc.id), fail_closed=True,
        )

    _index_in_background(doc)
    payload = dict(DocumentSerializer(doc).data)
    if getattr(settings, "IS_VERCEL", False) and not storage.is_s3_enabled():
        payload["ephemeral_notice"] = (
            "Beta demo upload (Vercel): uploaded files are capped at 4.5 MB and "
            "automatically deleted after 24 hours. Production deployments connect S3/R2 for permanent storage."
        )
    return Response(payload, status=201)


_INDEX_LOCK = threading.BoundedSemaphore(4)


def _index_in_background(doc: Document):
    """Extract/chunk/embed a document. Prefers the Celery worker when a broker
    is configured; on serverless platforms (SYNC_INDEXING=True) it runs inline
    before returning; otherwise it runs on a daemon thread: Stage 1 chunks land
    immediately without waiting for locks, while Stage 2 embedding uses bounded
    concurrency so uploads never contend on SQLite or thrash local Ollama."""
    if getattr(settings, "CELERY_BROKER_URL", "") and not getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        from .tasks import index_document_task
        index_document_task.delay(doc.id)
        return

    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        # Eager mode (tests / single-box debug): execute the task inline.
        from .tasks import index_document_task
        index_document_task.apply(args=[doc.id])
        doc.refresh_from_db()
        return

    def run():
        from django.db import close_old_connections
        close_old_connections()
        rows, pieces = [], []
        try:
            raw = storage.read_bytes(doc.stored_path, base_dir=settings.DATA_DIR)
            rows, pieces = rag.prepare_document_chunks(doc, raw)
            if not rows:
                doc.indexing_status = "ready"
                doc.index_error = ""
                if Document.objects.filter(pk=doc.pk).exists():
                    doc.save(update_fields=["indexing_status", "index_error"])
                return
        except Exception as exc:
            doc.indexing_status = "failed"
            doc.index_error = index_error_message(exc)
            try:
                if Document.objects.filter(pk=doc.pk).exists():
                    doc.save(update_fields=["indexing_status", "index_error"])
            except Exception:
                pass
            if not getattr(settings, "SYNC_INDEXING", False):
                close_old_connections()
            return

        with _INDEX_LOCK:
            close_old_connections()
            try:
                rag.attach_document_embeddings(doc, rows, pieces)
                doc.indexing_status = "ready"
                doc.index_error = ""
            except Exception as exc:
                doc.indexing_status = "failed"
                doc.index_error = index_error_message(exc)
            finally:
                try:
                    if Document.objects.filter(pk=doc.pk).exists():
                        doc.save(update_fields=["indexing_status", "index_error"])
                except Exception:
                    pass
                if not getattr(settings, "SYNC_INDEXING", False):
                    close_old_connections()

    if getattr(settings, "SYNC_INDEXING", False):
        run()
        return

    try:
        threading.Thread(target=run, daemon=True).start()
    except Exception:
        # Thread creation failed (rare): index inline so the doc is searchable.
        raw = storage.read_bytes(doc.stored_path, base_dir=settings.DATA_DIR)
        rag.index_document(doc, raw)
        doc.indexing_status = "ready"
        doc.save(update_fields=["indexing_status"])


@api_view(["POST"])
@permission_classes([IsEditor])
def document_reindex(request, pk):
    _guard = _platform_admin_blocked(request)
    if _guard:
        return _guard
    """Retry indexing for a failed/pending document."""
    doc = _get_doc(request, pk)
    dec = access.decide(request.user, "reindex", doc)
    if not dec.allowed:
        read_ok = access.decide(request.user, "view_ask", doc, context={"include_unapproved": True}).allowed
        audit(request, "reindex_denied", f"{_safe_doc_label(doc)} {dec.reason_code}",
              outcome="denied", target_type="document", target_id=str(doc.id))
        if not read_ok and not access.is_company_admin(request.user):
            raise Http404
        return Response({"detail": dec.rule_chain[-1], "reason_code": dec.reason_code}, status=403)
    if doc.indexing_status != "failed":
        return Response({"detail": "Only failed documents can be re-indexed."}, status=400)
    doc.indexing_status = "pending"
    doc.save(update_fields=["indexing_status"])
    _index_in_background(doc)
    audit(request, "reindex", _safe_doc_label(doc), target_type="document", target_id=str(doc.id))
    return Response(DocumentSerializer(doc).data)


@api_view(["POST"])
@permission_classes([IsAdmin])
def document_break_glass(request, pk):
    """Audited break-glass self-grant for a company admin on an own-company restricted document."""
    _guard = _platform_admin_blocked(request)
    if _guard:
        return _guard
    doc = _get_doc(request, pk)
    reason = str((request.data or {}).get("reason") or "").strip()[:300]
    dec = access.decide(request.user, "break_glass", doc, context={"reason": reason})
    if not dec.allowed:
        audit(
            request, "break_glass", f"doc#{doc.id} {dec.reason_code}",
            outcome="denied", target_type="document", target_id=str(doc.id),
        )
        code = 400 if dec.reason_code in ("DENY_REASON_REQUIRED", "DENY_NOT_RESTRICTED") else 403
        return Response({"detail": dec.rule_chain[-1], "reason_code": dec.reason_code}, status=code)
    from django.db import transaction
    with transaction.atomic():
        DocumentAccess.objects.update_or_create(
            document=doc,
            user=request.user,
            defaults={
                "can_download": True,
                "override_clearance": False,
                "grant_reason": reason,
                "granted_by": request.user,
                "is_break_glass": True,
            },
        )
        audit(
            request, "break_glass", f"doc#{doc.id} reason={reason[:200]}",
            outcome="allowed", target_type="document", target_id=str(doc.id), fail_closed=True,
        )
    return Response(DocumentSerializer(doc).data, status=200)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def document_detail(request, pk):
    _guard = _platform_admin_blocked(request)
    if _guard:
        return _guard
    """Read metadata, edit (category/description/tags/scope), or delete a doc."""
    if request.method == "GET":
        doc = _accessible_doc(request, pk)
        return Response(DocumentSerializer(doc).data)

    # Mutations are strictly own-company only (external share recipients get 404).
    doc = _get_doc(request, pk)
    if request.method == "DELETE":
        dec = access.decide(request.user, "delete", doc)
        if not dec.allowed:
            read_ok = access.decide(request.user, "view_ask", doc, context={"include_unapproved": True}).allowed
            audit(request, "delete_denied", f"{_safe_doc_label(doc)} {dec.reason_code}",
                  outcome="denied", target_type="document", target_id=str(doc.id))
            if not read_ok and not access.is_company_admin(request.user):
                raise Http404
            return Response({"detail": dec.rule_chain[-1], "reason_code": dec.reason_code}, status=403)
        paths = {doc.stored_path}
        paths.update(DocumentVersion.objects.filter(document=doc)
                     .values_list("stored_path", flat=True))
        for path in paths:
            storage.delete(path, base_dir=settings.DATA_DIR)
        label = _safe_doc_label(doc)
        doc_id = doc.id
        from django.db import transaction
        with transaction.atomic():
            audit(
                request, "delete", label,
                outcome="allowed", target_type="document", target_id=str(doc_id), fail_closed=True,
            )
            doc.delete()
        return Response(status=204)

    # PATCH
    edit_dec = access.decide(request.user, "edit_metadata", doc)
    if not edit_dec.allowed:
        read_ok = access.decide(request.user, "view_ask", doc, context={"include_unapproved": True}).allowed
        audit(request, "document_update_denied", f"{_safe_doc_label(doc)} {edit_dec.reason_code}",
              outcome="denied", target_type="document", target_id=str(doc.id))
        if not read_ok and not access.is_company_admin(request.user):
            raise Http404
        return Response({"detail": edit_dec.rule_chain[-1], "reason_code": edit_dec.reason_code}, status=403)

    data = request.data or {}
    before = (doc.access_scope, doc.sensitivity, doc.status, doc.legal_hold, doc.department_id)

    if any(k in data for k in ("is_template", "template_type", "is_okf")):
        if not access.is_company_admin(request.user):
            return Response({"detail": "Only company admins can change template or OKF settings."}, status=403)
    if "is_okf" in data:
        doc.is_okf = _parse_bool(data.get("is_okf"), doc.is_okf)
    if "is_template" in data:
        doc.is_template = _parse_bool(data.get("is_template"), doc.is_template)
    if "template_type" in data:
        ttype = str(data.get("template_type") or "").strip().lower()
        if ttype and ttype not in dict(Document.TEMPLATE_TYPES):
            return Response({"detail": "template_type must be email, form, policy or other."},
                            status=400)
        doc.template_type = ttype

    if "legal_hold" in data:
        if not access.is_company_admin(request.user):
            return Response({"detail": "Only company admins can change legal hold."}, status=403)
        doc.legal_hold = _parse_bool(data.get("legal_hold"), doc.legal_hold)

    # Scope / sensitivity / department changes go through canonical decide("change_scope_sensitivity")
    if any(k in data for k in ("access_scope", "sensitivity", "department_id")):
        new_scope = str(data.get("access_scope") or doc.access_scope).strip().lower()
        if new_scope not in {"company", "restricted", "department"}:
            return Response({"detail": "access_scope must be company, department or restricted."}, status=400)
        new_sens = str(data.get("sensitivity") or doc.sensitivity).strip().lower()
        if new_sens not in {"standard", "internal", "confidential"}:
            return Response({"detail": "sensitivity must be standard, internal or confidential."}, status=400)
        new_dept = doc.department
        if new_scope == "department":
            dept_id = data.get("department_id", doc.department_id)
            new_dept = Department.objects.filter(pk=dept_id, company=doc.company).first() if dept_id else None
            if new_dept is None:
                return Response({"detail": "Pick a valid department for department scope."}, status=400)
        elif "department_id" in data and not data.get("department_id"):
            new_dept = None

        sc_dec = access.decide(
            request.user, "change_scope_sensitivity", doc,
            context={
                "new_scope": new_scope,
                "new_sensitivity": new_sens,
                "new_department_id": new_dept.id if new_dept else None,
            },
        )
        if not sc_dec.allowed:
            audit(request, "document_scope_denied", f"{_safe_doc_label(doc)} {sc_dec.reason_code}",
                  outcome="denied", target_type="document", target_id=str(doc.id))
            code = 402 if sc_dec.reason_code == "DENY_PLAN_LIMIT" else 403
            return Response({"detail": sc_dec.rule_chain[-1], "reason_code": sc_dec.reason_code}, status=code)

        if new_sens == "confidential" and doc.sensitivity != "confidential":
            DocumentAccess.objects.filter(document=doc, override_clearance=False).exclude(user__role="admin").delete()
        doc.access_scope = new_scope
        doc.sensitivity = new_sens
        doc.department = new_dept

    if "status" in data:
        new_status = str(data.get("status") or "").strip().lower()
        if new_status not in {"draft", "in_review", "approved", "archived"}:
            return Response({"detail": "status must be draft, in_review, approved or archived."}, status=400)
        if new_status != doc.status:
            if new_status == "in_review":
                if not _can_manage_document(request, doc):
                    return Response({"detail": "Only admins or the uploader can submit for review."}, status=403)
            else:
                st_action = {"approved": "approve", "archived": "archive", "draft": "reject"}[new_status]
                st_dec = access.decide(request.user, st_action, doc)
                if not st_dec.allowed:
                    audit(request, f"document_{st_action}_denied", f"{_safe_doc_label(doc)} {st_dec.reason_code}",
                          outcome="denied", target_type="document", target_id=str(doc.id))
                    return Response({"detail": st_dec.rule_chain[-1], "reason_code": st_dec.reason_code}, status=403)
                doc.reviewed_by = request.user
                doc.reviewed_at = timezone.now()
            doc.status = new_status

    if "category" in data:
        doc.category = str(data.get("category") or "Other")[:50]
    if "description" in data:
        doc.description = str(data.get("description") or "")[:2000]
    if "tags" in data:
        doc.tags = str(data.get("tags") or "").strip()[:300]

    after = (doc.access_scope, doc.sensitivity, doc.status, doc.legal_hold, doc.department_id)
    from django.db import transaction
    with transaction.atomic():
        doc.save()
        detail = _safe_doc_label(doc)
        if before != after:
            detail = f"{detail} scope:{before[0]}->{after[0]} sens:{before[1]}->{after[1]} status:{before[2]}->{after[2]} hold:{before[3]}->{after[3]}"
        audit(
            request, "document_update", detail,
            outcome="allowed", target_type="document", target_id=str(doc.id), fail_closed=True,
        )
    return Response(DocumentSerializer(doc).data)


def _is_editor_request(request):
    u = request.user
    if not getattr(u, "company_id", None):
        return False
    return bool(u.role in ("admin", "employee") or _is_platform_level(u))


def _can_approve_document(user, doc) -> bool:
    """True for company admins, platform admins in company, or dept sub-admin of doc's department."""
    if not getattr(user, "company_id", None) or doc.company_id != user.company_id:
        return False
    if _is_platform_level(user) or user.role == "admin":
        return True
    return bool(is_dept_admin(user) and doc.department_id and doc.department_id == user.department_id)


def _can_manage_document(request, doc):
    """True for platform level, company admins, department sub-admins (own dept), and the uploader."""
    u = request.user
    if not getattr(u, "company_id", None) or doc.company_id != u.company_id:
        return False
    # AUTHZ-09: submitting for review needs read access (break-glass for admins
    # on restricted docs), not just a role.
    if not access.decide(u, "view_ask", doc, context={"include_unapproved": True}).allowed:
        return False
    return bool(
        _is_platform_level(u)
        or u.role == "admin"
        or doc.uploaded_by_id == u.id
        or (is_dept_admin(u) and doc.department_id and doc.department_id == u.department_id)
    )


@api_view(["POST"])
@permission_classes([IsEditor])
def document_review(request, pk):
    """Transition a document through draft -> in_review -> approved / archived."""
    _guard = _platform_admin_blocked(request)
    if _guard:
        return _guard
    doc = _get_doc(request, pk)
    data = request.data or {}
    action = str(data.get("action") or "").strip().lower()
    note = str(data.get("note") or "").strip()[:300]
    action_to_status = {
        "submit": "in_review",
        "approve": "approved",
        "reject": "draft",
        "archive": "archived",
    }
    target_status = action_to_status.get(action) or str(data.get("status") or "").strip().lower()
    if target_status not in {"draft", "in_review", "approved", "archived"}:
        return Response({"detail": "action must be submit, approve, reject, or archive."}, status=400)

    if target_status == "in_review":
        if not _can_manage_document(request, doc):
            return Response({"detail": "Only admins or the uploader can submit for review."}, status=403)
    else:
        st_action = {"approved": "approve", "archived": "archive", "draft": "reject"}[target_status]
        dec = access.decide(request.user, st_action, doc)
        if not dec.allowed:
            read_ok = access.decide(request.user, "view_ask", doc, context={"include_unapproved": True}).allowed
            audit(request, f"document_{st_action}_denied", f"{_safe_doc_label(doc)} {dec.reason_code}",
                  outcome="denied", target_type="document", target_id=str(doc.id))
            if not read_ok and not access.is_company_admin(request.user):
                raise Http404
            return Response({"detail": dec.rule_chain[-1], "reason_code": dec.reason_code}, status=403)
        doc.reviewed_by = request.user
        doc.reviewed_at = timezone.now()
        doc.review_note = note

    from django.db import transaction
    with transaction.atomic():
        doc.status = target_status
        doc.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note", "updated_at"])
        audit(
            request, f"document_{action or target_status}", f"{_safe_doc_label(doc)} ({target_status})",
            outcome="allowed", target_type="document", target_id=str(doc.id), fail_closed=True,
        )
    return Response(DocumentSerializer(doc).data)


@api_view(["POST"])
@permission_classes([IsEditor])
def document_new_version(request, pk):
    _guard = _platform_admin_blocked(request)
    if _guard:
        return _guard
    """Upload a new version of a document: the old file is archived to
    DocumentVersion, the new file is indexed, and `version` increments.
    Plan-gated (allow_versions) and ACL/legal-hold checked via core.access."""
    doc = _get_doc(request, pk)
    company = doc.company
    dec = access.decide(request.user, "new_version", doc)
    if not dec.allowed:
        if dec.reason_code == "DENY_PLAN_LIMIT":
            return Response({"detail": "Version history is not part of your current plan."}, status=402)
        read_ok = access.decide(request.user, "view_ask", doc, context={"include_unapproved": True}).allowed
        audit(request, "new_version_denied", f"{_safe_doc_label(doc)} {dec.reason_code}",
              outcome="denied", target_type="document", target_id=str(doc.id))
        if not read_ok and not access.is_company_admin(request.user):
            raise Http404
        return Response({"detail": dec.rule_chain[-1], "reason_code": dec.reason_code}, status=403)

    f = request.FILES.get("file")
    if not f:
        return Response({"detail": "No file provided."}, status=400)
    max_size = getattr(settings, "DATA_UPLOAD_MAX_MEMORY_SIZE", 50 * 1024 * 1024)
    if f.size > max_size:
        return Response({"detail": f"File too large. Max size is {max_size // (1024*1024)} MB."},
                        status=413)
    plan = _plan_for(company)
    if plan and plan.storage_mb is not None:
        used = _storage_used(company)
        if used + f.size > plan.storage_mb * 1024 * 1024:
            return Response({"detail": "Storage quota for your plan is full. Upgrade to upload more."}, status=402)
    rejected = _upload_rejection(f)
    if rejected:
        return rejected

    safe_name = os.path.basename(f.name)
    rel_key = os.path.join(company.slug, f"{uuid.uuid4().hex}_{safe_name}")
    if len(os.path.basename(rel_key)) > 255:
        return Response({"detail": "Filename is too long. Use a name of up to 220 characters."},
                        status=400)
    stored = storage.save_uploaded_file(rel_key, f, base_dir=settings.DATA_DIR)

    # Re-require approval on new version uploads from non-approvers when enabled.
    is_adm = access.is_company_admin(request.user)
    is_own_dept_mgr = bool(
        access.is_dept_manager(request.user)
        and doc.department_id == request.user.department_id
        and doc.access_scope != "restricted"
        and doc.sensitivity != "confidential"
    )
    from django.db import transaction
    with transaction.atomic():
        old_path, old_size = doc.stored_path, doc.size
        DocumentVersion.objects.create(
            document=doc, version_number=doc.version, stored_path=old_path,
            filename=doc.filename, size=old_size, uploaded_by=request.user,
        )
        doc.stored_path = stored
        doc.filename = safe_name
        doc.content_type = content_type_for(safe_name)
        doc.size = f.size
        doc.version += 1
        doc.indexing_status = "pending"
        doc.preview_text = ""  # cached text belongs to the old file; re-index refills it
        if getattr(company, "require_doc_approval", False) and not (is_adm or is_own_dept_mgr):
            doc.status = "in_review"
        doc.save()
        audit(
            request, "new_version", f"{_safe_doc_label(doc)} -> v{doc.version}",
            outcome="allowed", target_type="document", target_id=str(doc.id), fail_closed=True,
        )
    _index_in_background(doc)
    return Response(DocumentSerializer(doc).data, status=201)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def document_versions(request, pk):
    _guard = _platform_admin_blocked(request)
    if _guard:
        return _guard
    """Version history for a document (own-company readers only; never external share recipients)."""
    doc = _accessible_doc(request, pk)
    if doc.company_id != getattr(request.user, "company_id", None):
        raise Http404
    versions = doc.versions.all()
    return Response(DocumentVersionSerializer(versions, many=True).data)


def _get_doc(request, pk):
    """Owner-company only. A platform/root admin without a company sees nothing."""
    if not getattr(request.user, "company_id", None):
        raise Http404
    try:
        return Document.objects.get(pk=pk, company=request.user.company)
    except Document.DoesNotExist:
        raise Http404


def _accessible_doc(request, pk):
    """Resolve a document only when the canonical ACL grants this exact user access.

    Records a metadata-only denial audit event inside the caller's company while
    still returning 404 so document existence is never leaked to unauthorized callers.
    """
    doc = (
        access.accessible_documents_qs(
            request.user, action="view_ask", include_unapproved=True, include_external_shares=True,
        )
        .filter(pk=pk)
        .first()
    )
    if doc is None:
        if getattr(request.user, "company_id", None) and Document.objects.filter(pk=pk, company_id=request.user.company_id).exists():
            audit(
                request, "document_access_denied", f"doc#{pk}",
                outcome="denied", target_type="document", target_id=str(pk),
            )
        raise Http404
    return doc


def _can_download(request, doc):
    """Enforce download permission server-side via canonical `access.decide()`."""
    return access.decide(
        request.user, "download", doc,
        context={"include_unapproved": True, "include_external_shares": True},
    ).allowed


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def download_document(request, pk):
    _guard = _platform_admin_blocked(request)
    if _guard:
        return _guard
    doc = _accessible_doc(request, pk)
    dec = access.decide(
        request.user, "download", doc,
        context={"include_unapproved": True, "include_external_shares": True},
    )
    if not dec.allowed:
        audit(request, "download_denied", f"{_safe_doc_label(doc)} {dec.reason_code}",
              outcome="denied", target_type="document", target_id=str(doc.id))
        return Response({"detail": "Download is disabled for this document.", "reason_code": dec.reason_code}, status=403)
    if not doc.stored_path or not storage.exists(doc.stored_path, base_dir=settings.DATA_DIR):
        raise Http404
    doc.downloads += 1
    doc.save(update_fields=["downloads"])
    audit(request, "download", _safe_doc_label(doc), target_type="document", target_id=str(doc.id))
    return FileResponse(
        storage.open_stream(doc.stored_path, base_dir=settings.DATA_DIR),
        as_attachment=True,
        filename=doc.filename,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def document_preview(request, pk):
    _guard = _platform_admin_blocked(request)
    if _guard:
        return _guard
    """Return extracted plain text for in-browser preview (ACL-checked)."""
    doc = _accessible_doc(request, pk)
    text = doc.preview_text
    if not text:
        if not doc.stored_path or not storage.exists(doc.stored_path, base_dir=settings.DATA_DIR):
            raise Http404
        try:
            raw = storage.read_bytes(doc.stored_path, base_dir=settings.DATA_DIR)
            text = rag.extract_text(raw, doc.filename, doc.content_type)
            doc.preview_text = (text or "")[:500_000]
            doc.save(update_fields=["preview_text"])
        except OSError:
            raise Http404
    is_external = doc.company_id != getattr(request.user, "company_id", None)
    if is_external and doc.contains_pii:
        text, _ = moderation.redact_pii(text)
    audit(request, "preview", _safe_doc_label(doc), target_type="document", target_id=str(doc.id))
    return Response({
        "id": doc.id, "filename": doc.filename, "content_type": doc.content_type,
        "size": doc.size, "num_chunks": doc.num_chunks, "text": text[:200000],
        "truncated": len(text) > 200000, "version": doc.version,
    })


# ------------------------------------------------------------------- chat
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@rate_limit("ask", rate=20, per_seconds=60, key="user")
def ask(request):
    """Stream an answer as NDJSON, grounded only in documents this user may see.
    Persists the conversation when conversation_id is supplied (or creates one).

    Feature 4: every incoming question is first run through the policy scanner.
    A match is recorded as a POLICY_VIOLATION_DETECTED audit row and surfaced to
    the user as a `flag` event, while bulk-exfiltration prompts are blocked."""
    _guard = _platform_admin_blocked(request) or _ai_chat_disabled(request)
    if _guard:
        return _guard
    s = AskSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    question = s.validated_data["question"]
    mode = s.validated_data.get("mode")
    provider = s.validated_data.get("provider")
    conversation_id = s.validated_data.get("conversation_id")

    if moderation.is_exfiltration_attempt(question):
        audit(request, "POLICY_VIOLATION_DETECTED", "exfiltration_blocked", outcome="denied")
        return Response(
            {"detail": "Bulk verbatim extraction of documents is blocked by workspace security policy."},
            status=403,
        )

    scan = moderation.scan(question)
    moderation_flags = None
    if scan.flagged:
        moderation_flags = scan.labels
        audit(request, "POLICY_VIOLATION_DETECTED", f"{scan.summary()}", outcome="allowed")

    # Output routing: a policy question gets ONLY the grounded text answer, a
    # form/email request gets ONLY the finished document(s), and a mixed
    # request gets exactly the outputs it asked for. Template generation is
    # deterministic (no model call, no Bedrock, no invented facts).
    company = getattr(request.user, "company", None)
    if company and not getattr(company, "enable_docgen", True):
        doc_plan = docgen.RequestPlan(outputs=["text"], text_requested=True, artifacts=[])
    else:
        doc_plan = docgen.classify(question, outputs=s.validated_data.get("outputs"))
    overrides = s.validated_data.get("fields") or {}
    template_text, template_source_ids = (
        docgen.template_context_with_sources(request.user, doc_plan, question)
        if doc_plan.artifacts else ("", [])
    )

    # Provider selection is a bring-your-own-key feature: without the company's
    # own stored key a caller could steer shared platform spend at a costlier
    # provider, so the field is rejected outright for everyone else.
    if provider:
        own_cfg = LLMConfig.for_company(request.user.company) if request.user.company_id else None
        if not (own_cfg and (own_cfg.api_key or "").strip()):
            return Response(
                {"detail": "Choosing an AI provider requires your company's own AI key "
                           "(Workspace settings → AI)."},
                status=400,
            )

    # Plan quota: monthly ask limit counted over AskLog rows.
    plan = _plan_for(request.user.company) if request.user.company_id else None
    if plan and plan.monthly_ask_limit is not None:
        month_start = timezone.localtime().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        used = AskLog.objects.filter(company=request.user.company,
                                     created_at__gte=month_start).count()
        if used >= plan.monthly_ask_limit:
            return Response({"detail": f"Monthly question limit reached ({plan.monthly_ask_limit}). "
                                       "Upgrade your plan for more."}, status=402)

    conversation = None
    if request.user.company_id:
        if conversation_id:
            conversation = ChatConversation.objects.filter(
                pk=conversation_id, user=request.user, company=request.user.company
            ).first()
            if conversation is None:
                return Response({"detail": "Conversation not found."}, status=404)
        else:
            conversation = ChatConversation.objects.create(
                company=request.user.company, user=request.user,
                title=question.strip()[:120],
            )
    conv_payload = ({"type": "conversation", "conversation_id": conversation.id}
                    if conversation else None)

    def artifact_events(emit_done=True):
        """Generate the requested documents and stream them as NDJSON events."""
        import time as _time
        rendered = docgen.build_artifacts(request.user, question, doc_plan, overrides)
        source_tpl_ids = sorted({r["source_template_id"] for r in rendered if r.get("source_template_id")})
        for r in rendered:
            art = docgen.save_artifact(request.user, r)
            payload = {
                "id": art.id, "kind": art.kind, "title": art.title,
                "subject": art.subject, "content_md": art.content_md,
                "structured": r["structured"], "missing_fields": r["missing_fields"],
                "filled_fields": r.get("filled_fields", []),
                "source": r["source"], "source_template_id": r["source_template_id"],
                "downloads": {
                    fmt: f"/api/artifacts/{art.id}/download?fmt={fmt}"
                    for fmt in ("md", "txt", "docx", "pdf", "html")
                },
            }
            yield json.dumps({"type": "artifact", "artifact": payload}) + "\n"
        missing = sorted({m for r in rendered for m in r["missing_fields"]})
        if missing:
            yield json.dumps({"type": "missing_fields", "fields": missing}) + "\n"
        if rendered:
            rag._log_ask(request.user, question, mode or "", "template", 0,
                         True, False, _time.time())
            if conversation is not None:
                ChatMessage.objects.create(conversation=conversation, role="user",
                                           content=question)
                summary = "\n\n---\n\n".join(r["content_md"] for r in rendered)
                ChatMessage.objects.create(
                    conversation=conversation, role="assistant",
                    content=summary[:20000], source_document_ids=json.dumps(source_tpl_ids),
                )
        if emit_done:
            audit(request, "ask", f"mode={mode or 'default'} templates={source_tpl_ids}")
            yield json.dumps({"type": "done"}) + "\n"

    def stream():
        if conv_payload:
            yield json.dumps(conv_payload) + "\n"
        if doc_plan.artifacts_only:
            # No retrieval chunks, no LLM, no Bedrock: only the finished docs.
            yield from artifact_events(True)
            return
        template_rules = (docgen.TEMPLATE_SYSTEM_RULES
                          if (template_text and doc_plan.artifacts) else "")
        audited_ask = False
        for line in rag.stream_answer(
            request.user, question, mode=mode, provider_override=provider,
            moderation_flags=moderation_flags, conversation=conversation,
            template_text=template_text, template_rules=template_rules,
            template_source_ids=template_source_ids,
        ):
            if not audited_ask:
                try:
                    evt = json.loads(line)
                    if evt.get("type") == "sources":
                        src_ids = evt.get("source_doc_ids") or []
                        audit(request, "ask", f"mode={mode or 'default'} sources={src_ids}")
                        audited_ask = True
                except Exception:
                    pass
            yield line
        if not audited_ask:
            audit(request, "ask", f"mode={mode or 'default'} sources=[]")
        if doc_plan.artifacts:
            yield from artifact_events(False)

    resp = StreamingHttpResponse(stream(), content_type="application/x-ndjson")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def conversations(request):
    _guard = _platform_admin_blocked(request) or _ai_chat_disabled(request)
    if _guard:
        return _guard
    """List the caller's chat threads, or start an empty one."""
    if not request.user.company_id:
        return Response([])
    if request.method == "GET":
        qs = (ChatConversation.objects.filter(user=request.user, company=request.user.company)
              .annotate(_message_count=Count("messages")))
        page = _paginate(request, qs, default_page_size=30)
        return Response({
            "results": ChatConversationSerializer(page["qs"], many=True).data,
            "count": page["count"], "page": page["page"], "pages": page["pages"],
        })
    conv = ChatConversation.objects.create(
        company=request.user.company, user=request.user,
        title=str((request.data or {}).get("title") or "New chat")[:120],
    )
    return Response(ChatConversationSerializer(conv).data, status=201)


@api_view(["GET", "DELETE", "PATCH"])
@permission_classes([IsAuthenticated])
def conversation_detail(request, pk):
    _guard = _platform_admin_blocked(request) or _ai_chat_disabled(request)
    if _guard:
        return _guard
    """One thread with its messages (own threads only), or delete/rename it."""
    try:
        conv = ChatConversation.objects.get(pk=pk, user=request.user)
    except ChatConversation.DoesNotExist:
        raise Http404
    if request.method == "DELETE":
        conv.delete()
        return Response(status=204)
    if request.method == "PATCH":
        conv.title = str((request.data or {}).get("title") or conv.title)[:120]
        conv.save(update_fields=["title"])
        return Response(ChatConversationSerializer(conv).data)
    # Mask assistant messages whose cited source documents the user can no longer access.
    serialized_msgs = []
    for m, masked in rag.filter_conversation_messages_for_user(request.user, conv.messages.all()):
        item = dict(ChatMessageSerializer(m).data)
        if masked:
            item["content"] = "[This answer referenced a document you no longer have access to.]"
            item["sources"] = []
            item["masked"] = True
        else:
            item["masked"] = False
        serialized_msgs.append(item)
    return Response({
        "conversation": ChatConversationSerializer(conv).data,
        "messages": serialized_msgs,
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def message_rate(request, pk):
    _guard = _platform_admin_blocked(request) or _ai_chat_disabled(request)
    if _guard:
        return _guard
    """Thumbs up (1) / down (-1) on an assistant message (own messages only)."""
    try:
        msg = ChatMessage.objects.get(pk=pk, conversation__user=request.user, role="assistant")
    except ChatMessage.DoesNotExist:
        raise Http404
    rating = (request.data or {}).get("rating")
    if rating not in (1, -1, "1", "-1"):
        return Response({"detail": "rating must be 1 or -1."}, status=400)
    msg.rating = int(rating)
    msg.save(update_fields=["rating"])
    return Response({"ok": True, "rating": msg.rating})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def llm_status(request):
    """Lightweight status probe for the chat model (drives the UI status dot)."""
    from .models import LLMConfig as _LLMConfig
    company = getattr(request.user, "company", None)
    prov = providers.get_chat_provider(company=company)
    local_prov = providers.get_chat_provider(mode="local", company=company)
    online_prov = providers.get_chat_provider(mode="online", company=company)
    gemini_prov = providers.get_chat_provider(mode="gemini", company=company)
    selfhosted_prov = providers.get_chat_provider(mode="selfhosted", company=company)
    return Response({
        "online": prov.available(),
        "provider": prov.label,
        "model": prov.chat_model,
        "company_override": _LLMConfig.for_company(company) is not None if company else False,
        "key_source": providers._resolve(company)["key_source"],
        "local": {
            "online": local_prov.available(),
            "provider": local_prov.label,
            "model": local_prov.chat_model,
        },
        "online_api": {
            "online": online_prov.available(),
            "provider": online_prov.label,
            "model": online_prov.chat_model,
            "has_key": bool(online_prov.api_key),
        },
        "gemini": {
            "online": gemini_prov.available(),
            "provider": gemini_prov.label,
            "model": gemini_prov.chat_model,
            "has_key": bool(gemini_prov.api_key),
        },
            "selfhosted": {
                "online": selfhosted_prov.available(),
                "provider": selfhosted_prov.label,
                "model": selfhosted_prov.chat_model,
                "configured": bool(getattr(selfhosted_prov, "base", "")),
            },
    })


# -------------------------------------------------------- admin (company)
@api_view(["GET", "POST"])
@permission_classes([IsAdminOrDeptAdmin])
def users(request):
    """List or create users within the admin's own company (or dept sub-admin's department)."""
    company = request.user.company
    if company is None:
        return Response({"detail": "No company context."}, status=400)
    full_admin = bool(request.user.role == "admin" or _is_platform_level(request.user))
    if request.method == "GET":
        qs = User.objects.filter(company=company).order_by("email")
        if not full_admin:
            qs = qs.filter(department_id=request.user.department_id)
        return Response(UserSerializer(qs, many=True, context={"request": request}).data)

    s = UserCreateSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    d = s.validated_data
    raw_clearance = (d.get("clearance") or "").strip().lower()
    dec = access.decide(
        request.user, "manage_members",
        context={
            "new_role": d["role"],
            "new_is_dept_admin": bool(d.get("is_dept_admin")),
            "new_clearance": raw_clearance or None,
            "new_department_id": d.get("department_id"),
        },
    )
    if not dec.allowed:
        audit(request, "add_user_denied", dec.reason_code, outcome="denied")
        return Response({"detail": dec.rule_chain[-1], "reason_code": dec.reason_code}, status=403)
    if User.objects.filter(email__iexact=d["email"].strip()).exists():
        return Response(
            {"detail": "This email is already registered in Deskwise. Please enter a unique work "
                       "email for this workspace."},
            status=400,
        )

    # Seat limit: the stricter of the company's own cap and the plan's.
    plan = _plan_for(company)
    seat_caps = [c for c in (company.max_employees, plan.max_members if plan else None) if c]
    if seat_caps and company.users.count() >= min(seat_caps):
        cap = min(seat_caps)
        return Response(
            {"detail": f"Seat limit reached ({cap}). "
                       "Increase it in company settings or upgrade your plan."},
            status=400,
        )

    department = None
    if not full_admin:
        department = request.user.department
    elif d.get("department_id"):
        department = Department.objects.filter(pk=d["department_id"], company=company).first()
        if department is None:
            return Response({"detail": "Department not found in this company."}, status=400)

    is_dadmin = bool(d.get("is_dept_admin")) if full_admin else False
    if is_dadmin and (d["role"] != "employee" or department is None):
        return Response({"detail": "Department sub-admins must have role='employee' and a department."}, status=400)

    reason = str(d.get("reason") or "").strip()[:200]
    raw_pw = d.get("password") or ""
    from django.db import transaction
    from . import email_service
    with transaction.atomic():
        user = User.objects.create_user(
            email=d["email"], password=raw_pw if raw_pw else None,
            full_name=d.get("full_name", ""), title=d.get("title", ""),
            role=d["role"], is_dept_admin=is_dadmin, clearance=raw_clearance,
            company=company, department=department,
        )
        detail = f"{user.email} role={user.role} clearance={user.effective_clearance}"
        if reason:
            detail += f" reason={reason}"
        audit(
            request, "add_user", detail,
            outcome="allowed", target_type="user", target_id=str(user.id), fail_closed=True,
        )
    if not raw_pw:
        _, raw_inv = OneTimeToken.issue(user, "invite", minutes=60 * 24 * 7)
        email_service.send_auth_email(
            user,
            "invite",
            company_name=company.name,
            url=_frontend_url(f"/enterprise?tab=join&invite={raw_inv}&email={user.email}"),
        )
    else:
        _, raw = OneTimeToken.issue(user, "verify_email", minutes=60 * 24 * 3)
        email_service.send_auth_email(
            user,
            "verify",
            company_name=company.name,
            url=_frontend_url("/auth/verify?token=" + raw),
        )
    return Response(UserSerializer(user, context={"request": request}).data, status=201)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAdminOrDeptAdmin])
def user_detail(request, pk):
    """Edit (role/department/clearance/name/title/password/active) or remove a company member."""
    if not getattr(request.user, "company_id", None):
        # AUTHZ-03: company=None would match every not-yet-onboarded account.
        raise Http404
    if pk == request.user.id and request.method == "DELETE":
        return Response({"detail": "You can't remove yourself."}, status=400)
    try:
        user = User.objects.get(pk=pk, company=request.user.company)
    except User.DoesNotExist:
        raise Http404
    full_admin = access.is_company_admin(request.user)
    if not full_admin:
        if user.id == request.user.id or user.department_id != request.user.department_id or user.role == "admin" or user.is_dept_admin:
            audit(request, "update_user_denied", f"user#{user.id} DENY_OUTSIDE_DEPARTMENT",
                  outcome="denied", target_type="user", target_id=str(user.id))
            return Response({"detail": "Department managers can only manage non-admin members in their own department."},
                            status=403)

    def _is_last_active_admin(target_u: User) -> bool:
        if target_u.role != "admin" or not target_u.is_active:
            return False
        other_admins = User.objects.filter(
            company=request.user.company, role="admin", is_active=True,
        ).exclude(pk=target_u.pk).count()
        return other_admins == 0

    if request.method == "DELETE":
        if _is_last_active_admin(user):
            return Response({"detail": "Cannot remove the last active admin."}, status=400)
        email = user.email
        uid = user.id
        from django.db import transaction
        with transaction.atomic():
            audit(
                request, "remove_user", email,
                outcome="allowed", target_type="user", target_id=str(uid), fail_closed=True,
            )
            user.delete()
        return Response(status=204)

    data = request.data or {}
    # AUTHZ-01/02: nobody may choose another member's password (it bypasses
    # clearance caps and break-glass). Members reset via the emailed link.
    if "password" in data:
        audit(request, "update_user_denied", f"user#{user.id} DENY_PASSWORD_SET",
              outcome="denied", target_type="user", target_id=str(user.id))
        return Response({"detail": "Member passwords cannot be set by others. "
                                   "Ask the member to use 'Forgot password'."}, status=403)
    prev_role, prev_dept, prev_dadmin, prev_clr, prev_active = (
        user.role, user.department_id, user.is_dept_admin, user.effective_clearance, user.is_active,
    )

    new_role = data.get("role") if "role" in data else user.role
    if "role" in data and new_role not in ("admin", "employee", "viewer"):
        return Response({"detail": "Invalid role."}, status=400)

    new_clearance = user.clearance
    if "clearance" in data:
        raw_clr = str(data.get("clearance") or "").strip().lower()
        if raw_clr not in ("", "standard", "internal", "confidential"):
            return Response({"detail": "clearance must be standard, internal, confidential, or blank."}, status=400)
        new_clearance = raw_clr

    new_is_active = _parse_bool(data.get("is_active"), user.is_active) if "is_active" in data else user.is_active
    new_dept_id = data.get("department_id") if "department_id" in data else user.department_id
    new_is_dadmin = _parse_bool(data.get("is_dept_admin"), user.is_dept_admin) if "is_dept_admin" in data else user.is_dept_admin

    # Guardrail: canonical access decision for member role/clearance/dept edits.
    dec = access.decide(
        request.user, "change_roles",
        context={
            "target_user": user,
            "new_role": new_role if "role" in data else None,
            "new_is_dept_admin": new_is_dadmin if "is_dept_admin" in data else None,
            "new_clearance": new_clearance if ("clearance" in data and new_clearance) else None,
            "new_department_id": new_dept_id if "department_id" in data else None,
            "deactivate": (not new_is_active) if "is_active" in data else False,
        },
    )
    if not dec.allowed:
        audit(request, "update_user_denied", f"user#{user.id} {dec.reason_code}",
              outcome="denied", target_type="user", target_id=str(user.id))
        code = 400 if dec.reason_code == "DENY_SELF_DEMOTION" else 403
        return Response({"detail": dec.rule_chain[-1], "reason_code": dec.reason_code}, status=code)

    # Guardrail: cannot demote or deactivate the last active admin.
    if _is_last_active_admin(user) and (new_role != "admin" or not new_is_active):
        return Response({"detail": "Cannot demote or deactivate the last active admin."}, status=400)

    if "role" in data:
        user.role = new_role
        if user.role != "employee":
            user.is_dept_admin = False
    if "department_id" in data:
        dept_id = data.get("department_id")
        if dept_id:
            dept = Department.objects.filter(pk=dept_id, company=request.user.company).first()
            if dept is None:
                return Response({"detail": "Department not found in this company."}, status=400)
            user.department = dept
        else:
            user.department = None
            user.is_dept_admin = False
    if "is_dept_admin" in data:
        if new_is_dadmin and (user.role != "employee" or user.department_id is None):
            return Response({"detail": "Department managers must be employees assigned to a department."}, status=400)
        user.is_dept_admin = new_is_dadmin
    if "clearance" in data:
        user.clearance = new_clearance
    if "full_name" in data:
        user.full_name = str(data.get("full_name") or "")[:200]
    if "title" in data:
        user.title = str(data.get("title") or "")[:120]
    if data.get("password"):
        err = _password_error(str(data["password"]), user)
        if err:
            return Response({"detail": err}, status=400)
        user.set_password(str(data["password"]))
    if "is_active" in data:
        user.is_active = new_is_active

    reason = str(data.get("reason") or "").strip()[:200]
    after_clr = user.effective_clearance
    changes = []
    if user.role != prev_role:
        changes.append(f"role:{prev_role}->{user.role}")
    if user.department_id != prev_dept:
        changes.append(f"dept:{prev_dept}->{user.department_id}")
    if user.is_dept_admin != prev_dadmin:
        changes.append(f"dept_mgr:{prev_dadmin}->{user.is_dept_admin}")
    if after_clr != prev_clr:
        changes.append(f"clearance:{prev_clr}->{after_clr}")
    if user.is_active != prev_active:
        changes.append(f"active:{prev_active}->{user.is_active}")
    if reason:
        changes.append(f"reason={reason}")

    from django.db import transaction
    with transaction.atomic():
        user.save()
        detail = f"{user.email}" + (f" ({', '.join(changes)})" if changes else "")
        audit(
            request, "update_user", detail,
            outcome="allowed", target_type="user", target_id=str(user.id), fail_closed=True,
        )

    privilege_changed = (
        user.role != prev_role
        or user.department_id != prev_dept
        or user.is_dept_admin != prev_dadmin
        or after_clr != prev_clr
        or user.is_active != prev_active
    )
    if data.get("password") or not user.is_active or privilege_changed:
        revoke_user_refresh_tokens(user)
    return Response(UserSerializer(user, context={"request": request}).data)


@api_view(["GET"])
@permission_classes([IsAdminOrDeptAdmin])
def access_explain(request):
    """Explain why a user can or cannot perform an action on a document.

    Allowed for company admins (any user/doc in company) and department managers
    (within their own department, non-restricted <= internal docs). Every call is audited.
    """
    _guard = _platform_admin_blocked(request)
    if _guard:
        return _guard
    company = request.user.company
    try:
        user_id = int(request.query_params.get("user_id") or 0)
        doc_id = int(request.query_params.get("document_id") or 0)
    except (TypeError, ValueError):
        return Response({"detail": "user_id and document_id integers are required."}, status=400)
    action = str(request.query_params.get("action") or "view_ask").strip().lower()
    include_unapproved = _parse_bool(request.query_params.get("include_unapproved"), False)

    target_user = User.objects.select_related("company", "department").filter(pk=user_id, company=company).first()
    doc = Document.objects.select_related("company", "department").filter(pk=doc_id, company=company).first()
    if target_user is None or doc is None:
        raise Http404

    gate = access.decide(
        request.user, "explain_access",
        context={"target_user": target_user, "document": doc},
    )
    if not gate.allowed:
        audit(
            request, "access_explain", f"user#{user_id} doc#{doc_id} {gate.reason_code}",
            outcome="denied", target_type="document", target_id=str(doc.id),
        )
        return Response({"detail": gate.rule_chain[-1], "reason_code": gate.reason_code}, status=403)

    dec = access.decide(
        target_user, action, doc,
        context={"include_unapproved": include_unapproved, "include_external_shares": False},
    )
    audit(
        request, "access_explain",
        f"subject={target_user.email} action={action} doc#{doc.id} -> {dec.reason_code}",
        outcome="allowed", target_type="document", target_id=str(doc.id), fail_closed=True,
    )
    caller_can_read_doc = access.decide(
        request.user, "view_ask", doc, context={"include_unapproved": True},
    ).allowed
    return Response({
        "user": {
            "id": target_user.id,
            "email": target_user.email,
            "full_name": target_user.full_name,
            "role": target_user.role,
            "is_dept_admin": target_user.is_dept_admin,
            "department_name": target_user.department.name if target_user.department_id else None,
            "clearance": target_user.effective_clearance,
        },
        "document": {
            "id": doc.id,
            "filename": doc.filename if caller_can_read_doc else f"Restricted document #{doc.id}",
            "access_scope": doc.access_scope,
            "sensitivity": doc.sensitivity,
            "status": doc.status,
            "department_name": doc.department.name if doc.department_id else None,
            "masked": not caller_can_read_doc,
        },
        "action": action,
        **dec.to_dict(),
    })


@api_view(["GET"])
@permission_classes([IsAdminOrDeptAdmin])
def member_effective_access(request, pk):
    """Return effective document counts and lists for one member (read-only preview)."""
    _guard = _platform_admin_blocked(request)
    if _guard:
        return _guard
    company = request.user.company
    target_user = User.objects.select_related("company", "department").filter(pk=pk, company=company).first()
    if target_user is None:
        raise Http404
    gate = access.decide(request.user, "explain_access", context={"target_user": target_user})
    if not gate.allowed:
        audit(
            request, "effective_access_view", f"user#{pk} {gate.reason_code}",
            outcome="denied", target_type="user", target_id=str(pk),
        )
        return Response({"detail": gate.rule_chain[-1], "reason_code": gate.reason_code}, status=403)

    total_docs = Document.objects.filter(company=company).count()
    total_approved = Document.objects.filter(company=company, status="approved").count()
    searchable_qs = access.accessible_documents_qs(
        target_user, action="view_ask", include_unapproved=False, include_external_shares=False,
    ).select_related("department")
    workspace_qs = access.accessible_documents_qs(
        target_user, action="view_ask", include_unapproved=True, include_external_shares=False,
    ).select_related("department")
    downloadable_ids = set(
        access.accessible_documents_qs(
            target_user, action="download", include_unapproved=True, include_external_shares=False,
        ).values_list("id", flat=True)
    )
    searchable_ids = set(searchable_qs.values_list("id", flat=True))
    caller_readable_ids = set(
        access.accessible_documents_qs(
            request.user, action="view_ask", include_unapproved=True, include_external_shares=False,
        ).values_list("id", flat=True)
    )

    docs_list = []
    caller_is_admin = access.is_company_admin(request.user)
    for doc in workspace_qs.order_by("-updated_at")[:100]:
        masked = doc.id not in caller_readable_ids
        if masked and not caller_is_admin:
            # AUTHZ-10: dept managers get no metadata for docs they cannot read.
            continue
        docs_list.append({
            "id": doc.id,
            "filename": f"Restricted document #{doc.id}" if masked else doc.filename,
            "masked": masked,
            "access_scope": doc.access_scope,
            "sensitivity": doc.sensitivity,
            "status": doc.status,
            "department_name": doc.department.name if doc.department_id else None,
            "can_search": doc.id in searchable_ids,
            "can_download": doc.id in downloadable_ids,
        })

    audit(
        request, "effective_access_view",
        f"subject={target_user.email} searchable={len(searchable_ids)}/{total_approved}",
        outcome="allowed", target_type="user", target_id=str(target_user.id),
    )
    return Response({
        "user": UserSerializer(target_user, context={"request": request}).data,
        "summary": {
            "total_documents": total_docs,
            "total_approved": total_approved,
            "searchable_count": len(searchable_ids),
            "workspace_visible_count": workspace_qs.count(),
            "downloadable_count": len(downloadable_ids),
        },
        "documents": docs_list,
    })


@api_view(["GET"])
@permission_classes([IsAdmin])
def audit_log(request):
    """The company's tamper-evident audit entries, paginated, with streaming CSV export (?export=csv)."""
    company = request.user.company
    qs = AuditLog.objects.filter(company=company).order_by("-created_at", "-id")
    if request.query_params.get("export") == "csv":
        import csv as _csv

        audit(
            request, "audit_export", "csv",
            outcome="allowed", target_type="company", target_id=str(company.id), fail_closed=True,
        )

        class _Echo:
            def write(self, value):
                return value

        def _row_stream():
            writer = _csv.writer(_Echo())
            yield writer.writerow([
                "created_at", "action", "outcome", "actor_id", "actor_email",
                "target_type", "target_id", "detail", "ip", "hash_version",
                "prev_hash", "entry_hash",
            ]).encode("utf-8")
            for row in qs.iterator(chunk_size=1000):
                yield writer.writerow([
                    row.created_at.isoformat(),
                    _csv_safe(row.action),
                    _csv_safe(row.outcome),
                    row.actor_id if row.actor_id is not None else (row.user_id or ""),
                    _csv_safe(row.actor_email),
                    _csv_safe(row.target_type),
                    _csv_safe(row.target_id),
                    _csv_safe(row.detail),
                    _csv_safe(row.ip),
                    row.hash_version,
                    row.prev_hash,
                    row.entry_hash,
                ]).encode("utf-8")

        resp = StreamingHttpResponse(_row_stream(), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="deskwise-audit-{timezone.localdate().isoformat()}.csv"'
        return resp
    page = _paginate(request, qs, default_page_size=100)
    return Response({
        "results": AuditSerializer(page["qs"], many=True).data,
        "count": page["count"], "page": page["page"], "pages": page["pages"],
    })


@api_view(["GET"])
@permission_classes([IsAdmin])
def audit_verify(request):
    """Verify tamper-evident SHA-256 hash chain across the company's audit log.

    Pass `?format=certificate` to download a signed-metadata JSON verification certificate.
    """
    company = request.user.company
    report = AuditLog.verify_chain_report(company)
    payload = {
        "valid": report["valid"],
        "checked": report["checked"],
        "broken_id": report["broken_id"],
        "head_hash": report["head_hash"],
        "verified_at": report["verified_at"],
        "company_id": company.id,
        "company_name": company.name,
        "guarantee_note": (
            "Tamper-evident, append-only SHA-256 hash chain with database triggers. "
            "A database superuser with direct host access could still alter rows, "
            "but verification fails unless the entire chain is recomputed; "
            "external anchoring of head_hash provides independent verification."
        ),
    }
    if _parse_bool(request.query_params.get("certificate"), False) or request.query_params.get("download") == "certificate":
        resp = Response(payload)
        resp["Content-Disposition"] = (
            f'attachment; filename="deskwise-audit-certificate-{timezone.localdate().isoformat()}.json"'
        )
        return resp
    return Response(payload)


# --------------------------------------------------------- company settings
@api_view(["GET", "PATCH"])
@permission_classes([IsAdmin])
def company_settings(request):
    """Read or update the admin's own company profile (name/contact/seat cap)."""
    company = request.user.company
    if company is None:
        return Response({"detail": "No company context."}, status=400)
    if request.method == "GET":
        return Response(CompanyProfileSerializer(company).data)
    data = request.data
    if "name" in data:
        name = str(data.get("name") or "").strip()[:200]
        if name:
            company.name = name
    for field in ("website", "contact_email", "phone", "hr_email", "tone", "industry"):
        if field in data:
            setattr(company, field, str(data.get(field) or "").strip()[:200])
    if "signature" in data:
        company.signature = str(data.get("signature") or "").strip()[:2000]
    def _parse_bool(val):
        return val if isinstance(val, bool) else str(val).lower() in ("1", "true", "yes", "on")
    for flag in (
        "enable_attendance", "attendance_auto_freeze", "enable_docgen",
        "enable_ai_chat", "enable_team_chat", "enable_external_sharing",
        "require_doc_approval", "redact_pii_for_llm",
    ):
        if flag in data:
            setattr(company, flag, _parse_bool(data[flag]))
    if "doc_retention_days" in data:
        raw_ret = data.get("doc_retention_days")
        if raw_ret in (None, ""):
            company.doc_retention_days = None
        else:
            try:
                company.doc_retention_days = max(1, int(raw_ret))
            except (TypeError, ValueError):
                return Response({"detail": "doc_retention_days must be a positive integer."}, status=400)
    if "max_employees" in data:
        raw = data.get("max_employees")
        if raw in (None, ""):
            company.max_employees = None
        else:
            try:
                company.max_employees = max(1, int(raw))
            except (TypeError, ValueError):
                return Response({"detail": "max_employees must be a positive integer."}, status=400)
    company.save()
    audit(request, "company_settings_update", company.name)
    return Response(CompanyProfileSerializer(company).data)


@api_view(["GET"])
@permission_classes([IsPlatformAdmin])
def platform_reports(request):
    """Platform-level subscription/usage reporting ONLY.

    Root admins see which type of company (industry) uses which subscription,
    plus aggregate counts. No document contents, no chat text, no member
    emails or names, no tenant-owned rows — those stay inside each company.
    """
    from django.db.models import Count, Sum
    from datetime import timedelta
    from django.utils import timezone

    companies = []
    since = timezone.now() - timedelta(days=30)
    for c in (Company.objects.select_related("plan")
              .annotate(_members=Count("users", distinct=True),
                        _docs=Count("documents", distinct=True))
              .order_by("name")):
        companies.append({
            "id": c.id,
            "name": c.name,
            "industry": c.industry or "Unspecified",
            "plan": c.plan.name if c.plan else "No plan",
            "plan_price_usd": c.plan.price_usd if c.plan else 0,
            "billing_period": c.plan.billing_period if c.plan else "",
            "member_count": c._members,
            "document_count": c._docs,
            "asks_30d": AskLog.objects.filter(company=c, created_at__gte=since).count(),
            "storage_mb": round((c.documents.aggregate(s=Sum("size"))["s"] or 0) / (1024 * 1024), 2),
            "created_at": c.created_at.date().isoformat(),
        })

    by_plan: dict[str, int] = {}
    by_industry: dict[str, int] = {}
    for row in companies:
        by_plan[row["plan"]] = by_plan.get(row["plan"], 0) + 1
        by_industry[row["industry"]] = by_industry.get(row["industry"], 0) + 1

    return Response({
        "summary": {
            "total_companies": len(companies),
            "total_members": sum(r["member_count"] for r in companies),
            "total_documents": sum(r["document_count"] for r in companies),
            "asks_30d": sum(r["asks_30d"] for r in companies),
            "companies_by_plan": by_plan,
            "companies_by_industry": by_industry,
        },
        "companies": companies,
        "plans": [
            {"name": p.name, "price_usd": p.price_usd,
             "subscribers": Company.objects.filter(plan=p).count()}
            for p in Plan.objects.filter(is_active=True).order_by("price_usd")
        ],
    })


# --------------------------------------------------------- company directory
@api_view(["GET"])
@permission_classes([IsEditor])
@rate_limit("company_search", rate=20, per_seconds=60, key="ip")
def company_search(request):
    _guard = _platform_admin_blocked(request) or _external_sharing_disabled(request)
    if _guard:
        return _guard
    """Find a registered company by its short share code."""
    code = (request.query_params.get("code") or "").strip().upper()
    if not code:
        return Response({"detail": "Enter a company access code."}, status=400)
    company = Company.objects.filter(access_code__iexact=code).first()
    if not company or (company.id != request.user.company_id and not getattr(company, "enable_external_sharing", True)):
        return Response({"detail": "No registered company uses that access code."}, status=404)
    return Response(CompanyDirectorySerializer(company).data)


@api_view(["GET"])
@permission_classes([IsEditor])
@rate_limit("company_members", rate=20, per_seconds=60, key="ip")
def company_members(request, access_code):
    _guard = _platform_admin_blocked(request) or _external_sharing_disabled(request)
    if _guard:
        return _guard
    """List selectable enterprise members for a company found by access code.
    Rate-limited so the directory cannot be enumerated at speed."""
    company = Company.objects.filter(access_code__iexact=access_code.strip()).first()
    if not company or (company.id != request.user.company_id and not getattr(company, "enable_external_sharing", True)):
        return Response({"detail": "No registered company uses that access code."}, status=404)
    users = User.objects.filter(company=company, is_active=True).exclude(role="public").order_by("full_name", "email")
    return Response(MemberDirectorySerializer(users, many=True).data)


# ------------------------------------------------- cross-company collaboration
@api_view(["GET", "POST"])
@permission_classes([IsEditor])
def document_shares(request, pk):
    _guard = _platform_admin_blocked(request)
    if _guard:
        return _guard
    """List (GET) or grant (POST) access to ONE document for ONE user.

    Only the owning company's authorized document manager (uploader, own-dept manager,
    or admin with break-glass on restricted docs) may list or create grants/shares.
    """
    doc = _get_doc(request, pk)
    read_ok = access.decide(request.user, "view_ask", doc, context={"include_unapproved": True}).allowed
    mgmt_dec = access.decide(request.user, "manage_grants", doc)
    if not mgmt_dec.allowed:
        audit(request, "share_denied", f"{_safe_doc_label(doc)} {mgmt_dec.reason_code}",
              outcome="denied", target_type="document", target_id=str(doc.id))
        if not read_ok and not access.is_company_admin(request.user):
            raise Http404
        return Response({"detail": mgmt_dec.rule_chain[-1], "reason_code": mgmt_dec.reason_code}, status=403)

    if request.method == "GET":
        shares = DocumentShare.objects.filter(document=doc).select_related(
            "shared_with_user", "shared_with_user__company"
        )
        data = DocumentShareSerializer(shares, many=True).data
        if _parse_bool(request.query_params.get("include_internal"), False):
            grants = DocumentAccess.objects.filter(
                document=doc, user__company_id=doc.company_id,
            ).select_related("user", "granted_by")
            return Response({
                "external_shares": data,
                "internal_grants": [
                    {
                        "id": g.id,
                        "user_id": g.user_id,
                        "email": g.user.email,
                        "full_name": g.user.full_name,
                        "role": g.user.role,
                        "clearance": g.user.effective_clearance,
                        "can_download": g.can_download,
                        "override_clearance": g.override_clearance,
                        "grant_reason": g.grant_reason,
                        "is_break_glass": g.is_break_glass,
                        "granted_by": g.granted_by.email if g.granted_by_id else None,
                    }
                    for g in grants
                ],
            })
        return Response(data)

    target, error = share_target(request)
    if error:
        return Response({"detail": error}, status=400)

    can_download = _parse_bool(request.data.get("can_download"), True)

    # Branch A: Internal access grant (same company -> DocumentAccess only)
    if target.company_id == doc.company_id:
        override_clr = _parse_bool(request.data.get("override_clearance"), False)
        grant_reason = str(request.data.get("grant_reason") or request.data.get("reason") or "").strip()[:300]
        grant_dec = access.decide(
            request.user, "manage_grants", doc,
            context={"override_clearance": override_clr, "grant_reason": grant_reason},
        )
        if not grant_dec.allowed:
            audit(request, "grant_access_denied", f"{_safe_doc_label(doc)} {grant_dec.reason_code}",
                  outcome="denied", target_type="document", target_id=str(doc.id))
            code = 400 if grant_dec.reason_code == "DENY_REASON_REQUIRED" else 403
            return Response({"detail": grant_dec.rule_chain[-1], "reason_code": grant_dec.reason_code}, status=code)
        from django.db import transaction
        with transaction.atomic():
            grant_obj, _ = DocumentAccess.objects.update_or_create(
                document=doc,
                user=target,
                defaults={
                    "can_download": can_download,
                    "override_clearance": override_clr,
                    "grant_reason": grant_reason,
                    "granted_by": request.user,
                },
            )
            detail = (
                f"{_safe_doc_label(doc)} -> {target.email} "
                f"(download={can_download}, override_clearance={override_clr}"
                + (f", reason={grant_reason[:120]}" if grant_reason else "")
                + ")"
            )
            audit(
                request, "grant_access", detail,
                outcome="allowed", target_type="document", target_id=str(doc.id), fail_closed=True,
            )
        return Response({
            "id": grant_obj.id,
            "user_id": target.id,
            "email": target.email,
            "full_name": target.full_name,
            "can_download": grant_obj.can_download,
            "override_clearance": grant_obj.override_clearance,
            "grant_reason": grant_obj.grant_reason,
            "internal": True,
        }, status=201)

    # Branch B: External share (different company -> DocumentShare only)
    ext_guard = _external_sharing_disabled(request)
    if ext_guard:
        return ext_guard
    ext_dec = access.decide(request.user, "share_externally", doc)
    if not ext_dec.allowed:
        audit(request, "share_denied", f"{_safe_doc_label(doc)} {ext_dec.reason_code}",
              outcome="denied", target_type="document", target_id=str(doc.id))
        code = 400 if ext_dec.reason_code == "DENY_UNAPPROVED_STATUS" else 403
        return Response({"detail": ext_dec.rule_chain[-1], "reason_code": ext_dec.reason_code}, status=code)

    allow_pii = _parse_bool(request.data.get("allow_pii"), False)
    if doc.contains_pii and not (access.is_company_admin(request.user) and allow_pii):
        return Response(
            {"detail": "Document contains sensitive PII/credentials; an admin must confirm allow_pii=true to share externally."},
            status=403,
        )

    expires_at = None
    if request.data.get("expires_in_days") not in (None, ""):
        try:
            days = int(request.data.get("expires_in_days"))
            if days <= 0:
                raise ValueError
            expires_at = timezone.now() + timedelta(days=days)
        except (TypeError, ValueError):
            return Response({"detail": "expires_in_days must be a positive integer."}, status=400)
    elif request.data.get("expires_at"):
        parsed = parse_datetime(str(request.data.get("expires_at")))
        if parsed is None:
            return Response({"detail": "Invalid expires_at ISO timestamp."}, status=400)
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
        if parsed <= timezone.now():
            return Response({"detail": "expires_at must be in the future."}, status=400)
        expires_at = parsed

    from django.db import transaction
    with transaction.atomic():
        share, _ = DocumentShare.objects.update_or_create(
            document=doc, shared_with_user=target,
            defaults={
                "shared_by": request.user,
                "can_download": can_download,
                "expires_at": expires_at,
            },
        )
        audit(
            request, "share", f"{_safe_doc_label(doc)} -> {target.email} ({target.company.name})",
            outcome="allowed", target_type="document", target_id=str(doc.id), fail_closed=True,
        )
    return Response(DocumentShareSerializer(share).data, status=201)


@api_view(["DELETE"])
@permission_classes([IsEditor])
def document_share_detail(request, pk, user_id):
    _guard = _platform_admin_blocked(request)
    if _guard:
        return _guard
    """Revoke one user's access grant or external share on a document."""
    doc = _get_doc(request, pk)
    read_ok = access.decide(request.user, "view_ask", doc, context={"include_unapproved": True}).allowed
    mgmt_dec = access.decide(request.user, "manage_grants", doc)
    if not mgmt_dec.allowed:
        audit(request, "unshare_denied", f"{_safe_doc_label(doc)} {mgmt_dec.reason_code}",
              outcome="denied", target_type="document", target_id=str(doc.id))
        if not read_ok and not access.is_company_admin(request.user):
            raise Http404
        return Response({"detail": mgmt_dec.rule_chain[-1], "reason_code": mgmt_dec.reason_code}, status=403)
    from django.db import transaction
    with transaction.atomic():
        DocumentShare.objects.filter(document=doc, shared_with_user_id=user_id).delete()
        DocumentAccess.objects.filter(document=doc, user_id=user_id).delete()
        audit(
            request, "unshare", f"{_safe_doc_label(doc)} (user {user_id})",
            outcome="allowed", target_type="document", target_id=str(doc.id), fail_closed=True,
        )
    return Response(status=204)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def shared_with_me(request):
    _guard = _platform_admin_blocked(request)
    if _guard:
        return _guard
    """Documents from OTHER companies that were shared with the current user."""
    now = timezone.now()
    allowed_ext_ids = set(
        access.accessible_documents_qs(
            request.user, action="view_ask", include_unapproved=False, include_external_shares=True,
        )
        .exclude(company_id=request.user.company_id)
        .values_list("id", flat=True)
    )
    if not allowed_ext_ids:
        return Response([])
    shares = (
        DocumentShare.objects.filter(
            shared_with_user=request.user,
            document_id__in=allowed_ext_ids,
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .select_related("document", "document__company", "shared_by")
        .order_by("-created_at")
    )
    out = []
    for s in shares:
        data = DocumentSerializer(s.document).data
        data["shared_by"] = s.shared_by.email if s.shared_by else None
        data["can_download"] = s.can_download
        data["expires_at"] = s.expires_at.isoformat() if s.expires_at else None
        out.append(data)
    return Response(out)


# --------------------------------------------------------- LLM provider config
@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsAdmin])
def llm_config(request):
    """Read or update LLM settings.

    Platform admins manage the platform-wide default row (company NULL). Company
    admins manage their OWN company's override row — plan-gated
    (allow_custom_llm) — which lets a tenant bring its own model/key while
    everyone else stays on the platform default.
    """
    from .permissions import is_platform_admin as _is_plat
    if _is_plat(request.user) and request.user.company_id is None:
        cfg = LLMConfig.load()
        is_override = False
    else:
        if request.user.company_id is None:
            return Response({"detail": "No company context."}, status=400)
        if request.method != "GET":
            plan = _plan_for(request.user.company)
            if not (plan and plan.allow_custom_llm):
                return Response({"detail": "Custom AI settings are not part of your plan."},
                                status=402)
            # Validate the payload BEFORE creating the override row, so a
            # rejected base_url (SSRF guard) never leaves an empty row behind.
            probe = LLMConfigSerializer(data=request.data, partial=True)
            probe.is_valid(raise_exception=True)
            cfg, _created = LLMConfig.objects.get_or_create(company=request.user.company)
            is_override = True
        else:
            # Read-only: show the company's override if one exists, otherwise the
            # platform/.env default WITHOUT persisting a row that shadows .env.
            cfg = LLMConfig.for_company(request.user.company) or LLMConfig.load()
            is_override = cfg.pk is not None and cfg.company_id is not None

    if request.method == "GET":
        data = LLMConfigSerializer(cfg).data
        if not is_override:
            # Surface the EFFECTIVE platform defaults. A stale platform row must
            # not hide the shared platform Bedrock key / model.
            effective = providers._resolve(request.user.company)
            data.update({
                "provider": effective["provider"],
                "chat_model": effective["model"],
                "base_url": effective["base_url"],
                "temperature": effective["temperature"],
                "max_tokens": effective["max_tokens"],
                "key_source": effective["key_source"],
                "platform_key_in_use": effective["key_source"] == "platform_env",
                "has_api_key": effective["key_source"] in ("platform_env", "row", "company"),
            })
        return Response(data)
    if request.method == "DELETE":
        if not is_override:
            return Response({"detail": "Platform default LLM configuration cannot be deleted."}, status=400)
        cfg.delete()
        audit(request, "llm_config_reset", "company override removed", fail_closed=True)
        return Response(LLMConfigSerializer(LLMConfig.load()).data)
    s = LLMConfigSerializer(cfg, data=request.data, partial=True)
    s.is_valid(raise_exception=True)
    s.save()
    audit(request, "llm_config", f"{'company' if is_override else 'platform'} provider={cfg.provider} model={cfg.chat_model}", fail_closed=True)
    return Response(LLMConfigSerializer(cfg).data)


@api_view(["POST"])
@permission_classes([IsAdmin])
@rate_limit("llm_test", rate=10, per_seconds=60, key="user")
def llm_test(request):
    """Ping the currently-configured provider with a tiny prompt."""
    company = getattr(request.user, "company", None)
    prov = providers.get_chat_provider(company=company)
    if not prov.available():
        return Response({"ok": False, "provider": prov.label, "model": prov.chat_model,
                         "detail": "Not reachable / no API key set."})
    try:
        out = "".join(prov.stream_chat(
            [{"role": "system", "content": "Reply with exactly one word: pong."},
             {"role": "user", "content": "ping"}],
            temperature=0.0, max_tokens=64,
        ))
        return Response({"ok": True, "provider": prov.label, "model": prov.chat_model,
                         "sample": out.strip()[:120]})
    except Exception:
        # The raw provider error can echo internal endpoints/bodies back to the
        # browser (SSRF response disclosure); log it server-side instead.
        import logging
        logging.getLogger(__name__).exception("llm-test connectivity check failed")
        return Response({"ok": False, "provider": prov.label, "model": prov.chat_model,
                         "detail": "The AI endpoint could not be reached or rejected the "
                                   "request. Check the provider, model and key settings."})


# --------------------------------------------------------- departments
@api_view(["GET", "POST"])
@permission_classes([IsAdmin])
def departments(request):
    """List or create departments in the admin's own company (plan-gated)."""
    company = request.user.company
    if company is None:
        return Response({"detail": "No company context."}, status=400)
    plan = _plan_for(company)
    if request.method == "GET":
        depts = company.departments.annotate(_members=Count("members"))
        return Response(DepartmentSerializer(depts, many=True).data)
    if not (plan and plan.allow_departments):
        return Response({"detail": "Departments are not part of your current plan."}, status=402)
    name = str((request.data or {}).get("name") or "").strip()[:120]
    if not name:
        return Response({"detail": "Department name is required."}, status=400)
    dept, created = Department.objects.get_or_create(company=company, name=name)
    if not created:
        return Response({"detail": "That department already exists."}, status=400)
    audit(request, "department_add", name)
    return Response(DepartmentSerializer(dept).data, status=201)


@api_view(["DELETE"])
@permission_classes([IsAdmin])
def department_detail(request, pk):
    """Delete a department; department docs are re-scoped to 'restricted' (never company-wide)
    and affected members lose department-manager status with immediate session revocation."""
    try:
        dept = Department.objects.get(pk=pk, company=request.user.company)
    except Department.DoesNotExist:
        raise Http404
    name = dept.name
    dept_id = dept.id
    affected_users = list(User.objects.filter(department=dept))
    from django.db import transaction
    with transaction.atomic():
        Document.objects.filter(department=dept).update(department=None, access_scope="restricted")
        User.objects.filter(department=dept).update(department=None, is_dept_admin=False)
        dept.delete()
        audit(
            request, "department_remove", name,
            outcome="allowed", target_type="department", target_id=str(dept_id), fail_closed=True,
        )
    for u in affected_users:
        revoke_user_refresh_tokens(u)
    return Response(status=204)


# --------------------------------------------------------- announcements
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def announcements(request):
    """Company announcements. Anyone can read; only admins create."""
    company = request.user.company
    if company is None:
        return Response([])
    if request.method == "GET":
        qs = company.announcements.all()[:50]
        return Response(AnnouncementSerializer(qs, many=True, context={"request": request}).data)
    if request.user.role != "admin" and not _is_platform_level(request.user):
        return Response({"detail": "Only admins can post announcements."}, status=403)
    title = str((request.data or {}).get("title") or "").strip()[:200]
    body = str((request.data or {}).get("body") or "").strip()
    if not title or not body:
        return Response({"detail": "Title and body are required."}, status=400)
    raw_ack = (request.data or {}).get("require_ack", False)
    require_ack = raw_ack if isinstance(raw_ack, bool) else str(raw_ack).lower() in ("1", "true", "yes", "on")
    ann = Announcement.objects.create(
        company=company, title=title, body=body, require_ack=require_ack, created_by=request.user,
    )
    audit(request, "announcement", title)
    return Response(AnnouncementSerializer(ann, context={"request": request}).data, status=201)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def announcement_ack(request, pk):
    """Record that the signed-in employee read and acknowledged a mandatory announcement."""
    if not getattr(request.user, "company_id", None):
        raise Http404
    try:
        ann = Announcement.objects.get(pk=pk, company=request.user.company)
    except Announcement.DoesNotExist:
        raise Http404
    ack, created = AnnouncementAck.objects.get_or_create(announcement=ann, user=request.user)
    if created:
        audit(request, "announcement_ack", ann.title)
    return Response({
        "announcement_id": ann.id,
        "acknowledged": True,
        "acknowledged_at": ack.acknowledged_at.isoformat(),
    })


@api_view(["GET"])
@permission_classes([IsAdmin])
def announcement_acks(request, pk):
    """List who acknowledged (and who still hasn't) for a company announcement."""
    try:
        ann = Announcement.objects.get(pk=pk, company=request.user.company)
    except Announcement.DoesNotExist:
        raise Http404
    acks = list(
        AnnouncementAck.objects.filter(announcement=ann).select_related("user").order_by("acknowledged_at")
    )
    acked_ids = {a.user_id for a in acks}
    pending = User.objects.filter(company=request.user.company, is_active=True).exclude(id__in=acked_ids)
    return Response({
        "announcement_id": ann.id,
        "require_ack": ann.require_ack,
        "acknowledged": [
            {
                "user_id": a.user_id,
                "email": a.user.email,
                "full_name": a.user.full_name,
                "acknowledged_at": a.acknowledged_at.isoformat(),
            }
            for a in acks
        ],
        "pending": [
            {"user_id": u.id, "email": u.email, "full_name": u.full_name}
            for u in pending
        ],
    })


@api_view(["DELETE"])
@permission_classes([IsAdmin])
def announcement_detail(request, pk):
    try:
        ann = Announcement.objects.get(pk=pk, company=request.user.company)
    except Announcement.DoesNotExist:
        raise Http404
    ann.delete()
    audit(request, "announcement_remove", ann.title)
    return Response(status=204)


# --------------------------------------------------------- analytics (admin)
@api_view(["GET"])
@permission_classes([IsAdmin])
def analytics(request):
    """Usage analytics for the admin's company: asks by user/department,
    unanswered questions, flagged asks, ratings and top documents."""
    company = request.user.company
    if company is None:
        return Response({"detail": "No company context."}, status=400)
    logs = AskLog.objects.filter(company=company)
    days = 30
    try:
        days = min(90, max(1, int(request.query_params.get("days", 30))))
    except (TypeError, ValueError):
        pass
    since = timezone.now() - timezone.timedelta(days=days)
    recent = logs.filter(created_at__gte=since)

    by_user = list(
        recent.values("user__email", "user__full_name")
        .annotate(asks=Count("id"), unanswered=Count("id", filter=Q(chunks_found=0)))
        .order_by("-asks")[:20]
    )
    by_department = list(
        recent.exclude(department=None)
        .values("department__name")
        .annotate(asks=Count("id"), unanswered=Count("id", filter=Q(chunks_found=0)))
        .order_by("-asks")[:20]
    )
    unanswered = list(
        recent.filter(chunks_found=0).order_by("-created_at")
        .values("question", "created_at", "user__email")[:50]
    )
    ratings = {
        "up": ChatMessage.objects.filter(
            conversation__company=company, rating=1, created_at__gte=since).count(),
        "down": ChatMessage.objects.filter(
            conversation__company=company, rating=-1, created_at__gte=since).count(),
    }
    readable_ids = set(visible_documents(request.user).values_list("id", flat=True))
    top_docs = [
        {
            "filename": d.filename if d.id in readable_ids else f"Restricted document #{d.id}",
            "downloads": d.downloads,
        }
        for d in company.documents.order_by("-downloads")[:10]
    ]
    # Monthly ask usage vs the plan quota (for the usage meter).
    month_start = timezone.localtime().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_asks = logs.filter(created_at__gte=month_start).count()
    plan = _plan_for(company)
    return Response({
        "range_days": days,
        "totals": {
            "asks": recent.count(),
            "unanswered": recent.filter(chunks_found=0).count(),
            "flagged": recent.filter(flagged=True).count(),
            "avg_latency_ms": int(recent.aggregate(a=Avg("latency_ms"))["a"] or 0),
        },
        "by_user": by_user,
        "by_department": by_department,
        "unanswered_questions": unanswered,
        "ratings": ratings,
        "top_documents": top_docs,
        "usage": {"asks_this_month": month_asks,
                  "monthly_ask_limit": plan.monthly_ask_limit if plan else None},
    })


@api_view(["GET"])
@permission_classes([IsAdmin])
def usage(request):
    """Usage & plan dashboard data for the company's own admins: current
    consumption of every plan quota this month plus the upgrade catalogue."""
    company = request.user.company
    if company is None:
        return Response({"detail": "No company context."}, status=400)
    plan = _plan_for(company)

    month_start = timezone.localtime().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    asks_used = AskLog.objects.filter(company=company, created_at__gte=month_start).count()
    doc_count = company.documents.count()
    storage_bytes = _storage_used(company)
    member_count = company.users.count()
    department_count = company.departments.count()

    def remaining(used, cap):
        return None if cap is None else max(cap - used, 0)

    upgrades = Plan.objects.filter(is_active=True, price_usd__gt=plan.price_usd) \
                           .order_by("price_usd")
    return Response({
        "plan": PlanSerializer(plan).data,
        "usage": {
            "asks": {"used": asks_used,
                     "limit": plan.monthly_ask_limit,
                     "remaining": remaining(asks_used, plan.monthly_ask_limit)},
            "documents": {"used": doc_count,
                          "limit": plan.max_documents,
                          "remaining": remaining(doc_count, plan.max_documents)},
            "storage": {"used_bytes": storage_bytes,
                        "limit_mb": plan.storage_mb,
                        "used_mb": round(storage_bytes / (1024 * 1024), 1)},
            "members": {"used": member_count,
                        "limit": plan.max_members,
                        "remaining": remaining(member_count, plan.max_members)},
            "departments": {"used": department_count,
                            "enabled": bool(plan.allow_departments)},
        },
        "upgrades": PlanSerializer(upgrades, many=True).data,
    })


# --------------------------------------------------------- plans (public + admin)
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def plans(request):
    """Public plan catalogue (USD pricing) for the pricing page.

    Guaranteed never to return 500: auto-seeds if table is empty, and falls
    back to default specifications if there is unexpected database schema drift.
    """
    try:
        qs = Plan.objects.filter(is_active=True).order_by("price_usd")
        if not qs.exists():
            from django.core.management import call_command
            try:
                call_command("seed_plans")
                qs = Plan.objects.filter(is_active=True).order_by("price_usd")
            except Exception:
                pass
        return Response(PlanSerializer(qs, many=True).data)
    except Exception as exc:
        logger.exception("Failed to query plans from database: %s", exc)
        fallback = [
            {"id": 1, "name": "Free", "price_usd": 0, "billing_period": "month", "max_members": 3, "max_documents": 20, "storage_mb": 512, "monthly_ask_limit": 50, "allow_versions": False, "allow_departments": True, "allow_custom_llm": False, "is_default": True},
            {"id": 2, "name": "Go", "price_usd": 19, "billing_period": "month", "max_members": 15, "max_documents": 200, "storage_mb": 5120, "monthly_ask_limit": 1500, "allow_versions": True, "allow_departments": True, "allow_custom_llm": False, "is_default": False},
            {"id": 3, "name": "Plus", "price_usd": 49, "billing_period": "month", "max_members": 50, "max_documents": 1000, "storage_mb": 25600, "monthly_ask_limit": 6000, "allow_versions": True, "allow_departments": True, "allow_custom_llm": True, "is_default": False},
            {"id": 4, "name": "Max", "price_usd": 129, "billing_period": "month", "max_members": None, "max_documents": None, "storage_mb": None, "monthly_ask_limit": 25000, "allow_versions": True, "allow_departments": True, "allow_custom_llm": True, "is_default": False},
        ]
        return Response(fallback)


# --------------------------------------------------------- Stripe Billing & Subscriptions
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def billing_status(request):
    """Return Stripe setup status and company's current subscription."""
    company = getattr(request.user, "company", None)
    is_adm = access.is_company_admin(request.user)
    return Response({
        "has_stripe": billing.is_stripe_configured(),
        "stripe_publishable_key": getattr(settings, "STRIPE_PUBLISHABLE_KEY", "") if is_adm else "",
        "plan": PlanSerializer(company.plan).data if company and company.plan else None,
        "stripe_customer_id": (company.stripe_customer_id if (company and is_adm) else ""),
        "stripe_subscription_id": (company.stripe_subscription_id if (company and is_adm) else ""),
        "is_subscribed": bool(company and company.stripe_subscription_id),
    })


@api_view(["POST"])
@permission_classes([IsAdmin])
def billing_checkout(request):
    """Create a Stripe Checkout Session for self-serve plan upgrade."""
    plan_id = (request.data or {}).get("plan_id")
    if not plan_id:
        return Response({"detail": "plan_id is required."}, status=400)
    try:
        session_data = billing.create_checkout_session(
            user=request.user,
            plan_id=int(plan_id),
            success_url=(request.data or {}).get("success_url"),
            cancel_url=(request.data or {}).get("cancel_url"),
        )
        return Response(session_data, status=201)
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=400)
    except Exception as exc:
        logger.exception("Stripe checkout session creation failed: %s", exc)
        return Response({"detail": "The payment provider returned an error. Please try again."}, status=502)


@api_view(["POST"])
@permission_classes([IsAdmin])
def billing_portal(request):
    """Create a Stripe Customer Portal session for card/subscription management."""
    try:
        portal_data = billing.create_portal_session(
            user=request.user,
            return_url=(request.data or {}).get("return_url"),
        )
        return Response(portal_data, status=200)
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=400)
    except Exception as exc:
        logger.exception("Stripe customer portal creation failed: %s", exc)
        return Response({"detail": "The payment provider returned an error. Please try again."}, status=502)


@csrf_exempt
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def billing_webhook(request):
    """Handle incoming Stripe webhook events."""
    payload = request.body
    sig_header = request.headers.get("Stripe-Signature") or request.META.get("HTTP_STRIPE_SIGNATURE")
    try:
        res = billing.handle_webhook(payload, sig_header)
        return Response(res, status=200)
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=400)
    except Exception as exc:
        logger.exception("Stripe webhook processing error: %s", exc)
        return Response({"detail": "Webhook processing error"}, status=500)


@api_view(["POST"])
@permission_classes([IsPlatformAdmin])
def company_set_plan(request, pk):
    """Platform admin moves a company onto a plan (billing is offline: bank
    transfer / JazzCash / Easypaisa — record the change here)."""
    company = Company.objects.filter(pk=pk).first()
    if not company:
        return Response({"detail": "Company not found."}, status=404)
    plan_id = (request.data or {}).get("plan_id")
    plan = Plan.objects.filter(pk=plan_id, is_active=True).first() if plan_id else None
    if not plan:
        return Response({"detail": "Plan not found."}, status=404)
    company.plan = plan
    company.save(update_fields=["plan"])
    AuditLog.objects.create(company=company, user=request.user, action="plan_change",
                            detail=f"-> {plan.name} (${plan.price_usd}/{plan.billing_period})",
                            ip=client_ip(request))
    return Response({"ok": True, "company": company.name, "plan": PlanSerializer(plan).data})


# --------------------------------------------------------- Platform admin tools
@api_view(["GET"])
@permission_classes([IsPlatformAdmin])
def list_companies(request):
    """List every registered company with usage counters (platform admin only)."""
    # distinct=True on both counts avoids the cross-product of the two joins.
    companies = (Company.objects
                 .annotate(_members=Count("users", distinct=True),
                           _docs=Count("documents", distinct=True))
                 .order_by("name"))
    out = []
    for c in companies:
        out.append({
            "id": c.id, "name": c.name, "slug": c.slug, "access_code": c.access_code,
            "member_count": c._members, "doc_count": c._docs,
            "plan": PlanSerializer(c.plan).data if c.plan else None,
        })
    return Response(out)


@api_view(["POST"])
@permission_classes([IsPlatformAdmin])
def switch_company(request):
    """DISABLED: platform/root admins must never join a tenant — they may only
    see platform-level reports. Kept as an endpoint so older clients get a
    clear error instead of a 404."""
    return Response({"detail": "Platform admins cannot access company workspaces. "
                                "Use /api/admin/reports for platform analytics."}, status=403)
    company_id = request.data.get("company_id")
    if not company_id:
        return Response({"detail": "company_id is required."}, status=400)
    company = Company.objects.filter(pk=company_id).first()
    if not company:
        return Response({"detail": "Company not found."}, status=404)
    request.user.company = company
    request.user.save(update_fields=["company"])
    audit(request, "switch_company", f"Switched to {company.name}")
    return Response(UserSerializer(request.user, context={"request": request}).data)


@api_view(["POST"])
@permission_classes([IsPlatformAdmin])
def detach_company(request):
    """DISABLED: see switch_company."""
    return Response({"detail": "Platform admins cannot switch tenant context."}, status=403)
    request.user.company = None
    request.user.department = None
    request.user.save(update_fields=["company", "department"])
    return Response(UserSerializer(request.user, context={"request": request}).data)


# ------------------------------------------------- workflow document downloads
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@rate_limit("workflow_confirm", rate=10, per_seconds=60, key="user")
def workflow_confirm(request):
    """AI-01: run a chat-proposed action only after the user clicks Confirm.

    The proposal token is signed, bound to this user, expires after 15 minutes
    and works once (core.workflow.confirm_proposal)."""
    _guard = _platform_admin_blocked(request) or _ai_chat_disabled(request)
    if _guard:
        return _guard
    from . import workflow
    try:
        result = workflow.confirm_proposal(str((request.data or {}).get("token") or ""), request.user)
    except workflow.ProposalForbidden as exc:
        return Response({"detail": str(exc)}, status=403)
    except workflow.ProposalError as exc:
        return Response({"detail": str(exc)}, status=400)
    if not result:
        return Response({"detail": "There was nothing to do for this suggestion."}, status=400)
    audit(request, "workflow_confirmed", f"{result.get('action')} status={result.get('status')}",
          target_type="workflow")
    return Response({"type": "workflow", **result})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def workflow_form_download(request, user_id, name):
    _guard = _platform_admin_blocked(request) or _docgen_disabled(request)
    if _guard:
        return _guard
    """Serve a generated workflow document (e.g. an auto-filled leave form) to
    its owner. Path is confined to MEDIA_ROOT/forms/<user_id>/ (or S3 forms/<user_id>/)."""
    if request.user.id != user_id:
        return Response({"detail": "You can only download your own forms."}, status=403)

    safe_name = os.path.basename(name)
    if safe_name != name or ".." in name:
        raise Http404

    rel_key = os.path.join("forms", str(user_id), safe_name)
    if storage.is_s3_enabled() and storage.exists(rel_key, base_dir=settings.MEDIA_ROOT):
        audit(request, "form_download", safe_name)
        return FileResponse(
            storage.open_stream(rel_key, base_dir=settings.MEDIA_ROOT),
            as_attachment=True,
            filename=safe_name,
        )

    base_dir = os.path.realpath(os.path.join(settings.MEDIA_ROOT, "forms", str(user_id)))
    requested = os.path.realpath(os.path.join(base_dir, safe_name))
    if requested != base_dir and not requested.startswith(base_dir + os.sep):
        raise Http404
    if not os.path.isfile(requested):
        raise Http404
    audit(request, "form_download", os.path.basename(requested))
    return FileResponse(
        open(requested, "rb"), as_attachment=True, filename=os.path.basename(requested)
    )


# ------------------------------------------------------------- attendance (F5)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def attendance_scan(request):
    """Mark today's attendance for the signed-in user (the QR scan target).

    The QR encodes a signed, short-lived token (see core.qr_tokens): the scan
    only counts when the token is fresh, untampered, and belongs to the
    scanner's own company — a leaked URL cannot check anyone in remotely.
    Set ATTENDANCE_QR_REQUIRED=false to allow self-serve scans without a QR
    (kiosk-style deployments)."""
    _guard = _attendance_disabled(request)
    if _guard:
        return _guard
    from . import qr_tokens
    user = request.user
    if not getattr(user, "company_id", None):
        return Response({"detail": "Your account is not linked to a company."}, status=400)

    token = str((request.data or {}).get("token")
                or request.query_params.get("token") or "").strip()
    if getattr(settings, "ATTENDANCE_QR_REQUIRED", True):
        if not token:
            return Response({"detail": "Scan the office QR code to mark attendance."},
                            status=400)
        if not qr_tokens.verify(token, user.company_id):
            return Response(
                {"detail": "This QR code is invalid or expired. Ask your admin for "
                           "the current code."},
                status=403)

    today = timezone.localdate()
    existing = AttendanceRecord.objects.filter(user=user, date=today).first()
    if existing:
        return Response(
            {"detail": "Attendance already marked for today.",
             "record": AttendanceRecordSerializer(existing).data},
            status=409,
        )
    record = AttendanceRecord.objects.create(
        company=user.company, user=user, date=today, status="Present"
    )
    audit(request, "attendance_scan", f"Present {today.isoformat()}")
    return Response(AttendanceRecordSerializer(record).data, status=201)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def attendance_me(request):
    """The signed-in user's own attendance history and discipline counters."""
    _guard = _attendance_disabled(request)
    if _guard:
        return _guard
    user = request.user
    today = timezone.localdate()
    records = AttendanceRecord.objects.filter(user=user)[:120]
    strike = UserStrike.objects.filter(user=user).first()
    return Response({
        "today": today.isoformat(),
        "marked_today": AttendanceRecord.objects.filter(user=user, date=today).exists(),
        "absences_this_month": attendance_svc.absences_in_month(user, today.year, today.month),
        "records": AttendanceRecordSerializer(records, many=True).data,
        "strike": UserStrikeSerializer(strike).data if strike else None,
    })


@api_view(["GET"])
@permission_classes([IsAdmin])
def attendance_qr(request):
    """Return the attendance check-in target plus an inline SVG QR when the
    optional `qrcode` library is installed.

    The target embeds a signed token bound to the caller's company and a short
    TTL, so a photographed QR dies within minutes and never works for another
    company."""
    _guard = _attendance_disabled(request)
    if _guard:
        return _guard
    from . import qr_tokens
    user = request.user
    if not getattr(user, "company_id", None):
        return Response({"detail": "Your account is not linked to a company."}, status=400)
    base = settings.PUBLIC_BASE_URL or f"{request.scheme}://{request.get_host()}"
    target = f"{base}/workspace/attendance?scan=1&t={qr_tokens.issue(user.company_id)}"
    payload = {"target": target, "svg": None, "qr_available": False}
    try:
        import qrcode  # optional dependency
        import qrcode.image.svg

        img = qrcode.make(target, image_factory=qrcode.image.svg.SvgImage)
        buf = io.BytesIO()
        img.save(buf)
        payload["svg"] = buf.getvalue().decode("utf-8")
        payload["qr_available"] = True
    except Exception:
        pass
    return Response(payload)


@api_view(["GET", "POST"])
@permission_classes([IsAdmin])
def admin_holidays(request):
    """Company holiday calendar (plus platform-wide entries shown read-only):
    days that never count as absences."""
    _guard = _attendance_disabled(request)
    if _guard:
        return _guard
    from .models import Holiday
    company = request.user.company
    if company is None:
        return Response({"detail": "No company context."}, status=400)
    if request.method == "GET":
        rows = Holiday.objects.filter(company__in=[company, None]).order_by("date")[:200]
        return Response([{"id": h.id, "date": h.date.isoformat(), "name": h.name,
                          "platform_wide": h.company_id is None} for h in rows])
    raw_date = str((request.data or {}).get("date") or "").strip()
    try:
        holiday_date = _parse_iso_date(raw_date)
    except ValueError:
        return Response({"detail": "date must be YYYY-MM-DD."}, status=400)
    if not holiday_date:
        return Response({"detail": "date is required (YYYY-MM-DD)."}, status=400)
    holiday, created = Holiday.objects.get_or_create(
        company=company, date=holiday_date,
        defaults={"name": str((request.data or {}).get("name") or "")[:120]},
    )
    if not created:
        return Response({"detail": "That date is already a holiday."}, status=400)
    audit(request, "holiday_add", holiday_date.isoformat())
    return Response({"id": holiday.id, "date": holiday.date.isoformat(),
                     "name": holiday.name, "platform_wide": False}, status=201)


@api_view(["DELETE"])
@permission_classes([IsAdmin])
def admin_holiday_detail(request, pk):
    from .models import Holiday
    try:
        holiday = Holiday.objects.get(pk=pk, company=request.user.company)
    except Holiday.DoesNotExist:
        raise Http404
    holiday.delete()
    return Response(status=204)


@api_view(["GET", "POST"])
@permission_classes([IsAdmin])
def admin_exemptions(request):
    """Approved absence windows (leave/travel) — excluded from strike math."""
    _guard = _attendance_disabled(request)
    if _guard:
        return _guard
    from .models import AttendanceExemption
    company = request.user.company
    if company is None:
        return Response({"detail": "No company context."}, status=400)
    if request.method == "GET":
        rows = (AttendanceExemption.objects.filter(user__company=company)
                .select_related("user")[:200])
        return Response([{"id": e.id, "user_id": e.user_id, "email": e.user.email,
                          "start_date": e.start_date.isoformat(),
                          "end_date": e.end_date.isoformat(), "reason": e.reason}
                         for e in rows])
    d = request.data or {}
    try:
        start = _parse_iso_date(str(d.get("start_date") or ""))
        end = _parse_iso_date(str(d.get("end_date") or ""))
    except ValueError:
        return Response({"detail": "dates must be YYYY-MM-DD."}, status=400)
    if not start or not end or end < start:
        return Response({"detail": "start_date and end_date (YYYY-MM-DD) are required."},
                        status=400)
    try:
        target = User.objects.get(pk=int(d.get("user_id")), company=company)
    except (User.DoesNotExist, TypeError, ValueError):
        return Response({"detail": "Member not found in this company."}, status=400)
    exc = AttendanceExemption.objects.create(
        user=target, start_date=start, end_date=end,
        reason=str(d.get("reason") or "")[:200], created_by=request.user)
    audit(request, "attendance_exemption", f"{target.email} {start}..{end}")
    return Response({"id": exc.id}, status=201)


@api_view(["DELETE"])
@permission_classes([IsAdmin])
def admin_exemption_detail(request, pk):
    from .models import AttendanceExemption
    try:
        exc = AttendanceExemption.objects.get(pk=pk, user__company=request.user.company)
    except AttendanceExemption.DoesNotExist:
        raise Http404
    exc.delete()
    return Response(status=204)


def _parse_iso_date(raw: str):
    from datetime import date as _date
    if not raw:
        return None
    return _date.fromisoformat(raw)


@api_view(["POST"])
@permission_classes([IsAdmin])
def admin_attendance_evaluate(request):
    """Run the monthly attendance evaluation for the admin's own company."""
    company = request.user.company
    if company is None:
        return Response({"detail": "No company context for evaluation."}, status=400)
    _guard = _attendance_disabled(request)
    if _guard:
        return _guard

    def _flag(name, default):
        raw = request.data.get(name, default)
        return raw if isinstance(raw, bool) else str(raw).lower() in ("1", "true", "yes", "on")

    dry_run = _flag("dry_run", False)
    auto_freeze_default = getattr(company, "attendance_auto_freeze", False)
    freeze = _flag("freeze", auto_freeze_default)
    year, month = request.data.get("year"), request.data.get("month")
    try:
        year = int(year) if year not in (None, "") else None
        month = int(month) if month not in (None, "") else None
    except (TypeError, ValueError):
        return Response({"detail": "year and month must be integers."}, status=400)

    results = attendance_svc.evaluate_month(
        year=year, month=month, company=company, freeze=freeze, dry_run=dry_run
    )
    if not dry_run:
        struck = sum(1 for r in results if r["new_strike"])
        frozen = sum(1 for r in results if r["deactivated"])
        audit(request, "attendance_evaluate",
              f"{len(results)} users, {struck} new strike(s), {frozen} frozen")
    return Response({
        "dry_run": dry_run,
        "freeze": freeze,
        "evaluated": len(results),
        "results": results,
    })


# ------------------------------------------- template document generation
def _artifact_payload(art):
    import json as _json
    try:
        structured = _json.loads(art.structured or "{}")
    except ValueError:
        structured = {}
    try:
        missing = _json.loads(art.missing_fields or "[]")
    except ValueError:
        missing = []
    return {
        "id": art.id, "kind": art.kind, "title": art.title, "subject": art.subject,
        "content_md": art.content_md, "structured": structured,
        "missing_fields": missing, "created_at": art.created_at.isoformat(),
        "downloads": {
            fmt: f"/api/artifacts/{art.id}/download?fmt={fmt}"
            for fmt in ("md", "txt", "docx", "pdf", "html", "json")
        },
    }


def _owned_artifact(request, pk):
    """Artifacts are private to the user who generated them and require live access
    to any uploaded source template used to generate them."""
    try:
        art = GeneratedArtifact.objects.get(pk=pk, user=request.user)
    except GeneratedArtifact.DoesNotExist:
        raise Http404
    if art.source_template_id:
        still_allowed = access.accessible_documents_qs(
            request.user, action="view_ask", include_unapproved=False, include_external_shares=False,
        ).filter(pk=art.source_template_id).exists()
        if not still_allowed:
            raise Http404
    return art


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def templates_list(request):
    _guard = _platform_admin_blocked(request) or _docgen_disabled(request)
    if _guard:
        return _guard
    """Available templates for this user: uploaded company templates (ACL
    filtered, WHOLE documents) plus the built-in rough draft sections."""
    uploaded = []
    for doc in docgen.collect_uploaded_templates(request.user, []):
        uploaded.append({"id": doc.document_id, "title": doc.title,
                         "kind": doc.kind, "source": "uploaded"})
    builtin = [{"id": None, "title": t.title, "kind": t.kind, "source": "builtin"}
               for t in docgen.load_builtin_templates()]
    return Response({"templates": uploaded + builtin})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@rate_limit("docgen", rate=30, per_seconds=60, key="user")
def docgen_generate(request):
    _guard = _platform_admin_blocked(request) or _docgen_disabled(request)
    if _guard:
        return _guard
    """Generate finished, copy/paste-ready documents from templates.

    POST {question, outputs: ["form","email"], fields: {date: "..."}}.
    Text-only requests belong to /api/ask and are rejected here.
    """
    question = str((request.data or {}).get("question") or "")
    outputs = (request.data or {}).get("outputs") or None
    overrides = (request.data or {}).get("fields") or {}
    plan = docgen.classify(question, outputs=outputs)
    if not plan.artifacts:
        return Response({"detail": "Ask for a form, email, policy or table document; "
                                   "policy questions belong to /api/ask."}, status=400)
    rendered = docgen.build_artifacts(request.user, question, plan, overrides)
    saved = [docgen.save_artifact(request.user, r) for r in rendered]
    audit(request, "docgen", f"{len(saved)} document(s): {','.join(plan.artifacts)}")
    artifact_payloads = []
    for art, result in zip(saved, rendered):
        payload = _artifact_payload(art)
        payload["filled_fields"] = result.get("filled_fields", [])
        artifact_payloads.append(payload)
    return Response({
        "outputs": plan.outputs,
        "artifacts": artifact_payloads,
        "missing_fields": sorted({m for r in rendered for m in r["missing_fields"]}),
    }, status=201)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@rate_limit("docgen", rate=30, per_seconds=60, key="user")
def artifact_from_text(request):
    _guard = _platform_admin_blocked(request) or _docgen_disabled(request)
    if _guard:
        return _guard
    """Turn any chat answer into a downloadable artifact (DOCX/PDF/copy)."""
    d = request.data or {}
    content = str(d.get("content") or "").strip()
    if not content:
        return Response({"detail": "content is required."}, status=400)
    kind = str(d.get("kind") or "text").strip().lower()
    if kind not in dict(GeneratedArtifact.KINDS):
        kind = "text"
    structured = docgen._parse_structured(kind,
                                          str(d.get("title") or "Deskwise document")[:200],
                                          content)
    art = docgen.save_artifact(request.user, {
        "kind": kind, "title": str(d.get("title") or "Deskwise document")[:200],
        "subject": structured.get("subject", ""), "content_md": content,
        "structured": structured, "missing_fields": [], "source_template_id": None,
    })
    return Response(_artifact_payload(art), status=201)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def artifact_detail(request, pk):
    _guard = _platform_admin_blocked(request) or _docgen_disabled(request)
    if _guard:
        return _guard
    """Fetch a generated document (structured JSON + Markdown)."""
    return Response(_artifact_payload(_owned_artifact(request, pk)))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def artifact_download(request, pk):
    _guard = _platform_admin_blocked(request) or _docgen_disabled(request)
    if _guard:
        return _guard
    """Download a generated document as md/txt/docx/pdf/html/json."""
    art = _owned_artifact(request, pk)
    fmt = str(request.query_params.get("fmt") or "docx").strip().lower()
    try:
        data, content_type, filename = docgen.artifact_download_bytes(art, fmt)
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=400)
    except Exception:
        return Response({"detail": "Could not render this format."}, status=500)
    resp = FileResponse(io.BytesIO(data), as_attachment=True, filename=filename)
    resp["Content-Type"] = content_type
    return resp


# ----------------------------------------- unified search & governance alerts
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def unified_search(request):
    """Permission-filtered search across accessible documents, team messages, and artifacts."""
    _guard = _platform_admin_blocked(request)
    if _guard:
        return _guard
    q = str(request.query_params.get("q") or "").strip()
    if len(q) < 2:
        return Response({"detail": "Query parameter 'q' must be at least 2 characters."}, status=400)
    ql = q.lower()
    company = getattr(request.user, "company", None)

    doc_hits = []
    for doc in visible_documents(request.user).select_related("department").order_by("-updated_at")[:150]:
        if (
            ql in (doc.filename or "").lower()
            or ql in (doc.description or "").lower()
            or ql in (doc.tags or "").lower()
            or ql in (doc.preview_text or "").lower()
        ):
            doc_hits.append(DocumentSerializer(doc).data)
            if len(doc_hits) >= 20:
                break

    msg_hits = []
    if company and getattr(company, "enable_team_chat", True):
        from .team_chat import accessible_rooms_for
        rooms = list(accessible_rooms_for(request.user))
        room_ids = [r.id for r in rooms]
        if room_ids:
            from .team_chat import BotSourceFilter
            reader = BotSourceFilter(request.user)
            # S7-09: bot answers derived from documents this reader can't open
            # never appear in search results (not even masked).
            msgs = [
                m for m in (
                    TeamMessage.objects.filter(room_id__in=room_ids, content__icontains=q)
                    .select_related("room", "sender")
                    .order_by("-created_at")[:60]
                )
                if reader.can_read(m)
            ][:20]
            msg_hits = [
                {
                    "id": m.id,
                    "room_id": m.room_id,
                    "room_name": m.room.name,
                    "sender": m.sender.email if m.sender else "DeskWise",
                    "content": m.content[:240],
                    "created_at": m.created_at.isoformat(),
                }
                for m in msgs
            ]

    artifact_hits = []
    if company and getattr(company, "enable_docgen", True):
        live_doc_ids = set(
            access.accessible_documents_qs(
                request.user, action="view_ask", include_unapproved=False, include_external_shares=False,
            ).values_list("id", flat=True)
        )
        arts = (
            GeneratedArtifact.objects.filter(company=company, user=request.user)
            .filter(Q(title__icontains=q) | Q(content_md__icontains=q))
            .order_by("-created_at")[:20]
        )
        artifact_hits = [
            _artifact_payload(a)
            for a in arts
            if not a.source_template_id or a.source_template_id in live_doc_ids
        ]

    return Response({
        "query": q,
        "documents": doc_hits,
        "team_messages": msg_hits,
        "artifacts": artifact_hits,
    })


@api_view(["GET"])
@permission_classes([IsAdmin])
def admin_governance(request):
    """Governance & compliance overview: pending reviews, PII docs, legal holds, stale docs, expiring shares, audit chain."""
    company = request.user.company
    if company is None:
        return Response({"detail": "No company context."}, status=400)
    now = timezone.now()
    stale_days = company.doc_retention_days or 180
    stale_cutoff = now - timedelta(days=stale_days)
    expiring_cutoff = now + timedelta(days=7)

    pending_docs = Document.objects.filter(company=company, status="in_review").order_by("-updated_at")[:25]
    pii_docs = Document.objects.filter(company=company, contains_pii=True).order_by("-updated_at")[:25]
    held_docs = Document.objects.filter(company=company, legal_hold=True).order_by("-updated_at")[:25]
    stale_docs = Document.objects.filter(company=company, status="approved", updated_at__lt=stale_cutoff).order_by("updated_at")[:25]
    expiring_shares = (
        DocumentShare.objects.filter(
            document__company=company,
            expires_at__isnull=False,
            expires_at__gt=now,
            expires_at__lte=expiring_cutoff,
        )
        .select_related("document", "shared_with_user", "shared_with_user__company")
        .order_by("expires_at")[:25]
    )
    expired_count = DocumentShare.objects.filter(
        document__company=company, expires_at__isnull=False, expires_at__lte=now,
    ).count()

    active_members = User.objects.filter(company=company, is_active=True).count()
    mandatory_anns = []
    for ann in Announcement.objects.filter(company=company, require_ack=True)[:20]:
        acked = ann.acks.count()
        mandatory_anns.append({
            "id": ann.id,
            "title": ann.title,
            "acknowledged_count": acked,
            "pending_count": max(0, active_members - acked),
        })

    chain_valid, chain_checked, chain_broken_id = AuditLog.verify_chain(company)
    readable_ids = set(visible_documents(request.user).values_list("id", flat=True))

    def _safe_doc_list(qs_docs):
        return [
            DocumentSerializer(d).data if d.id in readable_ids else _masked_doc_payload(d)
            for d in qs_docs
        ]

    return Response({
        "pending_review_count": Document.objects.filter(company=company, status="in_review").count(),
        "pending_reviews": _safe_doc_list(pending_docs),
        "pii_document_count": Document.objects.filter(company=company, contains_pii=True).count(),
        "pii_documents": _safe_doc_list(pii_docs),
        "legal_hold_count": Document.objects.filter(company=company, legal_hold=True).count(),
        "legal_hold_documents": _safe_doc_list(held_docs),
        "stale_threshold_days": stale_days,
        "stale_document_count": Document.objects.filter(company=company, status="approved", updated_at__lt=stale_cutoff).count(),
        "stale_documents": _safe_doc_list(stale_docs),
        "expiring_shares": DocumentShareSerializer(expiring_shares, many=True).data,
        "expired_share_count": expired_count,
        "mandatory_announcements": mandatory_anns,
        "audit_integrity": {
            "valid": chain_valid,
            "checked": chain_checked,
            "broken_id": chain_broken_id,
        },
    })


@api_view(["GET", "POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def cron_maintenance(request):
    """Scheduled maintenance endpoint for serverless hosts (e.g. Vercel Cron).

    Protected by `CRON_SECRET` via `Authorization: Bearer <CRON_SECRET>`.
    Re-indexes up to 10 stuck pending documents and prunes old AskLog rows.
    """
    import hmac
    from io import StringIO
    from django.core.management import call_command

    secret = os.getenv("CRON_SECRET", "").strip()
    if not secret:
        return Response({"detail": "CRON_SECRET is not configured."}, status=503)
    auth = (request.headers.get("Authorization") or "").strip()
    expected = f"Bearer {secret}"
    if not hmac.compare_digest(auth, expected):
        return Response({"detail": "Unauthorized."}, status=401)

    cutoff = timezone.now() - timedelta(minutes=30)
    stuck_docs = list(
        Document.objects.filter(indexing_status="pending", updated_at__lt=cutoff)[:10]
    )
    reindexed = 0
    failed = 0
    for doc in stuck_docs:
        try:
            raw = storage.read_bytes(doc.stored_path, base_dir=settings.DATA_DIR)
            n = rag.index_document(doc, raw)
            doc.indexing_status = "ready" if n >= 0 else "failed"
            doc.index_error = ""
            reindexed += 1
        except Exception as exc:
            doc.indexing_status = "failed"
            doc.index_error = index_error_message(exc)
            failed += 1
        doc.save(update_fields=["indexing_status", "index_error"])

    pruned_ephemeral_docs = 0
    if getattr(settings, "IS_VERCEL", False) and not storage.is_s3_enabled():
        ephemeral_cutoff = timezone.now() - timedelta(hours=24)
        stale_uploads = list(
            Document.objects.filter(
                created_at__lt=ephemeral_cutoff,
                legal_hold=False,
            ).exclude(stored_path__startswith="demo/")
        )
        for doc in stale_uploads:
            storage.delete(doc.stored_path, base_dir=settings.DATA_DIR)
            doc.delete()
            pruned_ephemeral_docs += 1

    out = StringIO()
    call_command("prune_asklogs", days=90, stdout=out)
    from .tasks import purge_expired_pending_uploads
    try:
        purged_uploads = purge_expired_pending_uploads()
    except Exception:
        logger.exception("purge_expired_pending_uploads failed")
        purged_uploads = 0
    return Response({
        "ok": True,
        "reindexed": reindexed,
        "failed": failed,
        "pruned_ephemeral_docs": pruned_ephemeral_docs,
        "purged_expired_uploads": purged_uploads,
        "prune_output": out.getvalue().strip(),
    })
