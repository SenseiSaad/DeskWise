"""DRF REST endpoints for the real-time employee Team Chatroom."""
from __future__ import annotations

from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Department, TeamMessage, TeamRoom, User
from .ratelimit import _client_ip as client_ip, rate_limit
from .team_chat import (
    ALLOWED_REACTION_EMOJIS,
    _message_queryset,
    accessible_rooms_for,
    broadcast_group_event_sync,
    company_group_name,
    create_room,
    create_user_message,
    delete_room,
    delete_team_message,
    edit_user_message,
    edit_window_seconds,
    mark_room_read,
    pin_team_message,
    room_group_name,
    serialize_message,
    serialize_room,
    spawn_deskwise_reply,
    toggle_reaction,
    update_room,
    user_can_access_room,
)
from .ws import _COMPANY_PRESENCE


def _require_company(request):
    user = request.user
    if (
        getattr(user, "is_platform_admin", False) or getattr(user, "is_superuser", False)
    ) and not getattr(user, "company_id", None):
        return Response(
            {"detail": "Platform admins must select a company to access Team Chat."},
            status=403,
        )
    if not getattr(user, "company_id", None):
        return Response({"detail": "No company workspace attached to this account."}, status=403)
    return None


def _get_accessible_room_or_error(user, room_id: int):
    room = (
        TeamRoom.objects.filter(pk=room_id, company_id=user.company_id)
        .select_related("department", "created_by")
        .first()
    )
    if room is None:
        return None, Response({"detail": "Chatroom not found."}, status=404)
    if not user_can_access_room(user, room):
        return None, Response({"detail": "You do not have access to this chatroom."}, status=403)
    return room, None


def _get_accessible_message_or_error(user, msg_id: int):
    msg = (
        TeamMessage.objects.filter(pk=msg_id, company_id=user.company_id)
        .select_related("room", "room__company", "room__department", "sender", "company")
        .first()
    )
    if msg is None:
        return None, Response({"detail": "Message not found."}, status=404)
    if not user_can_access_room(user, msg.room):
        return None, Response({"detail": "You do not have access to this chatroom."}, status=403)
    return msg, None


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def team_chat_rooms(request):
    """List accessible company chatrooms (auto-creating #General) or create a new room."""
    guard = _require_company(request)
    if guard:
        return guard

    if request.method == "GET":
        rooms = accessible_rooms_for(request.user)
        online_ids = sorted(_COMPANY_PRESENCE.get(request.user.company_id, {}).keys())
        members = [
            {
                "id": u.id,
                "full_name": u.full_name or u.email.split("@")[0],
                "email": u.email,
                "title": u.title,
                "role": u.role,
                "department_id": u.department_id,
                "department_name": u.department.name if u.department else None,
                "is_online": u.id in online_ids,
            }
            for u in (
                User.objects.filter(company_id=request.user.company_id, is_active=True)
                .select_related("department")
                .order_by("full_name", "email")
            )
        ]
        depts = [
            {"id": d.id, "name": d.name}
            for d in Department.objects.filter(company_id=request.user.company_id).order_by("name")
        ]
        return Response({
            "rooms": [serialize_room(r, user=request.user) for r in rooms],
            "members": members,
            "departments": depts,
            "online_user_ids": online_ids,
            "edit_window_seconds": edit_window_seconds(),
            "allowed_emojis": sorted(ALLOWED_REACTION_EMOJIS),
        })

    data = request.data or {}
    room = create_room(
        user=request.user,
        name=data.get("name", ""),
        description=data.get("description", ""),
        scope=data.get("scope", "company"),
        department_id=data.get("department_id"),
        member_ids=data.get("member_ids"),
        ip=client_ip(request),
    )
    serialized = serialize_room(room, user=request.user)
    broadcast_group_event_sync(
        company_group_name(request.user.company_id),
        "room.created",
        {"room": serialize_room(room)},
    )
    return Response(serialized, status=201)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def team_chat_room_detail(request, room_id: int):
    """Rename/update an extra room or delete a non-default room (admin only)."""
    guard = _require_company(request)
    if guard:
        return guard

    room, err = _get_accessible_room_or_error(request.user, room_id)
    if err:
        return err

    if request.method == "PATCH":
        data = request.data or {}
        updated = update_room(
            user=request.user,
            room=room,
            name=data.get("name") if "name" in data else None,
            description=data.get("description") if "description" in data else None,
            scope=data.get("scope") if "scope" in data else None,
            department_id=data.get("department_id") if "department_id" in data else None,
            member_ids=data.get("member_ids") if "member_ids" in data else None,
            ip=client_ip(request),
        )
        serialized = serialize_room(updated, user=request.user)
        broadcast_group_event_sync(
            company_group_name(request.user.company_id),
            "room.updated",
            {"room": serialize_room(updated)},
        )
        return Response(serialized)

    deleted_id = delete_room(request.user, room, ip=client_ip(request))
    broadcast_group_event_sync(
        company_group_name(request.user.company_id),
        "room.deleted",
        {"room_id": deleted_id},
    )
    return Response({"ok": True, "deleted_id": deleted_id})


