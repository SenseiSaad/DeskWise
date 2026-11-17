"""Django Channels WebSocket auth middleware and Team Chatroom consumer."""
from __future__ import annotations

import asyncio
import logging
import time
from http.cookies import SimpleCookie
from urllib.parse import urlparse

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.urls import re_path
from rest_framework.exceptions import APIException

from .auth import ACCESS_COOKIE
from .models import TeamMessage, TeamRoom, User
from .team_chat import (
    accessible_rooms_for,
    company_group_name,
    create_user_message,
    delete_team_message,
    edit_user_message,
    edit_window_seconds,
    has_company_context,
    mark_room_read,
    pin_team_message,
    register_active_loop,
    room_group_name,
    spawn_deskwise_reply,
    toggle_reaction,
    user_can_access_room,
    user_can_post,
)

logger = logging.getLogger(__name__)

# In-process connection tracking for live online presence (user_id -> active socket count).
_PRESENCE_LOCK = asyncio.Lock()
_COMPANY_PRESENCE: dict[int, dict[int, int]] = {}


def _extract_error_message(exc: APIException) -> str:
    detail = getattr(exc, "detail", str(exc))
    if isinstance(detail, dict):
        first = next(iter(detail.values()), detail)
        if isinstance(first, list) and first:
            return str(first[0])
        return str(first)
    if isinstance(detail, list) and detail:
        return str(detail[0])
    return str(detail)


def _trusted_ws_origins(scope) -> set[str]:
    origins = set()
    for src in (
        getattr(settings, "CORS_ALLOWED_ORIGINS", []),
        getattr(settings, "CSRF_TRUSTED_ORIGINS", []),
    ):
        for entry in src or []:
            origins.add(entry.rstrip("/").lower())
    public = getattr(settings, "PUBLIC_BASE_URL", "")
    if public:
        origins.add(public.rstrip("/").lower())
    headers = dict(scope.get("headers") or [])
    host = headers.get(b"host", b"").decode("latin-1").strip()
    if host:
        origins.add(f"http://{host}".lower())
        origins.add(f"https://{host}".lower())
    return origins


def _origin_allowed(scope) -> bool:
    if getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False):
        return True
    headers = dict(scope.get("headers") or [])
    raw_origin = headers.get(b"origin", b"").decode("latin-1").strip()
    if not raw_origin:
        return True
    cleaned = raw_origin.rstrip("/").lower()
    if cleaned in _trusted_ws_origins(scope):
        return True
    # Dev convenience: accept localhost <-> 127.0.0.1 with matching allowed hosts/ports.
    parsed = urlparse(cleaned)
    if parsed.hostname in ("localhost", "127.0.0.1") and settings.DEBUG:
        return True
    return False


@database_sync_to_async
def _authenticate_scope(scope):
    from rest_framework_simplejwt.tokens import AccessToken

    headers = dict(scope.get("headers") or [])
    raw_token = None

    raw_cookie = headers.get(b"cookie", b"").decode("latin-1")
    if raw_cookie:
        cookie = SimpleCookie()
        try:
            cookie.load(raw_cookie)
            if ACCESS_COOKIE in cookie:
                raw_token = cookie[ACCESS_COOKIE].value
        except Exception:
            raw_token = None

    if not raw_token:
        auth_hdr = headers.get(b"authorization", b"").decode("latin-1").strip()
        if auth_hdr.lower().startswith("bearer "):
            raw_token = auth_hdr[7:].strip()

    if not raw_token:
        return AnonymousUser()

    try:
        validated = AccessToken(raw_token)
        user_id = validated.get("user_id")
        if not user_id:
            return AnonymousUser()
        user = (
            User.objects.select_related("company", "department")
            .filter(pk=user_id, is_active=True)
            .first()
        )
        return user if user is not None else AnonymousUser()
    except Exception:
        return AnonymousUser()


