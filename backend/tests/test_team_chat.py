"""Hardcore tests for the employee Team Chatroom (REST + WebSockets + RBAC + @DeskWise)."""
from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import unquote, urlparse

import pytest
from asgiref.sync import sync_to_async
from asgiref.testing import ApplicationCommunicator
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from config.asgi import application
from core import team_chat
from core.models import AuditLog, Chunk, Department, Document, Plan, TeamMessage, TeamRoom
from .fakes import StubChatProvider, StubEmbedder

pytestmark = pytest.mark.django_db


def _upload_and_index(client, name: str, text: str, scope: str = "company", department_id=None):
    up = SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/plain")
    data = {"file": up, "access_scope": scope}
    if department_id is not None:
        data["department_id"] = department_id
    resp = client.post("/api/documents/upload", data, format="multipart")
    assert resp.status_code == 201, resp.content
    doc_id = resp.json()["id"]
    doc = Document.objects.get(pk=doc_id)
    # Ensure chunk exists deterministically even if async indexing hasn't run.
    if not Chunk.objects.filter(document=doc).exists():
        Chunk.objects.create(document=doc, company=doc.company, ord=0, text=text)
        doc.num_chunks = 1
        doc.indexing_status = "ready"
        doc.save(update_fields=["num_chunks", "indexing_status"])
    return doc


def _jwt_cookie_header(user) -> list[tuple[bytes, bytes]]:
    token = str(AccessToken.for_user(user))
    return [
        (b"cookie", f"openvault_access={token}".encode("latin-1")),
        (b"origin", b"http://localhost:3000"),
    ]


class WebsocketCommunicator(ApplicationCommunicator):
    """Lightweight ASGI WebSocket test client using asgiref directly."""

    def __init__(self, app, path: str, headers=None):
        parsed = urlparse(path)
        self.scope = {
            "type": "websocket",
            "path": unquote(parsed.path),
            "query_string": parsed.query.encode("utf-8"),
            "headers": headers or [],
            "subprotocols": [],
        }
        super().__init__(app, self.scope)

    async def connect(self, timeout=2):
        await self.send_input({"type": "websocket.connect"})
        resp = await self.receive_output(timeout)
        if resp["type"] == "websocket.close":
            return (False, resp.get("code", 1000))
        assert resp["type"] == "websocket.accept"
        return (True, resp.get("subprotocol"))

    async def send_json_to(self, data):
        await self.send_input({"type": "websocket.receive", "text": json.dumps(data)})

    async def receive_json_from(self, timeout=2):
        resp = await self.receive_output(timeout)
        assert resp["type"] == "websocket.send", resp
        return json.loads(resp["text"])

    async def receive_nothing(self, timeout=0.1):
        if self.future.done():
            self.future.result()
        await asyncio.sleep(timeout)
        return self.output_queue.empty()

    async def disconnect(self, code=1000, timeout=1):
        await self.send_input({"type": "websocket.disconnect", "code": code})
        await self.wait(timeout)


# ----------------------------------------------------------------- room model & isolation

def test_default_room_auto_created_and_cannot_be_deleted(auth_client, make_company, make_user):
    co = make_company("Alpha Co")
    emp = make_user(co, email="emp@alpha.test", role="employee")
    admin = make_user(co, email="admin@alpha.test", role="admin")

    emp_client = auth_client(emp)
    res = emp_client.get("/api/team-chat/rooms")
    assert res.status_code == 200
    body = res.json()
    assert len(body["rooms"]) == 1
    default_room = body["rooms"][0]
    assert default_room["slug"] == "general"
    assert default_room["is_default"] is True
    assert default_room["scope"] == "company"
    assert default_room["member_count"] == 2

    # Idempotent: calling again never creates duplicate General rooms.
    res2 = auth_client(admin).get("/api/team-chat/rooms")
    assert res2.status_code == 200
    assert len(res2.json()["rooms"]) == 1

    # Employees cannot create or delete rooms; admins cannot delete the default room.
    assert emp_client.post("/api/team-chat/rooms", {"name": "Side Room"}, format="json").status_code == 403
    assert emp_client.delete(f"/api/team-chat/rooms/{default_room['id']}").status_code == 403
    del_default = auth_client(admin).delete(f"/api/team-chat/rooms/{default_room['id']}")
    assert del_default.status_code == 400


