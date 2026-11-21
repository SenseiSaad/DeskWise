"""End-to-end enterprise governance, security, and usefulness scenario suite.

Creates two realistic institutes (MedCore Hospital and LexPartner Law Firm)
with distinct roles (company admin, delegated department sub-admin, standard
employee, viewer/intern, and external partner) and exercises every feature:
  1. Universal admin feature switches (AI chat, Team Chat, External sharing)
  2. Role/sensitivity access locks across documents, AI RAG, and Team Chat AI
  3. Encrypted chunk & preview_text storage at rest
  4. PII/secret detection, LLM redaction gate, and PII external-share guard
  5. Expiring cross-company shares + instant admin kill-switch
  6. Document approval lifecycle (draft -> in_review -> approved -> archived) + legal hold
  7. Tamper-evident SHA-256 hash-chained AuditLog + integrity verification + CSV export
  8. Immediate session revocation on demotion / logout-all, sub-admin delegation,
     mandatory announcement read-acks, unified search, chat summary, anti-exfiltration,
     and admin governance dashboard.
"""
from __future__ import annotations

import json
import secrets
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from core import rag, team_chat
from core.models import (
    Announcement, AuditLog, Chunk, Company, Department, Document,
    DocumentShare, Plan, TeamRoom, User,
)
from .fakes import StubChatProvider

TEST_PASS = secrets.token_urlsafe(24)