@rate_limit("team_chat_post", rate=40, per_seconds=60, key="user")
def _create_team_message_post(request, room):
    data = request.data or {}
    msg, payload, trigger_ai = create_user_message(
        user=request.user,
        room=room,
        content=data.get("content", ""),
        reply_to_id=data.get("reply_to_id"),
        referenced_document_id=data.get("referenced_document_id"),
        client_nonce=data.get("client_nonce"),
        ip=client_ip(request),
    )
    broadcast_group_event_sync(
        room_group_name(room.id),
        "message.created",
        {"message": payload},
    )
    stream_id = None
    if trigger_ai:
        stream_id = spawn_deskwise_reply(room.id, msg.id, request.user.id)

    return Response(
        {
            "message": payload,
            "deskwise_triggered": trigger_ai,
            "stream_id": stream_id,
        },
        status=201,
    )


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def team_chat_messages(request, room_id: int):
    """Fetch paginated room messages + pinned items, or post a new message."""
    guard = _require_company(request)
    if guard:
        return guard

    room, err = _get_accessible_room_or_error(request.user, room_id)
    if err:
        return err

    if request.method == "GET":
        try:
            limit = min(100, max(1, int(request.query_params.get("limit") or 50)))
        except ValueError:
            limit = 50
        before_id_raw = request.query_params.get("before_id")
        query_str = (request.query_params.get("q") or "").strip()

        qs = _message_queryset().filter(room=room)
        if query_str:
            qs = qs.filter(Q(content__icontains=query_str) | Q(sources__icontains=query_str))
        if before_id_raw:
            try:
                qs = qs.filter(id__lt=int(before_id_raw))
            except ValueError:
                pass

        rows_desc = list(qs.order_by("-created_at", "-id")[: limit + 1])
        has_more = len(rows_desc) > limit
        rows = list(reversed(rows_desc[:limit]))

        pinned_rows = list(
            _message_queryset().filter(room=room, is_pinned=True).order_by("-pinned_at", "-id")[:25]
        )

        if not query_str and not before_id_raw and request.query_params.get("mark_read", "true").lower() != "false":
            mark_room_read(request.user, room)

        return Response({
            "room": serialize_room(room, user=request.user),
            "results": [serialize_message(m) for m in rows],
            "pinned": [serialize_message(m) for m in pinned_rows],
            "has_more": has_more,
            "edit_window_seconds": edit_window_seconds(),
        })

    return _create_team_message_post(request, room)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def team_chat_mark_read(request, room_id: int):
    guard = _require_company(request)
    if guard:
        return guard

    room, err = _get_accessible_room_or_error(request.user, room_id)
    if err:
        return err

    last_id = (request.data or {}).get("last_message_id")
    saved = mark_room_read(request.user, room, last_message_id=int(last_id) if last_id is not None else None)
    return Response({"ok": True, "last_read_message_id": saved})


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def team_chat_message_detail(request, msg_id: int):
    """Edit own message within time limit (marked edited), or permanently delete."""
    guard = _require_company(request)
    if guard:
        return guard

    msg, err = _get_accessible_message_or_error(request.user, msg_id)
    if err:
        return err

    if request.method == "PATCH":
        _, payload = edit_user_message(
            user=request.user,
            msg=msg,
            content=(request.data or {}).get("content", ""),
            ip=client_ip(request),
        )
        broadcast_group_event_sync(
            room_group_name(msg.room_id),
            "message.updated",
            {"message": payload},
        )
        return Response({"message": payload})

    room_id, deleted_id = delete_team_message(user=request.user, msg=msg, ip=client_ip(request))
    broadcast_group_event_sync(
        room_group_name(room_id),
        "message.deleted",
        {"room_id": room_id, "message_id": deleted_id},
    )
    return Response({"ok": True, "room_id": room_id, "deleted_id": deleted_id})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def team_chat_message_pin(request, msg_id: int):
    """Any non-viewer member may pin or unpin any message in an accessible room."""
    guard = _require_company(request)
    if guard:
        return guard

    msg, err = _get_accessible_message_or_error(request.user, msg_id)
    if err:
        return err

    pinned = (request.data or {}).get("pinned", None)
    _, payload = pin_team_message(user=request.user, msg=msg, pinned=pinned, ip=client_ip(request))
    broadcast_group_event_sync(
        room_group_name(msg.room_id),
        "message.pinned",
        {"message": payload},
    )
    return Response({"message": payload})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def team_chat_message_react(request, msg_id: int):
    """Toggle an emoji reaction on a TeamMessage."""
    guard = _require_company(request)
    if guard:
        return guard

    msg, err = _get_accessible_message_or_error(request.user, msg_id)
    if err:
        return err

    emoji = str((request.data or {}).get("emoji") or "")
    _, payload = toggle_reaction(user=request.user, msg=msg, emoji=emoji)
    broadcast_group_event_sync(
        room_group_name(msg.room_id),
        "reaction.updated",
        {"message": payload},
    )
    return Response({"message": payload})
