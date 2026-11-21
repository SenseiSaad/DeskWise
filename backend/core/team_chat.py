"""Real-time employee Team Chatroom domain services, RBAC rules, and @DeskWise AI.

Both the HTTP REST endpoints and the Django Channels WebSocket consumer call
the exact same permission checks, database mutations, and event serializers in
this module so security rules and real-time broadcasts never drift apart.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import uuid
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.db.models import Count, Prefetch, Q
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.exceptions import PermissionDenied, ValidationError

from . import docgen, moderation, providers, rag
from .models import (
    AskLog, AuditLog, Department, Document, Plan, TeamMessage,
    TeamMessageReaction, TeamRoom, TeamRoomMember, TeamRoomReadState, User,
)

logger = logging.getLogger(__name__)

# Recognise @DeskWise mentions in team messages (case-insensitive, word boundary).
DESKWISE_MENTION_RE = re.compile(r"(?<!\w)@deskwise\b", re.IGNORECASE)
MAX_MESSAGE_LENGTH = 4000
ALLOWED_REACTION_EMOJIS = {"👍", "✅", "❤️", "👀", "😂", "🎉", "🙏", "🔥"}

# Track the active ASGI server event loop so sync REST views and background
# @DeskWise threads dispatch WebSocket group events onto the same loop used by
# InMemoryChannelLayer queues (no cross-loop asyncio.Queue failures).
_ACTIVE_LOOP: asyncio.AbstractEventLoop | None = None
_LOOP_LOCK = threading.Lock()


def register_active_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    """Record the currently running ASGI event loop for sync-to-WS fan-out."""
    global _ACTIVE_LOOP
    with _LOOP_LOCK:
        _ACTIVE_LOOP = loop


def room_group_name(room_id: int) -> str:
    return f"team_chat_room_{room_id}"


def company_group_name(company_id: int) -> str:
    return f"team_chat_company_{company_id}"


def user_group_name(user_id: int) -> str:
    return f"team_chat_user_{user_id}"


def broadcast_group_event_sync(group: str, event_type: str, payload: dict) -> None:
    """Best-effort broadcast to a Channels group from synchronous code or threads."""
    layer = get_channel_layer()
    if layer is None:
        return
    message = {"type": "team_chat.event", "event": event_type, "payload": payload}
    with _LOOP_LOCK:
        loop = _ACTIVE_LOOP
    try:
        if loop is not None and loop.is_running():
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is not loop:
                fut = asyncio.run_coroutine_threadsafe(layer.group_send(group, message), loop)
                fut.result(timeout=5)
                return
        async_to_sync(layer.group_send)(group, message)
    except Exception:
        logger.debug("Channel broadcast skipped/failed for %s (%s)", group, event_type, exc_info=True)


def is_company_admin(user: User | None) -> bool:
    """True for company admins, superusers, and platform admins inside a tenant."""
    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and (
            getattr(user, "role", "") == "admin"
            or getattr(user, "is_superuser", False)
            or getattr(user, "is_platform_admin", False)
        )
    )


def has_company_context(user: User | None) -> bool:
    """True when authenticated, active, and attached to a concrete company."""
    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and getattr(user, "company_id", None)
    )


def edit_window_seconds() -> int:
    return max(1, int(getattr(settings, "TEAM_CHAT_EDIT_WINDOW_SECONDS", 900) or 900))


def user_can_access_room(user: User | None, room: TeamRoom) -> bool:
    """Whether `user` may view rooms & read message history in `room`."""
    if not has_company_context(user) or room.company_id != user.company_id:
        return False
    if is_company_admin(user):
        return True
    if room.scope == "company" or room.is_default:
        return True
    if room.scope == "department":
        return bool(room.department_id and user.department_id == room.department_id)
    if room.scope == "private":
        return TeamRoomMember.objects.filter(room=room, user=user).exists()
    return False


def user_can_post(user: User | None, room: TeamRoom) -> bool:
    """Viewers are read-only; admins and employees can participate in chat."""
    if not user_can_access_room(user, room):
        return False
    return getattr(user, "role", "") != "viewer" or is_company_admin(user)


def check_edit_permission(user: User, msg: TeamMessage) -> tuple[bool, str]:
    """Only the human author may edit their own message, within the time limit.

    Admins may delete any message, never edit another user's or @DeskWise's message.
    """
    if not user_can_post(user, msg.room):
        return False, "Read-only viewers cannot edit messages."
    if msg.sender_type != "user" or msg.sender_id != user.id:
        return False, "You can only edit your own messages."
    window = edit_window_seconds()
    elapsed = (timezone.now() - msg.created_at).total_seconds()
    if elapsed > window:
        minutes = max(1, round(window / 60))
        return False, f"Edit window ({minutes} min) has expired."
    return True, ""


def check_delete_permission(user: User, msg: TeamMessage) -> tuple[bool, str]:
    """Authors can delete their own messages; admins can delete any message."""
    if not user_can_post(user, msg.room):
        return False, "Read-only viewers cannot delete messages."
    if is_company_admin(user):
        return True, ""
    if msg.sender_type == "user" and msg.sender_id == user.id:
        return True, ""
    return False, "You can only delete your own messages."


def check_pin_permission(user: User, msg: TeamMessage) -> tuple[bool, str]:
    """Any non-viewer participant in the room can pin/unpin own or others' messages."""
    if not user_can_post(user, msg.room):
        return False, "Read-only viewers cannot pin or unpin messages."
    return True, ""


