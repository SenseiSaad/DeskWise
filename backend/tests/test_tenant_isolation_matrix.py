"""Comprehensive multi-tenant isolation, IDOR, authorization, and security matrix.

Strictly verifies tenant isolation boundaries between two distinct companies
(Acme Corp and Globex Inc) across all API endpoints, database models, RAG
retrieval, chat generation, department/restricted scopes, one-doc sharing,
mass-assignment prevention, secret serialization, upload path traversal,
JWT authentication, and rate limiting.
"""
from __future__ import annotations

import io
import json
import time
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from core import rag, storage
from core.auth import ACCESS_COOKIE, set_auth_cookies
from core.models import (
    Announcement, AskLog, AttendanceExemption, AttendanceRecord, AuditLog,
    ChatConversation, ChatMessage, Chunk, Company, Department, Document,
    DocumentAccess, DocumentShare, DocumentVersion, GeneratedArtifact, Holiday,
    LLMConfig, Plan, User,
)
from .fakes import StubChatProvider

pytestmark = pytest.mark.django_db

# Unique marker strings for strict leak detection
ACME_MARKER = "MARKER_ACME_ALPHA_12345_CONFIDENTIAL"
GLOBEX_MARKER = "MARKER_GLOBEX_BETA_67890_SECRET_PAYROLL"


