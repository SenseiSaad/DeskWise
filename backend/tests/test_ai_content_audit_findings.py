"""Regression tests for docs/security/ai-and-content.md (AI-NN)."""
from __future__ import annotations

import pytest
from django.core import mail

from core import workflow

pytestmark = pytest.mark.django_db


def test_ai01_meeting_workflow_only_emails_same_company_members(settings, make_company, make_user):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    co = make_company("Acme AI01")
    other = make_company("Other AI01")
    asker = make_user(co, email="asker@acme-ai01.test")
    colleague = make_user(co, email="colleague@acme-ai01.test")
    stranger = make_user(other, email="person@other-ai01.test")

    result = workflow.handle_ai_workflow_intent({
        "intent": "schedule_meeting",
        "data": {"title": "Sync", "date": "2030-01-02", "time": "10:00",
                 "participants": [colleague.email, stranger.email, "someone@example.org"]},
    }, asker)

    sent_to = {addr for m in mail.outbox for addr in m.to}
    assert colleague.email in sent_to
    assert stranger.email not in sent_to
    assert "someone@example.org" not in sent_to
    assert stranger.email not in result["participants"]


def test_ai02_outbound_llm_client_does_not_follow_redirects():
    import threading
    import urllib.error
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from core import providers

    hits = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            if self.path == "/start":
                self.send_response(302)
                self.send_header("Location", "/second")
                self.end_headers()
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with pytest.raises(urllib.error.HTTPError):
            providers._open(f"http://127.0.0.1:{server.server_port}/start")
    finally:
        server.shutdown()
    assert hits == ["/start"]


def test_ai04_presign_requires_a_signed_size(auth_client, make_company, make_user):
    from unittest.mock import patch

    co = make_company("Acme AI04")
    emp = make_user(co, email="emp@acme-ai04.test")
    with patch("core.storage.is_s3_enabled", return_value=True), \
         patch("core.storage.generate_presigned_put", return_value="https://r2.invalid/put") as gen:
        resp = auth_client(emp).post("/api/documents/presign", {"filename": "notes.txt"}, format="json")
    assert resp.status_code == 400
    gen.assert_not_called()


def test_ai05_private_key_redaction_is_linear():
    import time

    from core import moderation

    text = "-----BEGIN RSA PRIVATE KEY-----\n" * 16000  # ~512 KB, no END lines
    started = time.perf_counter()
    moderation.redact_pii(text)
    assert time.perf_counter() - started < 1.0
    block = "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----"
    assert moderation.redact_pii(f"a {block} b")[0] == "a [REDACTED:SECRET] b"


def test_ai06_provider_exception_text_is_not_sent_to_client(make_company, make_user):
    import json
    from unittest.mock import patch

    from core import rag

    class _Broken:
        label = "stub"
        chat_model = "stub-1"
        temperature = 0.0
        max_tokens = 64
        api_key = ""

        def available(self):
            return True

        def stream_chat(self, messages, temperature=0.0, max_tokens=64):
            raise RuntimeError("upstream db-internal-7.local:5432 refused")
            yield  # pragma: no cover

    co = make_company("Acme AI06")
    user = make_user(co, email="u@acme-ai06.test")
    with patch("core.providers.get_chat_provider", return_value=_Broken()):
        events = [json.loads(line) for line in rag.stream_answer(user, "what is the leave policy")]
    errors = [e for e in events if e.get("type") == "error"]
    assert errors and all("db-internal-7" not in e["message"] for e in errors)


def test_ai07_upload_rejects_mismatched_magic_and_sets_server_content_type(auth_client, make_company, make_user):
    from unittest.mock import patch

    from django.core.files.uploadedfile import SimpleUploadedFile

    from core.models import Document

    co = make_company("Acme AI07")
    emp = make_user(co, email="emp@acme-ai07.test")
    client = auth_client(emp)
    with patch("core.views._index_in_background"):
        bad = client.post("/api/documents/upload",
                          {"file": SimpleUploadedFile("report.pdf", b"just some text", content_type="application/pdf")},
                          format="multipart")
        good = client.post("/api/documents/upload",
                           {"file": SimpleUploadedFile("notes.txt", b"hello", content_type="text/html")},
                           format="multipart")
    assert bad.status_code == 400
    assert good.status_code == 201, good.content
    assert Document.objects.get(pk=good.json()["id"]).content_type == "text/plain"


def test_ai08_pdf_ocr_is_size_and_time_bounded(monkeypatch):
    import sys
    import types

    from core import rag

    seen = {}
    fake_pdf2image = types.ModuleType("pdf2image")
    fake_pdf2image.convert_from_bytes = lambda raw, **kw: seen.update(kw) or []
    fake_tesseract = types.ModuleType("pytesseract")
    fake_tesseract.image_to_string = lambda *a, **kw: ""
    monkeypatch.setitem(sys.modules, "pdf2image", fake_pdf2image)
    monkeypatch.setitem(sys.modules, "pytesseract", fake_tesseract)

    rag._ocr_pdf_bytes(b"%PDF-1.4")
    assert seen.get("size") and seen["size"][0] <= 2000
    assert seen.get("timeout")