def test_extra_rooms_scopes_and_cross_tenant_isolation(auth_client, make_company, make_user):
    co_a = make_company("Alpha Corp")
    co_b = make_company("Beta Corp")
    hr = Department.objects.create(company=co_a, name="HR")
    eng = Department.objects.create(company=co_a, name="Engineering")

    admin_a = make_user(co_a, email="admin@a.test", role="admin")
    hr_emp = make_user(co_a, email="hr@a.test", role="employee", department=hr)
    eng_emp = make_user(co_a, email="eng@a.test", role="employee", department=eng)
    admin_b = make_user(co_b, email="admin@b.test", role="admin")

    c_admin_a = auth_client(admin_a)
    c_hr = auth_client(hr_emp)
    c_eng = auth_client(eng_emp)
    c_admin_b = auth_client(admin_b)

    # Admin creates a department room (HR only) and a private room (Admin + Eng only).
    hr_room_res = c_admin_a.post(
        "/api/team-chat/rooms",
        {"name": "HR Lounge", "scope": "department", "department_id": hr.id},
        format="json",
    )
    assert hr_room_res.status_code == 201
    hr_room_id = hr_room_res.json()["id"]

    priv_room_res = c_admin_a.post(
        "/api/team-chat/rooms",
        {"name": "Secret Launch", "scope": "private", "member_ids": [eng_emp.id]},
        format="json",
    )
    assert priv_room_res.status_code == 201
    priv_room_id = priv_room_res.json()["id"]

    # HR sees General + HR Lounge (not Secret Launch).
    hr_rooms = {r["id"] for r in c_hr.get("/api/team-chat/rooms").json()["rooms"]}
    assert hr_room_id in hr_rooms
    assert priv_room_id not in hr_rooms
    assert c_hr.get(f"/api/team-chat/rooms/{priv_room_id}/messages").status_code == 403
    assert c_hr.post(f"/api/team-chat/rooms/{priv_room_id}/messages", {"content": "peek"}, format="json").status_code == 403

    # Eng sees General + Secret Launch (not HR Lounge).
    eng_rooms = {r["id"] for r in c_eng.get("/api/team-chat/rooms").json()["rooms"]}
    assert priv_room_id in eng_rooms
    assert hr_room_id not in eng_rooms
    assert c_eng.get(f"/api/team-chat/rooms/{hr_room_id}/messages").status_code == 403

    # Tenant B admin cannot access or delete any room in Company A.
    assert c_admin_b.get(f"/api/team-chat/rooms/{hr_room_id}/messages").status_code == 404
    assert c_admin_b.delete(f"/api/team-chat/rooms/{hr_room_id}").status_code == 404

    # Admin A can rename and delete the extra room cleanly.
    upd = c_admin_a.patch(f"/api/team-chat/rooms/{priv_room_id}", {"name": "Launch Room"}, format="json")
    assert upd.status_code == 200
    assert upd.json()["name"] == "Launch Room"
    assert c_admin_a.delete(f"/api/team-chat/rooms/{priv_room_id}").status_code == 200
    assert not TeamRoom.objects.filter(pk=priv_room_id).exists()


# ----------------------------------------------------------------- RBAC: edit, delete, pin, react

