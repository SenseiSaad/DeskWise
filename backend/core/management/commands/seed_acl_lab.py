"""Idempotent ACL permission-lab seeder for Deskwise.

Safety guards (hard rules):
  1. Refuses to run unless settings.DEBUG is True OR --allow-live is explicitly passed.
  2. Company name MUST start with "ACLTEST-".
  3. Platform admin account is created ONLY when settings.DEBUG is True (local only).
  4. Supports --cleanup to remove the lab companies cleanly via AuditLog.purge_for_company().
"""
from __future__ import annotations

from datetime import timedelta
import hashlib
import secrets

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.text import slugify

from core import storage
from core.models import (
    AuditLog,
    Chunk,
    Company,
    Department,
    Document,
    DocumentAccess,
    DocumentShare,
    DocumentVersion,
    Plan,
    TeamRoom,
    User,
)

LAB_DEFAULT_PASSWORD = "AclLab-TestPass!2026"


def _canary(tag: str) -> str:
    digest = hashlib.sha256(tag.encode("utf-8")).hexdigest()[:6].upper()
    clean = tag.upper().replace(" ", "-").replace("/", "-")
    return f"CANARY-{clean}-{digest}"


def seed_acl_lab_data(
    company_name: str = "ACLTEST-Lab",
    *,
    password: str = LAB_DEFAULT_PASSWORD,
    include_platform_admin: bool = True,
) -> dict:
    """Create or refresh the full ACL lab dataset and return structured handles."""
    if not company_name.startswith("ACLTEST-"):
        raise ValueError("ACL lab company name must start with 'ACLTEST-'.")

    slug = slugify(company_name)
    other_name = f"{company_name}-Other"
    other_slug = slugify(other_name)

    plan, _ = Plan.objects.get_or_create(
        name="ACL Lab Enterprise",
        defaults={
            "price_usd": 129,
            "max_members": None,
            "max_documents": None,
            "storage_mb": None,
            "monthly_ask_limit": None,
            "allow_versions": True,
            "allow_departments": True,
            "allow_custom_llm": True,
            "is_default": False,
        },
    )

    company, _ = Company.objects.update_or_create(
        slug=slug,
        defaults={
            "name": company_name,
            "plan": plan,
            "enable_ai_chat": True,
            "enable_docgen": True,
            "enable_external_sharing": True,
            "enable_team_chat": True,
            "enable_attendance": False,
            "require_doc_approval": False,
        },
    )
    other_company, _ = Company.objects.update_or_create(
        slug=other_slug,
        defaults={
            "name": other_name,
            "plan": plan,
            "enable_ai_chat": True,
            "enable_docgen": True,
            "enable_external_sharing": True,
            "enable_team_chat": False,
            "enable_attendance": False,
        },
    )

    depts: dict[str, Department] = {}
    for dname in ("HR", "Finance", "Engineering"):
        d, _ = Department.objects.get_or_create(company=company, name=dname)
        depts[dname] = d

    def _upsert_user(key: str, email: str, role: str, *, dept=None, is_dm=False,
                     clearance="", is_active=True, co=company, is_plat=False) -> User:
        u = User.objects.filter(email=email).first()
        if u is None:
            u = User.objects.create_user(
                email=email,
                password=password,
                full_name=key.replace("_", " ").title(),
                role=role,
                is_dept_admin=is_dm,
                clearance=clearance,
                company=co,
                department=dept,
                is_active=is_active,
                is_platform_admin=is_plat,
                email_verified=True,
            )
        else:
            u.role = role
            u.is_dept_admin = is_dm
            u.clearance = clearance
            u.company = co
            u.department = dept
            u.is_active = is_active
            u.is_platform_admin = is_plat
            u.email_verified = True
            u.set_password(password)
            u.save()
        return u

    domain = f"{slug}.acltest.local"
    users: dict[str, User] = {}
    users["admin"] = _upsert_user("admin", f"admin@{domain}", "admin")
    users["no_dept_employee"] = _upsert_user("no_dept_employee", f"nodept@{domain}", "employee", dept=None)
    users["ex_employee"] = _upsert_user("ex_employee", f"ex@{domain}", "employee", dept=depts["HR"], is_active=False)
    users["ext_partner"] = _upsert_user(
        "ext_partner", f"partner@{other_slug}.acltest.local", "employee", co=other_company,
    )
    if include_platform_admin:
        users["platform_admin"] = _upsert_user(
            "platform_admin", f"platform@{domain}", "admin", co=None, is_plat=True,
        )

    for dname, dept in depts.items():
        dl = dname.lower()
        users[f"{dl}_viewer"] = _upsert_user(f"{dl}_viewer", f"{dl}.viewer@{domain}", "viewer", dept=dept)
        users[f"{dl}_employee"] = _upsert_user(f"{dl}_employee", f"{dl}.emp@{domain}", "employee", dept=dept)
        users[f"{dl}_manager"] = _upsert_user(
            f"{dl}_manager", f"{dl}.mgr@{domain}", "employee", dept=dept, is_dm=True,
        )

    docs: dict[str, Document] = {}
    canaries: dict[int, str] = {}

    def _upsert_doc(
        key: str,
        filename: str,
        *,
        scope: str,
        sensitivity: str,
        status: str,
        uploader: User,
        dept: Department | None = None,
        legal_hold: bool = False,
        is_okf: bool = False,
        is_template: bool = False,
        template_type: str = "",
        extra_text: str = "",
    ) -> Document:
        canary = _canary(key)
        body = f"Document {key}. Secret marker: {canary}. {extra_text}".strip()
        rel_key = f"{company.slug}/acllab_{key}_{filename}"
        stored = storage.save_bytes(rel_key, body.encode("utf-8"), base_dir=settings.DATA_DIR)
        doc, _ = Document.objects.update_or_create(
            company=company,
            filename=filename,
            defaults={
                "stored_path": stored,
                "content_type": "text/plain",
                "size": len(body.encode("utf-8")),
                "category": dept.name if dept else "General",
                "description": f"ACL lab fixture {key}",
                "tags": f"acllab,{scope},{sensitivity},{status}",
                "access_scope": scope,
                "department": dept,
                "sensitivity": sensitivity,
                "status": status,
                "legal_hold": legal_hold,
                "is_okf": is_okf,
                "is_template": is_template,
                "template_type": template_type,
                "uploaded_by": uploader,
                "indexing_status": "ready",
                "num_chunks": 1,
                "preview_text": body,
            },
        )
        Chunk.objects.filter(document=doc).delete()
        Chunk.objects.create(company=company, document=doc, ord=0, text=body)
        docs[key] = doc
        canaries[doc.id] = canary
        return doc

    # Full matrix of scope × sensitivity × status (3 × 3 × 4 = 36 core docs)
    for scope in ("company", "department", "restricted"):
        for sensitivity in ("standard", "internal", "confidential"):
            for st in ("draft", "in_review", "approved", "archived"):
                dept = depts["HR"] if scope == "department" else None
                uploader = (
                    users["hr_employee"]
                    if scope == "restricted" and sensitivity != "confidential"
                    else users["admin"]
                )
                key = f"{scope}_{sensitivity}_{st}"
                _upsert_doc(
                    key,
                    f"lab_{key}.txt",
                    scope=scope,
                    sensitivity=sensitivity,
                    status=st,
                    uploader=uploader,
                    dept=dept,
                )

    # Extra department docs for Finance & Engineering to verify cross-dept isolation
    _upsert_doc(
        "finance_dept_internal_approved",
        "finance_contract.txt",
        scope="department",
        sensitivity="internal",
        status="approved",
        uploader=users["finance_manager"],
        dept=depts["Finance"],
    )
    _upsert_doc(
        "eng_dept_internal_approved",
        "eng_architecture.txt",
        scope="department",
        sensitivity="internal",
        status="approved",
        uploader=users["engineering_manager"],
        dept=depts["Engineering"],
    )

    # Special governance fixtures: legal_hold, OKF, template, multi-version
    _upsert_doc(
        "legal_hold_doc",
        "litigation_hold.txt",
        scope="company",
        sensitivity="internal",
        status="approved",
        uploader=users["admin"],
        legal_hold=True,
    )
    _upsert_doc(
        "okf_doc",
        "official_policy_okf.txt",
        scope="company",
        sensitivity="standard",
        status="approved",
        uploader=users["admin"],
        is_okf=True,
    )
    _upsert_doc(
        "template_hr_internal",
        "form_hr_leave_acl.md",
        scope="department",
        sensitivity="internal",
        status="approved",
        uploader=users["admin"],
        dept=depts["HR"],
        is_template=True,
        template_type="form",
        extra_text="\nEmployee Name: [Full Name]\nDepartment: [Department]\nDates: [Dates]",
    )
    mv_doc = _upsert_doc(
        "multiversion_doc",
        "handbook_v2.txt",
        scope="department",
        sensitivity="internal",
        status="approved",
        uploader=users["finance_manager"],
        dept=depts["Finance"],
    )
    mv_doc.version = 2
    mv_doc.save(update_fields=["version"])
    v1_body = f"Old version v1 content {_canary('multiversion_v1')}"
    v1_path = storage.save_bytes(f"{company.slug}/acllab_mv_v1.txt", v1_body.encode("utf-8"), base_dir=settings.DATA_DIR)
    DocumentVersion.objects.update_or_create(
        document=mv_doc,
        version_number=1,
        defaults={
            "stored_path": v1_path,
            "filename": "handbook_v1.txt",
            "size": len(v1_body),
            "uploaded_by": users["finance_manager"],
        },
    )

    # Explicit internal grants to test audience vs clearance override
    # 1) Plain grant on confidential doc for hr_viewer -> still DENIED (clearance < confidential)
    DocumentAccess.objects.update_or_create(
        document=docs["restricted_confidential_approved"],
        user=users["hr_viewer"],
        defaults={"can_download": True, "override_clearance": False},
    )
    # 2) Audited clearance-override grant on restricted confidential doc for finance_employee (view-only!)
    DocumentAccess.objects.update_or_create(
        document=docs["restricted_confidential_approved"],
        user=users["finance_employee"],
        defaults={
            "can_download": False,
            "override_clearance": True,
            "grant_reason": "External audit prep access",
            "granted_by": users["admin"],
        },
    )

    # External shares: valid downloadable, valid view-only, expired, revoked
    now = timezone.now()
    ext_valid_doc = _upsert_doc(
        "ext_share_valid",
        "partner_mou_valid.txt",
        scope="company",
        sensitivity="standard",
        status="approved",
        uploader=users["admin"],
    )
    ext_viewonly_doc = _upsert_doc(
        "ext_share_viewonly",
        "partner_mou_viewonly.txt",
        scope="company",
        sensitivity="internal",
        status="approved",
        uploader=users["admin"],
    )
    ext_expired_doc = _upsert_doc(
        "ext_share_expired",
        "partner_mou_expired.txt",
        scope="company",
        sensitivity="standard",
        status="approved",
        uploader=users["admin"],
    )
    DocumentShare.objects.update_or_create(
        document=ext_valid_doc,
        shared_with_user=users["ext_partner"],
        defaults={"shared_by": users["admin"], "can_download": True, "expires_at": now + timedelta(days=7)},
    )
    DocumentShare.objects.update_or_create(
        document=ext_viewonly_doc,
        shared_with_user=users["ext_partner"],
        defaults={"shared_by": users["admin"], "can_download": False, "expires_at": now + timedelta(days=7)},
    )
    DocumentShare.objects.update_or_create(
        document=ext_expired_doc,
        shared_with_user=users["ext_partner"],
        defaults={"shared_by": users["admin"], "can_download": True, "expires_at": now - timedelta(hours=2)},
    )

    # Team chat rooms (default #General + HR dept room)
    TeamRoom.ensure_default(company)
    TeamRoom.objects.get_or_create(
        company=company,
        slug="hr-room",
        defaults={"name": "HR", "scope": "department", "department": depts["HR"]},
    )

    return {
        "company": company,
        "other_company": other_company,
        "departments": depts,
        "users": users,
        "docs": docs,
        "canaries": canaries,
        "password": password,
    }