# ----------------------------------------------- step 4 follow-ups (AI-01/04/06/07)
_INTENT_REPLY = (
    "Sure, I can set that up. <<<INTENT_JSON>>>"
    '{"intent": "schedule_meeting", "data": {"title": "Budget sync", "date": "2030-01-02", '
    '"time": "10:00", "participants": ["%s", "outsider@example.org"]}}'
    "<<<END_INTENT_JSON>>>"
)


class _IntentChat:
    label = "stub"
    chat_model = "stub-1"
    temperature = 0.0
    max_tokens = 64
    api_key = ""

    def __init__(self, participant):
        self.participant = participant

    def available(self):
        return True

    def stream_chat(self, messages, temperature=0.0, max_tokens=64):
        yield _INTENT_REPLY % self.participant


def test_ai01_chat_stream_only_proposes_and_sends_nothing(settings, make_company, make_user):
    import json
    from unittest.mock import patch

    from core import rag

    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    co = make_company("Acme AI01b")
    asker = make_user(co, email="asker@acme-ai01b.test")
    colleague = make_user(co, email="colleague@acme-ai01b.test")
    with patch("core.providers.get_chat_provider", return_value=_IntentChat(colleague.email)):
        events = [json.loads(line) for line in rag.stream_answer(asker, "book a budget sync")]
    assert not [e for e in events if e.get("type") == "workflow"], "workflow ran during the stream"
    assert mail.outbox == []
    proposals = [e for e in events if e.get("type") == "workflow_proposal"]
    assert len(proposals) == 1 and proposals[0]["token"]
    assert proposals[0]["preview"]["participants"] == [colleague.email]


def test_ai01_confirm_runs_once_and_only_for_the_asker(settings, api, auth_client, make_company, make_user):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    co = make_company("Acme AI01c")
    asker = make_user(co, email="asker@acme-ai01c.test")
    colleague = make_user(co, email="colleague@acme-ai01c.test")
    proposal = workflow.build_proposal({
        "intent": "schedule_meeting",
        "data": {"title": "Sync", "date": "2030-01-02", "time": "10:00", "participants": [colleague.email]},
    }, asker)
    body = {"token": proposal["token"]}

    assert api.post("/api/workflow/confirm", body, format="json").status_code == 401
    assert auth_client(colleague).post("/api/workflow/confirm", body, format="json").status_code == 400
    assert mail.outbox == []

    ok = auth_client(asker).post("/api/workflow/confirm", body, format="json")
    assert ok.status_code == 200, ok.content
    assert ok.json()["action"] == "schedule_meeting"
    assert colleague.email in {a for m in mail.outbox for a in m.to}

    replay = auth_client(asker).post("/api/workflow/confirm", body, format="json")
    assert replay.status_code == 400
    assert len(mail.outbox) == 1

    forged = auth_client(asker).post("/api/workflow/confirm", {"token": proposal["token"][:-3] + "abc"},
                                     format="json")
    assert forged.status_code == 400


def test_ai01_team_chat_bot_never_proposes_or_runs_workflows(settings, auth_client, make_company, make_user):
    from unittest.mock import patch

    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    co = make_company("Acme AI01d")
    admin = make_user(co, email="admin@acme-ai01d.test", role="admin")
    client = auth_client(admin)
    room_id = client.get("/api/team-chat/rooms").json()["rooms"][0]["id"]
    with patch("core.providers.get_chat_provider", return_value=_IntentChat(admin.email)), \
         patch("core.workflow.handle_ai_workflow_intent") as run, \
         patch("core.workflow.build_proposal") as propose:
        res = client.post(f"/api/team-chat/rooms/{room_id}/messages",
                          {"content": "@DeskWise book a budget sync"}, format="json")
    assert res.status_code == 201
    run.assert_not_called()
    propose.assert_not_called()
    assert mail.outbox == []


def _presigned_key(client, filename, size=50):
    resp = client.post("/api/documents/presign", {"filename": filename, "size": size}, format="json")
    assert resp.status_code == 200, resp.content
    return resp.json()["key"]


def test_ai07_confirm_byte_checks_direct_upload_and_ai04_deletes_rejected_object(
        auth_client, make_company, make_user):
    from unittest.mock import patch

    from core import storage
    from core.models import Document, PendingUpload

    co = make_company("Acme AI07b")
    emp = make_user(co, email="emp@acme-ai07b.test")
    client = auth_client(emp)
    with patch.object(storage, "is_s3_enabled", return_value=True), \
         patch.object(storage, "generate_presigned_put", return_value="https://r2.invalid/put"), \
         patch.object(storage, "object_size", return_value=50), \
         patch.object(storage, "object_head", return_value=b"MZ\x90\x00 not a pdf") as head, \
         patch.object(storage, "delete_checked", return_value=True) as delete:
        key = _presigned_key(client, "report.pdf")
        resp = client.post("/api/documents/confirm", {"key": key, "filename": "report.pdf"}, format="json")
    assert resp.status_code == 400
    head.assert_called_once_with(key, 2048)
    delete.assert_called_once_with(key)
    assert not Document.objects.filter(stored_path=key).exists()
    assert PendingUpload.objects.get(key=key).consumed is True