@pytest.fixture
def isolation_setup(make_company, make_user, tmp_path):
    """Sets up two fully isolated tenants with admins, employees, departments,
    documents with unique content markers, and indexed chunks."""
    plan = Plan.objects.create(
        name="Enterprise Isolation Test Plan",
        price_usd=199,
        allow_custom_llm=True,
        allow_departments=True,
        allow_versions=True,
        max_documents=500,
        storage_mb=1024,
    )

    # ── Tenant A: Acme Corp ──
    acme = make_company("Acme Corp", plan=plan)
    dept_acme_eng = Department.objects.create(company=acme, name="Engineering")
    dept_acme_sales = Department.objects.create(company=acme, name="Sales")

    admin_a = make_user(acme, email="admin@acme.test", role="admin")
    emp_a = make_user(acme, email="emp@acme.test", role="employee")
    emp_a_eng = make_user(acme, email="eng@acme.test", role="employee", department=dept_acme_eng)
    emp_a_sales = make_user(acme, email="sales@acme.test", role="employee", department=dept_acme_sales)

    # Acme Company-wide Document
    doc_a_path = storage.save_bytes(
        f"{acme.slug}/acme_handbook.txt",
        f"Acme Corp Employee Handbook.\n{ACME_MARKER}\nAll policies and customer guidelines.".encode("utf-8"),
        content_type="text/plain",
        base_dir=settings.DATA_DIR,
    )
    doc_a = Document.objects.create(
        company=acme,
        filename="acme_handbook.txt",
        stored_path=doc_a_path,
        content_type="text/plain",
        size=120,
        uploaded_by=admin_a,
        access_scope="company",
        indexing_status="ready",
        preview_text=f"Acme Corp Employee Handbook. {ACME_MARKER}",
    )
    DocumentAccess.objects.create(document=doc_a, user=admin_a)
    chunk_a = Chunk.objects.create(
        document=doc_a,
        company=acme,
        ord=0,
        text=f"Acme Corp Employee Handbook. {ACME_MARKER}",
        embedding=None,
    )

    # Acme Department-scoped Document (Engineering only)
    doc_a_dept_path = storage.save_bytes(
        f"{acme.slug}/acme_eng_specs.txt",
        "Engineering internal architecture specifications.\nMARKER_ACME_DEPT_ENG_ONLY".encode("utf-8"),
        content_type="text/plain",
        base_dir=settings.DATA_DIR,
    )
    doc_a_dept = Document.objects.create(
        company=acme,
        filename="acme_eng_specs.txt",
        stored_path=doc_a_dept_path,
        content_type="text/plain",
        size=80,
        uploaded_by=emp_a_eng,
        access_scope="department",
        department=dept_acme_eng,
        indexing_status="ready",
        preview_text="Engineering internal architecture specifications. MARKER_ACME_DEPT_ENG_ONLY",
    )
    DocumentAccess.objects.create(document=doc_a_dept, user=emp_a_eng)
    Chunk.objects.create(
        document=doc_a_dept,
        company=acme,
        ord=0,
        text="Engineering internal architecture specifications. MARKER_ACME_DEPT_ENG_ONLY",
        embedding=None,
    )

    # Acme Restricted Document (Uploader only)
    doc_a_restricted_path = storage.save_bytes(
        f"{acme.slug}/acme_board_merger.txt",
        "Highly restricted Acme board merger minutes.\nMARKER_ACME_RESTRICTED_BOARD".encode("utf-8"),
        content_type="text/plain",
        base_dir=settings.DATA_DIR,
    )
    doc_a_restricted = Document.objects.create(
        company=acme,
        filename="acme_board_merger.txt",
        stored_path=doc_a_restricted_path,
        content_type="text/plain",
        size=75,
        uploaded_by=admin_a,
        access_scope="restricted",
        indexing_status="ready",
        preview_text="Highly restricted Acme board merger minutes. MARKER_ACME_RESTRICTED_BOARD",
    )
    DocumentAccess.objects.create(document=doc_a_restricted, user=admin_a)
    Chunk.objects.create(
        document=doc_a_restricted,
        company=acme,
        ord=0,
        text="Highly restricted Acme board merger minutes. MARKER_ACME_RESTRICTED_BOARD",
        embedding=None,
    )

    # ── Tenant B: Globex Inc ──
    globex = make_company("Globex Inc", plan=plan)
    dept_globex_fin = Department.objects.create(company=globex, name="Finance")

    admin_b = make_user(globex, email="admin@globex.test", role="admin")
    emp_b = make_user(globex, email="emp@globex.test", role="employee")
    emp_b2 = make_user(globex, email="emp2@globex.test", role="employee")

    # Globex Company-wide Document
    doc_b_path = storage.save_bytes(
        f"{globex.slug}/globex_payroll.txt",
        f"Globex Executive Compensation & Payroll 2026.\n{GLOBEX_MARKER}\nConfidential salaries.".encode("utf-8"),
        content_type="text/plain",
        base_dir=settings.DATA_DIR,
    )
    doc_b = Document.objects.create(
        company=globex,
        filename="globex_payroll.txt",
        stored_path=doc_b_path,
        content_type="text/plain",
        size=150,
        uploaded_by=admin_b,
        access_scope="company",
        indexing_status="ready",
        preview_text=f"Globex Executive Compensation & Payroll 2026. {GLOBEX_MARKER}",
    )
    DocumentAccess.objects.create(document=doc_b, user=admin_b)
    chunk_b = Chunk.objects.create(
        document=doc_b,
        company=globex,
        ord=0,
        text=f"Globex Executive Compensation & Payroll 2026. {GLOBEX_MARKER}",
        embedding=None,
    )

    return {
        "acme": acme,
        "dept_acme_eng": dept_acme_eng,
        "dept_acme_sales": dept_acme_sales,
        "admin_a": admin_a,
        "emp_a": emp_a,
        "emp_a_eng": emp_a_eng,
        "emp_a_sales": emp_a_sales,
        "doc_a": doc_a,
        "doc_a_dept": doc_a_dept,
        "doc_a_restricted": doc_a_restricted,
        "chunk_a": chunk_a,
        "globex": globex,
        "dept_globex_fin": dept_globex_fin,
        "admin_b": admin_b,
        "emp_b": emp_b,
        "emp_b2": emp_b2,
        "doc_b": doc_b,
        "chunk_b": chunk_b,
    }


def _stub_chat(monkeypatch, capture=None):
    stub = StubChatProvider(capture=capture)
    monkeypatch.setattr("core.rag.providers.get_chat_provider", lambda **kw: stub)
    monkeypatch.setattr("core.rag.embed", lambda texts: None)
    return stub