def accessible_rooms_for(user: User) -> list[TeamRoom]:
    """Ensure the company's default room exists and return all rooms `user` can see."""
    if not has_company_context(user):
        return []
    TeamRoom.ensure_default(user.company)
    qs = (
        TeamRoom.objects.filter(company_id=user.company_id)
        .select_related("department", "created_by")
        .prefetch_related("memberships")
    )
    if is_company_admin(user):
        return list(qs)
    member_room_ids = set(
        TeamRoomMember.objects.filter(user=user, room__company_id=user.company_id)
        .values_list("room_id", flat=True)
    )
    rooms = []
    for r in qs:
        if r.is_default or r.scope == "company":
            rooms.append(r)
        elif r.scope == "department" and r.department_id and user.department_id == r.department_id:
            rooms.append(r)
        elif r.scope == "private" and r.id in member_room_ids:
            rooms.append(r)
    return rooms


def _sender_payload(user: User | None) -> dict | None:
    if user is None:
        return None
    return {
        "id": user.id,
        "full_name": user.full_name or user.email.split("@")[0],
        "email": user.email,
        "title": user.title,
        "role": user.role,
        "department_name": user.department.name if getattr(user, "department", None) else None,
    }


def serialize_room(room: TeamRoom, user: User | None = None) -> dict:
    """Serialize a TeamRoom with unread count and member metadata."""
    unread_count = 0
    if user is not None and user.is_authenticated:
        state = TeamRoomReadState.objects.filter(room=room, user=user).first()
        last_id = state.last_read_message_id if state else 0
        unread_count = (
            TeamMessage.objects.filter(room=room, id__gt=last_id)
            .exclude(sender_id=user.id)
            .count()
        )
    if room.scope == "company" or room.is_default:
        member_count = User.objects.filter(company_id=room.company_id, is_active=True).count()
        member_ids = []
    elif room.scope == "department" and room.department_id:
        member_count = User.objects.filter(
            company_id=room.company_id, department_id=room.department_id, is_active=True,
        ).count()
        member_ids = []
    else:
        member_ids = list(
            TeamRoomMember.objects.filter(room=room).values_list("user_id", flat=True)
        )
        member_count = len(member_ids)

    return {
        "id": room.id,
        "name": room.name,
        "slug": room.slug,
        "description": room.description,
        "scope": room.scope,
        "department_id": room.department_id,
        "department_name": room.department.name if room.department else None,
        "is_default": room.is_default,
        "member_count": member_count,
        "member_ids": member_ids,
        "unread_count": unread_count,
        "pinned_count": TeamMessage.objects.filter(room=room, is_pinned=True).count(),
        "created_at": room.created_at.isoformat(),
    }


def _grouped_reactions(msg: TeamMessage) -> list[dict]:
    """Return [{emoji, count, user_ids}] preserving first-seen emoji order."""
    buckets: dict[str, list[int]] = {}
    for rx in msg.reactions.all():
        buckets.setdefault(rx.emoji, []).append(rx.user_id)
    return [
        {"emoji": emoji, "count": len(uids), "user_ids": sorted(uids)}
        for emoji, uids in buckets.items()
    ]