def cleanup_acl_lab_data(company_name: str = "ACLTEST-Lab") -> int:
    if not company_name.startswith("ACLTEST-"):
        raise ValueError("Refusing to clean up a company that does not start with 'ACLTEST-'.")
    slugs = [slugify(company_name), slugify(f"{company_name}-Other")]
    removed = 0
    for co in Company.objects.filter(slug__in=slugs):
        for doc in Document.objects.filter(company=co):
            if doc.stored_path:
                storage.delete(doc.stored_path, base_dir=settings.DATA_DIR)
        AuditLog.purge_for_company(co, reason="ACLTEST lab cleanup")
        co.delete()
        removed += 1
    User.objects.filter(email__endswith=f"@{slugs[0]}.acltest.local", company__isnull=True).delete()
    return removed


class Command(BaseCommand):
    help = "Seed an idempotent ACLTEST-* permission verification lab."

    def add_arguments(self, parser):
        parser.add_argument(
            "--company",
            type=str,
            default=f"ACLTEST-{timezone.localdate().strftime('%Y%m%d')}",
            help="Company name (MUST start with ACLTEST-).",
        )
        parser.add_argument(
            "--allow-live",
            action="store_true",
            help="Explicitly allow running when DEBUG is False.",
        )
        parser.add_argument(
            "--cleanup",
            action="store_true",
            help="Remove the specified ACLTEST-* company and all its lab data.",
        )

    def handle(self, *args, **options):
        company_name = (options["company"] or "").strip()
        if not company_name.startswith("ACLTEST-"):
            raise CommandError("Refused: --company MUST start with 'ACLTEST-'.")
        if not getattr(settings, "DEBUG", False) and not options["allow_live"]:
            raise CommandError("Refused: DEBUG is False. Pass --allow-live only for intentional ACLTEST-* runs.")

        if options["cleanup"]:
            n = cleanup_acl_lab_data(company_name)
            self.stdout.write(self.style.SUCCESS(f"Cleaned up {n} ACLTEST company workspace(s) for '{company_name}'."))
            return

        result = seed_acl_lab_data(
            company_name=company_name,
            include_platform_admin=bool(getattr(settings, "DEBUG", False)),
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {result['company'].name} ({result['company'].slug}): "
                f"{len(result['departments'])} departments, "
                f"{len(result['users'])} personas, "
                f"{len(result['docs'])} canary documents."
            )
        )