def test_ai04_confirm_deletes_oversize_object(auth_client, make_company, make_user, settings):
    from unittest.mock import patch

    from core import storage

    co = make_company("Acme AI04b")
    emp = make_user(co, email="emp@acme-ai04b.test")
    client = auth_client(emp)
    with patch.object(storage, "is_s3_enabled", return_value=True), \
         patch.object(storage, "generate_presigned_put", return_value="https://r2.invalid/put"), \
         patch.object(storage, "object_size", return_value=settings.DATA_UPLOAD_MAX_MEMORY_SIZE + 1), \
         patch.object(storage, "delete_checked", return_value=True) as delete:
        key = _presigned_key(client, "notes.txt")
        resp = client.post("/api/documents/confirm", {"key": key, "filename": "notes.txt"}, format="json")
    assert resp.status_code == 400
    delete.assert_called_once_with(key)


def test_ai04_cron_purges_expired_unconfirmed_uploads(api, make_company, make_user, monkeypatch):
    from datetime import timedelta
    from unittest.mock import patch

    from django.utils import timezone

    from core import storage
    from core.models import PendingUpload

    co = make_company("Acme AI04c")
    emp = make_user(co, email="emp@acme-ai04c.test")
    now = timezone.now()
    stale = PendingUpload.objects.create(company=co, user=emp, key=f"{co.slug}/stale_a.txt",
                                         filename="a.txt", size=5, expires_at=now - timedelta(minutes=1))
    live = PendingUpload.objects.create(company=co, user=emp, key=f"{co.slug}/live_b.txt",
                                        filename="b.txt", size=5, expires_at=now + timedelta(minutes=10))
    done = PendingUpload.objects.create(company=co, user=emp, key=f"{co.slug}/done_c.txt", filename="c.txt",
                                        size=5, expires_at=now - timedelta(minutes=1), consumed=True)
    monkeypatch.setenv("CRON_SECRET", "test-cron-secret-value")
    with patch.object(storage, "is_s3_enabled", return_value=True), \
         patch.object(storage, "delete_checked", return_value=True) as delete:
        resp = api.post("/api/cron/maintenance", HTTP_AUTHORIZATION="Bearer test-cron-secret-value")
    assert resp.status_code == 200, resp.content
    assert resp.json()["purged_expired_uploads"] == 1
    delete.assert_called_once_with(stale.key)
    assert not PendingUpload.objects.filter(pk=stale.pk).exists()
    assert PendingUpload.objects.filter(pk__in=[live.pk, done.pk]).count() == 2


def test_ai07_storage_object_head_is_a_ranged_get(settings):
    from unittest.mock import MagicMock, patch

    from core import storage

    settings.AWS_STORAGE_BUCKET_NAME = "bucket"
    client = MagicMock()
    client.get_object.return_value = {"Body": MagicMock(read=lambda n: b"%PDF-1.7")}
    with patch.object(storage, "_s3_client", return_value=client):
        assert storage.object_head("acme/x.pdf", 2048) == b"%PDF-1.7"
    client.get_object.assert_called_once_with(Bucket="bucket", Key="acme/x.pdf", Range="bytes=0-2047")


def test_ai06_index_error_hides_parser_exceptions_but_keeps_upload_rejections(make_company, make_user):
    from unittest.mock import patch

    from core import tasks
    from core.models import Document
    from core.serializers import DocumentSerializer
    from core.uploads import UploadRejected

    co = make_company("Acme AI06b")
    emp = make_user(co, email="emp@acme-ai06b.test")
    doc = Document.objects.create(company=co, filename="a.pdf", stored_path="x/a.pdf", uploaded_by=emp)

    with patch("core.storage.read_bytes", return_value=b"%PDF-"), \
         patch("core.rag.index_document", side_effect=RuntimeError("pdfminer at /srv/app/db-internal-7.local")):
        tasks.index_document_task.apply(args=[doc.id])
    doc.refresh_from_db()
    shown = DocumentSerializer(doc).data["index_error"]
    assert doc.indexing_status == "failed"
    assert "db-internal-7" not in shown and "/srv/app" not in shown
    assert shown

    with patch("core.storage.read_bytes", return_value=b"%PDF-"), \
         patch("core.rag.index_document", side_effect=UploadRejected("The PDF has more than 500 pages.")):
        tasks.index_document_task.apply(args=[doc.id])
    doc.refresh_from_db()
    assert doc.index_error == "The PDF has more than 500 pages."