def serialize_message(msg: TeamMessage) -> dict:
    """Serialize one TeamMessage cleanly for both HTTP JSON and WS fan-out."""
    try:
        sources = json.loads(msg.sources) if msg.sources else []
    except Exception:
        sources = []
    try:
        meta = json.loads(msg.metadata) if msg.metadata else {}
    except Exception:
        meta = {}

    reply_preview = None
    if msg.reply_to_id and msg.reply_to is not None:
        r = msg.reply_to
        r_name = (
            "DeskWise"
            if r.sender_type == "deskwise"
            else (_sender_payload(r.sender)["full_name"] if r.sender else "Former member")
        )
        reply_preview = {
            "id": r.id,
            "sender_type": r.sender_type,
            "sender_id": r.sender_id,
            "sender_name": r_name,
            "content": r.content[:140],
        }

    ref_doc = None
    if msg.referenced_document_id and msg.referenced_document is not None:
        d = msg.referenced_document
        ref_doc = {
            "id": d.id,
            "filename": d.filename,
            "category": d.category,
            "access_scope": d.access_scope,
        }

    window = edit_window_seconds()
    edit_expires_at = (
        (msg.created_at + timedelta(seconds=window)).isoformat()
        if msg.sender_type == "user"
        else None
    )

    pinned_by_name = None
    if msg.is_pinned and msg.pinned_by is not None:
        pinned_by_name = msg.pinned_by.full_name or msg.pinned_by.email.split("@")[0]

    return {
        "id": msg.id,
        "room_id": msg.room_id,
        "sender_type": msg.sender_type,
        "sender_id": msg.sender_id,
        "sender": _sender_payload(msg.sender) if msg.sender_type == "user" else None,
        "content": msg.content,
        "reply_to_id": msg.reply_to_id,
        "reply_to": reply_preview,
        "referenced_document": ref_doc,
        "sources": sources,
        "metadata": meta,
        "flag": meta.get("flag"),
        "reactions": _grouped_reactions(msg),
        "is_pinned": msg.is_pinned,
        "pinned_by_id": msg.pinned_by_id,
        "pinned_by_name": pinned_by_name,
        "pinned_at": msg.pinned_at.isoformat() if msg.pinned_at else None,
        "is_edited": msg.edited_at is not None,
        "edited_at": msg.edited_at.isoformat() if msg.edited_at else None,
        "edit_expires_at": edit_expires_at,
        "created_at": msg.created_at.isoformat(),
    }


def _message_queryset():
    return (
        TeamMessage.objects.select_related(
            "sender", "sender__department", "pinned_by",
            "reply_to", "reply_to__sender", "reply_to__sender__department",
            "referenced_document",
        )
        .prefetch_related("reactions")
    )


def _unique_room_slug(company_id: int, raw_name: str, exclude_id: int | None = None) -> str:
    base = slugify(raw_name)[:65] or "room"
    candidate = base
    n = 2
    while True:
        qs = TeamRoom.objects.filter(company_id=company_id, slug=candidate)
        if exclude_id:
            qs = qs.exclude(pk=exclude_id)
        if not qs.exists():
            return candidate
        suffix = f"-{n}"
        candidate = f"{base[:75 - len(suffix)]}{suffix}"
        n += 1


def create_room(
    user: User,
    name: str,
    description: str = "",
    scope: str = "company",
    department_id: int | None = None,
    member_ids: list[int] | None = None,
    ip: str = "",
) -> TeamRoom:
    if not has_company_context(user) or not is_company_admin(user):
        raise PermissionDenied("Only company admins can create team chat rooms.")
    clean_name = (name or "").strip()
    if len(clean_name) < 2 or len(clean_name) > 80:
        raise ValidationError({"name": "Room name must be between 2 and 80 characters."})
    scope = (scope or "company").strip().lower()
    if scope not in ("company", "department", "private"):
        raise ValidationError({"scope": "Scope must be company, department, or private."})

    dept = None
    if scope == "department":
        if not department_id:
            raise ValidationError({"department_id": "Select a department for a department room."})
        dept = Department.objects.filter(pk=department_id, company_id=user.company_id).first()
        if dept is None:
            raise ValidationError({"department_id": "Department not found in your company."})

    TeamRoom.ensure_default(user.company)
    slug = _unique_room_slug(user.company_id, clean_name)

    with transaction.atomic():
        room = TeamRoom.objects.create(
            company=user.company,
            name=clean_name,
            slug=slug,
            description=(description or "").strip()[:240],
            scope=scope,
            department=dept,
            is_default=False,
            created_by=user,
        )
        if scope == "private":
            valid_ids = set(
                User.objects.filter(
                    company_id=user.company_id, is_active=True, id__in=(member_ids or [])
                ).values_list("id", flat=True)
            )
            valid_ids.add(user.id)
            TeamRoomMember.objects.bulk_create(
                [TeamRoomMember(room=room, user_id=uid) for uid in valid_ids],
                ignore_conflicts=True,
            )
        AuditLog.objects.create(
            company=user.company,
            user=user,
            action="team_chat_room_create",
            detail=f"{room.slug} ({room.scope})",
            ip=ip,
        )

    return TeamRoom.objects.select_related("department", "created_by").get(pk=room.pk)


