"""Adapter for SoroPy. Keep provider-specific code out of moderation rules."""
from __future__ import annotations

from datetime import timedelta
from dataclasses import replace
import inspect
from typing import Any

from .models import Message


class SoroPyGateway:
    def __init__(self, client: Any, group_target: str | None = None) -> None:
        self.client = client
        self.group_target = group_target
        self._messages: dict[tuple[str, int], Message] = {}
        self._primed_chats: set[str] = set()
        self._observed_members: dict[str, dict[str, dict[str, str]]] = {}

    def _chat(self, event_chat_id: str) -> str:
        """Use the public group target for SoroPy RPCs, while events use IDs."""
        return self.group_target or event_chat_id

    def remember_message(self, message: Message) -> None:
        """Keep recent realtime events so reply commands can identify a target."""
        self._messages[(message.chat_id, message.message_id)] = message
        if message.sender_id:
            chat_members = self._observed_members.setdefault(message.chat_id, {})
            previous = chat_members.get(message.sender_id, {})
            chat_members[message.sender_id] = {
                "id": message.sender_id,
                "name": message.sender_name or previous.get("name", "") or "کاربر",
                "username": message.sender_username or previous.get("username", ""),
                "source": "observed",
            }

    async def is_group_admin(self, chat_id: str, user_id: str) -> bool:
        target = self._chat(chat_id)
        # SoroPy's get_permissions currently fails for some Soroush group
        # entities. Ask MTProto for the server's actual administrator list.
        server_result = self._is_server_admin_member(target, user_id)
        if server_result is not None:
            return server_result
        # SoroPy resolves a numeric user ID only after its entity was loaded.
        # This cache warm-up lets the following check remain server-side.
        if target not in self._primed_chats:
            members = await _maybe_await(self.client.get_participants(target, limit=200))
            if members is not None:
                self._primed_chats.add(target)
        permissions = await _maybe_await(self.client.get_permissions(target, user_id))
        if _has_management_rights(permissions):
            return True
        # The authenticated user is sometimes resolved more reliably without
        # an explicit user ID. It is still a server-side permission lookup.
        me = await _maybe_await(self.client.get_me()) if hasattr(self.client, "get_me") else None
        if me and str(me.get("id", "")) == str(user_id):
            permissions = await _maybe_await(self.client.get_permissions(target))
            return _has_management_rights(permissions)
        return False

    def _is_server_admin_member(self, target: str, user_id: str) -> bool | None:
        """Return admin status from MTProto, or None when that API is unavailable."""
        try:
            from splusthon.tl.types import ChannelParticipantsAdmins

            engine = self.client._backend._engine

            async def load_admins():
                entity = await engine._resolve(target)
                return await engine._client.get_participants(
                    entity, filter=ChannelParticipantsAdmins
                )

            admins = engine._runner.run(load_admins(), timeout=30)
            return any(str(getattr(admin, "id", "")) == str(user_id) for admin in admins)
        except Exception:
            return None

    async def get_message(self, chat_id: str, message_id: int) -> Message | None:
        cached = self._messages.get((chat_id, message_id))
        if cached:
            return cached
        # Some future SoroPy releases may provide this public API.
        if not hasattr(self.client, "get_message"):
            return None
        raw = await _maybe_await(self.client.get_message(chat_id, message_id))
        if raw is None:
            return None
        return Message(chat_id, message_id, str(_field(raw, "sender_id", "from_id")), _field(raw, "text") or "")

    async def delete_message(self, chat_id: str, message_id: int) -> None:
        await _maybe_await(self.client.delete_messages(self._chat(chat_id), [message_id], revoke=True))

    async def restrict_member(self, chat_id: str, user_id: str, duration: timedelta) -> None:
        await _maybe_await(self.client.set_permissions(
            self._chat(chat_id), user_id, send_messages=False, until_date=duration
        ))

    async def ban_member(self, chat_id: str, user_id: str) -> None:
        await _maybe_await(self.client.ban(self._chat(chat_id), user_id))

    async def send_message(self, chat_id: str, text: str) -> None:
        result = await _maybe_await(self.client.send_message(self._chat(chat_id), text))
        # SoroPy may return SendResult(success=False) instead of raising. Turn
        # that into an exception so callers can retry with plain text.
        if result is not None and hasattr(result, "success") and not result.success:
            raise RuntimeError(getattr(result, "error", "ارسال پیام ناموفق بود"))

    async def list_members(self, chat_id: str, limit: int = 500) -> list[dict[str, str]]:
        members: list[Any] = []
        targets = list(dict.fromkeys((self._chat(chat_id), chat_id)))
        for target in targets:
            try:
                members = await _maybe_await(self.client.get_participants(target, limit=limit)) or []
            except Exception:
                members = []
            if not members:
                members = self._list_server_members(target, limit)
            if members:
                break

        found: dict[str, dict[str, str]] = {}
        for member in members:
            item = _normalise_member(member, source="server")
            if item["id"] or item["username"]:
                found[item["id"] or f"@{item['username']}"] = item

        # Recent senders keep tag/reply useful even when this Soroush group
        # refuses a full participant-list request.
        for member_id, item in self._observed_members.get(chat_id, {}).items():
            if not item.get("username"):
                resolved = self._resolve_server_member(member_id)
                if resolved:
                    item = {**item, **{k: v for k, v in resolved.items() if v}}
            if member_id in found:
                if not found[member_id]["name"]:
                    found[member_id]["name"] = item["name"]
                if not found[member_id]["username"]:
                    found[member_id]["username"] = item["username"]
            else:
                found[member_id] = dict(item)
        return list(found.values())

    async def inspect_message(self, message: Message) -> Message:
        """Read media/forward metadata omitted by SoroPy's normalised event."""
        try:
            engine = self.client._backend._engine
            target = self._chat(message.chat_id)

            async def load_message():
                entity = await engine._resolve(target)
                return await engine._client.get_messages(entity, ids=message.message_id)

            raw = engine._runner.run(load_message(), timeout=30)
            if isinstance(raw, (list, tuple)):
                raw = raw[0] if raw else None
            if raw is None:
                return message
            return replace(
                message,
                is_forwarded=bool(_field(raw, "fwd_from", "forward")),
                content_type=_message_content_type(raw),
            )
        except Exception:
            return message

    async def set_default_permissions(self, chat_id: str, permissions: dict[str, bool]) -> bool:
        """Apply real default group permissions on the Soroush server."""
        result = await _maybe_await(
            self.client.set_permissions(self._chat(chat_id), user=None, **permissions)
        )
        return bool(result)

    def _list_server_members(self, target: str, limit: int) -> list[Any]:
        """Bypass SoroPy's wrapper when it silently returns an empty list."""
        try:
            engine = self.client._backend._engine

            async def load_members():
                entity = await engine._resolve(target)
                return await engine._client.get_participants(entity, limit=limit)

            return list(engine._runner.run(load_members(), timeout=60) or [])
        except Exception:
            return []

    def _resolve_server_member(self, user_id: str) -> dict[str, str] | None:
        """Resolve a recently seen sender from the MTProto entity cache."""
        try:
            engine = self.client._backend._engine

            async def resolve_member():
                return await engine._resolve(user_id)

            raw = engine._runner.run(resolve_member(), timeout=30)
            return _normalise_member(raw, source="resolved") if raw else None
        except Exception:
            return None