# ==============================================================================
# 1. DIRECT ACCESS & IDOR MATRIX ON ALL DOCUMENT ENDPOINTS
# ==============================================================================
def test_idor_cross_tenant_document_endpoints_return_404(auth_client, isolation_setup):
    """Company A members (admin or employee) must never read, download, preview,
    modify, delete, reindex, version, or inspect shares of Company B's documents."""
    s = isolation_setup
    doc_b = s["doc_b"]

    for user in (s["admin_a"], s["emp_a"]):
        client = auth_client(user)

        # GET detail, preview, download, versions, shares
        assert client.get(f"/api/documents/{doc_b.id}").status_code == 404
        assert client.get(f"/api/documents/{doc_b.id}/preview").status_code == 404
        assert client.get(f"/api/documents/{doc_b.id}/download").status_code == 404
        assert client.get(f"/api/documents/{doc_b.id}/versions").status_code == 404
        assert client.get(f"/api/documents/{doc_b.id}/shares").status_code == 404

        # PATCH (tag/scope/metadata tampering)
        resp = client.patch(
            f"/api/documents/{doc_b.id}",
            {"tags": "tampered", "description": "stolen", "category": "Hacked"},
            format="json",
        )
        assert resp.status_code == 404
        doc_b.refresh_from_db()
        assert doc_b.tags != "tampered"

        # DELETE
        assert client.delete(f"/api/documents/{doc_b.id}").status_code == 404
        assert Document.objects.filter(id=doc_b.id).exists()

        # REINDEX
        doc_b.indexing_status = "failed"
        doc_b.save(update_fields=["indexing_status"])
        assert client.post(f"/api/documents/{doc_b.id}/reindex").status_code == 404
        doc_b.indexing_status = "ready"
        doc_b.save(update_fields=["indexing_status"])

        # NEW VERSION
        f = SimpleUploadedFile("tamper_v2.txt", b"malicious content", content_type="text/plain")
        assert client.post(f"/api/documents/{doc_b.id}/versions/new", {"file": f}).status_code == 404

        # SHARE GRANT / REVOKE
        share_grant = client.post(
            f"/api/documents/{doc_b.id}/shares",
            {"access_code": s["acme"].access_code, "user_id": user.id},
            format="json",
        )
        assert share_grant.status_code == 404
        assert client.delete(f"/api/documents/{doc_b.id}/shares/{user.id}").status_code == 404


def test_documents_listing_strictly_isolates_tenants(auth_client, isolation_setup):
    """Document listing must never reveal foreign documents or markers."""
    s = isolation_setup
    res_a = auth_client(s["admin_a"]).get("/api/documents").json()
    filenames_a = [d["filename"] for d in res_a["results"]]
    assert "globex_payroll.txt" not in filenames_a
    assert json.dumps(res_a).find(GLOBEX_MARKER) == -1

    res_b = auth_client(s["admin_b"]).get("/api/documents").json()
    filenames_b = [d["filename"] for d in res_b["results"]]
    assert "acme_handbook.txt" not in filenames_b
    assert json.dumps(res_b).find(ACME_MARKER) == -1


# ==============================================================================
# 2. RETRIEVAL & CHAT GROUNDING NEVER CROSSES TENANTS
# ==============================================================================
def test_retrieval_never_returns_other_tenant_chunks_or_markers(isolation_setup):
    """rag.retrieve must never return chunks belonging to another tenant."""
    s = isolation_setup
    # Acme user searches for Globex keywords
    chunks = rag.retrieve(s["admin_a"], "Globex executive compensation and payroll records", k=10)
    for c in chunks:
        assert c.company_id == s["acme"].id
        assert c.document.company_id == s["acme"].id
        assert GLOBEX_MARKER not in c.text

    # Globex user searches for Acme keywords
    chunks_b = rag.retrieve(s["emp_b"], "Acme employee handbook customer guidelines", k=10)
    for c in chunks_b:
        assert c.company_id == s["globex"].id
        assert c.document.company_id == s["globex"].id
        assert ACME_MARKER not in c.text