def update_room(
    user: User,
    room: TeamRoom,
    name: str | None = None,
    description: str | None = None,
    scope: str | None = None,
    department_id: int | None = None,
    member_ids: list[int] | None = None,
    ip: str = "",
) -> TeamRoom:
    if not has_company_context(user) or room.company_id != user.company_id or not is_company_admin(user):
        raise PermissionDenied("Only company admins can modify chat rooms.")

    update_fields = ["updated_at"]
    if name is not None:
        clean_name = name.strip()
        if len(clean_name) < 2 or len(clean_name) > 80:
            raise ValidationError({"name": "Room name must be between 2 and 80 characters."})
        room.name = clean_name
        update_fields.append("name")
    if description is not None:
        room.description = description.strip()[:240]
        update_fields.append("description")
    if scope is not None:
        clean_scope = scope.strip().lower()
        if room.is_default and clean_scope != "company":
            raise ValidationError({"scope": "The default company chatroom must remain company-wide."})
        if clean_scope not in ("company", "department", "private"):
            raise ValidationError({"scope": "Scope must be company, department, or private."})
        room.scope = clean_scope
        update_fields.append("scope")
        if clean_scope != "department":
            room.department = None
            update_fields.append("department")

    if room.scope == "department":
        target_dept_id = department_id if department_id is not None else room.department_id
        dept = Department.objects.filter(pk=target_dept_id, company_id=user.company_id).first()
        if dept is None:
            raise ValidationError({"department_id": "Valid department_id is required."})
        room.department = dept
        if "department" not in update_fields:
            update_fields.append("department")

    with transaction.atomic():
        room.save(update_fields=update_fields)
        if room.scope == "private" and member_ids is not None:
            valid_ids = set(
                User.objects.filter(
                    company_id=user.company_id, is_active=True, id__in=member_ids
                ).values_list("id", flat=True)
            )
            valid_ids.add(user.id)
            TeamRoomMember.objects.filter(room=room).exclude(user_id__in=valid_ids).delete()
            TeamRoomMember.objects.bulk_create(
                [TeamRoomMember(room=room, user_id=uid) for uid in valid_ids],
                ignore_conflicts=True,
            )
        AuditLog.objects.create(
            company=user.company,
            user=user,
            action="team_chat_room_update",
            detail=f"{room.slug} ({room.scope})",
            ip=ip,
        )

    return TeamRoom.objects.select_related("department", "created_by").get(pk=room.pk)


def delete_room(user: User, room: TeamRoom, ip: str = "") -> int:
    if not has_company_context(user) or room.company_id != user.company_id or not is_company_admin(user):
        raise PermissionDenied("Only company admins can delete chat rooms.")
    if room.is_default:
        raise ValidationError({"detail": "The default company chatroom cannot be deleted."})
    room_id = room.id
    slug = room.slug
    company = room.company
    with transaction.atomic():
        AuditLog.objects.create(
            company=company,
            user=user,
            action="team_chat_room_delete",
            detail=f"{slug}",
            ip=ip,
        )
        room.delete()
    return room_id


def _accessible_ref_doc(user: User, doc_id: int | None, room: TeamRoom | None = None) -> Document | None:
    if doc_id is None:
        return None
    from . import access
    doc = access.accessible_documents_qs(
        user, action="view_ask", include_unapproved=False, include_external_shares=False,
    ).filter(pk=doc_id).first()
    if doc is None:
        raise ValidationError({"referenced_document_id": "Document not found or access denied."})
    if room is not None and doc.id not in room_allowed_doc_ids(room):
        raise ValidationError({"referenced_document_id": "This document cannot be referenced in a shared room with lower-clearance members."})
    return doc


def create_user_message(
    user: User,
    room: TeamRoom,
    content: str,
    reply_to_id: int | None = None,
    referenced_document_id: int | None = None,
    client_nonce: str | None = None,
    ip: str = "",
) -> tuple[TeamMessage, dict, bool]:
    """Create a human message, run moderation scan, update read state, and return
    `(msg, serialized_payload, trigger_ai)`."""
    if not user_can_post(user, room):
        raise PermissionDenied("Read-only viewers cannot send messages.")
    text = (content or "").strip()
    if not text:
        raise ValidationError({"content": "Message cannot be empty."})
    if len(text) > MAX_MESSAGE_LENGTH:
        raise ValidationError({"content": f"Message exceeds {MAX_MESSAGE_LENGTH} character limit."})

    reply_msg = None
    if reply_to_id is not None:
        reply_msg = TeamMessage.objects.filter(pk=reply_to_id, room=room).first()
        if reply_msg is None:
            raise ValidationError({"reply_to_id": "Replied message was not found in this room."})

    ref_doc = _accessible_ref_doc(user, referenced_document_id, room=room)

    scan = moderation.scan(text)
    meta: dict = {}
    if scan.flagged:
        meta["flag"] = {
            "message": f"Flagged for policy review: {scan.summary()}.",
            "categories": scan.labels,
        }
        AuditLog.objects.create(
            company=room.company,
            user=user,
            action="POLICY_VIOLATION_DETECTED",
            outcome="allowed",
            target_type="team_room",
            target_id=str(room.id),
            detail=f"[team-chat:{room.slug}] {scan.summary()}",
            ip=ip,
        )

    msg = TeamMessage.objects.create(
        company=room.company,
        room=room,
        sender=user,
        sender_type="user",
        content=text,
        reply_to=reply_msg,
        referenced_document=ref_doc,
        metadata=json.dumps(meta),
    )
    TeamRoomReadState.objects.update_or_create(
        room=room, user=user, defaults={"last_read_message_id": msg.id},
    )

    loaded = _message_queryset().get(pk=msg.pk)
    payload = serialize_message(loaded)
    if client_nonce:
        payload["client_nonce"] = client_nonce
    return loaded, payload, (has_deskwise_mention(text) and getattr(room.company, "enable_ai_chat", True))