def _field(value: Any, *names: str) -> Any:
    for name in names:
        if isinstance(value, dict) and name in value:
            return value[name]
        if hasattr(value, name):
            return getattr(value, name)
    return None


def _normalise_member(member: Any, source: str) -> dict[str, str]:
    first_name = str(_field(member, "first_name") or "").strip()
    last_name = str(_field(member, "last_name") or "").strip()
    name = str(_field(member, "name") or "").strip() or " ".join(
        part for part in (first_name, last_name) if part
    )
    return {
        "id": str(_field(member, "id") or ""),
        "name": name or "کاربر",
        "username": str(_field(member, "username") or ""),
        "source": source,
    }


def _message_content_type(raw: Any) -> str:
    if _field(raw, "photo") is not None:
        return "photo"
    if _field(raw, "video") is not None:
        return "video"
    if _field(raw, "voice") is not None:
        return "voice"
    if _field(raw, "audio") is not None:
        return "audio"
    if _field(raw, "document", "file") is not None:
        return "file"
    if _field(raw, "sticker") is not None:
        return "sticker"
    if _field(raw, "gif") is not None:
        return "gif"
    if _field(raw, "media") is not None:
        return "media"
    return "text"


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _has_management_rights(permissions: Any) -> bool:
    if not isinstance(permissions, dict):
        return False
    return bool(
        permissions.get("is_creator")
        or permissions.get("is_admin")
        or permissions.get("can_manage")
        or permissions.get("can_ban_users")
    )