def test_rbac_edit_time_limit_delete_and_pin_rules(auth_client, make_company, make_user, settings):
    settings.TEAM_CHAT_EDIT_WINDOW_SECONDS = 300  # 5 minutes

    co = make_company("Gamma Co")
    admin = make_user(co, email="admin@gamma.test", role="admin")
    alice = make_user(co, email="alice@gamma.test", role="employee", full_name="Alice")
    bob = make_user(co, email="bob@gamma.test", role="employee", full_name="Bob")
    viewer = make_user(co, email="viewer@gamma.test", role="viewer", full_name="Viewer")

    c_admin = auth_client(admin)
    c_alice = auth_client(alice)
    c_bob = auth_client(bob)
    c_viewer = auth_client(viewer)

    room_id = c_alice.get("/api/team-chat/rooms").json()["rooms"][0]["id"]

    # Viewer can read history, CANNOT post, edit, delete, pin, or react.
    assert c_viewer.get(f"/api/team-chat/rooms/{room_id}/messages").status_code == 200
    assert c_viewer.post(f"/api/team-chat/rooms/{room_id}/messages", {"content": "hi"}, format="json").status_code == 403

    # Alice posts two messages; Bob replies to #1.
    m1 = c_alice.post(f"/api/team-chat/rooms/{room_id}/messages", {"content": "Hello team!"}, format="json").json()["message"]
    m2 = c_alice.post(f"/api/team-chat/rooms/{room_id}/messages", {"content": "Temp note"}, format="json").json()["message"]
    m_bob = c_bob.post(
        f"/api/team-chat/rooms/{room_id}/messages",
        {"content": "Hey Alice!", "reply_to_id": m1["id"]},
        format="json",
    ).json()["message"]
    assert m_bob["reply_to"]["sender_name"] == "Alice"

    assert c_viewer.post(f"/api/team-chat/messages/{m1['id']}/pin", {}, format="json").status_code == 403
    assert c_viewer.post(f"/api/team-chat/messages/{m1['id']}/react", {"emoji": "👍"}, format="json").status_code == 403
    assert c_viewer.patch(f"/api/team-chat/messages/{m1['id']}", {"content": "hack"}, format="json").status_code == 403
    assert c_viewer.delete(f"/api/team-chat/messages/{m1['id']}").status_code == 403

    # ANY participant can pin own OR another person's message.
    pin_by_bob = c_bob.post(f"/api/team-chat/messages/{m1['id']}/pin", {}, format="json")
    assert pin_by_bob.status_code == 200
    assert pin_by_bob.json()["message"]["is_pinned"] is True
    assert pin_by_bob.json()["message"]["pinned_by_name"] == "Bob"

    pin_own_bob = c_bob.post(f"/api/team-chat/messages/{m_bob['id']}/pin", {}, format="json")
    assert pin_own_bob.status_code == 200 and pin_own_bob.json()["message"]["is_pinned"] is True

    # Alice can unpin Bob's message too.
    unpin_by_alice = c_alice.post(f"/api/team-chat/messages/{m_bob['id']}/pin", {"pinned": False}, format="json")
    assert unpin_by_alice.status_code == 200 and unpin_by_alice.json()["message"]["is_pinned"] is False

    # Reactions work & toggle off cleanly.
    r1 = c_bob.post(f"/api/team-chat/messages/{m1['id']}/react", {"emoji": "👍"}, format="json")
    assert r1.status_code == 200
    assert r1.json()["message"]["reactions"] == [{"emoji": "👍", "count": 1, "user_ids": [bob.id]}]
    r2 = c_bob.post(f"/api/team-chat/messages/{m1['id']}/react", {"emoji": "👍"}, format="json")
    assert r2.json()["message"]["reactions"] == []
    assert c_bob.post(f"/api/team-chat/messages/{m1['id']}/react", {"emoji": "INVALID"}, format="json").status_code == 400

    # Alice edits her OWN message within window -> marked (edited).
    ed = c_alice.patch(f"/api/team-chat/messages/{m1['id']}", {"content": "Hello awesome team!"}, format="json")
    assert ed.status_code == 200
    assert ed.json()["message"]["is_edited"] is True
    assert ed.json()["message"]["edited_at"] is not None
    assert ed.json()["message"]["content"] == "Hello awesome team!"

    # Admin CANNOT edit Alice's or Bob's message ("admin can only del").
    assert c_admin.patch(f"/api/team-chat/messages/{m1['id']}", {"content": "Rewritten by admin"}, format="json").status_code == 403
    assert c_bob.patch(f"/api/team-chat/messages/{m1['id']}", {"content": "Rewritten by bob"}, format="json").status_code == 403

    # Edit time limit enforced: expire Alice's edit window on m2.
    TeamMessage.objects.filter(pk=m2["id"]).update(created_at=timezone.now() - timedelta(minutes=10))
    expired = c_alice.patch(f"/api/team-chat/messages/{m2['id']}", {"content": "Too late edit"}, format="json")
    assert expired.status_code == 403
    assert "expired" in expired.json()["detail"].lower()

    # Alice CANNOT delete Bob's message; Alice CAN delete her OWN message.
    assert c_alice.delete(f"/api/team-chat/messages/{m_bob['id']}").status_code == 403
    assert c_alice.delete(f"/api/team-chat/messages/{m2['id']}").status_code == 200
    assert not TeamMessage.objects.filter(pk=m2["id"]).exists()

    # Admin CAN delete Alice's message (true deletion, NOT hidden), including pinned m1,
    # and Bob's reply survives cleanly with reply_to=None.
    del_by_admin = c_admin.delete(f"/api/team-chat/messages/{m1['id']}")
    assert del_by_admin.status_code == 200
    assert not TeamMessage.objects.filter(pk=m1["id"]).exists()

    feed = c_bob.get(f"/api/team-chat/rooms/{room_id}/messages").json()
    ids_in_feed = [m["id"] for m in feed["results"]]
    assert m1["id"] not in ids_in_feed
    assert m_bob["id"] in ids_in_feed
    bob_row = next(m for m in feed["results"] if m["id"] == m_bob["id"])
    assert bob_row["reply_to"] is None
    assert feed["pinned"] == []

    # Verify AuditLog captured both edit and permanent delete.
    assert AuditLog.objects.filter(company=co, action="team_chat_edit").exists()
    assert AuditLog.objects.filter(company=co, action="team_chat_delete").count() == 2