def edit_user_message(user: User, msg: TeamMessage, content: str, ip: str = "") -> tuple[TeamMessage, dict]:
    """Edit own message within the configured edit time limit."""
    allowed, reason = check_edit_permission(user, msg)
    if not allowed:
        raise PermissionDenied(reason)

    text = (content or "").strip()
    if not text:
        raise ValidationError({"content": "Message cannot be empty."})
    if len(text) > MAX_MESSAGE_LENGTH:
        raise ValidationError({"content": f"Message exceeds {MAX_MESSAGE_LENGTH} character limit."})

    try:
        meta = json.loads(msg.metadata) if msg.metadata else {}
    except Exception:
        meta = {}

    scan = moderation.scan(text)
    if scan.flagged:
        meta["flag"] = {
            "message": f"Flagged for policy review: {scan.summary()}.",
            "categories": scan.labels,
        }
        AuditLog.objects.create(
            company=msg.company,
            user=user,
            action="POLICY_VIOLATION_DETECTED",
            outcome="allowed",
            target_type="team_room",
            target_id=str(msg.room_id),
            detail=f"[team-chat-edit:{msg.room.slug}] {scan.summary()}",
            ip=ip,
        )
    else:
        meta.pop("flag", None)

    msg.content = text
    msg.edited_at = timezone.now()
    msg.metadata = json.dumps(meta)
    msg.save(update_fields=["content", "edited_at", "metadata"])

    AuditLog.objects.create(
        company=msg.company,
        user=user,
        action="team_chat_edit",
        detail=f"room={msg.room.slug} msg={msg.id}",
        ip=ip,
    )

    loaded = _message_queryset().get(pk=msg.pk)
    return loaded, serialize_message(loaded)


def delete_team_message(user: User, msg: TeamMessage, ip: str = "") -> tuple[int, int]:
    """Permanently delete a message (not hide) and write an AuditLog entry."""
    allowed, reason = check_delete_permission(user, msg)
    if not allowed:
        raise PermissionDenied(reason)

    room_id = msg.room_id
    msg_id = msg.id
    slug = msg.room.slug
    author_label = msg.sender.email if msg.sender_id else msg.sender_type

    with transaction.atomic():
        AuditLog.objects.create(
            company=msg.company,
            user=user,
            action="team_chat_delete",
            outcome="allowed",
            target_type="team_message",
            target_id=str(msg_id),
            detail=f"room={slug} msg={msg_id} author={author_label}",
            ip=ip,
        )
        msg.delete()

    return room_id, msg_id


def pin_team_message(user: User, msg: TeamMessage, pinned: bool | None = None, ip: str = "") -> tuple[TeamMessage, dict]:
    """Pin or unpin any accessible message (own, coworker, or @DeskWise)."""
    allowed, reason = check_pin_permission(user, msg)
    if not allowed:
        raise PermissionDenied(reason)

    target = (not msg.is_pinned) if pinned is None else bool(pinned)
    msg.is_pinned = target
    msg.pinned_by = user if target else None
    msg.pinned_at = timezone.now() if target else None
    msg.save(update_fields=["is_pinned", "pinned_by", "pinned_at"])

    AuditLog.objects.create(
        company=msg.company,
        user=user,
        action="team_chat_pin" if target else "team_chat_unpin",
        detail=f"room={msg.room.slug} msg={msg.id}",
        ip=ip,
    )

    loaded = _message_queryset().get(pk=msg.pk)
    return loaded, serialize_message(loaded)


def toggle_reaction(user: User, msg: TeamMessage, emoji: str) -> tuple[TeamMessage, dict]:
    """Toggle an emoji reaction on a TeamMessage."""
    if not user_can_post(user, msg.room):
        raise PermissionDenied("Read-only viewers cannot react to messages.")
    clean = (emoji or "").strip()
    if not clean or len(clean) > 16 or clean not in ALLOWED_REACTION_EMOJIS:
        raise ValidationError({"emoji": "Choose a valid reaction emoji."})

    existing = TeamMessageReaction.objects.filter(message=msg, user=user, emoji=clean).first()
    if existing is not None:
        existing.delete()
    else:
        try:
            TeamMessageReaction.objects.create(message=msg, user=user, emoji=clean)
        except IntegrityError:
            pass

    loaded = _message_queryset().get(pk=msg.pk)
    return loaded, serialize_message(loaded)


