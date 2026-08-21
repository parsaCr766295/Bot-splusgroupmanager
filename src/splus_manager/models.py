from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Action(StrEnum):
    MUTE = "mute"
    BAN = "ban"
    WARN = "warn"
    WARN_REMOVE = "warn_remove"
    WARN_RESET = "warn_reset"
    AUTO_INSULT_WARN = "auto_insult_warn"
    DELETE = "delete"
    ANNOUNCEMENT = "announcement"
    AUTO_LINK_DELETE = "auto_link_delete"
    CALL_MEMBERS = "call_members"
    TAG_MEMBER = "tag_member"
    REPLY_ADD = "reply_add"
    REPLY_REMOVE = "reply_remove"
    LOCK_DELETE = "lock_delete"
    LOCK_SETTINGS = "lock_settings"
    AD_DELETE = "ad_delete"
    AD_SETTINGS = "ad_settings"
    CHAT_SCHEDULE = "chat_schedule"
    SPAM_DELETE = "spam_delete"
    FILTER_DELETE = "filter_delete"
    SPAM_SETTINGS = "spam_settings"
    LINK_LOG = "link_log"
    LINK_SETTINGS = "link_settings"
    SUPPORT_SETTINGS = "support_settings"


class AccessMode(StrEnum):
    FREE = "free"
    ADMINS = "admins"
    LOCKED = "locked"


@dataclass(frozen=True)
class Message:
    chat_id: str
    message_id: int
    sender_id: str
    text: str = ""
    reply_to_id: int | None = None
    sent_at: datetime | None = None
    is_outgoing: bool = False
    sender_name: str = ""
    sender_username: str = ""
    is_forwarded: bool = False
    content_type: str = "text"


@dataclass(frozen=True)
class GroupSettings:
    warning_limit: int = 3
    warning_action: Action = Action.MUTE
    mute_minutes: int = 60
    welcome_text: str = ""
    anti_link: bool = False
    forward_mode: AccessMode = AccessMode.FREE
    link_mode: AccessMode = AccessMode.FREE
    media_mode: AccessMode = AccessMode.FREE
    send_mode: AccessMode = AccessMode.FREE