# ----------------------------------------------------------------- @DeskWise AI + ACL security

def test_deskwise_mention_in_team_chat_never_leaks_restricted_docs(
    auth_client, make_company, make_user, settings,
):
    settings.CELERY_TASK_ALWAYS_EAGER = True

    dept_plan = Plan.objects.create(
        name="DeptPlus", price_usd=49, allow_departments=True, max_documents=100, storage_mb=512
    )
    co = make_company("Delta Co", plan=dept_plan)
    hr = Department.objects.create(company=co, name="HR")
    admin = make_user(co, email="admin@delta.test", role="admin", full_name="Admin")
    emp = make_user(co, email="emp@delta.test", role="employee", full_name="Emp")

    c_admin = auth_client(admin)
    c_emp = auth_client(emp)

    # Company-wide doc vs restricted secret doc vs HR-only doc.
    pub_doc = _upload_and_index(c_admin, "wfh_policy.txt", "WFH policy allows 2 days remote per week.", scope="company")
    secret_doc = _upload_and_index(c_admin, "ceo_salaries.txt", "CONFIDENTIAL_SALARY_TOKEN_9999 CEO bonus.", scope="restricted")
    hr_doc = _upload_and_index(c_admin, "hr_notes.txt", "HR_INTERNAL_TOKEN_7777 onboarding checklist.", scope="department", department_id=hr.id)

    general_id = c_admin.get("/api/team-chat/rooms").json()["rooms"][0]["id"]
    hr_room_id = c_admin.post(
        "/api/team-chat/rooms",
        {"name": "HR Desk", "scope": "department", "department_id": hr.id},
        format="json",
    ).json()["id"]

    captured = []
    stub_chat = StubChatProvider(capture=captured)
    stub_emb = StubEmbedder()

    with patch("core.providers.get_chat_provider", return_value=stub_chat), \
         patch("core.providers.get_embed_provider", return_value=stub_emb):
        # Even though ADMIN sends @DeskWise in General, only company-wide docs enter context!
        res = c_admin.post(
            f"/api/team-chat/rooms/{general_id}/messages",
            {"content": "@DeskWise what is WFH policy CEO bonus and HR checklist?"},
            format="json",
        )
        assert res.status_code == 201
        assert res.json()["deskwise_triggered"] is True

    assert len(captured) == 1
    assert "WFH policy allows 2 days remote" in captured[0]
    assert "CONFIDENTIAL_SALARY_TOKEN_9999" not in captured[0]
    assert "HR_INTERNAL_TOKEN_7777" not in captured[0]

    feed = c_emp.get(f"/api/team-chat/rooms/{general_id}/messages").json()
    bot_msgs = [m for m in feed["results"] if m["sender_type"] == "deskwise"]
    assert len(bot_msgs) == 1
    assert "ANSWER-OK" in bot_msgs[0]["content"]
    assert bot_msgs[0]["reply_to_id"] == res.json()["message"]["id"]
    assert [s["filename"] for s in bot_msgs[0]["sources"]] == [pub_doc.filename]
    assert secret_doc.filename not in [s["filename"] for s in bot_msgs[0]["sources"]]

    # Admin CANNOT edit @DeskWise bot message, CAN delete it.
    assert c_admin.patch(f"/api/team-chat/messages/{bot_msgs[0]['id']}", {"content": "edited bot"}, format="json").status_code == 403
    assert c_emp.delete(f"/api/team-chat/messages/{bot_msgs[0]['id']}").status_code == 403
    assert c_admin.delete(f"/api/team-chat/messages/{bot_msgs[0]['id']}").status_code == 200

    # Inside the HR department room, @DeskWise CAN cite HR doc + company doc, still NEVER restricted doc.
    captured2 = []
    with patch("core.providers.get_chat_provider", return_value=StubChatProvider(capture=captured2)), \
         patch("core.providers.get_embed_provider", return_value=stub_emb):
        r_hr = c_admin.post(
            f"/api/team-chat/rooms/{hr_room_id}/messages",
            {"content": "@DeskWise what is the HR_INTERNAL_TOKEN_7777 checklist?"},
            format="json",
        )
        assert r_hr.status_code == 201

    assert len(captured2) == 1
    assert "HR_INTERNAL_TOKEN_7777" in captured2[0]
    assert "CONFIDENTIAL_SALARY_TOKEN_9999" not in captured2[0]
    assert hr_doc.filename in [
        s["filename"]
        for m in c_admin.get(f"/api/team-chat/rooms/{hr_room_id}/messages").json()["results"]
        if m["sender_type"] == "deskwise"
        for s in m["sources"]
    ]