def mark_room_read(user: User, room: TeamRoom, last_message_id: int | None = None) -> int:
    if not user_can_access_room(user, room):
        raise PermissionDenied("You do not have access to this room.")
    latest = (
        TeamMessage.objects.filter(room=room)
        .order_by("-id")
        .values_list("id", flat=True)
        .first()
        or 0
    )
    target = min(int(last_message_id), latest) if last_message_id is not None else latest
    state, created = TeamRoomReadState.objects.get_or_create(
        room=room, user=user, defaults={"last_read_message_id": target},
    )
    if not created and target > state.last_read_message_id:
        state.last_read_message_id = target
        state.save(update_fields=["last_read_message_id", "updated_at"])
    return state.last_read_message_id


# ── @DeskWise AI assistant integration ─────────────────────────────────────

def has_deskwise_mention(text: str) -> bool:
    return bool(DESKWISE_MENTION_RE.search(text or ""))


def extract_deskwise_question(text: str) -> str:
    cleaned = DESKWISE_MENTION_RE.sub("", text or "").strip()
    cleaned = re.sub(r"^[,:\-\s]+", "", cleaned).strip()
    return cleaned


def room_allowed_doc_ids(room: TeamRoom) -> set[int]:
    """Document IDs safe to cite in a shared room without leaking private files.

    Derived from the canonical permission engine (`core.access`):
    * `company` / default room: ONLY approved, `standard`-sensitivity `access_scope='company'` docs.
    * `department` room: intersection of all active department members' accessible docs
      (capped at non-restricted, <= internal sensitivity; if any viewer/standard-clearance
      member belongs to the department, internal docs are excluded automatically).
    * `private` room: intersection of all explicit active room members' canonical accessible docs.
    """
    from . import access

    base = Document.objects.filter(company_id=room.company_id, status="approved")
    if room.is_default or room.scope == "company":
        return set(base.filter(access_scope="company", sensitivity="standard").values_list("id", flat=True))
    if room.scope == "department" and room.department_id:
        dept_members = list(
            User.objects.filter(
                company_id=room.company_id, department_id=room.department_id, is_active=True,
            ).select_related("company", "department")
        )
        has_standard_only = any(access.effective_clearance(u) == "standard" for u in dept_members)
        dept_sens = ("standard",) if has_standard_only else ("standard", "internal")
        room_cap = set(
            base.filter(
                Q(access_scope="company", sensitivity="standard")
                | Q(access_scope="department", department_id=room.department_id, sensitivity__in=dept_sens)
            ).values_list("id", flat=True)
        )
        if not dept_members:
            return room_cap
        shared_ids: set[int] | None = room_cap
        for u in dept_members:
            u_ids = set(
                access.accessible_documents_qs(
                    u, action="view_ask", include_unapproved=False, include_external_shares=False,
                ).values_list("id", flat=True)
            )
            shared_ids = shared_ids & u_ids
        return shared_ids or set()
    if room.scope == "private":
        members = list(
            TeamRoomMember.objects.filter(room=room, user__is_active=True)
            .select_related("user", "user__company", "user__department")
        )
        if not members:
            return set(base.filter(access_scope="company", sensitivity="standard").values_list("id", flat=True))
        shared_ids = None
        for m in members:
            u_ids = set(
                access.accessible_documents_qs(
                    m.user, action="view_ask", include_unapproved=False, include_external_shares=False,
                ).values_list("id", flat=True)
            )
            shared_ids = u_ids if shared_ids is None else (shared_ids & u_ids)
        return shared_ids or set()
    return set()


def _recent_room_history(room: TeamRoom, before_id: int, limit: int = 6) -> list[dict]:
    rows = list(
        TeamMessage.objects.filter(room=room, id__lt=before_id)
        .select_related("sender")
        .order_by("-id")[:limit]
    )
    rows.reverse()
    out = []
    for m in rows:
        if m.sender_type == "deskwise":
            out.append({"role": "assistant", "content": m.content[:1200]})
        else:
            who = m.sender.full_name or m.sender.email.split("@")[0] if m.sender else "Teammate"
            out.append({"role": "user", "content": f"[{who}]: {m.content[:1200]}"})
    return out


def _plan_quota_exceeded(company) -> str | None:
    plan = company.plan or Plan.default()
    if plan and plan.monthly_ask_limit is not None:
        month_start = timezone.localtime().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        used = AskLog.objects.filter(company=company, created_at__gte=month_start).count()
        if used >= plan.monthly_ask_limit:
            return f"Monthly question limit reached ({plan.monthly_ask_limit}). Upgrade your plan for more."
    return None