class CookieJWTWebSocketMiddleware:
    """Populate `scope['user']` from the HttpOnly JWT cookie (or Bearer header)."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        scope["user"] = await _authenticate_scope(scope)
        scope["ws_origin_allowed"] = _origin_allowed(scope)
        return await self.inner(scope, receive, send)


class TeamChatConsumer(AsyncJsonWebsocketConsumer):
    """Tenant-isolated real-time WebSocket consumer for employee Team Chat."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user: User | None = None
        self.company_id: int | None = None
        self.joined_rooms: set[int] = set()
        self._msg_timestamps: list[float] = []
        self._presence_registered = False

    def _scope_ip(self) -> str:
        client = self.scope.get("client")
        return str(client[0]) if client else ""

    def _hit_rate_limit(self) -> bool:
        if not getattr(settings, "RATELIMIT_ENABLED", True):
            return False
        now = time.monotonic()
        self._msg_timestamps = [t for t in self._msg_timestamps if now - t < 10.0]
        if len(self._msg_timestamps) >= 20:
            return True
        self._msg_timestamps.append(now)
        return False

    async def _add_presence(self) -> list[int]:
        async with _PRESENCE_LOCK:
            bucket = _COMPANY_PRESENCE.setdefault(self.company_id, {})
            bucket[self.user.id] = bucket.get(self.user.id, 0) + 1
            self._presence_registered = True
            return sorted(bucket.keys())

    async def _remove_presence(self) -> list[int] | None:
        if not self._presence_registered or not self.company_id or not self.user:
            return None
        async with _PRESENCE_LOCK:
            bucket = _COMPANY_PRESENCE.get(self.company_id, {})
            cur = bucket.get(self.user.id, 0)
            if cur <= 1:
                bucket.pop(self.user.id, None)
            else:
                bucket[self.user.id] = cur - 1
            if not bucket:
                _COMPANY_PRESENCE.pop(self.company_id, None)
            self._presence_registered = False
            return sorted(bucket.keys())

    async def connect(self):
        register_active_loop(asyncio.get_running_loop())

        if not self.scope.get("ws_origin_allowed", True):
            await self.close(code=4403)
            return

        user = self.scope.get("user")
        if not has_company_context(user):
            await self.close(code=4401)
            return

        self.user = user
        self.company_id = user.company_id

        rooms = await database_sync_to_async(accessible_rooms_for)(user)
        await self.channel_layer.group_add(company_group_name(self.company_id), self.channel_name)
        for r in rooms:
            await self.channel_layer.group_add(room_group_name(r.id), self.channel_name)
            self.joined_rooms.add(r.id)

        await self.accept()

        online_ids = await self._add_presence()
        await self.send_json({
            "type": "hello",
            "user_id": user.id,
            "company_id": self.company_id,
            "room_ids": sorted(self.joined_rooms),
            "online_user_ids": online_ids,
            "edit_window_seconds": edit_window_seconds(),
        })
        await self.channel_layer.group_send(
            company_group_name(self.company_id),
            {
                "type": "team_chat.event",
                "event": "presence.update",
                "payload": {"online_user_ids": online_ids},
            },
        )

    async def disconnect(self, close_code):
        if self.company_id:
            online_ids = await self._remove_presence()
            if online_ids is not None:
                try:
                    await self.channel_layer.group_send(
                        company_group_name(self.company_id),
                        {
                            "type": "team_chat.event",
                            "event": "presence.update",
                            "payload": {"online_user_ids": online_ids},
                        },
                    )
                except Exception:
                    pass
            try:
                await self.channel_layer.group_discard(company_group_name(self.company_id), self.channel_name)
            except Exception:
                pass
        for rid in list(self.joined_rooms):
            try:
                await self.channel_layer.group_discard(room_group_name(rid), self.channel_name)
            except Exception:
                pass
        self.joined_rooms.clear()

    async def team_chat_event(self, event):
        """Relay group events to the WebSocket client and keep room subscriptions synced."""
        evt_name = event.get("event")
        payload = event.get("payload") or {}

        # Synchronize room group subscriptions when rooms are created/updated/deleted.
        if evt_name in ("room.created", "room.updated"):
            room_data = payload.get("room") or {}
            rid = room_data.get("id")
            if rid and self.user:
                allowed = await self._check_room_access_id(rid)
                if allowed and rid not in self.joined_rooms:
                    await self.channel_layer.group_add(room_group_name(rid), self.channel_name)
                    self.joined_rooms.add(rid)
                elif not allowed and rid in self.joined_rooms:
                    await self.channel_layer.group_discard(room_group_name(rid), self.channel_name)
                    self.joined_rooms.discard(rid)
                    await self.send_json({"type": "room.deleted", "room_id": rid})
                    return
                elif not allowed:
                    return
        elif evt_name == "room.deleted":
            rid = payload.get("room_id")
            if rid in self.joined_rooms:
                await self.channel_layer.group_discard(room_group_name(rid), self.channel_name)
                self.joined_rooms.discard(rid)

        await self.send_json({"type": evt_name, **payload})

    @database_sync_to_async
    def _check_room_access_id(self, room_id: int) -> bool:
        room = TeamRoom.objects.filter(pk=room_id, company_id=self.company_id).first()
        if room is None:
            return False
        # Reload user so department/role updates reflect immediately.
        fresh_user = User.objects.select_related("company", "department").filter(pk=self.user.id, is_active=True).first()
        if fresh_user is None:
            return False
        self.user = fresh_user
        return user_can_access_room(fresh_user, room)

    @database_sync_to_async
    def _load_fresh_user(self) -> User | None:
        fresh = User.objects.select_related("company", "department").filter(pk=self.user.id, is_active=True).first()
        if fresh is not None:
            self.user = fresh
        return fresh

    @database_sync_to_async
    def _do_send_message(self, room_id: int, data: dict) -> tuple[dict, bool, int]:
        user = User.objects.select_related("company", "department").filter(pk=self.user.id, is_active=True).first()
        if user is None:
            raise ValueError("Account inactive.")
        self.user = user
        room = TeamRoom.objects.select_related("company", "department").filter(pk=room_id, company_id=self.company_id).first()
        if room is None:
            raise ValueError("Room not found.")
        msg, payload, trigger_ai = create_user_message(
            user=user,
            room=room,
            content=data.get("content", ""),
            reply_to_id=data.get("reply_to_id"),
            referenced_document_id=data.get("referenced_document_id"),
            client_nonce=data.get("client_nonce"),
            ip=self._scope_ip(),
        )
        return payload, trigger_ai, msg.id

    @database_sync_to_async
    def _do_edit_message(self, message_id: int, content: str) -> tuple[int, dict]:
        user = User.objects.select_related("company", "department").filter(pk=self.user.id, is_active=True).first()
        msg = TeamMessage.objects.select_related("room", "room__company", "company").filter(
            pk=message_id, company_id=self.company_id,
        ).first()
        if msg is None:
            raise ValueError("Message not found.")
        _, payload = edit_user_message(user, msg, content, ip=self._scope_ip())
        return msg.room_id, payload

    @database_sync_to_async
    def _do_delete_message(self, message_id: int) -> tuple[int, int]:
        user = User.objects.select_related("company", "department").filter(pk=self.user.id, is_active=True).first()
        msg = TeamMessage.objects.select_related("room", "sender", "company").filter(
            pk=message_id, company_id=self.company_id,
        ).first()
        if msg is None:
            raise ValueError("Message not found.")
        return delete_team_message(user, msg, ip=self._scope_ip())

    @database_sync_to_async
    def _do_pin_message(self, message_id: int, pinned) -> tuple[int, dict]:
        user = User.objects.select_related("company", "department").filter(pk=self.user.id, is_active=True).first()
        msg = TeamMessage.objects.select_related("room", "company").filter(
            pk=message_id, company_id=self.company_id,
        ).first()
        if msg is None:
            raise ValueError("Message not found.")
        _, payload = pin_team_message(user, msg, pinned=pinned, ip=self._scope_ip())
        return msg.room_id, payload

    @database_sync_to_async
    def _do_react_message(self, message_id: int, emoji: str) -> tuple[int, dict]:
        user = User.objects.select_related("company", "department").filter(pk=self.user.id, is_active=True).first()
        msg = TeamMessage.objects.select_related("room", "company").filter(
            pk=message_id, company_id=self.company_id,
        ).first()
        if msg is None:
            raise ValueError("Message not found.")
        _, payload = toggle_reaction(user, msg, emoji)
        return msg.room_id, payload

    @database_sync_to_async
    def _do_mark_read(self, room_id: int, last_message_id: int | None) -> int:
        user = User.objects.select_related("company", "department").filter(pk=self.user.id, is_active=True).first()
        room = TeamRoom.objects.filter(pk=room_id, company_id=self.company_id).first()
        if room is None:
            raise ValueError("Room not found.")
        return mark_room_read(user, room, last_message_id=last_message_id)

    @database_sync_to_async
    def _can_type_in_room(self, room_id: int) -> bool:
        user = User.objects.select_related("company", "department").filter(pk=self.user.id, is_active=True).first()
        room = TeamRoom.objects.filter(pk=room_id, company_id=self.company_id).first()
        return bool(user and room and user_can_post(user, room))

    async def receive_json(self, content, **kwargs):
        if not isinstance(content, dict):
            await self.send_json({"type": "error", "message": "Invalid JSON object."})
            return

        action = content.get("action") or content.get("type")
        client_nonce = content.get("client_nonce")

        if action == "ping":
            await self.send_json({"type": "pong"})
            return

        if not self.user or not self.company_id:
            await self.close(code=4401)
            return

        try:
            if action == "room.subscribe":
                room_id = int(content.get("room_id") or 0)
                if not await self._check_room_access_id(room_id):
                    await self.send_json({"type": "error", "action": action, "message": "Access denied."})
                    return
                if room_id not in self.joined_rooms:
                    await self.channel_layer.group_add(room_group_name(room_id), self.channel_name)
                    self.joined_rooms.add(room_id)
                await self.send_json({"type": "room.subscribed", "room_id": room_id})
                return

            if action == "typing":
                room_id = int(content.get("room_id") or 0)
                if await self._can_type_in_room(room_id):
                    sender_name = self.user.full_name or self.user.email.split("@")[0]
                    await self.channel_layer.group_send(
                        room_group_name(room_id),
                        {
                            "type": "team_chat.event",
                            "event": "typing",
                            "payload": {
                                "room_id": room_id,
                                "user_id": self.user.id,
                                "user_name": sender_name,
                                "is_typing": bool(content.get("is_typing", True)),
                            },
                        },
                    )
                return

            if action == "room.read":
                room_id = int(content.get("room_id") or 0)
                last_id = content.get("last_message_id")
                saved_id = await self._do_mark_read(room_id, int(last_id) if last_id is not None else None)
                await self.send_json({"type": "room.read_ack", "room_id": room_id, "last_read_message_id": saved_id})
                return

            if action == "message.send":
                if self._hit_rate_limit():
                    await self.send_json({
                        "type": "error", "action": action, "client_nonce": client_nonce,
                        "message": "Slow down a bit before sending more messages.",
                    })
                    return
                room_id = int(content.get("room_id") or 0)
                payload, trigger_ai, msg_id = await self._do_send_message(room_id, content)
                if room_id not in self.joined_rooms:
                    await self.channel_layer.group_add(room_group_name(room_id), self.channel_name)
                    self.joined_rooms.add(room_id)
                await self.channel_layer.group_send(
                    room_group_name(room_id),
                    {
                        "type": "team_chat.event",
                        "event": "message.created",
                        "payload": {"message": payload},
                    },
                )
                if trigger_ai:
                    await database_sync_to_async(spawn_deskwise_reply)(
                        room_id, msg_id, self.user.id,
                    )
                return

            if action == "message.edit":
                message_id = int(content.get("message_id") or 0)
                room_id, payload = await self._do_edit_message(message_id, content.get("content", ""))
                await self.channel_layer.group_send(
                    room_group_name(room_id),
                    {
                        "type": "team_chat.event",
                        "event": "message.updated",
                        "payload": {"message": payload},
                    },
                )
                return

            if action == "message.delete":
                message_id = int(content.get("message_id") or 0)
                room_id, deleted_id = await self._do_delete_message(message_id)
                await self.channel_layer.group_send(
                    room_group_name(room_id),
                    {
                        "type": "team_chat.event",
                        "event": "message.deleted",
                        "payload": {"room_id": room_id, "message_id": deleted_id},
                    },
                )
                return

            if action == "message.pin":
                message_id = int(content.get("message_id") or 0)
                pinned = content.get("pinned", None)
                room_id, payload = await self._do_pin_message(message_id, pinned)
                await self.channel_layer.group_send(
                    room_group_name(room_id),
                    {
                        "type": "team_chat.event",
                        "event": "message.pinned",
                        "payload": {"message": payload},
                    },
                )
                return

            if action == "reaction.toggle":
                message_id = int(content.get("message_id") or 0)
                emoji = str(content.get("emoji") or "")
                room_id, payload = await self._do_react_message(message_id, emoji)
                await self.channel_layer.group_send(
                    room_group_name(room_id),
                    {
                        "type": "team_chat.event",
                        "event": "reaction.updated",
                        "payload": {"message": payload},
                    },
                )
                return

            await self.send_json({"type": "error", "action": action, "message": f"Unknown action: {action}"})
        except APIException as exc:
            await self.send_json({
                "type": "error",
                "action": action,
                "client_nonce": client_nonce,
                "message": _extract_error_message(exc),
            })
        except (TypeError, ValueError) as exc:
            await self.send_json({
                "type": "error",
                "action": action,
                "client_nonce": client_nonce,
                "message": str(exc) or "Invalid request.",
            })
        except Exception:
            logger.exception("Unhandled error in TeamChatConsumer action=%s", action)
            await self.send_json({
                "type": "error",
                "action": action,
                "client_nonce": client_nonce,
                "message": "Unexpected error processing chat action.",
            })


websocket_urlpatterns = [
    re_path(r"^ws/team-chat/?$", TeamChatConsumer.as_asgi()),
]