def test_moderation_flag_document_reference_acl_and_search(auth_client, make_company, make_user):
    co = make_company("Moderation Co")
    other = make_company("Other Co")
    admin = make_user(co, email="a@mod.test", role="admin")
    emp = make_user(co, email="e@mod.test", role="employee")
    other_admin = make_user(other, email="x@other.test", role="admin")

    c_admin = auth_client(admin)
    c_emp = auth_client(emp)
    c_other = auth_client(other_admin)

    pub = _upload_and_index(c_admin, "handbook.txt", "Welcome handbook", scope="company")
    restricted = _upload_and_index(c_admin, "payroll.txt", "Private payroll", scope="restricted")
    other_doc = _upload_and_index(c_other, "other.txt", "Other tenant", scope="company")

    room_id = c_emp.get("/api/team-chat/rooms").json()["rooms"][0]["id"]

    # Employee cannot attach another user's restricted doc or another company's doc.
    assert c_emp.post(
        f"/api/team-chat/rooms/{room_id}/messages",
        {"content": "look", "referenced_document_id": restricted.id},
        format="json",
    ).status_code == 400
    assert c_emp.post(
        f"/api/team-chat/rooms/{room_id}/messages",
        {"content": "look", "referenced_document_id": other_doc.id},
        format="json",
    ).status_code == 400

    # Valid attachment succeeds + moderation catches exposed secret keyword.
    ok_res = c_emp.post(
        f"/api/team-chat/rooms/{room_id}/messages",
        {"content": "Check this api_key setup in handbook", "referenced_document_id": pub.id},
        format="json",
    )
    assert ok_res.status_code == 201
    msg = ok_res.json()["message"]
    assert msg["referenced_document"]["id"] == pub.id
    assert msg["flag"] is not None
    assert AuditLog.objects.filter(company=co, action="POLICY_VIOLATION_DETECTED").exists()

    # Search filters accurately.
    c_emp.post(f"/api/team-chat/rooms/{room_id}/messages", {"content": "Lunch at noon"}, format="json")
    found = c_emp.get(f"/api/team-chat/rooms/{room_id}/messages?q=handbook").json()
    assert len(found["results"]) == 1
    assert found["results"][0]["id"] == msg["id"]


# ----------------------------------------------------------------- WebSocket end-to-end tests