def _save_and_broadcast_bot_message(
    room: TeamRoom,
    reply_to: TeamMessage,
    content: str,
    sources: list[dict] | None = None,
    meta: dict | None = None,
    stream_id: str | None = None,
    broadcast: bool = True,
) -> TeamMessage:
    bot_msg = TeamMessage.objects.create(
        company=room.company,
        room=room,
        sender=None,
        sender_type="deskwise",
        content=content,
        reply_to=reply_to,
        sources=json.dumps(sources or []),
        metadata=json.dumps(meta or {}),
    )
    loaded = _message_queryset().get(pk=bot_msg.pk)
    if broadcast:
        payload = serialize_message(loaded)
        if stream_id:
            payload["replaces_stream_id"] = stream_id
        broadcast_group_event_sync(room_group_name(room.id), "message.created", {"message": payload})
    return loaded


def generate_deskwise_reply(
    room_id: int,
    trigger_message_id: int,
    user_id: int,
    broadcast: bool = True,
    stream_id: str | None = None,
    close_db: bool = False,
) -> TeamMessage | None:
    """Answer an @DeskWise mention in a shared room using room-safe RAG docs."""
    sid = stream_id or uuid.uuid4().hex[:12]
    try:
        room = TeamRoom.objects.select_related("company", "department").filter(pk=room_id).first()
        trigger_msg = TeamMessage.objects.filter(pk=trigger_message_id, room_id=room_id).first()
        user = User.objects.select_related("company", "department").filter(pk=user_id).first()
        if room is None or trigger_msg is None or user is None:
            return None
        if not getattr(room.company, "enable_ai_chat", True):
            return _save_and_broadcast_bot_message(
                room,
                trigger_msg,
                "AI assistant is disabled for this workspace.",
                meta={"disabled": True},
                stream_id=sid,
                broadcast=broadcast,
            )

        question = extract_deskwise_question(trigger_msg.content)
        if not question:
            return _save_and_broadcast_bot_message(
                room,
                trigger_msg,
                "Hi! Tag `@DeskWise` followed by a question or work request (for example: `@DeskWise what is our annual leave policy?`).",
                stream_id=sid,
                broadcast=broadcast,
            )

        quota_err = _plan_quota_exceeded(room.company)
        if quota_err:
            return _save_and_broadcast_bot_message(
                room, trigger_msg, quota_err, meta={"error": True}, stream_id=sid, broadcast=broadcast,
            )

        if broadcast:
            broadcast_group_event_sync(
                room_group_name(room.id),
                "deskwise.status",
                {
                    "room_id": room.id,
                    "stream_id": sid,
                    "reply_to_id": trigger_msg.id,
                    "status": "thinking",
                },
            )

        allowed_ids = room_allowed_doc_ids(room)
        history = _recent_room_history(room, trigger_msg.id)

        # If asking for a template/draft, restrict template matching to room-safe docs only.
        doc_plan = docgen.classify(question)
        template_text = ""
        template_rules = ""
        if getattr(room.company, "enable_docgen", True) and doc_plan.artifacts:
            safe_templates = [
                tpl for tpl in docgen.collect_uploaded_templates(user, doc_plan.artifacts, include_like=True)
                if tpl.document_id in allowed_ids
            ]
            if safe_templates:
                best = max(safe_templates, key=lambda tpl: docgen.template_match_score(question, tpl))
                if docgen.template_match_score(question, best) > 0:
                    template_text = best.text[:6000]
                    template_rules = docgen.TEMPLATE_SYSTEM_RULES

        tokens: list[str] = []
        source_names: list[str] = []
        err_msg = ""

        # Buffer small deltas slightly to keep WebSocket traffic smooth during streaming.
        pending = []
        for raw_line in rag.stream_answer(
            user,
            question,
            doc_ids_override=allowed_ids,
            history_override=history,
            template_text=template_text,
            template_rules=template_rules,
        ):
            try:
                evt = json.loads(raw_line)
            except Exception:
                continue
            etype = evt.get("type")
            if etype == "sources":
                source_names = list(evt.get("sources") or [])
            elif etype == "token":
                tok = evt.get("token") or ""
                if tok:
                    tokens.append(tok)
                    pending.append(tok)
                    if broadcast and (len("".join(pending)) >= 24 or "\n" in tok):
                        broadcast_group_event_sync(
                            room_group_name(room.id),
                            "deskwise.delta",
                            {
                                "room_id": room.id,
                                "stream_id": sid,
                                "reply_to_id": trigger_msg.id,
                                "token": "".join(pending),
                            },
                        )
                        pending.clear()
            elif etype == "error":
                err_msg = evt.get("message") or "DeskWise AI could not respond right now."

        if broadcast and pending:
            broadcast_group_event_sync(
                room_group_name(room.id),
                "deskwise.delta",
                {
                    "room_id": room.id,
                    "stream_id": sid,
                    "reply_to_id": trigger_msg.id,
                    "token": "".join(pending),
                },
            )
            pending.clear()

        answer_text = "".join(tokens).strip()
        if not answer_text:
            answer_text = err_msg or "I could not generate an answer from the available company documents."

        # Map cited filenames back to permitted document IDs so frontend can open previews.
        doc_map = {
            d["filename"]: d["id"]
            for d in Document.objects.filter(
                id__in=allowed_ids, filename__in=source_names
            ).values("id", "filename")
        } if allowed_ids and source_names else {}

        sources_payload = [
            {"filename": name, "document_id": doc_map.get(name)}
            for name in source_names
        ]
        meta = {"stream_id": sid, "error": bool(err_msg and not tokens)}

        return _save_and_broadcast_bot_message(
            room,
            trigger_msg,
            answer_text,
            sources=sources_payload,
            meta=meta,
            stream_id=sid,
            broadcast=broadcast,
        )
    except Exception as exc:
        logger.exception("Failed to run @DeskWise in room=%s msg=%s", room_id, trigger_message_id)
        if broadcast:
            broadcast_group_event_sync(
                room_group_name(room_id),
                "deskwise.error",
                {"room_id": room_id, "stream_id": sid, "message": str(exc)[:200]},
            )
        return None
    finally:
        if close_db:
            connection.close()