def test_ask_endpoint_chat_never_leaks_cross_tenant_sources_or_context(auth_client, isolation_setup, monkeypatch):
    """The /api/ask endpoint must never cite foreign documents in sources and
    must never inject foreign chunks into the model context prompt."""
    s = isolation_setup
    captured_prompts: list[str] = []
    _stub_chat(monkeypatch, capture=captured_prompts)

    client = auth_client(s["admin_a"])
    resp = client.post(
        "/api/ask",
        {"question": "What is the secret payroll and compensation for executives?"},
        format="json",
    )
    assert resp.status_code == 200
    events = [json.loads(line) for line in resp.streaming_content if line.strip()]

    source_events = [e for e in events if e.get("type") == "sources"]
    if source_events:
        for src in source_events[0].get("sources", []):
            assert "globex" not in src.lower()
            assert "payroll" not in src.lower()

    # Verify model prompt context never received the Globex marker
    all_context = "".join(captured_prompts)
    assert GLOBEX_MARKER not in all_context


# ==============================================================================
# 3. COMPANY-FILTERED DOMAIN MODELS & ENDPOINTS
# ==============================================================================
def test_conversations_and_ratings_company_isolation(auth_client, isolation_setup):
    """Chat conversations and message ratings are strictly isolated per company and user."""
    s = isolation_setup
    # Create Globex conversation & message
    conv_b = ChatConversation.objects.create(company=s["globex"], user=s["emp_b"], title="Globex Chat")
    msg_b = ChatMessage.objects.create(conversation=conv_b, role="assistant", content="Globex answer")

    client_a = auth_client(s["admin_a"])

    # Conversations list
    convs_a = client_a.get("/api/conversations").json()
    assert conv_b.id not in [c["id"] for c in convs_a.get("results", [])]

    # Conversation IDOR
    assert client_a.get(f"/api/conversations/{conv_b.id}").status_code == 404
    assert client_a.patch(f"/api/conversations/{conv_b.id}", {"title": "Hacked"}, format="json").status_code == 404
    assert client_a.delete(f"/api/conversations/{conv_b.id}").status_code == 404

    # Message Rating IDOR
    assert client_a.post(f"/api/messages/{msg_b.id}/rate", {"rating": 1}, format="json").status_code == 404
    msg_b.refresh_from_db()
    assert msg_b.rating is None


def test_analytics_and_audit_company_isolation(auth_client, isolation_setup):
    """Audit logs, analytics questions, and usage metrics are strictly filtered by company."""
    s = isolation_setup
    # Seed Globex activity
    AskLog.objects.create(
        company=s["globex"], user=s["admin_b"],
        question="Globex Sensitive Question: How to evade taxes?",
        chunks_found=1, answered=True, created_at=timezone.now(),
    )
    AuditLog.objects.create(
        company=s["globex"], user=s["admin_b"],
        action="secret_globex_action", detail="Transferred secret funds",
    )

    client_a = auth_client(s["admin_a"])

    # Analytics
    analytics_a = client_a.get("/api/admin/analytics").json()
    blob_analytics = json.dumps(analytics_a)
    assert "Globex Sensitive Question" not in blob_analytics
    assert "admin@globex.test" not in blob_analytics

    # Audit log
    audit_a = client_a.get("/api/admin/audit").json()
    blob_audit = json.dumps(audit_a)
    assert "secret_globex_action" not in blob_audit
    assert "Transferred secret funds" not in blob_audit


def test_announcements_company_isolation(auth_client, isolation_setup):
    """Company announcements cannot be read or deleted across tenant boundaries."""
    s = isolation_setup
    ann_b = Announcement.objects.create(
        company=s["globex"], title="Globex Secret Offsite",
        body="Offsite at confidential island", created_by=s["admin_b"],
    )

    client_a = auth_client(s["admin_a"])
    announcements_a = client_a.get("/api/admin/announcements").json()
    assert ann_b.id not in [a["id"] for a in announcements_a]
    assert client_a.delete(f"/api/admin/announcements/{ann_b.id}").status_code == 404
    assert Announcement.objects.filter(id=ann_b.id).exists()