@pytest.mark.django_db(transaction=True)
def test_websocket_auth_realtime_edit_pin_delete_deskwise_and_isolation(
    make_company, make_user, settings,
):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.TEAM_CHAT_EDIT_WINDOW_SECONDS = 300
    settings.RATELIMIT_ENABLED = False

    co_a = make_company("WS Alpha")
    co_b = make_company("WS Beta")
    admin_a = make_user(co_a, email="ws-admin@a.test", role="admin", full_name="Alice Admin")
    emp_a = make_user(co_a, email="ws-emp@a.test", role="employee", full_name="Bob Emp")
    eve_b = make_user(co_b, email="ws-eve@b.test", role="admin", full_name="Eve Beta")

    room_a = TeamRoom.ensure_default(co_a)
    TeamRoom.ensure_default(co_b)

    doc = Document.objects.create(
        company=co_a, filename="leave_rules.txt", stored_path="x",
        access_scope="company", uploaded_by=admin_a, num_chunks=1, indexing_status="ready",
    )
    Chunk.objects.create(document=doc, company=co_a, ord=0, text="Employees get 20 annual leave days.")

    async def scenario():
        # 1. Unauthenticated connection is rejected.
        unauth = WebsocketCommunicator(application, "/ws/team-chat/")
        connected, _ = await unauth.connect()
        assert connected is False

        # 2. Untrusted browser Origin is rejected when DEBUG=False.
        old_debug = settings.DEBUG
        settings.DEBUG = False
        try:
            evil_origin = WebsocketCommunicator(
                application,
                "/ws/team-chat/",
                headers=[(b"origin", b"https://evil.attacker.test"), *_jwt_cookie_header(emp_a)[0:1]],
            )
            ok_origin, _ = await evil_origin.connect()
            assert ok_origin is False
        finally:
            settings.DEBUG = old_debug

        # 3. Connect Alice (Admin A), Bob (Emp A), Eve (Admin B).
        ws_alice = WebsocketCommunicator(application, "/ws/team-chat/", headers=_jwt_cookie_header(admin_a))
        ws_bob = WebsocketCommunicator(application, "/ws/team-chat/", headers=_jwt_cookie_header(emp_a))
        ws_eve = WebsocketCommunicator(application, "/ws/team-chat/", headers=_jwt_cookie_header(eve_b))

        assert (await ws_alice.connect())[0] is True
        hello_alice = await ws_alice.receive_json_from()
        assert hello_alice["type"] == "hello"
        assert hello_alice["user_id"] == admin_a.id
        # Drain alice's initial presence broadcast.
        p1 = await ws_alice.receive_json_from()
        assert p1["type"] == "presence.update"

        assert (await ws_bob.connect())[0] is True
        hello_bob = await ws_bob.receive_json_from()
        assert hello_bob["type"] == "hello"
        p_bob = await ws_bob.receive_json_from()
        assert set(p_bob["online_user_ids"]) == {admin_a.id, emp_a.id}
        p_alice2 = await ws_alice.receive_json_from()
        assert set(p_alice2["online_user_ids"]) == {admin_a.id, emp_a.id}

        assert (await ws_eve.connect())[0] is True
        assert (await ws_eve.receive_json_from())["type"] == "hello"
        assert (await ws_eve.receive_json_from())["type"] == "presence.update"

        # 4. Eve cannot subscribe to Company A's room.
        await ws_eve.send_json_to({"action": "room.subscribe", "room_id": room_a.id})
        eve_err = await ws_eve.receive_json_from()
        assert eve_err["type"] == "error"

        # 5. Bob sends a message over WebSocket -> Alice receives live, Eve gets nothing.
        await ws_bob.send_json_to({
            "action": "message.send",
            "room_id": room_a.id,
            "content": "Initial message from Bob",
            "client_nonce": "n1",
        })
        created_bob = await ws_bob.receive_json_from()
        created_alice = await ws_alice.receive_json_from()
        assert created_bob["type"] == "message.created"
        assert created_alice["type"] == "message.created"
        assert created_bob["message"]["client_nonce"] == "n1"
        msg_id = created_bob["message"]["id"]
        assert await ws_eve.receive_nothing(timeout=0.1) is True

        # 6. Alice pins Bob's message over WebSocket -> both receive message.pinned.
        await ws_alice.send_json_to({"action": "message.pin", "message_id": msg_id})
        assert (await ws_alice.receive_json_from())["type"] == "message.pinned"
        pin_bob = await ws_bob.receive_json_from()
        assert pin_bob["type"] == "message.pinned" and pin_bob["message"]["is_pinned"] is True

        # 7. Admin Alice tries to edit Bob's message -> blocked by RBAC ("admin can only del").
        await ws_alice.send_json_to({"action": "message.edit", "message_id": msg_id, "content": "Hacked"})
        edit_err = await ws_alice.receive_json_from()
        assert edit_err["type"] == "error"

        # 8. Bob edits own message -> both receive message.updated with is_edited=True.
        await ws_bob.send_json_to({"action": "message.edit", "message_id": msg_id, "content": "Updated by Bob"})
        upd_bob = await ws_bob.receive_json_from()
        upd_alice = await ws_alice.receive_json_from()
        assert upd_bob["type"] == "message.updated"
        assert upd_bob["message"]["is_edited"] is True
        assert upd_bob["message"]["content"] == "Updated by Bob"
        assert upd_alice["message"]["content"] == "Updated by Bob"

        # 9. Bob triggers @DeskWise over WebSocket -> both receive live AI stream & saved bot message.
        with patch("core.providers.get_chat_provider", return_value=StubChatProvider()), \
             patch("core.providers.get_embed_provider", return_value=StubEmbedder()):
            await ws_bob.send_json_to({
                "action": "message.send",
                "room_id": room_a.id,
                "content": "@DeskWise how many annual leave days?",
            })
            seen_bob = []
            for _ in range(5):
                ev = await ws_bob.receive_json_from(timeout=3)
                seen_bob.append(ev)
                if ev["type"] == "message.created" and ev["message"]["sender_type"] == "deskwise":
                    break
            seen_alice = []
            for _ in range(5):
                ev = await ws_alice.receive_json_from(timeout=3)
                seen_alice.append(ev)
                if ev["type"] == "message.created" and ev["message"]["sender_type"] == "deskwise":
                    break

        assert any(e["type"] == "message.created" and e["message"]["sender_type"] == "deskwise" for e in seen_bob)
        bot_ev = next(e for e in seen_alice if e["type"] == "message.created" and e["message"]["sender_type"] == "deskwise")
        assert "ANSWER-OK" in bot_ev["message"]["content"]
        assert bot_ev["message"]["sources"][0]["filename"] == "leave_rules.txt"

        # 10. Admin deletes Bob's message -> both receive message.deleted, row is gone from DB.
        await ws_alice.send_json_to({"action": "message.delete", "message_id": msg_id})
        del_alice = await ws_alice.receive_json_from()
        del_bob = await ws_bob.receive_json_from()
        assert del_alice["type"] == "message.deleted" and del_alice["message_id"] == msg_id
        assert del_bob["type"] == "message.deleted" and del_bob["message_id"] == msg_id

        # 11. Disconnect updates presence cleanly.
        await ws_bob.disconnect()
        p_after = await ws_alice.receive_json_from()
        assert p_after["type"] == "presence.update"
        assert p_after["online_user_ids"] == [admin_a.id]

        await ws_alice.disconnect()
        await ws_eve.disconnect()

    try:
        asyncio.run(scenario())
    finally:
        team_chat.register_active_loop(None)

    assert not TeamMessage.objects.filter(content="Updated by Bob").exists()