def spawn_deskwise_reply(room_id: int, trigger_message_id: int, user_id: int, stream_id: str | None = None) -> str:
    """Launch @DeskWise reply asynchronously (inline on serverless / eager mode)."""
    sid = stream_id or uuid.uuid4().hex[:12]
    if (
        getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False)
        or getattr(settings, "SYNC_INDEXING", False)
        or getattr(settings, "IS_VERCEL", False)
    ):
        generate_deskwise_reply(room_id, trigger_message_id, user_id, broadcast=True, stream_id=sid, close_db=False)
        return sid
    t = threading.Thread(
        target=generate_deskwise_reply,
        kwargs={
            "room_id": room_id,
            "trigger_message_id": trigger_message_id,
            "user_id": user_id,
            "broadcast": True,
            "stream_id": sid,
            "close_db": True,
        },
        daemon=True,
    )
    t.start()
    return sid


def summarize_room_messages(room: TeamRoom, limit: int = 50) -> dict:
    """Summarize recent room discussion into pinned highlights, open questions, and action items."""
    rows = list(
        TeamMessage.objects.filter(room=room)
        .select_related("sender")
        .order_by("-id")[:max(1, min(100, limit))]
    )
    rows.reverse()
    if not rows:
        return {
            "room_id": room.id,
            "message_count": 0,
            "summary": "No messages in this room yet.",
            "action_items": [],
            "open_questions": [],
            "pinned": [],
            "mode": "deterministic",
        }

    transcript_lines = []
    action_items = []
    open_questions = []
    pinned = []
    redact = getattr(room.company, "redact_pii_for_llm", True)
    for m in rows:
        who = "DeskWise" if m.sender_type == "deskwise" else (
            m.sender.full_name or m.sender.email.split("@")[0] if m.sender else "Teammate"
        )
        content = m.content.strip()
        if redact:
            content, _ = moderation.redact_pii(content)
        transcript_lines.append(f"{who}: {content[:400]}")
        if m.is_pinned:
            pinned.append(f"{who}: {content[:200]}")
        if m.sender_type == "user":
            if "?" in content:
                open_questions.append(f"{who}: {content[:200]}")
            if re.search(r"\b(todo|action|please|will|need to|assign|deadline|by Friday|by Monday)\b", content, re.I):
                action_items.append(f"{who}: {content[:200]}")

    chat = providers.get_chat_provider(company=room.company)
    if chat.available():
        prompt = [
            {
                "role": "system",
                "content": (
                    "Summarize this team chat concisely in plain text with 3 short bullets: "
                    "Key Decisions, Action Items, and Open Questions. Stay strictly grounded in the transcript."
                ),
            },
            {"role": "user", "content": "\n".join(transcript_lines[-40:])},
        ]
        try:
            ai_text = "".join(t for t in chat.stream_chat(prompt, 0.2, 400) if t).strip()
            if ai_text:
                return {
                    "room_id": room.id,
                    "message_count": len(rows),
                    "summary": ai_text,
                    "action_items": action_items[:10],
                    "open_questions": open_questions[:10],
                    "pinned": pinned[:10],
                    "mode": chat.label,
                }
        except Exception:
            pass

    return {
        "room_id": room.id,
        "message_count": len(rows),
        "summary": f"{len(rows)} message(s) reviewed: {len(pinned)} pinned, {len(action_items)} potential action item(s), {len(open_questions)} question(s).",
        "action_items": action_items[:10],
        "open_questions": open_questions[:10],
        "pinned": pinned[:10],
        "mode": "deterministic",
    }