def test_users_and_departments_administration_isolation(auth_client, isolation_setup):
    """Member management and department administration cannot cross tenant boundaries."""
    s = isolation_setup
    client_a = auth_client(s["admin_a"])

    # Users listing & IDOR
    users_a = client_a.get("/api/admin/users").json()
    emails_a = [u["email"] for u in users_a]
    assert "admin@globex.test" not in emails_a
    assert "emp@globex.test" not in emails_a

    assert client_a.patch(f"/api/admin/users/{s['emp_b'].id}", {"role": "viewer"}, format="json").status_code == 404
    assert client_a.delete(f"/api/admin/users/{s['emp_b'].id}").status_code == 404
    assert User.objects.filter(id=s["emp_b"].id).exists()

    # Departments listing & IDOR
    depts_a = client_a.get("/api/admin/departments").json()
    names_a = [d["name"] for d in depts_a]
    assert "Finance" not in names_a  # Globex dept
    assert client_a.delete(f"/api/admin/departments/{s['dept_globex_fin'].id}").status_code == 404
    assert Department.objects.filter(id=s["dept_globex_fin"].id).exists()


def test_attendance_holidays_and_exemptions_isolation(auth_client, isolation_setup):
    """Attendance records, QR codes, holidays, and exemptions are strictly partitioned."""
    s = isolation_setup
    today = timezone.localdate()

    # Globex records
    att_b = AttendanceRecord.objects.create(company=s["globex"], user=s["emp_b"], date=today, status="Present")
    hol_b = Holiday.objects.create(company=s["globex"], date=today + timedelta(days=5), name="Globex Founders Day")
    ex_b = AttendanceExemption.objects.create(
        user=s["emp_b"], start_date=today, end_date=today + timedelta(days=2),
        reason="Globex Executive Mission", created_by=s["admin_b"],
    )

    client_a_emp = auth_client(s["emp_a"])
    client_a_admin = auth_client(s["admin_a"])

    # Attendance me
    me_a = client_a_emp.get("/api/attendance/me").json()
    assert att_b.id not in [r["id"] for r in me_a.get("records", [])]

    # Holidays IDOR
    holidays_a = client_a_admin.get("/api/admin/attendance/holidays").json()
    assert hol_b.id not in [h["id"] for h in holidays_a if not h.get("platform_wide")]
    assert client_a_admin.delete(f"/api/admin/attendance/holidays/{hol_b.id}").status_code == 404

    # Exemptions IDOR
    exemptions_a = client_a_admin.get("/api/admin/attendance/exemptions").json()
    assert ex_b.id not in [e["id"] for e in exemptions_a]
    assert client_a_admin.delete(f"/api/admin/attendance/exemptions/{ex_b.id}").status_code == 404

    # Evaluate attendance
    eval_res = client_a_admin.post("/api/admin/attendance/evaluate", {"dry_run": True}, format="json").json()
    eval_emails = {r["email"] for r in eval_res.get("results", [])}
    assert "emp@globex.test" not in eval_emails
    assert "admin@globex.test" not in eval_emails


# ==============================================================================
# 4. DEPARTMENT & RESTRICTED SCOPES INSIDE ONE COMPANY
# ==============================================================================
def test_department_scope_isolation_inside_company(auth_client, isolation_setup):
    """Documents scoped to 'department' are readable by members of that department,
    and 404 for members of a different department in the same company."""
    s = isolation_setup
    doc_dept = s["doc_a_dept"]

    # Engineering member (authorized)
    client_eng = auth_client(s["emp_a_eng"])
    assert client_eng.get(f"/api/documents/{doc_dept.id}").status_code == 200
    assert client_eng.get(f"/api/documents/{doc_dept.id}/preview").status_code == 200
    assert client_eng.get(f"/api/documents/{doc_dept.id}/download").status_code == 200
    chunks = rag.retrieve(s["emp_a_eng"], "Engineering internal architecture", k=5)
    assert doc_dept.id in [c.document_id for c in chunks]

    # Sales member (unauthorized for Engineering document)
    client_sales = auth_client(s["emp_a_sales"])
    assert client_sales.get(f"/api/documents/{doc_dept.id}").status_code == 404
    assert client_sales.get(f"/api/documents/{doc_dept.id}/preview").status_code == 404
    assert client_sales.get(f"/api/documents/{doc_dept.id}/download").status_code == 404
    sales_docs = client_sales.get("/api/documents").json()
    assert doc_dept.id not in [d["id"] for d in sales_docs["results"]]
    chunks_sales = rag.retrieve(s["emp_a_sales"], "Engineering internal architecture", k=5)
    assert doc_dept.id not in [c.document_id for c in chunks_sales]


