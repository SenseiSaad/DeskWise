"""Canonical permission engine for Deskwise.

EVERY authorization check across REST views, WebSockets, document search,
docgen templates, and AI retrieval derives from this module.

Three questions are evaluated in strict order (first denial wins):
  1. Entry Gate     — authenticated, active, non-platform-admin tenant boundary,
                      feature flags & plan limits.
  2. Document Scope — lifecycle status, audience (company / department / restricted),
                      and legal hold.
  3. Clearance &    — explicit user clearance (standard < internal < confidential)
     Action Matrix    against document sensitivity, then role/action matrix.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db.models import Q
from django.utils import timezone

from .models import Document, DocumentAccess, DocumentShare

CLEARANCE_RANK: dict[str, int] = {
    "standard": 1,
    "internal": 2,
    "confidential": 3,
}

SCOPE_RESTRICTIVENESS: dict[str, int] = {
    "company": 1,
    "department": 2,
    "restricted": 3,
}

SENSITIVITY_BY_RANK = {v: k for k, v in CLEARANCE_RANK.items()}


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason_code: str
    rule_chain: tuple[str, ...]
    metadata_only: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason_code": self.reason_code,
            "rule_chain": list(self.rule_chain),
            "metadata_only": self.metadata_only,
        }


# ------------------------------------------------------------------ helpers
def effective_clearance(user) -> str:
    """Explicit user clearance if set; otherwise derived from role."""
    if not user:
        return "standard"
    explicit = (getattr(user, "clearance", "") or "").strip().lower()
    if explicit in CLEARANCE_RANK:
        return explicit
    role = (getattr(user, "role", "employee") or "employee").strip().lower()
    if role == "admin":
        return "confidential"
    if role == "viewer":
        return "standard"
    return "internal"


def clearance_rank(level: str) -> int:
    return CLEARANCE_RANK.get((level or "standard").strip().lower(), 1)


def allowed_sensitivities_for(user) -> tuple[str, ...]:
    rank = clearance_rank(effective_clearance(user))
    return tuple(k for k, v in CLEARANCE_RANK.items() if v <= rank)


def is_platform_level(user) -> bool:
    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and (getattr(user, "is_platform_admin", False) or getattr(user, "is_superuser", False))
    )


def is_company_admin(user) -> bool:
    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and not is_platform_level(user)
        and getattr(user, "company_id", None) is not None
        and getattr(user, "role", "") == "admin"
    )


def is_dept_manager(user) -> bool:
    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and not is_platform_level(user)
        and getattr(user, "company_id", None) is not None
        and getattr(user, "role", "") == "employee"
        and getattr(user, "is_dept_admin", False)
        and getattr(user, "department_id", None) is not None
    )


def _find_grant(user, document: Document) -> DocumentAccess | None:
    if not user or not getattr(user, "pk", None) or not document or not getattr(document, "pk", None):
        return None
    return DocumentAccess.objects.filter(document_id=document.pk, user_id=user.pk).first()


def _find_active_share(user, document: Document) -> DocumentShare | None:
    if not user or not getattr(user, "pk", None) or not document or not getattr(document, "pk", None):
        return None
    now = timezone.now()
    return (
        DocumentShare.objects.filter(document_id=document.pk, shared_with_user_id=user.pk)
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .first()
    )


def _company_plan(company):
    if company is None:
        return None
    return getattr(company, "plan", None)


# -------------------------------------------------------- canonical queryset
def accessible_documents_qs(
    user,
    *,
    action: str = "view_ask",
    include_unapproved: bool = False,
    include_external_shares: bool = True,
):
    """Canonical Document queryset derived from the exact same rules as `decide()`.

    Guaranteed by differential tests to match `decide(user, action, doc)` for
    every combination of user, document, grant, share, scope, sensitivity and status.
    """
    if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return Document.objects.none()

    if is_platform_level(user):
        return Document.objects.none()

    company_id = getattr(user, "company_id", None)
    allowed_sens = list(allowed_sensitivities_for(user))
    q = Q(pk__in=[])

    if company_id:
        is_adm = is_company_admin(user)
        is_dm = is_dept_manager(user)
        dept_id = getattr(user, "department_id", None)

        # Audience predicates within the owning company
        # 1) Non-restricted audience matched naturally (without needing a grant)
        natural_audience_q = Q(access_scope="company")
        if is_adm:
            natural_audience_q |= Q(access_scope="department")
        elif dept_id:
            natural_audience_q |= Q(access_scope="department", department_id=dept_id)

        # 2) Restricted docs uploaded by this user
        uploader_audience_q = Q(access_scope="restricted", uploaded_by=user)

        # 3) Explicit DocumentAccess grant (widens audience; only overrides clearance if override_clearance=True)
        grant_base = DocumentAccess.objects.filter(user=user, document__company_id=company_id)
        if action == "download":
            # Direct natural audience or uploader can download without grant.can_download,
            # whereas grant-only access requires grant.can_download=True.
            grant_qs_normal = grant_base.filter(can_download=True, document__sensitivity__in=allowed_sens)
            grant_qs_override = grant_base.filter(can_download=True, override_clearance=True)
        else:
            grant_qs_normal = grant_base.filter(document__sensitivity__in=allowed_sens)
            grant_qs_override = grant_base.filter(override_clearance=True)

        granted_doc_ids = set(grant_qs_normal.values_list("document_id", flat=True)) | set(
            grant_qs_override.values_list("document_id", flat=True)
        )
        grant_q = Q(id__in=granted_doc_ids) if granted_doc_ids else Q(pk__in=[])

        # Natural & uploader access ALWAYS respect user's sensitivity clearance
        natural_with_clearance = (natural_audience_q | uploader_audience_q) & Q(sensitivity__in=allowed_sens)

        if not include_unapproved:
            # AI / approved-only surface: ONLY approved documents
            own_q = Q(company_id=company_id, status="approved") & (natural_with_clearance | grant_q)
        else:
            # Workspace management surface: approved + permitted unapproved/archived lifecycle rows
            approved_part = Q(status="approved") & (natural_with_clearance | grant_q)

            # Uploader sees own drafts / in_review still within their audience & clearance (or via grant)
            uploader_wip = Q(uploaded_by=user, status__in=("draft", "in_review")) & (
                natural_with_clearance | grant_q
            )

            # Department manager sees own department non-restricted WIP & archived within <= internal
            dm_wip = Q(pk__in=[])
            if is_dm and dept_id:
                dm_wip = (
                    Q(
                        department_id=dept_id,
                        status__in=("draft", "in_review", "archived"),
                        sensitivity__in=("standard", "internal"),
                    )
                    & ~Q(access_scope="restricted")
                    & (Q(sensitivity__in=allowed_sens) | grant_q)
                )

            # Company admin sees own-company non-restricted WIP & archived within clearance (or override),
            # plus restricted WIP/archived ONLY if explicitly granted or uploaded by admin.
            adm_wip = Q(pk__in=[])
            if is_adm:
                adm_wip = Q(status__in=("draft", "in_review", "archived")) & (
                    (~Q(access_scope="restricted") & (Q(sensitivity__in=allowed_sens) | grant_q))
                    | (uploader_audience_q & Q(sensitivity__in=allowed_sens))
                    | grant_q
                )

            own_q = Q(company_id=company_id) & (approved_part | uploader_wip | dm_wip | adm_wip)

        q |= own_q

    if include_external_shares:
        now = timezone.now()
        ext_sens = [s for s in allowed_sens if s != "confidential"]
        if ext_sens:
            share_qs = DocumentShare.objects.filter(
                shared_with_user=user,
                document__status="approved",
                document__company__enable_external_sharing=True,
                document__sensitivity__in=ext_sens,
            ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            if company_id:
                share_qs = share_qs.exclude(document__company_id=company_id)
            if action == "download":
                share_qs = share_qs.filter(can_download=True)
            ext_ids = list(share_qs.values_list("document_id", flat=True))
            if ext_ids:
                q |= Q(id__in=ext_ids)

    return Document.objects.filter(q).distinct()


def admin_restricted_metadata_qs(user):
    """Restricted documents in the admin's own company that the admin CANNOT read
    yet (no grant, not uploader) — surfaced as masked metadata rows for Break-Glass."""
    if not is_company_admin(user):
        return Document.objects.none()
    granted_ids = DocumentAccess.objects.filter(
        user=user, document__company_id=user.company_id
    ).values_list("document_id", flat=True)
    return (
        Document.objects.filter(company_id=user.company_id, access_scope="restricted")
        .exclude(uploaded_by=user)
        .exclude(id__in=granted_ids)
    )


# ----------------------------------------------------------- pure decide()
def decide(
    user,
    action: str,
    document: Document | None = None,
    *,
    context: dict[str, Any] | None = None,
) -> Decision:
    """Evaluate the 3 permission gates in order; first denial wins.

    Returns Decision(allowed, reason_code, rule_chain, metadata_only).
    """
    ctx = context or {}
    chain: list[str] = []

    # ── GATE 1: Entry Gate ──────────────────────────────────────────────
    if not user or not getattr(user, "is_authenticated", False):
        chain.append("Entry denied: user is not authenticated.")
        return Decision(False, "DENY_UNAUTHENTICATED", tuple(chain))

    if not getattr(user, "is_active", False):
        chain.append("Entry denied: user account is deactivated.")
        return Decision(False, "DENY_INACTIVE_USER", tuple(chain))

    if is_platform_level(user):
        if action in ("billing", "llm_config", "platform_admin"):
            chain.append("Entry allowed: platform root admin performing platform action.")
            return Decision(True, "ALLOW_PLATFORM_ADMIN", tuple(chain))
        chain.append("Entry denied: platform admins have no access to tenant data or documents.")
        return Decision(False, "DENY_PLATFORM_ADMIN_NO_TENANT_DATA", tuple(chain))

    company = getattr(user, "company", None)
    company_id = getattr(user, "company_id", None)
    if company_id is None or company is None:
        chain.append("Entry denied: user is not attached to any company.")
        return Decision(False, "DENY_NO_COMPANY", tuple(chain))

    chain.append(f"Gate 1 passed: active {user.role} in company #{company_id} (clearance={effective_clearance(user)}).")

    # Feature flag & plan checks for workspace-level actions
    if action == "ai_chat" and not getattr(company, "enable_ai_chat", True):
        chain.append("Feature denied: AI Chat is disabled for this workspace.")
        return Decision(False, "DENY_FEATURE_DISABLED", tuple(chain))
    if action == "docgen" and not getattr(company, "enable_docgen", True):
        chain.append("Feature denied: Document generation is disabled for this workspace.")
        return Decision(False, "DENY_FEATURE_DISABLED", tuple(chain))
    if action == "team_chat" and not getattr(company, "enable_team_chat", True):
        chain.append("Feature denied: Team Chat is disabled for this workspace.")
        return Decision(False, "DENY_FEATURE_DISABLED", tuple(chain))
    if action == "attendance" and not getattr(company, "enable_attendance", True):
        chain.append("Feature denied: Attendance is disabled for this workspace.")
        return Decision(False, "DENY_FEATURE_DISABLED", tuple(chain))
    if action == "share_externally" and not getattr(company, "enable_external_sharing", True):
        chain.append("Feature denied: External document sharing is disabled for this workspace.")
        return Decision(False, "DENY_FEATURE_DISABLED", tuple(chain))

    # Non-document workspace/admin actions
    if document is None:
        return _decide_workspace_action(user, company, action, ctx, chain)

    # ── GATE 2 & GATE 3: Document-scoped actions ────────────────────────
    same_tenant = document.company_id == company_id
    is_adm = is_company_admin(user)
    is_dm = is_dept_manager(user)
    user_clr = effective_clearance(user)
    user_clr_rank = clearance_rank(user_clr)
    doc_sens = document.sensitivity or "standard"
    doc_sens_rank = clearance_rank(doc_sens)
    include_unapproved = bool(ctx.get("include_unapproved", False))
    include_external = bool(ctx.get("include_external_shares", True))

    if not same_tenant:
        # Cross-tenant actions: ONLY read/ask/download via an active, unexpired external share.
        if action not in ("view_ask", "download") or not include_external:
            chain.append("Tenant denied: document belongs to another company.")
            return Decision(False, "DENY_WRONG_TENANT", tuple(chain))
        owner_co = getattr(document, "company", None)
        if not owner_co or not getattr(owner_co, "enable_external_sharing", True):
            chain.append("Tenant denied: owning company has disabled external sharing.")
            return Decision(False, "DENY_EXTERNAL_SHARING_DISABLED", tuple(chain))
        share = _find_active_share(user, document)
        if share is None:
            chain.append("Tenant denied: no active, unexpired external share for this user.")
            return Decision(False, "DENY_WRONG_TENANT", tuple(chain))
        if document.status != "approved":
            chain.append(f"Lifecycle denied: external share requires approved status (currently {document.status}).")
            return Decision(False, "DENY_UNAPPROVED_STATUS", tuple(chain))
        if doc_sens == "confidential":
            chain.append("Clearance denied: confidential documents cannot be accessed via external share.")
            return Decision(False, "DENY_CONFIDENTIAL_EXTERNAL", tuple(chain))
        if user_clr_rank < doc_sens_rank:
            chain.append(
                f"Clearance denied: user clearance ({user_clr}) is below document sensitivity ({doc_sens})."
            )
            return Decision(False, "DENY_CLEARANCE_INSUFFICIENT", tuple(chain))
        if action == "download" and not share.can_download:
            chain.append("Action denied: external share has download disabled (view-only).")
            return Decision(False, "DENY_DOWNLOAD_DISABLED", tuple(chain))
        chain.append("Allowed via active external DocumentShare matching clearance.")
        return Decision(True, "ALLOW_EXTERNAL_SHARE", tuple(chain))

    # Same-tenant document actions
    grant = _find_grant(user, document)
    is_uploader = bool(document.uploaded_by_id and document.uploaded_by_id == user.id)
    in_doc_dept = bool(user.department_id and document.department_id and user.department_id == document.department_id)

    # Break-glass action (admin self-grant on restricted doc)
    if action == "break_glass":
        if not is_adm:
            chain.append("Role denied: only a company admin may invoke break-glass access.")
            return Decision(False, "DENY_ADMIN_REQUIRED", tuple(chain))
        if document.access_scope != "restricted":
            chain.append("Action denied: break-glass is only needed for restricted documents.")
            return Decision(False, "DENY_NOT_RESTRICTED", tuple(chain))
        reason = str(ctx.get("reason") or "").strip()
        if len(reason) < 5:
            chain.append("Validation denied: break-glass requires a written reason (at least 5 characters).")
            return Decision(False, "DENY_REASON_REQUIRED", tuple(chain))
        chain.append("Allowed: company admin invoking audited break-glass on own-company restricted document.")
        return Decision(True, "ALLOW_BREAK_GLASS", tuple(chain))

    # Read / AI Ask / Download
    if action in ("view_ask", "download"):
        return _decide_doc_read(
            user, document, action,
            is_adm=is_adm, is_dm=is_dm, is_uploader=is_uploader,
            in_doc_dept=in_doc_dept, grant=grant,
            user_clr=user_clr, user_clr_rank=user_clr_rank,
            doc_sens=doc_sens, doc_sens_rank=doc_sens_rank,
            include_unapproved=include_unapproved, chain=chain,
        )

    # Management actions require same-tenant visibility or specific admin/manager authority
    if action == "edit_metadata":
        if user.role == "viewer":
            chain.append("Role denied: viewers cannot edit document metadata.")
            return Decision(False, "DENY_VIEWER_READ_ONLY", tuple(chain))
        read_dec = _decide_doc_read(
            user, document, "view_ask",
            is_adm=is_adm, is_dm=is_dm, is_uploader=is_uploader,
            in_doc_dept=in_doc_dept, grant=grant,
            user_clr=user_clr, user_clr_rank=user_clr_rank,
            doc_sens=doc_sens, doc_sens_rank=doc_sens_rank,
            include_unapproved=True, chain=list(chain),
        )
        if not read_dec.allowed:
            return read_dec
        chain.append("Allowed: same-company editor with read access editing metadata.")
        return Decision(True, "ALLOW_EDIT_METADATA", tuple(chain))

    if action == "change_scope_sensitivity":
        if user.role == "viewer":
            chain.append("Role denied: viewers cannot change scope or sensitivity.")
            return Decision(False, "DENY_VIEWER_READ_ONLY", tuple(chain))
        new_scope = ctx.get("new_scope") or document.access_scope
        new_sens = ctx.get("new_sensitivity") or document.sensitivity
        new_dept_id = ctx.get("new_department_id", document.department_id)

        if new_scope == "department":
            plan = _company_plan(company)
            if plan and not plan.allow_departments:
                chain.append("Plan denied: department-scoped documents require a plan with departments enabled.")
                return Decision(False, "DENY_PLAN_LIMIT", tuple(chain))

        if is_adm:
            if document.access_scope == "restricted" and not is_uploader and grant is None:
                chain.append("Scope denied: admin needs break-glass grant before modifying a restricted document.")
                return Decision(False, "DENY_ADMIN_NEEDS_BREAK_GLASS", tuple(chain), metadata_only=True)
            if clearance_rank(new_sens) > user_clr_rank:
                chain.append("Clearance denied: cannot assign sensitivity above your own clearance.")
                return Decision(False, "DENY_CLEARANCE_EXCEEDS_ACTOR", tuple(chain))
            chain.append("Allowed: company admin changing document scope/sensitivity.")
            return Decision(True, "ALLOW_ADMIN_SCOPE_CHANGE", tuple(chain))

        if is_dm:
            if document.access_scope == "restricted" and not is_uploader and grant is None:
                chain.append("Scope denied: department manager cannot alter an ungranted restricted document.")
                return Decision(False, "DENY_SCOPE_RESTRICTED", tuple(chain))
            if not (in_doc_dept or is_uploader):
                chain.append("Department denied: department manager may only manage documents in their own department.")
                return Decision(False, "DENY_OUTSIDE_DEPARTMENT", tuple(chain))
            if doc_sens == "confidential" or new_sens == "confidential":
                chain.append("Clearance denied: department managers cannot modify or set confidential sensitivity.")
                return Decision(False, "DENY_DEPT_MANAGER_CONFIDENTIAL", tuple(chain))
            if new_scope == "department" and new_dept_id != user.department_id:
                chain.append("Department denied: department manager cannot move documents into another department.")
                return Decision(False, "DENY_OUTSIDE_DEPARTMENT", tuple(chain))
            chain.append("Allowed: department manager changing scope/sensitivity within own department (<= internal).")
            return Decision(True, "ALLOW_DEPT_MANAGER_SCOPE_CHANGE", tuple(chain))

        # Regular employee: ONLY uploader, and ONLY MORE restrictive
        if not is_uploader:
            chain.append("Role denied: only the uploader, a department manager, or an admin can change access scope or sensitivity.")
            return Decision(False, "DENY_NOT_OWNER", tuple(chain))
        if new_sens == "confidential" or clearance_rank(new_sens) > user_clr_rank:
            chain.append("Clearance denied: employees cannot set confidential sensitivity.")
            return Decision(False, "DENY_CLEARANCE_EXCEEDS_ACTOR", tuple(chain))
        old_scope_rank = SCOPE_RESTRICTIVENESS.get(document.access_scope, 1)
        new_scope_rank = SCOPE_RESTRICTIVENESS.get(new_scope, 1)
        if new_scope_rank < old_scope_rank:
            chain.append(
                f"Policy denied: uploaders may only make their document more restrictive "
                f"(cannot widen {document.access_scope} -> {new_scope}; ask a manager or admin)."
            )
            return Decision(False, "DENY_UPLOADER_CANNOT_WIDEN", tuple(chain))
        if clearance_rank(new_sens) < doc_sens_rank:
            chain.append(
                f"Policy denied: uploaders cannot lower sensitivity ({doc_sens} -> {new_sens}); ask a manager or admin."
            )
            return Decision(False, "DENY_UPLOADER_CANNOT_LOWER_SENSITIVITY", tuple(chain))
        if new_scope == "department" and new_dept_id != user.department_id:
            chain.append("Department denied: employees may only scope documents to their own department.")
            return Decision(False, "DENY_OUTSIDE_DEPARTMENT", tuple(chain))
        chain.append("Allowed: uploader tightening their own document's scope/sensitivity.")
        return Decision(True, "ALLOW_UPLOADER_TIGHTEN", tuple(chain))

    if action in ("approve", "reject"):
        if is_adm:
            if document.access_scope == "restricted" and not is_uploader and grant is None:
                chain.append("Scope denied: admin needs break-glass grant before reviewing a restricted document.")
                return Decision(False, "DENY_ADMIN_NEEDS_BREAK_GLASS", tuple(chain), metadata_only=True)
            chain.append("Allowed: company admin reviewing document.")
            return Decision(True, "ALLOW_ADMIN_REVIEW", tuple(chain))
        if is_dm:
            if document.access_scope == "restricted":
                chain.append("Scope denied: department managers cannot approve restricted documents.")
                return Decision(False, "DENY_SCOPE_RESTRICTED", tuple(chain))
            if not in_doc_dept:
                chain.append("Department denied: department managers can only review documents in their own department.")
                return Decision(False, "DENY_OUTSIDE_DEPARTMENT", tuple(chain))
            if doc_sens == "confidential":
                chain.append("Clearance denied: department managers cannot review confidential documents.")
                return Decision(False, "DENY_DEPT_MANAGER_CONFIDENTIAL", tuple(chain))
            if action == "approve" and is_uploader and getattr(company, "require_doc_approval", False):
                chain.append("Policy denied: uploaders cannot self-approve when approval workflow is enabled.")
                return Decision(False, "DENY_SELF_APPROVAL", tuple(chain))
            chain.append("Allowed: department manager reviewing own-department document (<= internal).")
            return Decision(True, "ALLOW_DEPT_MANAGER_REVIEW", tuple(chain))
        chain.append("Role denied: only a department manager or company admin can approve or reject documents.")
        return Decision(False, "DENY_REVIEW_ROLE_REQUIRED", tuple(chain))

    if action == "archive":
        if document.legal_hold:
            chain.append("Legal hold denied: documents under legal hold cannot be archived.")
            return Decision(False, "DENY_LEGAL_HOLD", tuple(chain))
        if is_adm:
            if document.access_scope == "restricted" and not is_uploader and grant is None:
                chain.append("Scope denied: admin needs break-glass grant before archiving a restricted document.")
                return Decision(False, "DENY_ADMIN_NEEDS_BREAK_GLASS", tuple(chain), metadata_only=True)
            chain.append("Allowed: company admin archiving document.")
            return Decision(True, "ALLOW_ADMIN_ARCHIVE", tuple(chain))
        if is_dm and in_doc_dept and document.access_scope != "restricted" and doc_sens != "confidential":
            chain.append("Allowed: department manager archiving own-department document (<= internal).")
            return Decision(True, "ALLOW_DEPT_MANAGER_ARCHIVE", tuple(chain))
        chain.append("Role denied: only a company admin or own-department manager may archive this document.")
        return Decision(False, "DENY_ARCHIVE_ROLE_REQUIRED", tuple(chain))

    if action == "delete":
        if document.legal_hold:
            chain.append("Legal hold denied: document is under legal hold and cannot be deleted.")
            return Decision(False, "DENY_LEGAL_HOLD", tuple(chain))
        if is_adm:
            # AUTHZ-08: same break-glass rule as every other admin action on restricted docs.
            if document.access_scope == "restricted" and not is_uploader and grant is None:
                chain.append("Scope denied: admin needs break-glass grant before deleting a restricted document.")
                return Decision(False, "DENY_ADMIN_NEEDS_BREAK_GLASS", tuple(chain), metadata_only=True)
            chain.append("Allowed: company admin deleting own-company document (no legal hold).")
            return Decision(True, "ALLOW_ADMIN_DELETE", tuple(chain))
        if is_dm and (is_uploader or (in_doc_dept and document.access_scope != "restricted" and doc_sens != "confidential")):
            chain.append("Allowed: department manager deleting permitted document (no legal hold).")
            return Decision(True, "ALLOW_DEPT_MANAGER_DELETE", tuple(chain))
        if user.role == "employee" and is_uploader:
            chain.append("Allowed: uploader deleting their own document (no legal hold).")
            return Decision(True, "ALLOW_UPLOADER_DELETE", tuple(chain))
        chain.append("Role denied: only the uploader, department manager, or admin may delete this document.")
        return Decision(False, "DENY_DELETE_NOT_PERMITTED", tuple(chain))

    if action == "new_version":
        plan = _company_plan(company)
        if plan and not plan.allow_versions:
            chain.append("Plan denied: document version history is not included on this plan.")
            return Decision(False, "DENY_PLAN_LIMIT", tuple(chain))
        if document.legal_hold:
            chain.append("Legal hold denied: cannot overwrite a document under legal hold.")
            return Decision(False, "DENY_LEGAL_HOLD", tuple(chain))
        if is_adm:
            if document.access_scope == "restricted" and not is_uploader and grant is None:
                chain.append("Scope denied: admin needs break-glass grant before uploading a new version of a restricted document.")
                return Decision(False, "DENY_ADMIN_NEEDS_BREAK_GLASS", tuple(chain), metadata_only=True)
            chain.append("Allowed: company admin uploading new version.")
            return Decision(True, "ALLOW_NEW_VERSION", tuple(chain))
        if is_dm and (is_uploader or (in_doc_dept and document.access_scope != "restricted" and doc_sens != "confidential")):
            chain.append("Allowed: department manager uploading new version within department.")
            return Decision(True, "ALLOW_NEW_VERSION", tuple(chain))
        if user.role == "employee" and is_uploader:
            chain.append("Allowed: uploader uploading new version of own document.")
            return Decision(True, "ALLOW_NEW_VERSION", tuple(chain))
        chain.append("Role denied: only the uploader, own-department manager, or admin may upload a new version.")
        return Decision(False, "DENY_NEW_VERSION_NOT_PERMITTED", tuple(chain))

    if action == "reindex":
        if is_adm:
            if document.access_scope == "restricted" and not is_uploader and grant is None:
                chain.append("Scope denied: admin needs break-glass grant before reindexing a restricted document.")
                return Decision(False, "DENY_ADMIN_NEEDS_BREAK_GLASS", tuple(chain), metadata_only=True)
            chain.append("Allowed: company admin reindexing document.")
            return Decision(True, "ALLOW_REINDEX", tuple(chain))
        if is_dm and (is_uploader or (in_doc_dept and document.access_scope != "restricted" and doc_sens != "confidential")):
            chain.append("Allowed: department manager reindexing own-department document.")
            return Decision(True, "ALLOW_REINDEX", tuple(chain))
        if user.role == "employee" and is_uploader:
            chain.append("Allowed: uploader reindexing own document.")
            return Decision(True, "ALLOW_REINDEX", tuple(chain))
        chain.append("Role denied: cannot reindex a document you do not manage.")
        return Decision(False, "DENY_REINDEX_NOT_PERMITTED", tuple(chain))

    if action == "share_externally":
        if document.status != "approved":
            chain.append("Lifecycle denied: only approved documents may be shared externally.")
            return Decision(False, "DENY_UNAPPROVED_STATUS", tuple(chain))
        if doc_sens == "confidential":
            chain.append("Clearance denied: confidential documents cannot be shared externally.")
            return Decision(False, "DENY_CONFIDENTIAL_EXTERNAL", tuple(chain))
        if is_adm:
            if document.access_scope == "restricted" and not is_uploader and grant is None:
                chain.append("Scope denied: admin needs break-glass grant before sharing a restricted document.")
                return Decision(False, "DENY_ADMIN_NEEDS_BREAK_GLASS", tuple(chain), metadata_only=True)
            chain.append("Allowed: company admin sharing approved non-confidential document externally.")
            return Decision(True, "ALLOW_EXTERNAL_SHARE_CREATE", tuple(chain))
        # Uploader/manager may share non-confidential approved documents they manage only if company policy allows
        if is_dm and (is_uploader or (in_doc_dept and document.access_scope != "restricted")):
            chain.append("Allowed: department manager sharing approved department document externally.")
            return Decision(True, "ALLOW_EXTERNAL_SHARE_CREATE", tuple(chain))
        if user.role == "employee" and is_uploader and document.access_scope != "company":
            chain.append("Allowed: uploader sharing own approved non-confidential document externally.")
            return Decision(True, "ALLOW_EXTERNAL_SHARE_CREATE", tuple(chain))
        chain.append("Role denied: you do not have permission to share this document externally.")
        return Decision(False, "DENY_SHARE_NOT_PERMITTED", tuple(chain))

    if action == "manage_grants":
        override_clr = bool(ctx.get("override_clearance", False))
        grant_reason = str(ctx.get("grant_reason") or "").strip()
        if override_clr:
            if not is_adm:
                chain.append("Role denied: only a company admin may override clearance on a grant.")
                return Decision(False, "DENY_CLEARANCE_OVERRIDE_ADMIN_ONLY", tuple(chain))
            if len(grant_reason) < 5:
                chain.append("Validation denied: overriding clearance requires a mandatory reason (at least 5 characters).")
                return Decision(False, "DENY_REASON_REQUIRED", tuple(chain))
        if is_adm:
            if document.access_scope == "restricted" and not is_uploader and grant is None:
                chain.append("Scope denied: admin needs break-glass grant before managing grants on a restricted document.")
                return Decision(False, "DENY_ADMIN_NEEDS_BREAK_GLASS", tuple(chain), metadata_only=True)
            chain.append("Allowed: company admin managing document grants.")
            return Decision(True, "ALLOW_MANAGE_GRANTS", tuple(chain))
        if is_dm and (is_uploader or (in_doc_dept and document.access_scope != "restricted" and doc_sens != "confidential")):
            chain.append("Allowed: department manager managing grants within own department.")
            return Decision(True, "ALLOW_MANAGE_GRANTS", tuple(chain))
        if user.role == "employee" and is_uploader:
            chain.append("Allowed: uploader managing grants on their own document.")
            return Decision(True, "ALLOW_MANAGE_GRANTS", tuple(chain))
        chain.append("Role denied: you do not have permission to manage access grants for this document.")
        return Decision(False, "DENY_MANAGE_GRANTS_NOT_PERMITTED", tuple(chain))

    chain.append(f"Unknown action '{action}' denied by default (fail-closed).")
    return Decision(False, "DENY_UNKNOWN_ACTION", tuple(chain))


def _decide_doc_read(
    user,
    document: Document,
    action: str,
    *,
    is_adm: bool,
    is_dm: bool,
    is_uploader: bool,
    in_doc_dept: bool,
    grant: DocumentAccess | None,
    user_clr: str,
    user_clr_rank: int,
    doc_sens: str,
    doc_sens_rank: int,
    include_unapproved: bool,
    chain: list[str],
) -> Decision:
    # 1) Determine audience match
    via_natural = False
    via_uploader = False
    via_grant = grant is not None

    if document.access_scope == "company":
        via_natural = True
    elif document.access_scope == "department":
        if is_adm or in_doc_dept:
            via_natural = True
    elif document.access_scope == "restricted":
        if is_uploader:
            via_uploader = True

    if not (via_natural or via_uploader or via_grant):
        if document.access_scope == "restricted":
            if is_adm:
                chain.append(
                    "Gate 2 denied: document is restricted; company admins see masked metadata only "
                    "and must invoke break-glass with a reason to read content."
                )
                return Decision(False, "DENY_ADMIN_NEEDS_BREAK_GLASS", tuple(chain), metadata_only=True)
            chain.append("Gate 2 denied: document is restricted to the uploader and explicitly granted users.")
            return Decision(False, "DENY_SCOPE_RESTRICTED", tuple(chain))
        chain.append("Gate 2 denied: document is restricted to another department.")
        return Decision(False, "DENY_SCOPE_DEPARTMENT", tuple(chain))

    # 2) Lifecycle status check
    st = document.status or "approved"
    if not include_unapproved:
        if st != "approved":
            chain.append(f"Gate 2 denied: document status is '{st}'; AI and standard views require 'approved'.")
            return Decision(False, "DENY_ARCHIVED_STATUS" if st == "archived" else "DENY_UNAPPROVED_STATUS", tuple(chain))
    else:
        if st in ("draft", "in_review"):
            can_see_wip = (
                is_uploader
                or (is_adm and (document.access_scope != "restricted" or via_grant))
                or (is_dm and in_doc_dept and document.access_scope != "restricted" and doc_sens in ("standard", "internal"))
            )
            if not can_see_wip:
                chain.append(f"Gate 2 denied: document is '{st}' and only visible to uploader, department manager, or admin.")
                return Decision(False, "DENY_UNAPPROVED_STATUS", tuple(chain))
        elif st == "archived":
            can_see_arch = (
                (is_adm and (document.access_scope != "restricted" or via_grant or is_uploader))
                or (is_dm and in_doc_dept and document.access_scope != "restricted" and doc_sens in ("standard", "internal"))
            )
            if not can_see_arch:
                chain.append("Gate 2 denied: archived documents are only visible to admins and department managers.")
                return Decision(False, "DENY_ARCHIVED_STATUS", tuple(chain))

    chain.append(f"Gate 2 passed: audience={document.access_scope}, status={st}.")

    # 3) Clearance vs Sensitivity check
    clearance_ok = user_clr_rank >= doc_sens_rank
    override_ok = bool(grant and grant.override_clearance)
    if not (clearance_ok or override_ok):
        chain.append(
            f"Gate 3 denied: user clearance '{user_clr}' is below document sensitivity '{doc_sens}'"
            + (" (grant widens audience only; no clearance override set)." if via_grant else ".")
        )
        return Decision(False, "DENY_CLEARANCE_INSUFFICIENT", tuple(chain))

    # 4) Download check (when access comes solely from a grant with can_download=False)
    if action == "download":
        has_direct = (via_natural or via_uploader) and clearance_ok
        if not has_direct and grant is not None and not grant.can_download:
            chain.append("Gate 3 denied: grant allows viewing/AI Q&A only (download disabled).")
            return Decision(False, "DENY_DOWNLOAD_DISABLED", tuple(chain))

    if override_ok and not clearance_ok:
        chain.append(f"Gate 3 passed via audited clearance override on grant (reason: {grant.grant_reason or 'recorded'}).")
        return Decision(True, "ALLOW_GRANT_OVERRIDE", tuple(chain))
    if via_grant and not (via_natural or via_uploader):
        chain.append(f"Gate 3 passed via explicit DocumentAccess grant (clearance={user_clr} >= {doc_sens}).")
        return Decision(True, "ALLOW_GRANT", tuple(chain))
    if via_uploader and document.access_scope == "restricted":
        chain.append(f"Gate 3 passed: uploader accessing own restricted document (clearance={user_clr} >= {doc_sens}).")
        return Decision(True, "ALLOW_UPLOADER", tuple(chain))
    chain.append(f"Gate 3 passed: {document.access_scope} audience & clearance ({user_clr} >= {doc_sens}).")
    return Decision(True, "ALLOW_SCOPE_AND_CLEARANCE", tuple(chain))


def _decide_workspace_action(user, company, action: str, ctx: dict[str, Any], chain: list[str]) -> Decision:
    is_adm = is_company_admin(user)
    is_dm = is_dept_manager(user)
    user_clr = effective_clearance(user)
    user_clr_rank = clearance_rank(user_clr)

    if action == "upload":
        if user.role == "viewer":
            chain.append("Role denied: viewers cannot upload documents.")
            return Decision(False, "DENY_VIEWER_READ_ONLY", tuple(chain))
        scope = (ctx.get("access_scope") or "company").strip().lower()
        sens = (ctx.get("sensitivity") or "standard").strip().lower()
        dept_id = ctx.get("department_id")
        is_okf = bool(ctx.get("is_okf", False))
        is_template = bool(ctx.get("is_template", False))

        if (is_okf or is_template) and not is_adm:
            chain.append("Role denied: only a company admin may mark a document as OKF or template.")
            return Decision(False, "DENY_ADMIN_REQUIRED", tuple(chain))
        if scope == "department":
            plan = _company_plan(company)
            if plan and not plan.allow_departments:
                chain.append("Plan denied: department-scoped uploads require a plan with departments enabled.")
                return Decision(False, "DENY_PLAN_LIMIT", tuple(chain))
            if not is_adm and dept_id and user.department_id != dept_id:
                chain.append("Department denied: non-admins may only upload department documents to their own department.")
                return Decision(False, "DENY_OUTSIDE_DEPARTMENT", tuple(chain))
        if not is_adm and sens == "confidential":
            chain.append("Clearance denied: only a company admin may upload confidential documents.")
            return Decision(False, "DENY_CONFIDENTIAL_ADMIN_ONLY", tuple(chain))
        if clearance_rank(sens) > user_clr_rank:
            chain.append(f"Clearance denied: cannot upload sensitivity '{sens}' above your own clearance '{user_clr}'.")
            return Decision(False, "DENY_CLEARANCE_EXCEEDS_ACTOR", tuple(chain))
        chain.append("Allowed: upload permitted by role, department, and clearance.")
        return Decision(True, "ALLOW_UPLOAD", tuple(chain))

    if action == "explain_access":
        target_user = ctx.get("target_user")
        target_doc = ctx.get("document")
        if is_adm:
            if target_user and target_user.company_id != user.company_id:
                chain.append("Tenant denied: target user belongs to another company.")
                return Decision(False, "DENY_WRONG_TENANT", tuple(chain))
            if target_doc and target_doc.company_id != user.company_id:
                chain.append("Tenant denied: target document belongs to another company.")
                return Decision(False, "DENY_WRONG_TENANT", tuple(chain))
            chain.append("Allowed: company admin explaining access inside own company.")
            return Decision(True, "ALLOW_EXPLAIN", tuple(chain))
        if is_dm:
            if target_user and (target_user.company_id != user.company_id or target_user.department_id != user.department_id):
                chain.append("Department denied: department managers may only explain access for members of their own department.")
                return Decision(False, "DENY_OUTSIDE_DEPARTMENT", tuple(chain))
            if target_doc and (
                target_doc.company_id != user.company_id
                or target_doc.access_scope == "restricted"
                or target_doc.sensitivity == "confidential"
                or (target_doc.access_scope == "department" and target_doc.department_id != user.department_id)
            ):
                chain.append("Department denied: department managers may only inspect non-restricted, <= internal docs in their scope.")
                return Decision(False, "DENY_OUTSIDE_DEPARTMENT", tuple(chain))
            chain.append("Allowed: department manager explaining access inside own department.")
            return Decision(True, "ALLOW_EXPLAIN", tuple(chain))
        chain.append("Role denied: only company admins and department managers may inspect effective access.")
        return Decision(False, "DENY_EXPLAIN_ROLE_REQUIRED", tuple(chain))

    if action in ("manage_members", "change_roles"):
        target_user = ctx.get("target_user")
        new_role = ctx.get("new_role")
        new_is_dept_admin = ctx.get("new_is_dept_admin")
        new_clearance = ctx.get("new_clearance")
        new_dept_id = ctx.get("new_department_id")

        if is_adm:
            if target_user and target_user.company_id != user.company_id:
                chain.append("Tenant denied: target member belongs to another company.")
                return Decision(False, "DENY_WRONG_TENANT", tuple(chain))
            if target_user and target_user.id == user.id and (
                (new_role and new_role != user.role)
                or (new_clearance and clearance_rank(new_clearance) != user_clr_rank)
                or ctx.get("deactivate")
            ):
                chain.append("Guardrail denied: admins cannot demote or deactivate themselves.")
                return Decision(False, "DENY_SELF_DEMOTION", tuple(chain))
            if new_clearance and clearance_rank(new_clearance) > user_clr_rank:
                chain.append("Clearance denied: cannot assign clearance above your own clearance.")
                return Decision(False, "DENY_CLEARANCE_EXCEEDS_ACTOR", tuple(chain))
            chain.append("Allowed: company admin managing member.")
            return Decision(True, "ALLOW_MANAGE_MEMBERS", tuple(chain))

        if is_dm:
            if target_user:
                if target_user.id == user.id:
                    chain.append("Guardrail denied: department managers cannot modify their own role, department, or clearance.")
                    return Decision(False, "DENY_SELF_MODIFY", tuple(chain))
                if target_user.company_id != user.company_id or target_user.department_id != user.department_id:
                    chain.append("Department denied: department managers only manage members in their own department.")
                    return Decision(False, "DENY_OUTSIDE_DEPARTMENT", tuple(chain))
                if target_user.role == "admin":
                    chain.append("Role denied: department managers cannot modify company admins.")
                    return Decision(False, "DENY_ESCALATION_BLOCKED", tuple(chain))
            if new_role == "admin" or new_is_dept_admin:
                chain.append("Role denied: department managers cannot create or promote admins or managers.")
                return Decision(False, "DENY_ESCALATION_BLOCKED", tuple(chain))
            if new_dept_id is not None and new_dept_id != user.department_id:
                chain.append("Department denied: department managers cannot move users across departments.")
                return Decision(False, "DENY_OUTSIDE_DEPARTMENT", tuple(chain))
            if new_clearance and clearance_rank(new_clearance) > CLEARANCE_RANK["internal"]:
                chain.append("Clearance denied: department managers cannot raise clearance above internal.")
                return Decision(False, "DENY_CLEARANCE_EXCEEDS_ACTOR", tuple(chain))
            chain.append("Allowed: department manager managing own-department non-admin member.")
            return Decision(True, "ALLOW_DEPT_MANAGER_MEMBERS", tuple(chain))

        chain.append("Role denied: only admins and department managers can manage members.")
        return Decision(False, "DENY_MANAGE_MEMBERS_ROLE_REQUIRED", tuple(chain))

    if action in ("view_export_audit", "settings", "billing", "llm_config", "manage_departments", "manage_attendance"):
        if not is_adm:
            chain.append(f"Role denied: '{action}' requires a company admin.")
            return Decision(False, "DENY_ADMIN_REQUIRED", tuple(chain))
        if action == "llm_config":
            plan = _company_plan(company)
            if plan and not plan.allow_custom_llm:
                chain.append("Plan denied: custom LLM configuration requires a higher plan.")
                return Decision(False, "DENY_PLAN_LIMIT", tuple(chain))
        if action == "manage_departments":
            plan = _company_plan(company)
            if plan and not plan.allow_departments:
                chain.append("Plan denied: departments are not enabled on this plan.")
                return Decision(False, "DENY_PLAN_LIMIT", tuple(chain))
        chain.append(f"Allowed: company admin performing '{action}'.")
        return Decision(True, "ALLOW_ADMIN_ACTION", tuple(chain))

    if action in ("ai_chat", "docgen", "team_chat", "attendance"):
        chain.append(f"Allowed: feature '{action}' is enabled for this workspace.")
        return Decision(True, "ALLOW_FEATURE", tuple(chain))

    chain.append(f"Unknown action '{action}' denied by default (fail-closed).")
    return Decision(False, "DENY_UNKNOWN_ACTION", tuple(chain))
