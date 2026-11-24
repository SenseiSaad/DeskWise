"""Hostile re-review (step 7): attacks against the local test client.

Every attack goes through a local Django/DRF test client. External services
are inert fakes; sockets are blocked. The S7-xx tests were written as failing
attacks and are now regression tests for the fixes. The remaining tests are
controls: attacks that were already blocked and must stay blocked.
"""
from __future__ import annotations

import io
import json
import socket
import time
from datetime import timedelta

import pytest
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from core import mfa
from core.models import (
    ChatConversation, Chunk, Document, DocumentAccess,
    DocumentShare, GeneratedArtifact, OneTimeToken, PendingUpload, Plan,
)
from .conftest import PASSWORD

pytestmark = pytest.mark.django_db
NEW_PASSWORD = "Local-Test-New-Password!927"


@pytest.fixture(autouse=True)
def local_only(settings, monkeypatch, _no_rate_limit):
    """No external email, R2, Google, LLM, cache or socket traffic."""
    settings.CACHES = {"default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "step7-only",
    }}
    cache.clear()
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.EMAIL_ASYNC = False
    settings.RATELIMIT_ENABLED = True
    settings.REQUIRE_EMAIL_VERIFICATION = True
    settings.AWS_STORAGE_BUCKET_NAME = ""
    settings.GOOGLE_CALENDAR_CREDENTIALS = ""
    settings.SYNC_INDEXING = True
    settings.RAG_USE_PGVECTOR = False
    settings.CHANNEL_LAYERS = {"default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }}
    monkeypatch.setattr("core.rag.embed", lambda texts: None)
    monkeypatch.setattr("core.providers.get_chat_provider", lambda **kw: EchoChat())
    monkeypatch.setattr("core.team_chat.broadcast_group_event_sync", lambda *a, **kw: None)

    def no_network(*a, **kw):
        raise AssertionError("External sockets are forbidden in step7 tests")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    yield
    cache.clear()


class EchoChat:
    """Deterministic output: echoes only the supplied document context."""
    label = "step7-fake"
    chat_model = "local-fake"
    temperature = 0
    max_tokens = 64
    last_usage = {}

    def available(self):
        return True

    def stream_chat(self, messages, temperature=0, max_tokens=64):
        yield messages[-1]["content"] + '\n<<<INTENT_JSON>>>{"intent":"none"}<<<END_INTENT_JSON>>>'


class IntentChat(EchoChat):
    def __init__(self, intent):
        self.intent = intent

    def stream_chat(self, messages, temperature=0, max_tokens=64):
        yield "Please review this suggestion.\n<<<INTENT_JSON>>>"
        yield json.dumps(self.intent)
        yield "<<<END_INTENT_JSON>>>"


def login(user, password=PASSWORD, ip="10.77.0.1"):
    client = APIClient()
    response = client.post("/api/auth/login", {"email": user.email, "password": password},
                           format="json", REMOTE_ADDR=ip, HTTP_X_FORWARDED_FOR=ip)
    return client, response


def root(make_company, make_user, enrolled=False):
    user = make_user(make_company("Step7 Root"), email="root@step7.test", role="admin",
                     is_platform_admin=True, is_superuser=True, is_staff=True)
    if enrolled:
        user.mfa_secret = mfa.generate_secret()
        user.mfa_enabled = True
        user.save(update_fields=["mfa_secret", "mfa_enabled"])
    return user


def totp(secret, offset=0):
    return mfa._code_at(secret, int(time.time()) // 30 + offset)


def doc(company, owner, filename="local.txt", text="STEP7_DOCUMENT_TEXT", **kw):
    document = Document.objects.create(
        company=company, uploaded_by=owner, filename=filename,
        content_type="text/plain", stored_path=f"{company.slug}/{filename}", size=64,
        preview_text=text, indexing_status="ready", **kw,
    )
    Chunk.objects.create(document=document, company=company, ord=0, text=text)
    return document


def ask(client, question="Explain the office policy", **kw):
    response = client.post("/api/ask", {"question": question, **kw}, format="json")
    assert response.status_code == 200, "local ask setup failed"
    events = [json.loads(line) for line in b"".join(response.streaming_content).decode().splitlines()]
    return events


# ---------------------------------------------------------------- auth
def test_s701_enrollment_challenge_cannot_restore_session_after_password_reset(make_company, make_user):
    user = root(make_company, make_user)
    attacker, initial = login(user)
    assert initial.status_code == 200 and initial.json()["mfa_required"]
    enrollment = initial.json()
    _, reset = OneTimeToken.issue(user, "password_reset", minutes=30)
    assert APIClient().post("/api/auth/reset-password", {"token": reset, "password": NEW_PASSWORD},
                            format="json").status_code == 200
    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD) and user.token_version > 1

    activated = attacker.post("/api/auth/mfa/activate", {
        "challenge": enrollment["challenge"], "code": totp(enrollment["enrollment"]["secret"]),
    }, format="json")
    still_signed_in = attacker.get("/api/auth/me").status_code == 200
    assert activated.status_code in (400, 401, 403) and not still_signed_in, \
        "pre-reset challenge issued a fresh, usable platform-admin session"


def test_s701_login_challenge_is_revoked_by_logout_all(make_company, make_user):
    user = root(make_company, make_user, enrolled=True)
    victim, first = login(user)
    assert victim.post("/api/auth/mfa/verify", {
        "challenge": first.json()["challenge"], "code": totp(user.mfa_secret),
    }, format="json").status_code == 200
    attacker, second = login(user)
    assert victim.post("/api/auth/logout-all", format="json").status_code == 200
    response = attacker.post("/api/auth/mfa/verify", {
        "challenge": second.json()["challenge"], "code": totp(user.mfa_secret, 1),
    }, format="json")
    signed_in = attacker.get("/api/auth/me").status_code == 200
    assert response.status_code in (400, 401, 403) and not signed_in, \
        "logout-all left a pending MFA challenge able to mint a current-generation session"


def test_s702_old_enrollment_cannot_replace_the_completed_enrollment(make_company, make_user):
    user = root(make_company, make_user)
    legitimate, first = login(user)
    attacker, second = login(user)
    enrollment1, enrollment2 = first.json(), second.json()
    assert legitimate.post("/api/auth/mfa/activate", {
        "challenge": enrollment1["challenge"], "code": totp(enrollment1["enrollment"]["secret"]),
    }, format="json").status_code == 200
    response = attacker.post("/api/auth/mfa/activate", {
        "challenge": enrollment2["challenge"], "code": totp(enrollment2["enrollment"]["secret"], 1),
    }, format="json")
    user.refresh_from_db()
    replaced = user.mfa_secret == enrollment2["enrollment"]["secret"]
    assert response.status_code in (400, 401, 403) and not replaced, \
        "a leftover password-only enrollment replaced the owner's already-enabled authenticator"


def test_s703_old_invitation_cannot_reset_password_and_preserve_sessions(make_company, make_user):
    user = make_user(make_company("Step7 Invited"), email="invited@step7.test", password=None)
    user.email_verified = False
    user.save(update_fields=["email_verified"])
    # Simulate a valid invitation copied before the user accepted/recovered the account.
    _, invitation = OneTimeToken.issue(user, "invite", minutes=60 * 24 * 7)
    _, reset = OneTimeToken.issue(user, "password_reset", minutes=30)
    assert APIClient().post("/api/auth/reset-password", {"token": reset, "password": NEW_PASSWORD},
                            format="json").status_code == 200
    victim, success = login(user, NEW_PASSWORD)
    assert success.status_code == 200
    thief = APIClient()
    response = thief.post("/api/auth/join", {
        "invite_token": invitation, "email": user.email, "password": PASSWORD,
    }, format="json")
    user.refresh_from_db()
    thief_in = thief.get("/api/auth/me").status_code == 200
    victim_in = victim.get("/api/auth/me").status_code == 200
    assert response.status_code in (400, 401, 403) and not user.check_password(PASSWORD) and not thief_in, \
        f"old invitation replaced the recovered password; thief_session={thief_in}, victim_session={victim_in}"


def test_s703_invitation_after_platform_promotion_does_not_skip_mfa(make_company, make_user):
    user = make_user(make_company("Step7 Promoted"), email="promoted@step7.test")
    _, invitation = OneTimeToken.issue(user, "invite", minutes=60 * 24 * 7)
    # Previously invited account is subsequently promoted by the operator.
    call_command("create_platform_admin", user.email, promote=True, stdout=io.StringIO())
    user.refresh_from_db()
    user.mfa_enabled = True
    user.mfa_secret = mfa.generate_secret()
    user.save(update_fields=["mfa_enabled", "mfa_secret"])
    attacker = APIClient()
    response = attacker.post("/api/auth/join", {
        "invite_token": invitation, "email": user.email, "password": NEW_PASSWORD,
    }, format="json")
    root_access = attacker.get("/api/admin/reports").status_code == 200
    assert not root_access, "an old invitation signed into platform reports without a TOTP code"
    assert response.status_code != 200 or response.json().get("mfa_required")


def test_s704_logout_revokes_pre_rotation_access_token(make_company, make_user):
    user = make_user(make_company("Step7 Logout"), email="logout@step7.test")
    owner, response = login(user)
    assert response.status_code == 200
    old_access = owner.cookies["openvault_access"].value
    assert owner.post("/api/auth/refresh", format="json").status_code == 200
    assert owner.post("/api/auth/logout", format="json").status_code == 200
    thief = APIClient()
    thief.cookies["openvault_access"] = old_access
    assert thief.get("/api/auth/me").status_code == 401, \
        "a copied access token from this same session before refresh still works after logout"


# ---------------------------------------------------------------- tenant isolation controls
@pytest.mark.parametrize("suffix", ["", "/preview", "/download", "/versions"])
def test_cross_tenant_document_idor_is_blocked(make_company, make_user, suffix):
    a, b = make_company("Step7 Tenant A"), make_company("Step7 Tenant B")
    owner = make_user(a, role="admin")
    outsider = make_user(b, role="admin")
    secret = doc(a, owner, text="TENANT_A_ONLY_SECRET")
    client, response = login(outsider)
    assert response.status_code == 200
    assert client.get(f"/api/documents/{secret.pk}{suffix}").status_code == 404


def test_cross_tenant_mutation_and_share_are_blocked(make_company, make_user):
    a, b = make_company("Step7 Mutate A"), make_company("Step7 Mutate B")
    owner = make_user(a, role="admin")
    outsider = make_user(b, role="admin")
    secret = doc(a, owner, access_scope="restricted")
    client, _ = login(outsider)
    assert client.patch(f"/api/documents/{secret.pk}", {"access_scope": "company"}, format="json").status_code == 404
    assert client.post(f"/api/documents/{secret.pk}/shares", {"user_id": outsider.pk}, format="json").status_code == 404
    assert client.delete(f"/api/documents/{secret.pk}").status_code == 404
    secret.refresh_from_db()
    assert secret.access_scope == "restricted"


def test_cross_tenant_artifact_and_conversation_idor_are_blocked(make_company, make_user):
    a, b = make_company("Step7 Object A"), make_company("Step7 Object B")
    owner = make_user(a)
    outsider = make_user(b)
    artifact = GeneratedArtifact.objects.create(company=a, user=owner, content_md="ARTIFACT_SECRET")
    conversation = ChatConversation.objects.create(company=a, user=owner)
    client, _ = login(outsider)
    assert client.get(f"/api/artifacts/{artifact.pk}").status_code == 404
    assert client.get(f"/api/artifacts/{artifact.pk}/download?fmt=txt").status_code == 404
    assert client.get(f"/api/conversations/{conversation.pk}").status_code == 404


def test_external_share_revocation_blocks_read_and_rag(make_company, make_user):
    a, b = make_company("Step7 Share A"), make_company("Step7 Share B")
    owner = make_user(a, role="admin")
    outsider = make_user(b)
    document = doc(a, owner, text="EXTERNAL_SHARE_MARKER")
    share = DocumentShare.objects.create(document=document, shared_with_user=outsider,
                                         shared_by=owner, can_download=False)
    client, _ = login(outsider)
    assert client.get(f"/api/documents/{document.pk}/preview").status_code == 200
    assert client.get(f"/api/documents/{document.pk}/download").status_code == 403
    share.delete()
    assert client.get(f"/api/documents/{document.pk}/preview").status_code == 404
    events = ask(client)
    assert "EXTERNAL_SHARE_MARKER" not in json.dumps(events)


def test_ai_rag_cannot_retrieve_unshared_other_tenant_chunks(make_company, make_user):
    a, b = make_company("Step7 RAG A"), make_company("Step7 RAG B")
    owner = make_user(a)
    outsider = make_user(b)
    doc(a, owner, text="OTHER_TENANT_RAG_SECRET")
    client, _ = login(outsider)
    assert "OTHER_TENANT_RAG_SECRET" not in json.dumps(ask(client))


# ---------------------------------------------------------------- uploads
class FakeR2:
    """In-memory object service. Tests exercise real core.storage methods."""
    def __init__(self):
        self.objects = {}
        self.deleted = []
        self.ranges = []
        self.delete_fails = False
        self.presigned = {}

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        self.presigned[Params["Key"]] = dict(Params)
        return "https://not-contacted.invalid/fake-put"

    def head_object(self, Bucket, Key):
        return {"ContentLength": len(self.objects[Key])}

    def get_object(self, Bucket, Key, Range=None):
        raw = self.objects[Key]
        if Range:
            self.ranges.append(Range)
            raw = raw[:int(Range.split("-")[1]) + 1]
        return {"Body": io.BytesIO(raw)}

    def delete_object(self, Bucket, Key):
        if self.delete_fails:
            raise OSError("STEP7_FAKE_R2_DELETE_FAILURE")
        self.deleted.append(Key)
        self.objects.pop(Key, None)


@pytest.fixture
def r2(settings, monkeypatch):
    settings.AWS_STORAGE_BUCKET_NAME = "step7-fake-bucket"
    fake = FakeR2()
    monkeypatch.setattr("core.storage._s3_client", lambda: fake)
    # Parsing/indexing is not needed to demonstrate acceptance into Document.
    monkeypatch.setattr("core.views._index_in_background", lambda document: None)
    return fake


def presign(client, name, raw, r2):
    response = client.post("/api/documents/presign", {"filename": name, "size": len(raw)}, format="json")
    assert response.status_code == 200
    key = response.json()["key"]
    r2.objects[key] = raw
    return key


def test_s705_changing_confirm_filename_cannot_bypass_binary_magic(make_company, make_user, r2):
    user = make_user(make_company("Step7 Upload Rename"))
    client, _ = login(user)
    key = presign(client, "report.pdf", b"MZ\x90\x00THIS_IS_NOT_A_PDF", r2)
    assert r2.presigned[key]["ContentType"] == "application/pdf"
    response = client.post("/api/documents/confirm", {"key": key, "filename": "notes.txt"}, format="json")
    created = Document.objects.filter(stored_path=key).exists()
    assert response.status_code in (400, 403) and not created, \
        "confirm accepted non-PDF bytes at a PDF key by byte-checking client-renamed .txt"


def test_bad_pdf_without_rename_is_rejected_and_removed(make_company, make_user, r2):
    user = make_user(make_company("Step7 Upload Bad PDF"))
    client, _ = login(user)
    key = presign(client, "report.pdf", b"MZ\x90\x00NOT_A_PDF", r2)
    response = client.post("/api/documents/confirm", {"key": key, "filename": "report.pdf"}, format="json")
    assert response.status_code == 400
    assert key not in r2.objects and key in r2.deleted
    assert not Document.objects.filter(stored_path=key).exists()
    assert r2.ranges == ["bytes=0-2047"]


def test_forged_other_users_upload_key_is_not_read_or_deleted(make_company, make_user, r2):
    company = make_company("Step7 Upload Owner")
    victim = make_user(company)
    attacker = make_user(company)
    victim_client, _ = login(victim)
    attacker_client, _ = login(attacker)
    key = presign(victim_client, "victim.pdf", b"%PDF-1.7 safe", r2)
    response = attacker_client.post("/api/documents/confirm", {"key": key, "filename": "victim.pdf"}, format="json")
    assert response.status_code == 403
    assert key in r2.objects and r2.ranges == [] and r2.deleted == []


@pytest.mark.parametrize("trigger", ["expiry", "rejection"])
def test_s706_cleanup_does_not_forget_an_object_whose_delete_failed(
        make_company, make_user, r2, monkeypatch, trigger):
    user = make_user(make_company("Step7 Cleanup Failure"))
    client, _ = login(user)
    key = presign(client, "bad.pdf", b"NOT_A_PDF", r2)
    r2.delete_fails = True
    if trigger == "expiry":
        PendingUpload.objects.filter(key=key).update(expires_at=timezone.now() - timedelta(minutes=1))
    else:
        response = client.post("/api/documents/confirm", {"key": key, "filename": "bad.pdf"}, format="json")
        assert response.status_code == 400
        PendingUpload.objects.filter(key=key).update(expires_at=timezone.now() - timedelta(minutes=1))
    monkeypatch.setenv("CRON_SECRET", "local-step7-cron-secret")
    cron = APIClient().post("/api/cron/maintenance", HTTP_AUTHORIZATION="Bearer local-step7-cron-secret")
    assert cron.status_code == 200
    assert key in r2.objects, "fake delete failure setup was ineffective"
    retryable = PendingUpload.objects.filter(key=key, consumed=False).exists()
    assert retryable, "storage swallowed delete failure; row removed/burned so no sweep will retry"
    # The object store recovers: the next sweep removes the object and the row.
    r2.delete_fails = False
    again = APIClient().post("/api/cron/maintenance", HTTP_AUTHORIZATION="Bearer local-step7-cron-secret")
    assert again.status_code == 200
    assert key not in r2.objects and key in r2.deleted
    assert not PendingUpload.objects.filter(key=key).exists()


# ---------------------------------------------------------------- AI confirmation controls
def proposal(client, monkeypatch, **data):
    intent = {"intent": "schedule_meeting", "data": {"title": "Step7 Sync", "date": "2030-01-02", **data}}
    monkeypatch.setattr("core.providers.get_chat_provider", lambda **kw: IntentChat(intent))
    events = ask(client)
    proposals = [e for e in events if e.get("type") == "workflow_proposal"]
    assert len(proposals) == 1
    assert not [e for e in events if e.get("type") == "workflow"]
    assert len(mail.outbox) == 0, "an action executed before confirmation"
    return proposals[0]


def test_proposal_forgery_other_user_and_reuse_are_blocked(make_company, make_user, monkeypatch):
    company = make_company("Step7 Proposal Controls")
    user = make_user(company)
    other = make_user(company)
    client, _ = login(user)
    stranger, _ = login(other)
    p = proposal(client, monkeypatch, participants=["outsider@not-our-tenant.test"])
    assert p["preview"]["participants"] == []
    body = {"token": p["token"]}
    assert stranger.post("/api/workflow/confirm", body, format="json").status_code == 400
    assert client.post("/api/workflow/confirm", {"token": p["token"] + "x"}, format="json").status_code == 400
    assert len(mail.outbox) == 0
    assert client.post("/api/workflow/confirm", body, format="json").status_code == 200
    assert client.post("/api/workflow/confirm", body, format="json").status_code == 400
    assert len(mail.outbox) == 1 and mail.outbox[0].to == [user.email]


def test_s707_leave_proposal_cannot_execute_when_docgen_disabled(make_company, make_user, monkeypatch):
    from core import workflow

    company = make_company("Step7 Docgen Disabled")
    user = make_user(company)
    client, _ = login(user)
    leave = {"intent": "leave_request", "data": {"date": "2030-01-02", "reason": "local-test"}}

    # 1) A proposal made while the feature is on...
    monkeypatch.setattr("core.providers.get_chat_provider", lambda **kw: IntentChat(leave))
    proposal_token = next(e for e in ask(client) if e.get("type") == "workflow_proposal")["token"]
    # ...a form the user generated while it was on...
    on = client.post("/api/workflow/confirm", {"token": next(
        e for e in ask(client) if e.get("type") == "workflow_proposal")["token"]}, format="json")
    assert on.status_code == 200
    old_form = f"/api/workflow/forms/{user.pk}/{on.json()['filename']}"
    assert client.get(old_form).status_code == 200

    # 2) ...then an admin switches document generation off.
    company.enable_docgen = False
    company.save(update_fields=["enable_docgen"])
    assert client.post("/api/docgen", {"question": "draft leave form", "outputs": ["form"]},
                       format="json").status_code == 403

    # The stale proposal is refused (and not burned), nothing is generated.
    response = client.post("/api/workflow/confirm", {"token": proposal_token}, format="json")
    assert response.status_code == 403
    # Previously generated forms are not downloadable either.
    assert client.get(old_form).status_code == 403
    # New chat turns no longer offer the action at all.
    monkeypatch.setattr("core.providers.get_chat_provider", lambda **kw: IntentChat(leave))
    assert not [e for e in ask(client) if e.get("type") == "workflow_proposal"]
    assert workflow.build_proposal(leave, user) is None

    # Re-enabling the feature makes the (unburned) proposal usable again.
    company.enable_docgen = True
    company.save(update_fields=["enable_docgen"])
    assert client.post("/api/workflow/confirm", {"token": proposal_token}, format="json").status_code == 200


def test_s708_template_derived_llm_answer_is_masked_after_grant_revocation(
        make_company, make_user):
    company = make_company("Step7 Template Revocation")
    owner = make_user(company, role="admin")
    reader = make_user(company)
    template = doc(company, owner, filename="form_zebraclaim.txt",
                   text="Zebraclaim Application Form\nTEMPLATE_PRIVATE_MARKER\nName: [Full Name]",
                   access_scope="restricted", is_template=True, template_type="form")
    grant = DocumentAccess.objects.create(document=template, user=reader, can_download=True)
    client, _ = login(reader)
    events = ask(client, question="Explain and prepare the zebraclaim application form",
                 outputs=["text", "form"])
    conversation_id = next(e["conversation_id"] for e in events if e["type"] == "conversation")
    llm_message_id = next(e["message_id"] for e in events if e["type"] == "saved")
    # The model really saw the protected template, not a fabricated DB message.
    assert "TEMPLATE_PRIVATE_MARKER" in "".join(e.get("token", "") for e in events)
    grant.delete()
    assert client.get(f"/api/documents/{template.pk}/preview").status_code == 404
    response = client.get(f"/api/conversations/{conversation_id}")
    assert response.status_code == 200
    old_answer = next(m for m in response.json()["messages"] if m["id"] == llm_message_id)
    assert old_answer["masked"] and "TEMPLATE_PRIVATE_MARKER" not in old_answer["content"], \
        "revoked template content remains visible because the LLM answer saved no template source IDs"


def test_s709_new_lower_clearance_room_member_cannot_read_old_protected_bot_answer(
        make_company, make_user, monkeypatch):
    company = make_company("Step7 Room History")
    admin = make_user(company, role="admin")
    reader = make_user(company)
    newcomer = make_user(company, role="viewer")
    document = doc(company, admin, filename="private_notes.txt", text="ROOM_PRIVATE_MARKER",
                   access_scope="restricted", sensitivity="internal")
    DocumentAccess.objects.create(document=document, user=admin, can_download=True)
    DocumentAccess.objects.create(document=document, user=reader, can_download=True)
    admin_client, _ = login(admin)
    reader_client, _ = login(reader)
    new_client, _ = login(newcomer)
    room_response = admin_client.post("/api/team-chat/rooms", {
        "name": "Protected Working Group", "scope": "private", "member_ids": [reader.pk],
    }, format="json")
    assert room_response.status_code == 201
    room_id = room_response.json()["id"]
    initial = reader_client.post(f"/api/team-chat/rooms/{room_id}/messages", {
        "content": "@DeskWise Explain the private notes",
    }, format="json")
    assert initial.status_code == 201
    bot = initial.json()["deskwise_message"]
    assert bot and "ROOM_PRIVATE_MARKER" in bot["content"]
    added = admin_client.patch(f"/api/team-chat/rooms/{room_id}", {
        "member_ids": [reader.pk, newcomer.pk],
    }, format="json")
    assert added.status_code == 200
    assert new_client.get(f"/api/documents/{document.pk}/preview").status_code == 404
    history = new_client.get(f"/api/team-chat/rooms/{room_id}/messages")
    assert history.status_code == 200
    assert "ROOM_PRIVATE_MARKER" not in json.dumps(history.json()), \
        "new lower-clearance room member received the old bot's restricted-document content"


def test_cross_tenant_team_room_and_message_ids_are_blocked(make_company, make_user):
    company = make_company("Step7 Room A")
    victim = make_user(company)
    outsider = make_user(make_company("Step7 Room B"), role="admin")
    victim_client, _ = login(victim)
    attacker, _ = login(outsider)
    room_id = victim_client.get("/api/team-chat/rooms").json()["rooms"][0]["id"]
    posted = victim_client.post(f"/api/team-chat/rooms/{room_id}/messages",
                                {"content": "ROOM_A_SECRET"}, format="json")
    assert posted.status_code == 201
    message_id = posted.json()["message"]["id"]
    assert attacker.get(f"/api/team-chat/rooms/{room_id}/messages").status_code == 404
    assert attacker.patch(f"/api/team-chat/messages/{message_id}",
                          {"content": "tampered"}, format="json").status_code == 404
    assert attacker.delete(f"/api/team-chat/messages/{message_id}").status_code == 404


def test_untrusted_origin_cannot_change_an_authenticated_profile(make_company, make_user):
    user = make_user(make_company("Step7 Origin"))
    client, _ = login(user)
    response = client.patch("/api/auth/update-me", {"full_name": "CSRF_CHANGED"},
                            format="json", HTTP_ORIGIN="https://untrusted.invalid")
    assert response.status_code == 403
    user.refresh_from_db()
    assert user.full_name != "CSRF_CHANGED"


def test_account_lockout_cannot_be_bypassed_by_changing_ips(make_company, make_user):
    user = make_user(make_company("Step7 Lockout"))
    for n in range(10):
        _, response = login(user, "wrong-local-password", ip=f"10.77.1.{n + 1}")
        assert response.status_code == 401
    _, locked = login(user, ip="10.77.2.1")
    assert locked.status_code == 429 and locked.json().get("code") == "account_locked"


def test_burned_mfa_challenge_does_not_accept_correct_code(make_company, make_user):
    user = root(make_company, make_user, enrolled=True)
    client, response = login(user)
    challenge = response.json()["challenge"]
    for n in range(5):
        wrong = client.post("/api/auth/mfa/verify", {"challenge": challenge, "code": "invalid"},
                            format="json", REMOTE_ADDR=f"10.77.3.{n + 1}",
                            HTTP_X_FORWARDED_FOR=f"10.77.3.{n + 1}")
        assert wrong.status_code == 400
    assert client.post("/api/auth/mfa/verify", {
        "challenge": challenge, "code": totp(user.mfa_secret),
    }, format="json").status_code == 400
    assert client.get("/api/auth/me").status_code == 401


def test_google_different_sub_cannot_link_to_bound_account(make_company, make_user, monkeypatch):
    user = make_user(make_company("Step7 Google"))
    user.google_sub = "local-original-google-sub"
    user.save(update_fields=["google_sub"])
    # Cryptographic verification is an external dependency, not under attack
    # here: simulate two genuinely verified identities with the same email.
    monkeypatch.setattr("core.views.verify_google_id_token", lambda credential: {
        "sub": "local-different-google-sub", "email": user.email, "email_verified": True,
    })
    client = APIClient()
    response = client.post("/api/auth/google", {"credential": "fake-local-credential"}, format="json")
    assert response.status_code == 403
    assert client.get("/api/auth/me").status_code == 401


def test_direct_upload_zip_path_traversal_filename_is_rejected(make_company, make_user):
    user = make_user(make_company("Step7 Filename"))
    client, _ = login(user)
    response = client.post("/api/documents/upload", {
        "file": SimpleUploadedFile("..escape.txt", b"LOCAL_ONLY"),
    }, format="multipart")
    assert response.status_code == 400
    assert Document.objects.filter(company=user.company).count() == 0


def test_s710_pre_promotion_session_cannot_get_platform_powers_without_mfa(make_company, make_user):
    company = make_company("Step7 Promotion Session")
    promoted = make_user(company, email="promote-session@step7.test")
    stolen_session, response = login(promoted)
    assert response.status_code == 200
    assert stolen_session.get("/api/admin/companies").status_code == 403
    version_before = promoted.token_version
    call_command("create_platform_admin", promoted.email, promote=True, stdout=io.StringIO())
    promoted.refresh_from_db()
    assert promoted.is_platform_admin and not promoted.mfa_enabled
    # An operator legitimately promotes the account. No attacker action is
    # allowed to promote it; the attack is replaying its old, password-only JWT.
    listing = stolen_session.get("/api/admin/companies")
    victim_company = make_company("Step7 Other Tenant Plan")
    paid_plan = Plan.objects.create(name="Step7 Paid Plan", price_usd=25)
    changed = stolen_session.post(f"/api/admin/companies/{victim_company.pk}/plan", {
        "plan_id": paid_plan.pk,
    }, format="json")
    victim_company.refresh_from_db()
    assert listing.status_code in (401, 403) and changed.status_code in (401, 403), \
        ("pre-promotion password-only JWT read platform company directory and changed another tenant's plan; "
         f"token_version_changed={promoted.token_version != version_before}, "
         f"plan_changed={victim_company.plan_id == paid_plan.pk}")


def test_s710_pre_promotion_session_cannot_use_platform_authority_without_mfa(make_company, make_user):
    user = make_user(make_company("Step7 Operator Promotion"))
    old_session, response = login(user)
    assert response.status_code == 200
    assert old_session.get("/api/admin/reports").status_code == 403
    call_command("create_platform_admin", user.email, promote=True, stdout=io.StringIO())
    user.refresh_from_db()
    assert user.is_platform_admin and not user.mfa_enabled
    # A *new* password login correctly stops at mandatory enrollment.
    _, new_login = login(user)
    assert new_login.json().get("mfa_required") is True
    # But the old ordinary-user JWT is reinterpreted as platform authority.
    response = old_session.get("/api/admin/reports")
    assert response.status_code in (401, 403), \
        "pre-promotion password-only JWT became a usable platform-admin session without enrollment/TOTP"


# ================================================================ fix verification
# Legitimate behaviour that the step-7 fixes must NOT break.
def _platform_session(make_company, make_user):
    user = root(make_company, make_user, enrolled=True)
    client, first = login(user)
    done = client.post("/api/auth/mfa/verify", {
        "challenge": first.json()["challenge"], "code": totp(user.mfa_secret),
    }, format="json")
    assert done.status_code == 200
    return user, client


def test_fix_platform_admin_with_mfa_session_keeps_working_across_refresh(make_company, make_user):
    user, client = _platform_session(make_company, make_user)
    assert client.get("/api/admin/reports").status_code == 200
    # The MFA claim and session id survive rotation, so refreshing never logs
    # the platform admin out or downgrades the session.
    assert client.post("/api/auth/refresh", format="json").status_code == 200
    assert client.get("/api/admin/reports").status_code == 200
    assert client.post("/api/auth/refresh", format="json").status_code == 200
    assert client.get("/api/admin/reports").status_code == 200


def test_fix_platform_token_without_mfa_claim_is_rejected(make_company, make_user):
    from rest_framework_simplejwt.tokens import AccessToken

    user = root(make_company, make_user, enrolled=True)
    token = AccessToken.for_user(user)
    token["tv"] = user.token_version  # a valid, current, password-only style token
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    assert client.get("/api/admin/reports").status_code == 401
    token["mfa"] = True
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    assert client.get("/api/admin/reports").status_code == 200


def test_fix_ordinary_users_are_unaffected_by_the_mfa_claim_rule(make_company, make_user):
    user = make_user(make_company("Step7 Ordinary"))
    client, response = login(user)
    assert response.status_code == 200
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/refresh", format="json").status_code == 200
    assert client.get("/api/auth/me").status_code == 200


def test_fix_authenticator_rotation_by_an_mfa_session_still_works(make_company, make_user):
    user, client = _platform_session(make_company, make_user)
    setup = client.post("/api/auth/mfa/setup", format="json")
    assert setup.status_code == 200
    new_secret = setup.json()["secret"]
    activated = client.post("/api/auth/mfa/activate", {
        "challenge": setup.json()["challenge"], "code": totp(new_secret, 1),
    }, format="json")
    assert activated.status_code == 200
    user.refresh_from_db()
    assert user.mfa_secret == new_secret and user.mfa_enabled
    assert client.get("/api/admin/reports").status_code == 200


def test_fix_a_password_only_enroll_challenge_cannot_be_used_as_a_rotation(make_company, make_user):
    user = root(make_company, make_user, enrolled=True)
    old_secret = user.mfa_secret
    attacker = APIClient()
    forged = mfa.issue_challenge(user.pk, "enroll", secret=mfa.generate_secret())
    response = attacker.post("/api/auth/mfa/activate", {"challenge": forged, "code": "000000"}, format="json")
    assert response.status_code == 400
    user.refresh_from_db()
    assert user.mfa_secret == old_secret


def test_fix_first_time_enrollment_still_works(make_company, make_user):
    user = root(make_company, make_user)
    client, response = login(user)
    secret = response.json()["enrollment"]["secret"]
    done = client.post("/api/auth/mfa/activate", {
        "challenge": response.json()["challenge"], "code": totp(secret),
    }, format="json")
    assert done.status_code == 200
    user.refresh_from_db()
    assert user.mfa_enabled and user.mfa_secret == secret
    assert client.get("/api/admin/reports").status_code == 200


def test_fix_login_challenge_still_works_when_nothing_was_revoked(make_company, make_user):
    user = root(make_company, make_user, enrolled=True)
    client, response = login(user)
    done = client.post("/api/auth/mfa/verify", {
        "challenge": response.json()["challenge"], "code": totp(user.mfa_secret),
    }, format="json")
    assert done.status_code == 200 and client.get("/api/auth/me").status_code == 200


def test_fix_promotion_revokes_old_sessions_and_pending_links_but_not_other_users(make_company, make_user):
    company = make_company("Step7 Promotion Scope")
    promoted = make_user(company, email="promoted-scope@step7.test")
    bystander = make_user(company, email="bystander@step7.test")
    old, _ = login(promoted)
    other, _ = login(bystander, ip="10.77.9.9")
    call_command("create_platform_admin", promoted.email, promote=True, stdout=io.StringIO())
    assert old.get("/api/auth/me").status_code == 401
    assert old.post("/api/auth/refresh", format="json").status_code == 401
    assert other.get("/api/auth/me").status_code == 200
    # The promoted account can still reach the MFA step, as designed.
    _, again = login(promoted)
    assert again.json().get("mfa_required") is True


def test_fix_normal_invitation_flow_still_completes_and_sets_a_session(make_company, make_user):
    company = make_company("Step7 Normal Invite")
    invited = make_user(company, email="invitee@step7.test", password=None)
    invited.email_verified = False
    invited.save(update_fields=["email_verified"])
    _, token = OneTimeToken.issue(invited, "invite", minutes=60)
    client = APIClient()
    response = client.post("/api/auth/join", {
        "invite_token": token, "email": invited.email, "password": NEW_PASSWORD,
    }, format="json")
    assert response.status_code == 200
    assert client.get("/api/auth/me").status_code == 200
    invited.refresh_from_db()
    assert invited.check_password(NEW_PASSWORD) and invited.email_verified
    # single use
    assert APIClient().post("/api/auth/join", {
        "invite_token": token, "email": invited.email, "password": PASSWORD,
    }, format="json").status_code == 400


def test_fix_confirm_uses_the_presigned_filename_and_ignores_the_client_one(make_company, make_user, r2):
    user = make_user(make_company("Step7 Confirm Name"))
    client, _ = login(user)
    key = presign(client, "handbook.txt", b"plain handbook text", r2)
    response = client.post("/api/documents/confirm",
                           {"key": key, "filename": "something-else.pdf"}, format="json")
    assert response.status_code == 201, response.content
    document = Document.objects.get(stored_path=key)
    assert document.filename == "handbook.txt" and document.content_type == "text/plain"


def test_fix_confirm_still_accepts_a_genuine_pdf(make_company, make_user, r2):
    user = make_user(make_company("Step7 Genuine PDF"))
    client, _ = login(user)
    key = presign(client, "policy.pdf", b"%PDF-1.7\n%real header", r2)
    response = client.post("/api/documents/confirm", {"key": key, "filename": "policy.pdf"}, format="json")
    assert response.status_code == 201, response.content
    assert Document.objects.filter(stored_path=key, content_type="application/pdf").exists()


def test_fix_successful_rejection_burns_the_row_and_removes_the_object(make_company, make_user, r2):
    user = make_user(make_company("Step7 Reject Cleanup"))
    client, _ = login(user)
    key = presign(client, "bad.pdf", b"NOT_A_PDF", r2)
    assert client.post("/api/documents/confirm", {"key": key, "filename": "bad.pdf"},
                       format="json").status_code == 400
    assert key not in r2.objects
    assert PendingUpload.objects.get(key=key).consumed is True


def test_fix_cleanup_does_not_touch_live_or_confirmed_uploads(make_company, make_user, r2, monkeypatch):
    user = make_user(make_company("Step7 Cleanup Scope"))
    client, _ = login(user)
    live = presign(client, "live.txt", b"live", r2)
    confirmed = presign(client, "kept.txt", b"kept", r2)
    assert client.post("/api/documents/confirm", {"key": confirmed}, format="json").status_code == 201
    expired = presign(client, "stale.txt", b"stale", r2)
    PendingUpload.objects.filter(key=expired).update(expires_at=timezone.now() - timedelta(minutes=1))
    monkeypatch.setenv("CRON_SECRET", "local-step7-cron-secret")
    cron = APIClient().post("/api/cron/maintenance", HTTP_AUTHORIZATION="Bearer local-step7-cron-secret")
    assert cron.json()["purged_expired_uploads"] == 1
    assert expired not in r2.objects and live in r2.objects and confirmed in r2.objects


def _template_conversation(make_company, make_user):
    company = make_company("Step7 Template Scope")
    owner = make_user(company, role="admin")
    reader = make_user(company)
    template = doc(company, owner, filename="form_zebraclaim.txt",
                   text="Zebraclaim Application Form\nTEMPLATE_PRIVATE_MARKER\nName: [Full Name]",
                   access_scope="restricted", is_template=True, template_type="form")
    grant = DocumentAccess.objects.create(document=template, user=reader, can_download=True)
    client, _ = login(reader)
    events = ask(client, question="Explain and prepare the zebraclaim application form",
                 outputs=["text", "form"])
    return reader, client, template, grant, events


def test_fix_template_answer_is_readable_while_access_exists_and_records_provenance(make_company, make_user):
    from core.models import ChatMessage

    reader, client, template, grant, events = _template_conversation(make_company, make_user)
    saved = next(e for e in events if e["type"] == "saved")
    conversation_id = next(e["conversation_id"] for e in events if e["type"] == "conversation")
    assert json.loads(ChatMessage.objects.get(pk=saved["message_id"]).source_document_ids) == [template.pk]
    sources_event = next(e for e in events if e["type"] == "sources")
    assert sources_event["source_doc_ids"] == [template.pk]
    body = client.get(f"/api/conversations/{conversation_id}").json()
    answer = next(m for m in body["messages"] if m["id"] == saved["message_id"])
    assert answer["masked"] is False and "TEMPLATE_PRIVATE_MARKER" in answer["content"]


def _private_room(make_company, make_user):
    company = make_company("Step7 Room Scope")
    admin = make_user(company, role="admin")
    reader = make_user(company)
    newcomer = make_user(company, role="viewer")
    document = doc(company, admin, filename="private_notes.txt", text="ROOM_PRIVATE_MARKER",
                   access_scope="restricted", sensitivity="internal")
    DocumentAccess.objects.create(document=document, user=admin, can_download=True)
    DocumentAccess.objects.create(document=document, user=reader, can_download=True)
    admin_client, _ = login(admin)
    reader_client, _ = login(reader, ip="10.77.8.1")
    new_client, _ = login(newcomer, ip="10.77.8.2")
    room_id = admin_client.post("/api/team-chat/rooms", {
        "name": "Protected Working Group", "scope": "private", "member_ids": [reader.pk],
    }, format="json").json()["id"]
    reader_client.post(f"/api/team-chat/rooms/{room_id}/messages",
                       {"content": "@DeskWise Explain the private notes"}, format="json")
    admin_client.patch(f"/api/team-chat/rooms/{room_id}", {"member_ids": [reader.pk, newcomer.pk]},
                       format="json")
    return room_id, reader_client, new_client, document


def test_fix_room_members_with_access_still_read_bot_answers_others_get_a_mask(make_company, make_user):
    room_id, reader_client, new_client, _ = _private_room(make_company, make_user)
    allowed = reader_client.get(f"/api/team-chat/rooms/{room_id}/messages").json()
    bot = next(m for m in allowed["results"] if m["sender_type"] == "deskwise")
    assert "ROOM_PRIVATE_MARKER" in bot["content"] and not bot.get("masked")

    hidden = new_client.get(f"/api/team-chat/rooms/{room_id}/messages").json()
    bot = next(m for m in hidden["results"] if m["sender_type"] == "deskwise")
    assert bot["masked"] is True and bot["sources"] == []
    assert "ROOM_PRIVATE_MARKER" not in json.dumps(hidden)


def test_fix_room_search_and_summary_do_not_relay_masked_bot_answers(make_company, make_user):
    room_id, reader_client, new_client, _ = _private_room(make_company, make_user)
    searched = new_client.get(f"/api/team-chat/rooms/{room_id}/messages?q=ROOM_PRIVATE_MARKER").json()
    assert searched["results"] == []
    assert any(m["sender_type"] == "deskwise"
               for m in reader_client.get(
                   f"/api/team-chat/rooms/{room_id}/messages?q=ROOM_PRIVATE_MARKER").json()["results"])
    unified = new_client.get("/api/search?q=ROOM_PRIVATE_MARKER").json()
    assert unified["team_messages"] == [] and unified["documents"] == []
    summary = new_client.post(f"/api/team-chat/rooms/{room_id}/summarize", format="json")
    assert "ROOM_PRIVATE_MARKER" not in json.dumps(summary.json())


def test_fix_logout_of_one_session_leaves_a_second_login_alone(make_company, make_user):
    user = make_user(make_company("Step7 Two Sessions"))
    laptop, _ = login(user)
    phone, _ = login(user, ip="10.77.7.7")
    laptop.post("/api/auth/refresh", format="json")
    laptop.post("/api/auth/logout", format="json")
    assert laptop.get("/api/auth/me").status_code == 401
    assert phone.get("/api/auth/me").status_code == 200
    assert phone.post("/api/auth/refresh", format="json").status_code == 200