def test_restricted_scope_isolation_inside_company(auth_client, isolation_setup):
    """Documents scoped to 'restricted' are viewable only by the uploader and
    explicit DocumentAccess grantees; ungranted colleagues get 404."""
    s = isolation_setup
    doc_res = s["doc_a_restricted"]

    # Uploader (admin_a)
    client_admin = auth_client(s["admin_a"])
    assert client_admin.get(f"/api/documents/{doc_res.id}").status_code == 200

    # Colleague without grant
    client_colleague = auth_client(s["emp_a"])
    assert client_colleague.get(f"/api/documents/{doc_res.id}").status_code == 404
    assert client_colleague.get(f"/api/documents/{doc_res.id}/preview").status_code == 404
    assert client_colleague.get(f"/api/documents/{doc_res.id}/download").status_code == 404

    # Grant colleague access
    DocumentAccess.objects.create(document=doc_res, user=s["emp_a"], can_download=True)
    assert client_colleague.get(f"/api/documents/{doc_res.id}").status_code == 200
    assert client_colleague.get(f"/api/documents/{doc_res.id}/download").status_code == 200


# ==============================================================================
# 5. ONE-DOC / ONE-USER SHARING BOUNDARY
# ==============================================================================
def test_granular_cross_company_document_sharing_boundary(auth_client, isolation_setup):
    """Sharing one document with one user grants access strictly to that single
    document for that single user, leaving all other documents and users isolated."""
    s = isolation_setup
    doc_a = s["doc_a"]
    doc_a_res = s["doc_a_restricted"]
    emp_b = s["emp_b"]
    emp_b2 = s["emp_b2"]
    admin_b = s["admin_b"]

    # Pre-grant: no access
    client_b = auth_client(emp_b)
    assert client_b.get(f"/api/documents/{doc_a.id}").status_code == 404
    assert client_b.get("/api/shared-with-me").json() == []

    # Acme Admin shares doc_a with emp_b
    grant_resp = auth_client(s["admin_a"]).post(
        f"/api/documents/{doc_a.id}/shares",
        {"access_code": s["globex"].access_code, "user_id": emp_b.id, "can_download": True},
        format="json",
    )
    assert grant_resp.status_code == 201

    # emp_b now has access to doc_a
    assert client_b.get(f"/api/documents/{doc_a.id}").status_code == 200
    assert client_b.get(f"/api/documents/{doc_a.id}/download").status_code == 200
    shared = client_b.get("/api/shared-with-me").json()
    assert [d["filename"] for d in shared] == ["acme_handbook.txt"]

    # emp_b STILL cannot see other Acme documents
    assert client_b.get(f"/api/documents/{doc_a_res.id}").status_code == 404

    # Other Globex users (emp_b2, admin_b) CANNOT see doc_a
    assert auth_client(emp_b2).get(f"/api/documents/{doc_a.id}").status_code == 404
    assert auth_client(admin_b).get(f"/api/documents/{doc_a.id}").status_code == 404

    # emp_b cannot manage shares on doc_a
    assert client_b.get(f"/api/documents/{doc_a.id}/shares").status_code == 404
    assert client_b.delete(f"/api/documents/{doc_a.id}/shares/{emp_b.id}").status_code == 404

    # RAG retrieval for emp_b includes doc_a but never doc_a_restricted
    chunks = rag.retrieve(emp_b, "Acme employee handbook customer guidelines", k=5)
    doc_ids = {c.document_id for c in chunks}
    assert doc_a.id in doc_ids
    assert doc_a_res.id not in doc_ids