class EnterpriseGovernanceScenariosTest(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls._settings_cm = override_settings(
            DATA_DIR=cls._tmpdir.name,
            MEDIA_ROOT=cls._tmpdir.name,
            RATELIMIT_ENABLED=False,
            SYNC_INDEXING=True,
            CELERY_TASK_ALWAYS_EAGER=True,
        )
        cls._settings_cm.enable()

    @classmethod
    def tearDownClass(cls):
        cls._settings_cm.disable()
        cls._tmpdir.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.plan = Plan.objects.create(
            name="Enterprise Governance Test Plan",
            price_usd=199,
            allow_custom_llm=True,
            allow_departments=True,
            allow_versions=True,
            max_documents=200,
            storage_mb=1024,
        )
        # Institute 1: MedCore Hospital
        self.medcore = Company.objects.create(
            name="MedCore Hospital", slug="medcore-hospital", plan=self.plan,
        )
        self.dept_hr = Department.objects.create(company=self.medcore, name="HR")
        self.dept_it = Department.objects.create(company=self.medcore, name="IT")

        self.ceo = User.objects.create_user(
            email="dr.sara@medcore.test", password=TEST_PASS, full_name="Dr. Sara",
            role="admin", company=self.medcore, email_verified=True,
        )
        self.hr_subadmin = User.objects.create_user(
            email="hr.lead@medcore.test", password=TEST_PASS, full_name="Hina HR",
            role="employee", is_dept_admin=True, department=self.dept_hr,
            company=self.medcore, email_verified=True,
        )
        self.it_emp = User.objects.create_user(
            email="ali.it@medcore.test", password=TEST_PASS, full_name="Ali IT",
            role="employee", department=self.dept_it,
            company=self.medcore, email_verified=True,
        )
        self.intern = User.objects.create_user(
            email="intern@medcore.test", password=TEST_PASS, full_name="Bilal Intern",
            role="viewer", department=self.dept_it,
            company=self.medcore, email_verified=True,
        )

        # Institute 2: LexPartner Law Firm
        self.lex = Company.objects.create(
            name="LexPartner Law", slug="lexpartner-law", plan=self.plan,
        )
        self.partner_admin = User.objects.create_user(
            email="omar@lex.test", password=TEST_PASS, full_name="Omar Partner",
            role="admin", company=self.lex, email_verified=True,
        )
        self.counsel = User.objects.create_user(
            email="nadia@lex.test", password=TEST_PASS, full_name="Nadia Counsel",
            role="employee", company=self.lex, email_verified=True,
        )

    def _client(self, user: User) -> APIClient:
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _upload(self, user: User, filename: str, content: str, **extra) -> dict:
        c = self._client(user)
        f = SimpleUploadedFile(filename, content.encode("utf-8"), content_type="text/plain")
        payload = {"file": f, **extra}
        res = c.post("/api/documents/upload", payload, format="multipart")
        return res

    def _ask_events(self, user: User, question: str) -> tuple[int, list[dict], list[str]]:
        captured: list[str] = []
        stub = StubChatProvider(capture=captured)
        with patch("core.rag.providers.get_chat_provider", return_value=stub), \
             patch("core.rag.embed", return_value=None):
            res = self._client(user).post("/api/ask", {"question": question}, format="json")
            if res.status_code != 200:
                return res.status_code, [], captured
            events = [json.loads(line) for line in res.streaming_content if line.strip()]
            return 200, events, captured

    # ------------------------------------------------------------------ 1
    def test_01_universal_admin_feature_switches(self):
        adm = self._client(self.ceo)
        emp = self._client(self.it_emp)

        res = adm.patch("/api/admin/company", {
            "enable_ai_chat": False,
            "enable_team_chat": False,
            "enable_external_sharing": False,
        }, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["enable_ai_chat"])
        self.assertFalse(res.data["enable_team_chat"])
        self.assertFalse(res.data["enable_external_sharing"])

        # AI chat endpoints blocked server-side
        self.assertEqual(emp.post("/api/ask", {"question": "hi"}, format="json").status_code, 403)
        self.assertEqual(emp.get("/api/conversations").status_code, 403)

        # Team chat blocked server-side
        self.assertEqual(emp.get("/api/team-chat/rooms").status_code, 403)

        # @DeskWise in team_chat refuses to call AI when enable_ai_chat=False
        self.medcore.refresh_from_db()
        room = TeamRoom.ensure_default(self.medcore)
        _, _, trigger = team_chat.create_user_message(self.it_emp, room, "@DeskWise help?")
        self.assertFalse(trigger)

        # External directory & sharing blocked
        self.assertEqual(emp.get(f"/api/companies/search?code={self.lex.access_code}").status_code, 403)
        doc_res = self._upload(self.ceo, "guide.txt", "General hospital guide")
        self.assertEqual(doc_res.status_code, 201)
        share_res = adm.post(f"/api/documents/{doc_res.data['id']}/shares", {
            "access_code": self.lex.access_code, "user_id": self.counsel.id,
        }, format="json")
        self.assertEqual(share_res.status_code, 403)

        # Re-enabling restores access
        adm.patch("/api/admin/company", {
            "enable_ai_chat": True, "enable_team_chat": True, "enable_external_sharing": True,
        }, format="json")
        self.assertEqual(emp.get("/api/team-chat/rooms").status_code, 200)
        self.assertEqual(emp.get(f"/api/companies/search?code={self.lex.access_code}").status_code, 200)

    # ------------------------------------------------------------------ 2
    def test_02_role_and_sensitivity_hardcore_lock(self):
        r1 = self._upload(self.ceo, "public_handbook.txt",
                          "Hospital visiting hours are 9am to 8pm. HANDBOOK_STD_111",
                          sensitivity="standard")
        r2 = self._upload(self.ceo, "internal_ops.txt",
                          "Server incident runbook escalation. INTERNAL_OPS_222",
                          sensitivity="internal")
        r3 = self._upload(self.ceo, "exec_payroll.txt",
                          "Executive compensation package details. CEO_SECRET_333",
                          sensitivity="confidential")
        self.assertEqual((r1.status_code, r2.status_code, r3.status_code), (201, 201, 201))

        # Non-admins cannot upload confidential documents directly
        bad_up = self._upload(self.it_emp, "nope.txt", "secret", sensitivity="confidential")
        self.assertEqual(bad_up.status_code, 403)

        # Document listing isolation by role
        viewer_docs = {d["filename"] for d in self._client(self.intern).get("/api/documents").json()["results"]}
        emp_docs = {d["filename"] for d in self._client(self.it_emp).get("/api/documents").json()["results"]}
        admin_docs = {d["filename"] for d in self._client(self.ceo).get("/api/documents").json()["results"]}
        self.assertEqual(viewer_docs, {"public_handbook.txt"})
        self.assertEqual(emp_docs, {"public_handbook.txt", "internal_ops.txt"})
        self.assertEqual(admin_docs, {"public_handbook.txt", "internal_ops.txt", "exec_payroll.txt"})

        # Direct detail / preview endpoints return 404 for unauthorized sensitivity
        self.assertEqual(self._client(self.intern).get(f"/api/documents/{r2.data['id']}/preview").status_code, 404)
        self.assertEqual(self._client(self.it_emp).get(f"/api/documents/{r3.data['id']}/preview").status_code, 404)

        # AI retrieval + /api/ask prompt context check
        code, events, ctx = self._ask_events(self.intern, "executive compensation and incident runbook escalation")
        self.assertEqual(code, 200)
        joined = "".join(ctx)
        self.assertNotIn("INTERNAL_OPS_222", joined)
        self.assertNotIn("CEO_SECRET_333", joined)

        code, events, ctx = self._ask_events(self.it_emp, "executive compensation and incident runbook escalation")
        self.assertEqual(code, 200)
        joined_emp = "".join(ctx)
        self.assertIn("INTERNAL_OPS_222", joined_emp)
        self.assertNotIn("CEO_SECRET_333", joined_emp)

        # Team Chat default room AI only permits approved standard docs
        default_room = TeamRoom.ensure_default(self.medcore)
        allowed = team_chat.room_allowed_doc_ids(default_room)
        self.assertEqual(allowed, {r1.data["id"]})

    # ------------------------------------------------------------------ 3
    def test_03_encrypted_chunks_and_preview_at_rest(self):
        secret_phrase = "VAULT_ENCRYPTED_TEXT_MARKER_991"
        res = self._upload(self.ceo, "vault_note.txt", f"Top note: {secret_phrase}")
        self.assertEqual(res.status_code, 201)
        doc_id = res.data["id"]

        # Raw database rows must hold enc:v1: ciphertext, NEVER plaintext
        with connection.cursor() as cur:
            cur.execute("SELECT text FROM core_chunk WHERE document_id = %s", [doc_id])
            raw_chunk = cur.fetchone()[0]
            cur.execute("SELECT preview_text FROM core_document WHERE id = %s", [doc_id])
            raw_preview = cur.fetchone()[0]

        self.assertTrue(raw_chunk.startswith("enc:v1:"), raw_chunk)
        self.assertTrue(raw_preview.startswith("enc:v1:"), raw_preview)
        self.assertNotIn(secret_phrase, raw_chunk)
        self.assertNotIn(secret_phrase, raw_preview)

        # ORM + API transparently decrypt for authorized users
        chunk = Chunk.objects.get(document_id=doc_id)
        self.assertIn(secret_phrase, chunk.text)
        prev_res = self._client(self.ceo).get(f"/api/documents/{doc_id}/preview")
        self.assertEqual(prev_res.status_code, 200)
        self.assertIn(secret_phrase, prev_res.json()["text"])

    # ------------------------------------------------------------------ 4
    def test_04_pii_detection_llm_redaction_and_external_share_gate(self):
        raw_content = (
            "Patient onboarding record for clinic workflow.\n"
            "CNIC: 42101-1234567-1\n"
            "SSN: 123-45-6789\n"
            "IBAN: PK36SCBL0000001123456702\n"
            "API_KEY=sk-SuperSecretToken1234567890\n"
        )
        res = self._upload(self.ceo, "patient_claims.txt", raw_content)
        self.assertEqual(res.status_code, 201)
        self.assertTrue(res.data["contains_pii"])
        doc_id = res.data["id"]

        # AI query triggers PII redaction before prompt leaves to LLM
        code, events, ctx = self._ask_events(self.ceo, "What is in patient onboarding record?")
        self.assertEqual(code, 200)
        joined_ctx = "".join(ctx)
        self.assertNotIn("42101-1234567-1", joined_ctx)
        self.assertNotIn("123-45-6789", joined_ctx)
        self.assertNotIn("PK36SCBL0000001123456702", joined_ctx)
        self.assertNotIn("sk-SuperSecretToken1234567890", joined_ctx)
        self.assertIn("[REDACTED:PII]", joined_ctx)
        self.assertIn("[REDACTED:SECRET]", joined_ctx)
        self.assertTrue(any(e.get("type") == "redaction" for e in events))

        # External share of PII document blocked for employees and unconfirmed admins
        emp_share = self._client(self.it_emp).post(f"/api/documents/{doc_id}/shares", {
            "access_code": self.lex.access_code, "user_id": self.counsel.id, "allow_pii": True,
        }, format="json")
        self.assertEqual(emp_share.status_code, 403)

        adm_no_confirm = self._client(self.ceo).post(f"/api/documents/{doc_id}/shares", {
            "access_code": self.lex.access_code, "user_id": self.counsel.id,
        }, format="json")
        self.assertEqual(adm_no_confirm.status_code, 403)

        # Admin override succeeds; external user preview masks PII automatically
        adm_ok = self._client(self.ceo).post(f"/api/documents/{doc_id}/shares", {
            "access_code": self.lex.access_code, "user_id": self.counsel.id,
            "allow_pii": True, "can_download": False,
        }, format="json")
        self.assertEqual(adm_ok.status_code, 201)

        ext_preview = self._client(self.counsel).get(f"/api/documents/{doc_id}/preview")
        self.assertEqual(ext_preview.status_code, 200)
        self.assertNotIn("42101-1234567-1", ext_preview.json()["text"])
        self.assertIn("[REDACTED:PII]", ext_preview.json()["text"])

    # ------------------------------------------------------------------ 5
    def test_05_expiring_cross_company_share_and_kill_switch(self):
        up = self._upload(self.ceo, "mou_partner.txt", "Shared MOU clause ALPHA_PARTNER_444")
        doc_id = up.data["id"]

        share_res = self._client(self.ceo).post(f"/api/documents/{doc_id}/shares", {
            "access_code": self.lex.access_code,
            "user_id": self.counsel.id,
            "can_download": False,
            "expires_in_days": 7,
        }, format="json")
        self.assertEqual(share_res.status_code, 201)
        self.assertIsNotNone(share_res.data["expires_at"])

        counsel_c = self._client(self.counsel)
        self.assertEqual(len(counsel_c.get("/api/shared-with-me").json()), 1)
        self.assertEqual(counsel_c.get(f"/api/documents/{doc_id}/preview").status_code, 200)
        self.assertEqual(counsel_c.get(f"/api/documents/{doc_id}/download").status_code, 403)
        self.assertIn(doc_id, rag.accessible_doc_ids(self.counsel))

        # Expire the share -> access vanishes immediately everywhere
        DocumentShare.objects.filter(document_id=doc_id, shared_with_user=self.counsel).update(
            expires_at=timezone.now() - timedelta(minutes=2),
        )
        self.assertEqual(counsel_c.get("/api/shared-with-me").json(), [])
        self.assertEqual(counsel_c.get(f"/api/documents/{doc_id}/preview").status_code, 404)
        self.assertNotIn(doc_id, rag.accessible_doc_ids(self.counsel))

        # Re-grant active share, then flip admin kill-switch enable_external_sharing=False
        self._client(self.ceo).post(f"/api/documents/{doc_id}/shares", {
            "access_code": self.lex.access_code, "user_id": self.counsel.id, "expires_in_days": 3,
        }, format="json")
        self.assertIn(doc_id, rag.accessible_doc_ids(self.counsel))

        self._client(self.ceo).patch("/api/admin/company", {"enable_external_sharing": False}, format="json")
        self.assertEqual(counsel_c.get("/api/shared-with-me").json(), [])
        self.assertEqual(counsel_c.get(f"/api/documents/{doc_id}/preview").status_code, 404)
        self.assertNotIn(doc_id, rag.accessible_doc_ids(self.counsel))

    # ------------------------------------------------------------------ 6
    def test_06_document_approval_lifecycle_and_legal_hold(self):
        self._client(self.ceo).patch("/api/admin/company", {"require_doc_approval": True}, format="json")

        # Non-admin upload automatically starts in_review
        up = self._upload(self.it_emp, "firewall_v2.txt",
                          "Firewall rule port 8443 allowed. FIREWALL_DRAFT_555",
                          access_scope="department", department_id=self.dept_it.id)
        self.assertEqual(up.status_code, 201)
        doc_id = up.data["id"]
        self.assertEqual(up.data["status"], "in_review")

        # Unapproved doc is NOT retrievable by AI and CANNOT be shared externally
        self.assertNotIn(doc_id, rag.accessible_doc_ids(self.it_emp))
        self.assertNotIn(doc_id, rag.accessible_doc_ids(self.ceo))
        bad_share = self._client(self.ceo).post(f"/api/documents/{doc_id}/shares", {
            "access_code": self.lex.access_code, "user_id": self.counsel.id,
        }, format="json")
        self.assertEqual(bad_share.status_code, 400)

        # HR sub-admin cannot approve an IT department document
        wrong_sub = self._client(self.hr_subadmin).post(
            f"/api/documents/{doc_id}/review", {"action": "approve"}, format="json",
        )
        self.assertIn(wrong_sub.status_code, (403, 404))

        # Company admin approves it -> becomes AI-searchable
        ok_rev = self._client(self.ceo).post(
            f"/api/documents/{doc_id}/review", {"action": "approve", "note": "Verified by security"},
            format="json",
        )
        self.assertEqual(ok_rev.status_code, 200)
        self.assertEqual(ok_rev.data["status"], "approved")
        self.assertIn(doc_id, rag.accessible_doc_ids(self.it_emp))

        # Legal hold blocks deletion even by company admin
        hold_res = self._client(self.ceo).patch(f"/api/documents/{doc_id}", {"legal_hold": True}, format="json")
        self.assertEqual(hold_res.status_code, 200)
        self.assertTrue(hold_res.data["legal_hold"])
        self.assertEqual(self._client(self.ceo).delete(f"/api/documents/{doc_id}").status_code, 403)

        # Non-admin cannot lift legal hold
        self.assertEqual(
            self._client(self.it_emp).patch(f"/api/documents/{doc_id}", {"legal_hold": False}, format="json").status_code,
            403,
        )
        self._client(self.ceo).patch(f"/api/documents/{doc_id}", {"legal_hold": False}, format="json")
        self.assertEqual(self._client(self.ceo).delete(f"/api/documents/{doc_id}").status_code, 204)

    # ------------------------------------------------------------------ 7
    def test_07_tamper_evident_audit_chain_and_csv_export(self):
        self._upload(self.ceo, "audit_doc.txt", "Audit verification doc")
        self._client(self.ceo).patch("/api/admin/company", {"tone": "Formal"}, format="json")

        adm = self._client(self.ceo)
        v_ok = adm.get("/api/admin/audit/verify").json()
        self.assertTrue(v_ok["valid"])
        self.assertGreaterEqual(v_ok["checked"], 2)
        self.assertIsNone(v_ok["broken_id"])

        csv_res = adm.get("/api/admin/audit?export=csv")
        self.assertEqual(csv_res.status_code, 200)
        csv_body = b"".join(csv_res.streaming_content).decode("utf-8")
        self.assertIn("prev_hash,entry_hash", csv_body)

        # ORM update is blocked by Phase F append-only enforcement; simulate a rogue DB
        # superuser bypassing the trigger directly in SQL (Decision D-07) to confirm hash verification catches it.
        target_row = AuditLog.objects.filter(company=self.medcore).order_by("id").first()
        with self.assertRaises(PermissionError):
            AuditLog.objects.filter(pk=target_row.pk).update(detail="BLOCKED_BY_ORM")
        with connection.cursor() as cur:
            if connection.vendor == "sqlite":
                cur.execute("DROP TRIGGER IF EXISTS core_auditlog_no_update;")
                cur.execute(
                    "UPDATE core_auditlog SET detail = %s WHERE id = %s",
                    ["TAMPERED_BY_ROGUE_ADMIN", target_row.pk],
                )
                cur.execute(
                    """
                    CREATE TRIGGER core_auditlog_no_update
                    BEFORE UPDATE ON core_auditlog
                    FOR EACH ROW
                    WHEN NOT (
                        OLD.user_id IS NOT NULL AND NEW.user_id IS NULL
                        AND OLD.company_id = NEW.company_id
                        AND OLD.actor_id IS NEW.actor_id
                        AND OLD.actor_email = NEW.actor_email
                        AND OLD.action = NEW.action
                        AND OLD.outcome = NEW.outcome
                        AND OLD.target_type = NEW.target_type
                        AND OLD.target_id = NEW.target_id
                        AND OLD.detail = NEW.detail
                        AND OLD.ip = NEW.ip
                        AND OLD.hash_version = NEW.hash_version
                        AND OLD.prev_hash = NEW.prev_hash
                        AND OLD.entry_hash = NEW.entry_hash
                        AND OLD.created_at = NEW.created_at
                    )
                    BEGIN
                        SELECT RAISE(ABORT, 'AuditLog is append-only; updates are forbidden');
                    END;
                    """
                )
            else:
                cur.execute("ALTER TABLE core_auditlog DISABLE TRIGGER core_auditlog_no_update;")
                cur.execute(
                    "UPDATE core_auditlog SET detail = %s WHERE id = %s",
                    ["TAMPERED_BY_ROGUE_ADMIN", target_row.pk],
                )
                cur.execute("ALTER TABLE core_auditlog ENABLE TRIGGER core_auditlog_no_update;")

        v_bad = adm.get("/api/admin/audit/verify").json()
        self.assertFalse(v_bad["valid"])
        self.assertEqual(v_bad["broken_id"], target_row.id)

    # ------------------------------------------------------------------ 8
    def test_08_session_revocation_subadmin_acks_search_exfil_and_governance(self):
        # Real cookie login for Ali IT
        anon = APIClient()
        login_res = anon.post("/api/auth/login", {"email": self.it_emp.email, "password": TEST_PASS}, format="json")
        self.assertEqual(login_res.status_code, 200)
        self.assertEqual(anon.get("/api/auth/me").status_code, 200)

        # Admin demotes Ali IT to viewer -> active JWT cookie is immediately rejected!
        demote = self._client(self.ceo).patch(f"/api/admin/users/{self.it_emp.id}", {"role": "viewer"}, format="json")
        self.assertEqual(demote.status_code, 200)
        self.assertEqual(anon.get("/api/auth/me").status_code, 401)
        self.assertEqual(anon.post("/api/auth/refresh").status_code, 401)

        # Re-promote Ali IT and test logout-all
        self._client(self.ceo).patch(f"/api/admin/users/{self.it_emp.id}", {"role": "employee"}, format="json")
        anon2 = APIClient()
        anon2.post("/api/auth/login", {"email": self.it_emp.email, "password": TEST_PASS}, format="json")
        self.assertEqual(anon2.post("/api/auth/logout-all").status_code, 200)

        # Department sub-admin scoping: Hina HR sees only HR members, cannot create company admin
        hr_c = self._client(self.hr_subadmin)
        hr_members = hr_c.get("/api/admin/users").json()
        self.assertEqual({m["email"] for m in hr_members}, {self.hr_subadmin.email})
        esc = hr_c.post("/api/admin/users", {
            "email": "rogue@medcore.test", "password": TEST_PASS, "role": "admin",
        }, format="json")
        self.assertEqual(esc.status_code, 403)
        new_hr = hr_c.post("/api/admin/users", {
            "email": "zara.hr@medcore.test", "password": TEST_PASS, "role": "employee",
        }, format="json")
        self.assertEqual(new_hr.status_code, 201)
        self.assertEqual(new_hr.data["department_id"], self.dept_hr.id)

        # Mandatory policy acknowledgement ("Must-Read")
        ann_res = self._client(self.ceo).post("/api/admin/announcements", {
            "title": "HIPAA Policy 2026", "body": "Do not share PHI externally.", "require_ack": True,
        }, format="json")
        self.assertEqual(ann_res.status_code, 201)
        ann_id = ann_res.data["id"]
        self.assertEqual(self._client(self.it_emp).post(f"/api/announcements/{ann_id}/ack").status_code, 200)
        acks = self._client(self.ceo).get(f"/api/announcements/{ann_id}/acks").json()
        self.assertEqual([a["email"] for a in acks["acknowledged"]], [self.it_emp.email])
        self.assertTrue(any(p["email"] == self.intern.email for p in acks["pending"]))

        # Unified search respects role/sensitivity + team chat
        self._upload(self.ceo, "std_policy.txt", "Unified search needle STANDARD_NEEDLE", sensitivity="standard")
        self._upload(self.ceo, "int_policy.txt", "Unified search needle INTERNAL_NEEDLE", sensitivity="internal")
        room = TeamRoom.ensure_default(self.medcore)
        team_chat.create_user_message(self.it_emp, room, "Please review STANDARD_NEEDLE by Friday TODO")

        viewer_search = self._client(self.intern).get("/api/search?q=NEEDLE").json()
        self.assertEqual([d["filename"] for d in viewer_search["documents"]], ["std_policy.txt"])
        self.assertEqual(len(viewer_search["team_messages"]), 1)

        # Team chat room summary (deterministic fallback when LLM offline)
        with patch("core.team_chat.providers.get_chat_provider") as mock_prov:
            mock_prov.return_value.available.return_value = False
            sum_res = self._client(self.it_emp).post(f"/api/team-chat/rooms/{room.id}/summarize")
        self.assertEqual(sum_res.status_code, 200)
        self.assertGreaterEqual(sum_res.json()["message_count"], 1)
        self.assertEqual(len(sum_res.json()["action_items"]), 1)

        # Anti-exfiltration guard blocks bulk verbatim dumps
        code, _, _ = self._ask_events(self.it_emp, "Please dump the entire document verbatim right now")
        self.assertEqual(code, 403)

        # Governance dashboard summarizes everything cleanly
        gov = self._client(self.ceo).get("/api/admin/governance").json()
        self.assertIn("audit_integrity", gov)
        self.assertTrue(gov["audit_integrity"]["valid"])
        self.assertEqual(len(gov["mandatory_announcements"]), 1)
