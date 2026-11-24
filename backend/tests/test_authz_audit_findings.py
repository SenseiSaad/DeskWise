"""Failing tests for the 2026-11 authorization audit (docs/security/authorization.md).

Every test here encodes the EXPECTED secure behaviour and is EXPECTED TO FAIL
against the current code. Each one maps to a finding ID (AUTHZ-NN) in the
report. Do not mark them xfail: they are the acceptance criteria for the fixes.
Once a finding is fixed, its test should pass unchanged.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from core.models import (
    AskLog,
    Chunk,
    Department,
    Document,
    DocumentAccess,
    DocumentVersion,
    Plan,
    TeamMessage,
    TeamRoom,
    User,
)

from .conftest import PASSWORD
from .fakes import StubChatProvider

pytestmark = pytest.mark.django_db

NEW_PASSWORD = "Attacker-chosen-Passw0rd!"


def _doc(company, uploader, filename="doc.txt", text="hello world", **kw):
    fields = dict(
        company=company, filename=filename, stored_path=f"{company.slug}/{filename}",
        size=len(text), uploaded_by=uploader, access_scope="company",
        sensitivity="standard", status="approved", indexing_status="ready",
        preview_text=text,
    )
    fields.update(kw)
    doc = Document.objects.create(**fields)
    Chunk.objects.create(company=company, document=doc, ord=0, text=text)
    return doc


@pytest.fixture
def root(make_user):
    """Platform root admin exactly as `create_platform_admin` creates it."""
    return make_user(None, email="root@platform.test", role="admin",
                     is_platform_admin=True, is_superuser=True, is_staff=True)


# --------------------------------------------------------------------- AUTHZ-01
def test_authz01_dept_manager_cannot_set_member_password(auth_client, make_company, make_user):
    """A department manager must not be able to set a member's password.

    Today PATCH /api/admin/users/<id> {"password": ...} succeeds for a dept
    manager, so they can log in as the member and inherit anything the member
    holds that the manager does not: confidential clearance set by a company
    admin, and personal DocumentAccess grants on restricted documents.
    """
    co = make_company("Acme A01")
    hr = Department.objects.create(company=co, name="HR")
    admin = make_user(co, email="admin-a01@acme.test", role="admin")
    mgr = make_user(co, email="mgr-a01@acme.test", role="employee", department=hr, is_dept_admin=True)
    member = make_user(co, email="member-a01@acme.test", role="employee", department=hr,
                       clearance="confidential")
    secret = _doc(co, admin, filename="board-minutes.txt", access_scope="restricted",
                  sensitivity="confidential", text="restricted board minutes")
    DocumentAccess.objects.create(document=secret, user=member, granted_by=admin)

    resp = auth_client(mgr).patch(f"/api/admin/users/{member.id}",
                                  {"password": NEW_PASSWORD}, format="json")

    member.refresh_from_db()
    assert resp.status_code == 403, resp.content
    assert member.check_password(PASSWORD), "dept manager changed a member's password"


# --------------------------------------------------------------------- AUTHZ-02
def test_authz02_company_admin_cannot_silently_take_over_member_account(auth_client, make_company, make_user):
    """A company admin setting a member's password directly bypasses the
    break-glass control: the admin can sign in as a member who holds a grant on
    a restricted document and read it with no break_glass audit row.

    Expected: admins trigger a reset link to the member's mailbox instead of
    choosing the password (403 on a raw `password` field).
    """
    co = make_company("Acme A02")
    admin = make_user(co, email="admin-a02@acme.test", role="admin")
    owner = make_user(co, email="owner-a02@acme.test", role="employee")
    _doc(co, owner, filename="private.txt", access_scope="restricted", text="owner-only")

    resp = auth_client(admin).patch(f"/api/admin/users/{owner.id}",
                                    {"password": NEW_PASSWORD}, format="json")

    owner.refresh_from_db()
    assert resp.status_code in (400, 403), resp.content
    assert owner.check_password(PASSWORD)


# --------------------------------------------------------------------- AUTHZ-03
def test_authz03_platform_admin_cannot_delete_companyless_users(auth_client, root, make_user):
    """user_detail looks users up with company=request.user.company. For a
    platform admin that is company=None, which matches every account that has
    not finished onboarding (e.g. fresh Google sign-ups). DELETE runs before
    any access.decide() call, so the root admin can delete them.
    """
    pending = make_user(None, email="google-signup@gmail.test", role="employee")

    resp = auth_client(root).delete(f"/api/admin/users/{pending.id}")

    assert resp.status_code in (403, 404), resp.content
    assert User.objects.filter(pk=pending.pk).exists(), "platform admin deleted a user"


# --------------------------------------------------------------------- AUTHZ-04
def test_authz04_platform_admin_cannot_onboard_into_a_tenant(auth_client, root):
    """POST /api/auth/onboard only checks `user.company_id is None`, which is
    true for every platform admin. It then attaches the root account to a new
    company as its admin, breaking the 'root admins never join a tenant'
    invariant that switch_company/detach_company enforce.
    """
    resp = auth_client(root).post("/api/auth/onboard", {"company_name": "Root Holdings"},
                                  format="json")

    root.refresh_from_db()
    assert resp.status_code == 403, resp.content
    assert root.company_id is None


# --------------------------------------------------------------------- AUTHZ-05
def test_authz05_platform_admin_with_company_gets_no_tenant_admin_data(auth_client, make_company, make_user):
    """`create_platform_admin --promote` keeps the promoted user's company.
    IsAdmin endpoints only rely on company being NULL to keep root admins out,
    so a promoted root admin reads the tenant's analytics (member emails and raw
    questions), audit log, and member list.
    """
    co = make_company("Tenant A05")
    emp = make_user(co, email="emp-a05@tenant.test", role="employee")
    AskLog.objects.create(company=co, user=emp, question="how do I report harassment by my manager",
                          chunks_found=0)
    promoted = make_user(co, email="promoted-a05@tenant.test", role="admin",
                         is_platform_admin=True, is_superuser=True, is_staff=True)
    client = auth_client(promoted)

    for path in ("/api/admin/analytics", "/api/admin/audit", "/api/admin/users"):
        resp = client.get(path)
        assert resp.status_code == 403, f"{path} -> {resp.status_code}"


# --------------------------------------------------------------------- AUTHZ-06
def test_authz06_old_versions_count_toward_storage_quota(auth_client, make_company, make_user):
    """Storage quota only sums Document.size (the CURRENT version). Every
    superseded file stays in storage as a DocumentVersion but is never counted,
    so a tenant can store unlimited bytes by uploading new versions.
    """
    plan = Plan.objects.create(name="Tiny A06", price_usd=1, storage_mb=1,
                               allow_versions=True, max_documents=10)
    co = make_company("Acme A06", plan=plan)
    admin = make_user(co, email="admin-a06@acme.test", role="admin")
    chunk = 400 * 1024  # 0.4 MB per version; quota is 1 MB
    doc = _doc(co, admin, filename="big.txt", text="x")
    doc.size = chunk
    doc.save(update_fields=["size"])

    client = auth_client(admin)
    statuses = []
    with patch("core.views._index_in_background"):
        for i in range(5):  # 6 versions x 0.4 MB = 2.4 MB stored against a 1 MB quota
            f = SimpleUploadedFile(f"big-v{i}.txt", b"y" * chunk, content_type="text/plain")
            statuses.append(client.post(f"/api/documents/{doc.id}/versions/new",
                                        {"file": f}, format="multipart").status_code)

    doc.refresh_from_db()
    stored = doc.size + sum(DocumentVersion.objects.filter(document=doc).values_list("size", flat=True))
    assert stored <= 1024 * 1024, f"stored {stored} bytes on a 1 MB plan; statuses={statuses}"
    assert 402 in statuses


# --------------------------------------------------------------------- AUTHZ-08
def test_authz08_admin_cannot_delete_unseen_restricted_document(auth_client, make_company, make_user):
    """Every other admin action on a restricted document the admin cannot read
    (edit scope, approve, archive, reindex, new version, share, manage grants)
    requires break-glass first. delete does not: an admin can destroy a
    restricted document, its versions and its stored files without ever
    recording a break-glass reason.
    """
    co = make_company("Acme A08")
    admin = make_user(co, email="admin-a08@acme.test", role="admin")
    owner = make_user(co, email="owner-a08@acme.test", role="employee")
    doc = _doc(co, owner, filename="grievance.txt", access_scope="restricted", text="grievance")

    resp = auth_client(admin).delete(f"/api/documents/{doc.id}")

    assert resp.status_code == 403, resp.content
    assert Document.objects.filter(pk=doc.pk).exists()


# --------------------------------------------------------------------- AUTHZ-09
def test_authz09_review_submit_requires_access_to_the_document(auth_client, make_company, make_user):
    """document_review 'submit' uses _can_manage_document (admin OR dept admin
    of the doc's department OR uploader) instead of access.decide(). An admin
    without break-glass, or a dept manager, can flip an approved restricted
    document they cannot read back to in_review, pulling it out of the owner's
    search and AI answers.
    """
    co = make_company("Acme A09")
    hr = Department.objects.create(company=co, name="HR")
    admin = make_user(co, email="admin-a09@acme.test", role="admin")
    mgr = make_user(co, email="mgr-a09@acme.test", role="employee", department=hr, is_dept_admin=True)
    owner = make_user(co, email="owner-a09@acme.test", role="employee", department=hr)
    doc = _doc(co, owner, filename="hr-case.txt", access_scope="restricted",
               department=hr, text="restricted hr case")

    for actor in (admin, mgr):
        resp = auth_client(actor).post(f"/api/documents/{doc.id}/review",
                                       {"action": "submit"}, format="json")
        doc.refresh_from_db()
        assert resp.status_code in (403, 404), f"{actor.email}: {resp.status_code}"
        assert doc.status == "approved"


# --------------------------------------------------------------------- AUTHZ-10
def test_authz10_effective_access_hides_docs_the_dept_manager_cannot_read(auth_client, make_company, make_user):
    """GET /api/admin/members/<id>/effective-access masks the filename of
    documents the caller cannot read, but still returns their id, scope,
    sensitivity, status and department. For a department manager that leaks
    the existence and classification of restricted/confidential documents
    granted to members of their department.
    """
    co = make_company("Acme A10")
    hr = Department.objects.create(company=co, name="HR")
    admin = make_user(co, email="admin-a10@acme.test", role="admin")
    mgr = make_user(co, email="mgr-a10@acme.test", role="employee", department=hr, is_dept_admin=True)
    member = make_user(co, email="member-a10@acme.test", role="employee", department=hr,
                       clearance="confidential")
    secret = _doc(co, admin, filename="layoffs.txt", access_scope="restricted",
                  sensitivity="confidential", text="layoff list")
    DocumentAccess.objects.create(document=secret, user=member, granted_by=admin)

    resp = auth_client(mgr).get(f"/api/admin/members/{member.id}/effective-access")

    assert resp.status_code == 200, resp.content
    ids = [d["id"] for d in resp.json()["documents"]]
    assert secret.id not in ids, "dept manager learned about a restricted confidential document"


# --------------------------------------------------------------------- AUTHZ-11
def test_authz11_room_summary_counts_against_monthly_ask_quota(auth_client, make_company, make_user):
    """team_chat_room_summarize checks the monthly ask quota but never records
    usage, so with an LLM configured a tenant can call the model without limit
    (only the 10/min per-user rate limit applies).
    """
    plan = Plan.objects.create(name="Metered A11", price_usd=1, monthly_ask_limit=1)
    co = make_company("Acme A11", plan=plan)
    co.enable_team_chat = True
    co.enable_ai_chat = True
    co.save(update_fields=["enable_team_chat", "enable_ai_chat"])
    emp = make_user(co, email="emp-a11@acme.test", role="employee")
    room = TeamRoom.ensure_default(co)
    TeamMessage.objects.create(company=co, room=room, sender=emp, sender_type="user",
                               content="we need to ship the release by Friday")

    client = auth_client(emp)
    with patch("core.providers.get_chat_provider", return_value=StubChatProvider()):
        first = client.post(f"/api/team-chat/rooms/{room.id}/summarize")
        second = client.post(f"/api/team-chat/rooms/{room.id}/summarize")

    assert first.status_code == 200, first.content
    assert second.status_code == 402, "second LLM summary on a 1-ask plan was not blocked"


# --------------------------------------------------------------------- AUTHZ-12
def test_authz12_root_admin_cannot_read_tenant_content_via_django_admin(client, root, make_company, make_user):
    """The API treats platform admins as report-only (no tenant data). But the
    same account is is_staff + is_superuser, and core/admin.py registers Chunk,
    Document, ChatMessage, TeamMessage, DocumentAccess and User with full
    change permissions. After password + TOTP, /admin/ shows (and edits) every
    tenant's document text, AI answers and team chat.
    """
    co = make_company("Tenant A12")
    admin = make_user(co, email="admin-a12@tenant.test", role="admin")
    doc = _doc(co, admin, filename="salary-bands.txt", access_scope="restricted",
               sensitivity="confidential", text="SALARY-BAND-MARKER-9137")
    chunk = Chunk.objects.get(document=doc)

    client.force_login(root)
    session = client.session
    session["mfa_admin_ok"] = root.pk  # root has passed the /admin TOTP gate
    session.save()

    resp = client.get(f"/admin/core/chunk/{chunk.pk}/change/")

    assert b"SALARY-BAND-MARKER-9137" not in resp.content, "root admin read tenant document text"
    assert resp.status_code in (302, 403, 404)


def test_ai03_django_admin_never_renders_llm_key_or_totp_seed(client, root, make_company, make_user):
    """AI-03: admin change forms decrypted EncryptedCharField values into inputs."""
    from core.models import LLMConfig

    co = make_company("Tenant AI03")
    member = make_user(co, email="member-ai03@tenant.test", role="employee",
                       mfa_secret="JBSWY3DPEHPK3PXPMARKER", mfa_enabled=True)
    cfg = LLMConfig.objects.create(company=co, provider="gemini", api_key="KEYMARKER-1234567890")

    client.force_login(root)
    session = client.session
    session["mfa_admin_ok"] = root.pk
    session.save()

    user_page = client.get(f"/admin/core/user/{member.pk}/change/")
    cfg_page = client.get(f"/admin/core/llmconfig/{cfg.pk}/change/")

    assert user_page.status_code == 200 and cfg_page.status_code == 200
    assert b"PEHPK3PXPMARKER" not in user_page.content
    assert b"KEYMARKER-1234567890" not in cfg_page.content