# ==============================================================================
# 6. MASS-ASSIGNMENT OF COMPANY IDS ON WRITES
# ==============================================================================
def test_mass_assignment_company_protection_on_all_writes(auth_client, isolation_setup):
    """Payloads attempting to inject 'company' or 'company_id' cannot bind records
    to a foreign company or move accounts across companies."""
    s = isolation_setup
    foreign_company_id = s["globex"].id
    client_admin = auth_client(s["admin_a"])
    client_emp = auth_client(s["emp_a"])

    # 1. Upload document with spoofed company_id
    f = SimpleUploadedFile("mass_assign.txt", b"payload content", content_type="text/plain")
    up_resp = client_admin.post(
        "/api/documents/upload",
        {"file": f, "company_id": foreign_company_id, "company": foreign_company_id},
    )
    assert up_resp.status_code == 201
    new_doc_id = up_resp.json()["id"]
    new_doc = Document.objects.get(id=new_doc_id)
    assert new_doc.company_id == s["acme"].id  # Bound to caller's company

    # 2. User creation with spoofed company_id
    user_resp = client_admin.post(
        "/api/admin/users",
        {
            "email": "injected@acme.test",
            "password": "Password12345!Secure",
            "role": "employee",
            "company_id": foreign_company_id,
            "company": foreign_company_id,
        },
        format="json",
    )
    assert user_resp.status_code == 201
    injected_user = User.objects.get(email="injected@acme.test")
    assert injected_user.company_id == s["acme"].id

    # 3. Department creation with spoofed company_id
    dept_resp = client_admin.post(
        "/api/admin/departments",
        {"name": "Security Research", "company_id": foreign_company_id},
        format="json",
    )
    assert dept_resp.status_code == 201
    new_dept = Department.objects.get(name="Security Research")
    assert new_dept.company_id == s["acme"].id

    # 4. Announcement creation with spoofed company_id
    ann_resp = client_admin.post(
        "/api/admin/announcements",
        {"title": "Test Ann", "body": "Body", "company_id": foreign_company_id},
        format="json",
    )
    assert ann_resp.status_code == 201
    new_ann = Announcement.objects.get(title="Test Ann")
    assert new_ann.company_id == s["acme"].id

    # 5. Conversation creation with spoofed company_id
    conv_resp = client_emp.post(
        "/api/conversations",
        {"title": "Spoofed Conv", "company_id": foreign_company_id},
        format="json",
    )
    assert conv_resp.status_code == 201
    new_conv = ChatConversation.objects.get(title="Spoofed Conv")
    assert new_conv.company_id == s["acme"].id

    # 6. Profile self-update cannot change own company or role
    patch_me = client_emp.patch(
        "/api/auth/update-me",
        {"company_id": foreign_company_id, "company": foreign_company_id, "role": "admin"},
        format="json",
    )
    assert patch_me.status_code == 200
    s["emp_a"].refresh_from_db()
    assert s["emp_a"].company_id == s["acme"].id
    assert s["emp_a"].role == "employee"


# ==============================================================================
# 7. LLMCONFIG API_KEY NEVER SERIALIZED
# ==============================================================================
def test_llm_config_api_key_never_serialized_in_responses(auth_client, isolation_setup):
    """Tenant-configured LLM api_key is write-only and must never be echoed in GET responses."""
    s = isolation_setup
    secret_key = "sk-super-secret-acme-enterprise-key-999"

    client_admin_a = auth_client(s["admin_a"])
    put_resp = client_admin_a.put(
        "/api/admin/llm-config",
        {"provider": "openai", "chat_model": "gpt-4o-mini", "api_key": secret_key},
        format="json",
    )
    assert put_resp.status_code == 200
    assert secret_key not in json.dumps(put_resp.json())

    # Read back as Acme Admin
    get_resp = client_admin_a.get("/api/admin/llm-config")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["has_api_key"] is True
    assert data["is_company_override"] is True
    assert secret_key not in json.dumps(data)

    # Read back as Globex Admin (must see platform default, not Acme override)
    client_admin_b = auth_client(s["admin_b"])
    data_b = client_admin_b.get("/api/admin/llm-config").json()
    assert data_b["is_company_override"] is False
    assert secret_key not in json.dumps(data_b)