@pytest.mark.django_db(transaction=True)
def test_websocket_validation_reactions_read_and_room_broadcasts(
    auth_client, make_company, make_user, settings,
):
    settings.TEAM_CHAT_EDIT_WINDOW_SECONDS = 300
    co = make_company("Epsilon Co")
    admin = make_user(co, email="admin@eps.test", role="admin", full_name="Admin Eps")
    emp = make_user(co, email="emp@eps.test", role="employee", full_name="Emp Eps")
    viewer = make_user(co, email="view@eps.test", role="viewer", full_name="View Eps")
    room = TeamRoom.ensure_default(co)

    admin_client = auth_client(admin)
    emp_client = auth_client(emp)

    async def scenario():
        ws_admin = WebsocketCommunicator(application, "/ws/team-chat/", headers=_jwt_cookie_header(admin))
        ws_emp = WebsocketCommunicator(application, "/ws/team-chat/", headers=_jwt_cookie_header(emp))
        ws_view = WebsocketCommunicator(application, "/ws/team-chat/", headers=_jwt_cookie_header(viewer))

        assert (await ws_admin.connect())[0] is True
        assert (await ws_admin.receive_json_from())["type"] == "hello"
        assert (await ws_admin.receive_json_from())["type"] == "presence.update"

        assert (await ws_emp.connect())[0] is True
        assert (await ws_emp.receive_json_from())["type"] == "hello"
        assert (await ws_emp.receive_json_from())["type"] == "presence.update"
        assert (await ws_admin.receive_json_from())["type"] == "presence.update"

        assert (await ws_view.connect())[0] is True
        assert (await ws_view.receive_json_from())["type"] == "hello"
        assert (await ws_view.receive_json_from())["type"] == "presence.update"
        assert (await ws_admin.receive_json_from())["type"] == "presence.update"
        assert (await ws_emp.receive_json_from())["type"] == "presence.update"

        # 1. Ping & unknown action.
        await ws_admin.send_json_to({"action": "ping"})
        assert (await ws_admin.receive_json_from())["type"] == "pong"

        await ws_admin.send_json_to({"action": "bogus.action"})
        err_unknown = await ws_admin.receive_json_from()
        assert err_unknown["type"] == "error" and err_unknown["action"] == "bogus.action"

        # 2. Empty and oversized (>4000 chars) messages rejected over WS.
        await ws_emp.send_json_to({"action": "message.send", "room_id": room.id, "content": "   ", "client_nonce": "e1"})
        err_empty = await ws_emp.receive_json_from()
        assert err_empty["type"] == "error" and err_empty["client_nonce"] == "e1"

        await ws_emp.send_json_to({"action": "message.send", "room_id": room.id, "content": "x" * 4001, "client_nonce": "o1"})
        err_big = await ws_emp.receive_json_from()
        assert err_big["type"] == "error" and err_big["client_nonce"] == "o1"

        # 3. Viewer cannot post or broadcast typing.
        await ws_view.send_json_to({"action": "message.send", "room_id": room.id, "content": "Viewer msg"})
        assert (await ws_view.receive_json_from())["type"] == "error"

        await ws_view.send_json_to({"action": "typing", "room_id": room.id, "is_typing": True})
        assert await ws_admin.receive_nothing(timeout=0.08) is True
        assert await ws_emp.receive_nothing(timeout=0.08) is True

        # 4. Employee typing indicator reaches connected members.
        await ws_emp.send_json_to({"action": "typing", "room_id": room.id, "is_typing": True})
        t_admin = await ws_admin.receive_json_from()
        assert t_admin["type"] == "typing" and t_admin["user_id"] == emp.id and t_admin["is_typing"] is True
        assert (await ws_emp.receive_json_from())["type"] == "typing"
        assert (await ws_view.receive_json_from())["type"] == "typing"

        # 5. Admin posts -> employee unread increments -> WS room.read clears unread -> count returns to 0.
        await ws_admin.send_json_to({"action": "message.send", "room_id": room.id, "content": "Quarterly townhall at 4pm"})
        m_admin = await ws_admin.receive_json_from()
        m_emp = await ws_emp.receive_json_from()
        m_view = await ws_view.receive_json_from()
        assert m_admin["type"] == "message.created" and m_emp["type"] == "message.created" and m_view["type"] == "message.created"
        msg_id = m_admin["message"]["id"]

        rooms_before = await sync_to_async(lambda: emp_client.get("/api/team-chat/rooms").json()["rooms"])()
        assert next(r for r in rooms_before if r["id"] == room.id)["unread_count"] == 1

        await ws_emp.send_json_to({"action": "room.read", "room_id": room.id, "last_message_id": msg_id})
        ack = await ws_emp.receive_json_from()
        assert ack["type"] == "room.read_ack" and ack["last_read_message_id"] == msg_id

        rooms_after = await sync_to_async(lambda: emp_client.get("/api/team-chat/rooms").json()["rooms"])()
        assert next(r for r in rooms_after if r["id"] == room.id)["unread_count"] == 0

        # 6. Reaction toggle + invalid emoji rejection over WS.
        await ws_emp.send_json_to({"action": "reaction.toggle", "message_id": msg_id, "emoji": "🛸"})
        assert (await ws_emp.receive_json_from())["type"] == "error"

        await ws_emp.send_json_to({"action": "reaction.toggle", "message_id": msg_id, "emoji": "👍"})
        r_admin = await ws_admin.receive_json_from()
        r_emp = await ws_emp.receive_json_from()
        r_view = await ws_view.receive_json_from()
        assert r_admin["type"] == "reaction.updated"
        assert r_emp["message"]["reactions"] == [{"emoji": "👍", "count": 1, "user_ids": [emp.id]}]
        assert r_view["type"] == "reaction.updated"

        # 7. Expired edit window enforced over WS.
        await sync_to_async(
            lambda: TeamMessage.objects.filter(pk=msg_id).update(
                created_at=timezone.now() - timedelta(seconds=600)
            )
        )()
        await ws_admin.send_json_to({"action": "message.edit", "message_id": msg_id, "content": "Late edit"})
        edit_exp_err = await ws_admin.receive_json_from()
        assert edit_exp_err["type"] == "error"

        # 8. REST room create / patch / delete broadcasts to connected WebSocket clients.
        created_resp = await sync_to_async(
            lambda: admin_client.post("/api/team-chat/rooms", {"name": "Engineering", "scope": "company"}, format="json")
        )()
        assert created_resp.status_code == 201
        extra_id = created_resp.json()["id"]
        rc_emp = await ws_emp.receive_json_from()
        rc_admin = await ws_admin.receive_json_from()
        rc_view = await ws_view.receive_json_from()
        assert rc_emp["type"] == "room.created" and rc_emp["room"]["id"] == extra_id
        assert rc_admin["type"] == "room.created" and rc_view["type"] == "room.created"

        patched_resp = await sync_to_async(
            lambda: admin_client.patch(f"/api/team-chat/rooms/{extra_id}", {"name": "Platform Eng"}, format="json")
        )()
        assert patched_resp.status_code == 200
        ru_emp = await ws_emp.receive_json_from()
        ru_admin = await ws_admin.receive_json_from()
        ru_view = await ws_view.receive_json_from()
        assert ru_emp["type"] == "room.updated" and ru_emp["room"]["name"] == "Platform Eng"
        assert ru_admin["type"] == "room.updated" and ru_view["type"] == "room.updated"

        deleted_resp = await sync_to_async(
            lambda: admin_client.delete(f"/api/team-chat/rooms/{extra_id}")
        )()
        assert deleted_resp.status_code == 200
        rd_emp = await ws_emp.receive_json_from()
        rd_admin = await ws_admin.receive_json_from()
        rd_view = await ws_view.receive_json_from()
        assert rd_emp["type"] == "room.deleted" and rd_emp["room_id"] == extra_id
        assert rd_admin["type"] == "room.deleted" and rd_view["type"] == "room.deleted"

        await ws_view.disconnect()
        await ws_emp.disconnect()
        await ws_admin.disconnect()

    try:
        asyncio.run(scenario())
    finally:
        team_chat.register_active_loop(None)