# ==============================================================================
# 8. UPLOAD PATH TRAVERSAL DEFENSE
# ==============================================================================
def test_upload_path_traversal_is_blocked_at_api_boundary(auth_client, isolation_setup):
    """Filenames with directory separators or traversal components (../) must be
    rejected at the upload validation layer and storage resolution."""
    from core.uploads import UploadRejected, validate_filename
    from django.core.exceptions import SuspiciousFileOperation

    malicious_names = [
        "../../etc/passwd.txt",
        "subdir/../../evil.txt",
        "..\\..\\windows_system32.txt",
        "/absolute/path/evil.txt",
    ]

    for bad_name in malicious_names:
        with pytest.raises(UploadRejected):
            validate_filename(bad_name)

    # Storage layer defense in depth
    with pytest.raises(SuspiciousFileOperation):
        storage._resolve_local_path("acme/../../../../etc/passwd", base_dir=settings.DATA_DIR)


def test_upload_confirm_blocks_traversal_storage_keys(auth_client, isolation_setup, monkeypatch):
    """upload_confirm must reject keys that escape the tenant's slug prefix."""
    s = isolation_setup
    monkeypatch.setattr("core.storage.is_s3_enabled", lambda: True)
    monkeypatch.setattr("core.storage.object_size", lambda key: 100)

    client = auth_client(s["admin_a"])
    bad_keys = [
        f"{s['acme'].slug}/../../globex-inc/secret.txt",
        f"{s['acme'].slug}/..\\..\\secret.txt",
        "globex-inc/secret.txt",
        "../etc/passwd",
    ]
    for key in bad_keys:
        resp = client.post(
            "/api/documents/confirm",
            {"key": key, "filename": "safe.txt", "content_type": "text/plain"},
            format="json",
        )
        assert resp.status_code == 400
        assert "Invalid storage key" in resp.json().get("detail", "")


# ==============================================================================
# 9. AUTHENTICATION & JWT SECURITY (EXPIRED, TAMPERED, MISSING, RATE LIMITS)
# ==============================================================================
def test_jwt_security_guards_expired_tampered_and_missing(api, isolation_setup):
    """Protected endpoints reject requests with expired, tampered, or missing JWTs."""
    user = isolation_setup["emp_a"]

    # 1. Missing cookie & missing Authorization header
    assert api.get("/api/auth/me").status_code == 401

    # 2. Valid token works via cookie
    refresh = RefreshToken.for_user(user)
    api.cookies[ACCESS_COOKIE] = str(refresh.access_token)
    assert api.get("/api/auth/me").status_code == 200

    # 3. Tampered token signature
    tampered_token = str(refresh.access_token)[:-6] + "xxxxxx"
    api.cookies[ACCESS_COOKIE] = tampered_token
    assert api.get("/api/auth/me").status_code == 401

    # 4. Expired token
    expired_token = AccessToken.for_user(user)
    expired_token.set_exp(lifetime=-timedelta(minutes=10))
    api.cookies[ACCESS_COOKIE] = str(expired_token)
    assert api.get("/api/auth/me").status_code == 401


def test_rate_limiting_enforcement_returns_429(api, settings, monkeypatch):
    """Calling rate-limited endpoints beyond threshold returns 429 with Retry-After."""
    import time
    fixed_time = 1700000010.0
    monkeypatch.setattr(time, "time", lambda: fixed_time)
    settings.RATELIMIT_ENABLED = True
    from django.core.cache import cache
    cache.clear()

    # /api/auth/login allows 8 attempts per 60s per ip_email
    for _ in range(8):
        resp = api.post(
            "/api/auth/login",
            {"email": "brute@acme.test", "password": "WrongPassword123!"},
            format="json",
        )
        assert resp.status_code == 401

    # 9th attempt must be rate-limited
    blocked = api.post(
        "/api/auth/login",
        {"email": "brute@acme.test", "password": "WrongPassword123!"},
        format="json",
    )
    assert blocked.status_code == 429
    assert "Too many attempts" in blocked.json().get("detail", "")
    assert "Retry-After" in blocked.headers
