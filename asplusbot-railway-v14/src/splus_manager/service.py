from __future__ import annotations

import asyncio
import re
from collections import defaultdict, deque
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from time import monotonic

from .gateway import Gateway
from .models import AccessMode, Action, GroupSettings, Message
from .storage import Store

LINK_RE = re.compile(r"(?:https?://|www\.|t\.me/|splus\.ir/)", re.I)
LINK_EXTRACT_RE = re.compile(
    r"(?:(?:https?://|www\.)[^\s<>]+|(?:t\.me|telegram\.me|splus\.ir|sapp\.ir)/[^\s<>]+)",
    re.I,
)
USERNAME_RE = re.compile(r"(?<![\w@])@[A-Za-z0-9_]{4,32}\b")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?98|0098|0)?9\d{9}(?!\d)")
STRONG_AD_RE = re.compile(
    r"(?:جهت\s+سفارش|کسب\s+درآمد|تخفیف\s+ویژه|فروش\s+ویژه|"
    r"عضویت\s+در\s+(?:کانال|گروه)|تبلیغات\s+(?:پذیرفته|قبول)|قرعه[‌ -]?کشی)",
    re.I,
)
AD_WORD_RE = re.compile(r"(?:تبلیغ|فروش|خرید|تخفیف|عضویت|کانال|پیج|فالو|سفارش|درآمد)", re.I)
DURATIONS = {"15دقیقه": 15, "1ساعت": 60, "24ساعت": 1440}
COMMAND_PREFIXES = (
    "🔇", "🚫", "⚠️", "🧹", "📢", "⚙️", "📣", "➕", "🗑", "📋", "🏷️",
    "سکوت", "مسدود کردن", "اخطار", "حذف پیام", "اطلاعیه", "تنظیمات",
    "🔐", "قفل", "دسترسی", "دسترسی‌ها", "بازکردن", "حذف تبلیغات", "چت",
    "ضداسپم", "فیلتر", "پردازش لینک", "پشتیبانی", "صدا زدن اعضا",
    "افزودن جواب", "اضافه کردن جواب",
    "حذف جواب", "جواب‌ها", "تگ",
)
PANEL_COMMANDS = {
    "پنل", "راهنما", "📋 راهنما",
    "👥 مدیریت اعضا", "⚙️ تنظیمات گروه", "🛡️ مدیریت",
    "🔐 قفل‌ها", "🔐 قفل پیشرفته و دسترسی‌ها",
    "🧹 حذف تبلیغات",
    "⏰ زمان‌بندی چت",
    "🛡 ضداسپم و فیلترها",
    "🔗 پردازش لینک",
}
STATUS_COMMANDS = {"🤖 وضعیت", "/status", "وضعیت ربات"}
PUBLIC_COMMANDS = {
    "📋 راهنما", "راهنما", "📞 پشتیبانی", "☎️ پشتیبانی",
    "پشتیبانی", "ارتباط با پشتیبانی",
}
MEDIA_TYPES = {"photo", "video", "voice", "audio", "file", "sticker", "gif", "media"}
MODE_NAMES = {
    AccessMode.FREE: "آزاد",
    AccessMode.ADMINS: "فقط ادمین",
    AccessMode.LOCKED: "کاملاً قفل",
}
DEFAULT_PERMISSIONS = {
    "send_messages": True,
    "send_media": True,
    "send_stickers": True,
    "send_gifs": True,
    "send_games": True,
    "send_inline": True,
    "embed_link_previews": True,
    "send_polls": True,
    "change_info": True,
    "invite_users": True,
    "pin_messages": True,
}
PERMISSION_LABELS = {
    "send_messages": "ارسال پیام",
    "send_media": "رسانه و فایل",
    "send_stickers": "استیکر",
    "send_gifs": "GIF",
    "send_games": "بازی",
    "send_inline": "ربات درون‌خطی",
    "embed_link_previews": "پیش‌نمایش لینک",
    "send_polls": "نظرسنجی",
    "change_info": "تغییر اطلاعات گروه",
    "invite_users": "افزودن عضو",
    "pin_messages": "سنجاق پیام",
}
PERMISSION_ALIASES = {
    "پیام": "send_messages", "ارسال پیام": "send_messages",
    "رسانه": "send_media", "فایل": "send_media", "رسانه و فایل": "send_media",
    "استیکر": "send_stickers", "گیف": "send_gifs", "gif": "send_gifs",
    "بازی": "send_games", "ربات": "send_inline", "ربات درون خطی": "send_inline",
    "ربات درون‌خطی": "send_inline", "پیش نمایش لینک": "embed_link_previews",
    "پیش‌نمایش لینک": "embed_link_previews", "نظرسنجی": "send_polls",
    "تغییر اطلاعات": "change_info", "تغییر اطلاعات گروه": "change_info",
    "افزودن عضو": "invite_users", "دعوت عضو": "invite_users",
    "سنجاق": "pin_messages", "سنجاق پیام": "pin_messages", "پین": "pin_messages",
}
DEFAULT_AD_FILTERS = {
    "link": False,
    "username": False,
    "phone": False,
    "forward": False,
    "keywords": False,
}
AD_FILTER_LABELS = {
    "link": "لینک و لینک دعوت",
    "username": "آیدی @username",
    "phone": "شماره تماس",
    "forward": "پیام فورواردی",
    "keywords": "عبارت‌های تبلیغاتی",
}
AD_FILTER_ALIASES = {
    "لینک": "link", "دعوت": "link", "لینک دعوت": "link",
    "آیدی": "username", "ایدی": "username", "نام کاربری": "username",
    "شماره": "phone", "شماره تماس": "phone", "تلفن": "phone",
    "فوروارد": "forward", "فورواردی": "forward",
    "کلمات": "keywords", "عبارت": "keywords", "عبارت تبلیغاتی": "keywords",
}
DEFAULT_SPAM_OPTIONS: dict[str, bool | int] = {
    "enabled": False,
    "flood_enabled": True,
    "duplicate_enabled": True,
    "mentions_enabled": True,
    "repeat_chars_enabled": True,
    "length_enabled": True,
    "word_filter_enabled": False,
    "flood_count": 5,
    "flood_seconds": 10,
    "duplicate_count": 3,
    "duplicate_seconds": 60,
    "mention_limit": 5,
    "repeat_char_limit": 12,
    "max_length": 1500,
}
SPAM_TOGGLE_ALIASES = {
    "فلود": "flood_enabled", "سرعت": "flood_enabled",
    "تکرار": "duplicate_enabled", "تکراری": "duplicate_enabled",
    "منشن": "mentions_enabled", "تگ": "mentions_enabled",
    "کشیده": "repeat_chars_enabled", "حروف کشیده": "repeat_chars_enabled",
    "طولانی": "length_enabled", "طول": "length_enabled",
}


class Manager:
    def __init__(
        self,
        gateway: Gateway,
        store: Store,
        managed_chat: str,
        managed_chat_aliases: set[str] | None = None,
        call_members_limit: int = 500,
        call_batch_size: int = 20,
        call_batch_delay: float = 1.5,
        schedule_timezone: str = "+03:30",
    ) -> None:
        self.gateway, self.store, self.managed_chat = gateway, store, managed_chat
        self.managed_chat_aliases = {managed_chat, *(managed_chat_aliases or set())}
        self.call_members_limit = max(1, call_members_limit)
        self.call_batch_size = max(1, min(call_batch_size, 30))
        self.call_batch_delay = max(0.0, call_batch_delay)
        self.schedule_timezone = schedule_timezone
        self.started_at = datetime.now(timezone.utc)
        self._message_times: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._recent_texts: dict[tuple[str, str], deque[tuple[float, str]]] = defaultdict(deque)

    async def handle(self, message: Message) -> None:
        text = message.text.strip()
        support_request = _is_support_request(text)
        is_command = (
            text in STATUS_COMMANDS or text in PANEL_COMMANDS
            or text.startswith(COMMAND_PREFIXES) or support_request
        )
        if not _chat_id_matches(message.chat_id, self.managed_chat_aliases):
            if is_command:
                print(
                    "[COMMAND IGNORED] شناسه گروه رویداد با تنظیمات برابر نیست: "
                    f"chat_id={message.chat_id!r} configured={sorted(self.managed_chat_aliases)!r}",
                    flush=True,
                )
            return
        if is_command:
            print(
                f"[COMMAND RECEIVED] chat_id={message.chat_id!r} "
                f"sender_id={message.sender_id!r} outgoing={message.is_outgoing} text={text!r}",
                flush=True,
            )
        if is_command and text not in PUBLIC_COMMANDS and not support_request:
            # Commands stay usable while every normal message is locked.
            if not await self.gateway.is_group_admin(message.chat_id, message.sender_id):
                await self.gateway.send_message(message.chat_id, "⛔ مجوز ادمین شما از سمت سرور تأیید نشد؛ هیچ عملیاتی انجام نشد.")
                return
        if not message.is_outgoing:
            await self._process_links(message)
        if support_request:
            await self._show_support(message)
            return
        if text in STATUS_COMMANDS:
            uptime = datetime.now(timezone.utc) - self.started_at
            await self.gateway.send_message(
                message.chat_id,
                "🤖 پنل وضعیت مدیر گروه\n\n"
                "🟢 وضعیت ربات: آنلاین\n"
                "👑 نقش: مالک / ادمین\n"
                "\n👥 مدیریت اعضا\n"
                "⚙️ تنظیمات گروه\n"
                "🛡️ مدیریت\n\n"
                f"⏱ زمان فعالیت: {int(uptime.total_seconds() // 60)} دقیقه",
            )
            return
        if text in PANEL_COMMANDS and await self._panel(message):
            return
        settings = self.store.settings(message.chat_id)
        if is_command:
            await self._command(message)
            return
        if await self._enforce_locks(message, settings):
            return
        if await self._enforce_ad_filters(message):
            return
        if await self._enforce_spam_and_words(message):
            return
        if not message.is_outgoing:
            response = self.store.find_reply(message.chat_id, message.text)
            if response:
                await self.gateway.send_message(message.chat_id, response)
                return

    async def _panel(self, message: Message) -> bool:
        text = message.text.strip()
        panels = {
            "پنل": (
                "🛠 پنل مدیر گروه\n\n"
                "📋 راهنما — نمایش همهٔ دستورات\n\n"
                "📞 پشتیبانی — ارتباط با پشتیبانی\n\n"
                "👥 مدیریت اعضا\n"
                "⚙️ تنظیمات گروه\n"
                "🛡️ مدیریت\n\n"
                "🔐 قفل پیشرفته و دسترسی‌ها\n\n"
                "🧹 حذف تبلیغات\n\n"
                "⏰ زمان‌بندی چت\n\n"
                "🛡 ضداسپم و فیلترها\n\n"
                "🔗 پردازش لینک\n\n"
                "برای دیدن فرمان‌های هر بخش، عنوان آن را ارسال کنید."
            ),
            "👥 مدیریت اعضا": (
                "👥 مدیریت اعضا\n\n"
                "روی پیام کاربر ریپلای کنید و بنویسید:\n"
                "• سکوت ۵دقیقه\n"
                "• اخطار\n"
                "• مسدود کردن\n"
                "• حذف پیام"
            ),
            "⚙️ تنظیمات گروه": (
                "⚙️ تنظیمات گروه\n\n"
                "💾 ذخیره‌سازی: SQLite\n"
                "نمونه فرمان:\n"
                "تنظیمات اخطار=3 سکوت=1h ضدلینک=روشن خوش‌آمد=سلام_{name}\n\n"
                "برای خاموش‌کردن ضدلینک: تنظیمات ضدلینک=خاموش"
            ),
            "🛡️ مدیریت": (
                "🛡️ مدیریت\n\n"
                "• اطلاعیه متن اطلاعیه\n"
                "• 🤖 وضعیت\n"
                "• صدا زدن اعضا (ارسال مرحله‌ای برای گروه‌های شلوغ)\n"
                "• صدا زدن اعضا جلسه شروع شد\n"
                "• تگ لطفاً پاسخ بده (با ریپلای روی پیام عضو)\n"
                "• افزودن جواب سلام | درود، خوش آمدید\n"
                "• حذف جواب سلام\n"
                "• جواب‌ها\n\n"
                "همهٔ عملیات موفق در گزارش مدیریت ثبت می‌شوند."
            ),
            "🔐 قفل‌ها": _advanced_permissions_help(),
            "🔐 قفل پیشرفته و دسترسی‌ها": _advanced_permissions_help(),
            "🧹 حذف تبلیغات": _ad_filter_help(),
            "⏰ زمان‌بندی چت": _chat_schedule_help(),
            "🛡 ضداسپم و فیلترها": _spam_help(),
            "🔗 پردازش لینک": _link_processing_help(),
            "راهنما": _full_help(),
            "📋 راهنما": _full_help(),
        }
        response = panels.get(text)
        if response is None:
            return False
        await self.gateway.send_message(message.chat_id, response)
        return True

    async def member_joined(self, chat_id: str, user_id: str, name: str) -> None:
        """Call this from the provider's member-joined event."""
        if not _chat_id_matches(chat_id, self.managed_chat_aliases):
            return
        template = self.store.settings(chat_id).welcome_text
        if template:
            await self.gateway.send_message(chat_id, template.replace("{name}", name))

    async def _target(self, message: Message) -> Message | None:
        if message.reply_to_id is None:
            await self.gateway.send_message(message.chat_id, "این دستور باید روی پیام کاربر ریپلای شود.")
            return None
        target = await self.gateway.get_message(message.chat_id, message.reply_to_id)
        if not target:
            await self.gateway.send_message(message.chat_id, "پیام موردنظر پیدا نشد.")
        return target

    async def _command(self, message: Message) -> None:
        text = message.text.strip()
        if text.startswith("پشتیبانی"):
            await self._support_command(message)
            return
        if text.startswith("پردازش لینک"):
            await self._link_processing_command(message)
            return
        if text.startswith("ضداسپم"):
            await self._spam_settings(message)
            return
        if text.startswith("فیلتر"):
            await self._word_filter_settings(message)
            return
        if text.startswith("چت"):
            await self._chat_schedule_command(message)
            return
        if text.startswith("حذف تبلیغات"):
            await self._ad_filter_settings(message)
            return
        if (
            text.startswith(("دسترسی", "دسترسی‌ها", "بازکردن", "قفل پیشرفته"))
            or _is_simple_permission_lock(text)
        ):
            await self._advanced_permissions(message)
            return
        if text.startswith(("🔐", "قفل")):
            await self._locks(message)
            return
        if text.startswith(("📣", "صدا زدن اعضا")):
            await self._call_members(message)
            return
        if text.startswith(("➕", "افزودن جواب", "اضافه کردن جواب")):
            await self._add_reply(message)
            return
        if text.startswith(("🗑", "حذف جواب")):
            trigger = text.removeprefix("🗑").removeprefix("حذف جواب").strip()
            if trigger:
                removed = self.store.remove_reply(message.chat_id, trigger)
                await self.gateway.send_message(message.chat_id, "✅ جواب حذف شد." if removed else "جوابی با این عبارت پیدا نشد.")
                if removed:
                    self.store.log(message.chat_id, message.sender_id, None, Action.REPLY_REMOVE, trigger)
            return
        if text.startswith(("📋", "جواب‌ها")):
            triggers = self.store.list_replies(message.chat_id)
            body = "\n".join(f"• {item}" for item in triggers) or "هنوز پاسخ خودکاری ثبت نشده است."
            await self.gateway.send_message(message.chat_id, f"📋 پاسخ‌های خودکار\n\n{body}")
            return
        if text.startswith(("📢", "اطلاعیه")):
            body = text.removeprefix("📢").removeprefix("اطلاعیه").strip()
            if body:
                await self.gateway.send_message(message.chat_id, body)
                self.store.log(message.chat_id, message.sender_id, None, Action.ANNOUNCEMENT, body)
            return
        if text.startswith(("⚙️", "تنظیمات")):
            await self._settings(message)
            return
        if text.startswith(("🏷️", "تگ")):
            await self._tag_member(message)
            return
        target = await self._target(message)
        if target is None:
            return
        # Never discipline other group admins.
        if await self.gateway.is_group_admin(message.chat_id, target.sender_id):
            await self.gateway.send_message(message.chat_id, "امکان اعمال مدیریت روی ادمین گروه وجود ندارد.")
            return
        if text.startswith(("🧹", "حذف پیام")):
            await self.gateway.delete_message(message.chat_id, target.message_id)
            self.store.log(message.chat_id, message.sender_id, target.sender_id, Action.DELETE, str(target.message_id))
        elif text.startswith(("🚫", "مسدود کردن")):
            await self.gateway.ban_member(message.chat_id, target.sender_id)
            self.store.log(message.chat_id, message.sender_id, target.sender_id, Action.BAN, "manual")
        elif text.startswith(("⚠️", "اخطار")):
            count = self.store.add_warning(message.chat_id, target.sender_id)
            s = self.store.settings(message.chat_id)
            self.store.log(message.chat_id, message.sender_id, target.sender_id, Action.WARN, f"count={count}")
            await self.gateway.send_message(message.chat_id, f"⚠️ اخطار {count} از {s.warning_limit} ثبت شد.")
            if count >= s.warning_limit:
                await self._apply_warning_action(message, target.sender_id)
        elif text.startswith(("🔇", "سکوت")):
            minutes = next((v for k, v in DURATIONS.items() if k in text), None) or _find_duration(text)
            if minutes is None:
                await self.gateway.send_message(message.chat_id, "مدت را انتخاب کنید: 15دقیقه، 1ساعت یا 24ساعت")
                return
            await self._mute(message, target.sender_id, minutes)

    async def _enforce_locks(self, message: Message, settings: GroupSettings) -> bool:
        # Outgoing events include the userbot's own replies; never delete them.
        if message.is_outgoing:
            return False
        needs_inspection = (
            settings.forward_mode is not AccessMode.FREE
            or settings.media_mode is not AccessMode.FREE
        )
        inspected = await self.gateway.inspect_message(message) if needs_inspection else message
        admin_needed = any(
            mode is AccessMode.ADMINS
            for mode in (
                settings.forward_mode, settings.link_mode,
                settings.media_mode, settings.send_mode,
            )
        ) or settings.anti_link
        is_admin = await self.gateway.is_group_admin(message.chat_id, message.sender_id) if admin_needed else False
        reasons: list[str] = []
        if _mode_blocks(settings.send_mode, is_admin):
            reasons.append("ارسال")
        if inspected.is_forwarded and _mode_blocks(settings.forward_mode, is_admin):
            reasons.append("فوروارد")
        link_mode = settings.link_mode
        if settings.anti_link and link_mode is AccessMode.FREE:
            link_mode = AccessMode.ADMINS
        if LINK_RE.search(inspected.text) and _mode_blocks(link_mode, is_admin):
            reasons.append("لینک")
        if inspected.content_type in MEDIA_TYPES and _mode_blocks(settings.media_mode, is_admin):
            reasons.append("رسانه")
        if not reasons:
            return False
        await self.gateway.delete_message(message.chat_id, message.message_id)
        self.store.log(
            message.chat_id, "system", message.sender_id,
            Action.LOCK_DELETE, f"message={message.message_id};reasons={','.join(reasons)}",
        )
        return True

    async def _locks(self, message: Message) -> None:
        raw = _remove_prefix(message.text, "🔐", "قفل")
        current = self.store.settings(message.chat_id)
        if raw in {"", "وضعیت"}:
            await self.gateway.send_message(message.chat_id, _lock_status(current))
            return
        match = re.fullmatch(
            r"(فوروارد|لینک|آیدی|رسانه|فایل|ارسال|همه)\s+"
            r"(آزاد|فقط\s*ادمین|کاملا?ً?\s*قفل)",
            raw,
        )
        if not match:
            await self.gateway.send_message(
                message.chat_id,
                "فرمان نامعتبر است. نمونه: قفل همه فقط ادمین\n"
                "حالت‌ها: آزاد، فقط ادمین، کاملاً قفل",
            )
            return
        target, mode_text = match.groups()
        mode = _parse_access_mode(mode_text)
        field_map = {
            "فوروارد": "forward_mode", "لینک": "link_mode", "آیدی": "link_mode",
            "رسانه": "media_mode", "فایل": "media_mode", "ارسال": "send_mode",
        }
        if target == "همه":
            updated = replace(
                current, forward_mode=mode, link_mode=mode,
                media_mode=mode, send_mode=mode,
            )
        else:
            updated = replace(current, **{field_map[target]: mode})
        self.store.save_settings(message.chat_id, updated)
        self.store.log(
            message.chat_id, message.sender_id, None,
            Action.LOCK_SETTINGS, f"target={target};mode={mode}",
        )
        await self.gateway.send_message(message.chat_id, f"✅ قفل {target}: {MODE_NAMES[mode]}")

    async def _advanced_permissions(self, message: Message) -> None:
        current = self.store.permissions(message.chat_id, DEFAULT_PERMISSIONS)
        parsed = _parse_permission_command(message.text)
        if parsed is None:
            await self.gateway.send_message(message.chat_id, _permissions_status(current))
            return
        target, allowed = parsed
        updated = dict(current)
        if target == "all":
            updated = {key: allowed for key in updated}
            target_label = "همهٔ دسترسی‌ها"
        else:
            updated[target] = allowed
            target_label = PERMISSION_LABELS[target]
        try:
            success = await self.gateway.set_default_permissions(message.chat_id, updated)
        except Exception as exc:
            await self.gateway.send_message(
                message.chat_id,
                f"❌ سرور سروش تغییر دسترسی را نپذیرفت: {exc}",
            )
            return
        if not success:
            await self.gateway.send_message(
                message.chat_id,
                "❌ تغییر دسترسی در سرور سروش انجام نشد؛ مجوز مدیریت گروه را بررسی کنید.",
            )
            return
        self.store.save_permissions(message.chat_id, updated)
        self.store.log(
            message.chat_id, message.sender_id, None, Action.LOCK_SETTINGS,
            f"permission={target};allowed={allowed}",
        )
        state = "مجاز ✅" if allowed else "قفل شد 🔒"
        await self.gateway.send_message(message.chat_id, f"{target_label}: {state}")

    async def _enforce_ad_filters(self, message: Message) -> bool:
        if message.is_outgoing:
            return False
        filters = self.store.ad_filters(message.chat_id, DEFAULT_AD_FILTERS)
        if not any(filters.values()):
            return False
        if await self.gateway.is_group_admin(message.chat_id, message.sender_id):
            return False
        inspected = await self.gateway.inspect_message(message) if filters["forward"] else message
        reasons: list[str] = []
        if filters["link"] and LINK_RE.search(inspected.text):
            reasons.append("link")
        if filters["username"] and USERNAME_RE.search(inspected.text):
            reasons.append("username")
        if filters["phone"] and PHONE_RE.search(inspected.text):
            reasons.append("phone")
        if filters["forward"] and inspected.is_forwarded:
            reasons.append("forward")
        if filters["keywords"] and _looks_like_advertising(inspected.text):
            reasons.append("keywords")
        if not reasons:
            return False
        await self.gateway.delete_message(message.chat_id, message.message_id)
        self.store.log(
            message.chat_id, "system", message.sender_id, Action.AD_DELETE,
            f"message={message.message_id};reasons={','.join(reasons)}",
        )
        return True

    async def _ad_filter_settings(self, message: Message) -> None:
        current = self.store.ad_filters(message.chat_id, DEFAULT_AD_FILTERS)
        parsed = _parse_ad_filter_command(message.text)
        if parsed is None:
            await self.gateway.send_message(message.chat_id, _ad_filter_status(current))
            return
        target, enabled = parsed
        updated = dict(current)
        if target == "all":
            updated = {key: enabled for key in updated}
            label = "همهٔ فیلترهای تبلیغات"
        else:
            updated[target] = enabled
            label = AD_FILTER_LABELS[target]
        self.store.save_ad_filters(message.chat_id, updated)
        self.store.log(
            message.chat_id, message.sender_id, None, Action.AD_SETTINGS,
            f"filter={target};enabled={enabled}",
        )
        state = "روشن ✅" if enabled else "خاموش ⭕"
        await self.gateway.send_message(message.chat_id, f"🧹 {label}: {state}")

    async def _enforce_spam_and_words(self, message: Message) -> bool:
        if message.is_outgoing:
            return False
        options = self.store.spam_options(message.chat_id, DEFAULT_SPAM_OPTIONS)
        if not bool(options["enabled"]) and not bool(options["word_filter_enabled"]):
            return False
        if await self.gateway.is_group_admin(message.chat_id, message.sender_id):
            return False
        text = message.text or ""
        normal = _normalize_spam_text(text)
        if bool(options["word_filter_enabled"]):
            matched = next(
                (phrase for phrase in self.store.list_filter_words(message.chat_id) if _phrase_matches(normal, phrase)),
                None,
            )
            if matched:
                await self.gateway.delete_message(message.chat_id, message.message_id)
                self.store.log(
                    message.chat_id, "system", message.sender_id, Action.FILTER_DELETE,
                    f"message={message.message_id};phrase={matched}",
                )
                return True
        if not bool(options["enabled"]):
            return False
        now = monotonic()
        key = (message.chat_id, message.sender_id)
        reasons: list[str] = []
        if bool(options["flood_enabled"]):
            window = self._message_times[key]
            seconds = int(options["flood_seconds"])
            while window and now - window[0] > seconds:
                window.popleft()
            window.append(now)
            if len(window) > int(options["flood_count"]):
                reasons.append("flood")
        if bool(options["duplicate_enabled"]) and normal:
            recent = self._recent_texts[key]
            seconds = int(options["duplicate_seconds"])
            while recent and now - recent[0][0] > seconds:
                recent.popleft()
            recent.append((now, normal))
            if sum(1 for _, previous in recent if previous == normal) >= int(options["duplicate_count"]):
                reasons.append("duplicate")
        if bool(options["mentions_enabled"]) and len(USERNAME_RE.findall(text)) > int(options["mention_limit"]):
            reasons.append("mentions")
        if bool(options["repeat_chars_enabled"]):
            limit = int(options["repeat_char_limit"])
            if re.search(rf"(.)\1{{{limit},}}", text, re.DOTALL):
                reasons.append("repeat_chars")
        if bool(options["length_enabled"]) and len(text) > int(options["max_length"]):
            reasons.append("length")
        if not reasons:
            return False
        await self.gateway.delete_message(message.chat_id, message.message_id)
        self.store.log(
            message.chat_id, "system", message.sender_id, Action.SPAM_DELETE,
            f"message={message.message_id};reasons={','.join(reasons)}",
        )
        return True

    async def _process_links(self, message: Message) -> None:
        if not self.store.link_processing_enabled(message.chat_id):
            return
        links = list(dict.fromkeys(_extract_links(message.text)))
        for link in links:
            link_type = _link_type(link)
            self.store.record_link(
                message.chat_id, message.message_id, message.sender_id, link, link_type,
            )
            self.store.log(
                message.chat_id, message.sender_id, None, Action.LINK_LOG,
                f"message={message.message_id};type={link_type};link={link}",
            )

    async def _show_support(self, message: Message) -> None:
        contact = self.store.support_contact(message.chat_id)
        if not contact:
            await self.gateway.send_message(
                message.chat_id,
                "📞 پشتیبانی\n\nهنوز راه ارتباط با پشتیبانی توسط ادمین تنظیم نشده است.",
            )
            return
        await self.gateway.send_message(
            message.chat_id,
            f"📞 پشتیبانی\n\nارتباط با پشتیبانی:\n{contact}",
        )

    async def _support_command(self, message: Message) -> None:
        raw = _remove_prefix(message.text, "پشتیبانی").strip()
        normal = _normal_permission_text(raw)
        if normal.startswith("تنظیم "):
            contact = raw.split(" ", 1)[1].strip()
            if not contact or len(contact) > 300:
                await self.gateway.send_message(
                    message.chat_id, "متن پشتیبانی باید بین ۱ تا ۳۰۰ نویسه باشد.",
                )
                return
            self.store.save_support_contact(message.chat_id, contact)
            self.store.log(
                message.chat_id, message.sender_id, None,
                Action.SUPPORT_SETTINGS, "contact_updated",
            )
            await self.gateway.send_message(message.chat_id, "✅ اطلاعات پشتیبانی ذخیره شد.")
            return
        if normal in {"حذف", "پاکسازی", "خاموش"}:
            self.store.save_support_contact(message.chat_id, "")
            self.store.log(
                message.chat_id, message.sender_id, None,
                Action.SUPPORT_SETTINGS, "contact_removed",
            )
            await self.gateway.send_message(message.chat_id, "⭕ اطلاعات پشتیبانی حذف شد.")
            return
        if normal == "وضعیت":
            await self._show_support(message)
            return
        await self.gateway.send_message(message.chat_id, _support_help())

    async def _link_processing_command(self, message: Message) -> None:
        raw = _normal_permission_text(_remove_prefix(message.text, "پردازش لینک"))
        if raw in {"روشن", "فعال"}:
            self.store.save_link_processing(message.chat_id, True)
            self.store.log(
                message.chat_id, message.sender_id, None,
                Action.LINK_SETTINGS, "enabled=True",
            )
            await self.gateway.send_message(
                message.chat_id,
                "✅ پردازش لینک روشن شد؛ همهٔ لینک‌ها فقط در گزارش ثبت می‌شوند.",
            )
            return
        if raw in {"خاموش", "غیرفعال"}:
            self.store.save_link_processing(message.chat_id, False)
            self.store.log(
                message.chat_id, message.sender_id, None,
                Action.LINK_SETTINGS, "enabled=False",
            )
            await self.gateway.send_message(message.chat_id, "⭕ پردازش لینک خاموش شد.")
            return
        if raw.startswith(("گزارش", "لیست", "فهرست")):
            match = re.search(r"\d+", _normal_digits(raw))
            limit = max(1, min(int(match.group()) if match else 10, 50))
            reports = self.store.recent_links(message.chat_id, limit)
            if not reports:
                await self.gateway.send_message(message.chat_id, "هنوز لینکی ثبت نشده است.")
                return
            lines = ["🔗 آخرین لینک‌های ثبت‌شده", ""]
            for item in reports:
                label = "گروه/کانال" if item["link_type"] == "group_channel" else "سایت"
                timestamp = item["created_at"][:16].replace("T", " ")
                lines.append(
                    f"• {label} | عضو: {item['sender_id']} | پیام: {item['message_id']}\n"
                    f"  {item['link']}\n  {timestamp} UTC"
                )
            await self.gateway.send_message(message.chat_id, "\n".join(lines))
            return
        if raw in {"", "وضعیت"}:
            enabled = self.store.link_processing_enabled(message.chat_id)
            state = "روشن ✅" if enabled else "خاموش ⭕"
            await self.gateway.send_message(
                message.chat_id,
                f"🔗 پردازش لینک: {state}\nحالت: ثبت همهٔ لینک‌های گروه، کانال و سایت در گزارش",
            )
            return
        await self.gateway.send_message(message.chat_id, _link_processing_help())

    async def _spam_settings(self, message: Message) -> None:
        options = self.store.spam_options(message.chat_id, DEFAULT_SPAM_OPTIONS)
        raw = _normal_permission_text(_normal_digits(_remove_prefix(message.text, "ضداسپم")))
        if raw in {"", "وضعیت"}:
            await self.gateway.send_message(message.chat_id, _spam_status(options))
            return
        updated = dict(options)
        if raw in {"روشن", "فعال"}:
            updated["enabled"] = True
        elif raw in {"خاموش", "غیرفعال"}:
            updated["enabled"] = False
        elif raw in {"همه روشن", "همه فعال"}:
            updated["enabled"] = True
            for key in SPAM_TOGGLE_ALIASES.values():
                updated[key] = True
        elif raw in {"همه خاموش", "همه غیرفعال"}:
            updated["enabled"] = False
            for key in SPAM_TOGGLE_ALIASES.values():
                updated[key] = False
        else:
            toggle = re.fullmatch(r"(.+?)\s+(روشن|فعال|خاموش|غیرفعال)", raw)
            if toggle and toggle.group(1) in SPAM_TOGGLE_ALIASES:
                updated[SPAM_TOGGLE_ALIASES[toggle.group(1)]] = toggle.group(2) in {"روشن", "فعال"}
            else:
                parsed = _parse_spam_limits(raw)
                if parsed is None:
                    await self.gateway.send_message(message.chat_id, _spam_help())
                    return
                updated.update(parsed)
        self.store.save_spam_options(message.chat_id, updated)
        self.store.log(
            message.chat_id, message.sender_id, None, Action.SPAM_SETTINGS, raw,
        )
        await self.gateway.send_message(message.chat_id, "✅ تنظیمات ضداسپم ذخیره شد.")

    async def _word_filter_settings(self, message: Message) -> None:
        raw = _remove_prefix(message.text, "فیلتر").strip()
        options = self.store.spam_options(message.chat_id, DEFAULT_SPAM_OPTIONS)
        normal = _normal_permission_text(raw)
        if normal in {"روشن", "فعال"}:
            options["word_filter_enabled"] = True
            self.store.save_spam_options(message.chat_id, options)
            await self.gateway.send_message(message.chat_id, "✅ فیلتر کلمات روشن شد.")
            return
        if normal in {"خاموش", "غیرفعال"}:
            options["word_filter_enabled"] = False
            self.store.save_spam_options(message.chat_id, options)
            await self.gateway.send_message(message.chat_id, "⭕ فیلتر کلمات خاموش شد.")
            return
        if normal in {"", "وضعیت", "لیست", "فهرست"}:
            words = self.store.list_filter_words(message.chat_id)
            body = "\n".join(f"• {word}" for word in words) or "هنوز کلمه‌ای ثبت نشده است."
            state = "روشن ✅" if bool(options["word_filter_enabled"]) else "خاموش ⭕"
            await self.gateway.send_message(message.chat_id, f"📝 فیلتر کلمات: {state}\n\n{body}")
            return
        if normal in {"پاکسازی", "پاک کردن همه", "حذف همه"}:
            count = self.store.clear_filter_words(message.chat_id)
            await self.gateway.send_message(message.chat_id, f"🗑 {count} عبارت از فیلتر پاک شد.")
            return
        if normal.startswith(("افزودن ", "اضافه کردن ")):
            phrase = raw.split(" ", 1)[1].strip()
            if not phrase or len(phrase) > 100:
                await self.gateway.send_message(message.chat_id, "عبارت فیلتر باید بین ۱ تا ۱۰۰ نویسه باشد.")
                return
            self.store.add_filter_word(message.chat_id, phrase, message.sender_id)
            await self.gateway.send_message(message.chat_id, f"✅ «{phrase}» به فیلتر اضافه شد.")
            return
        if normal.startswith("حذف "):
            phrase = raw.split(" ", 1)[1].strip()
            removed = self.store.remove_filter_word(message.chat_id, phrase)
            await self.gateway.send_message(
                message.chat_id,
                "✅ عبارت حذف شد." if removed else "این عبارت در فیلتر نبود.",
            )
            return
        await self.gateway.send_message(message.chat_id, _spam_help())

    async def _chat_schedule_command(self, message: Message) -> None:
        raw = _normal_digits(_remove_prefix(message.text, "چت"))
        schedule = self.store.chat_schedule(message.chat_id, self.schedule_timezone)
        if raw in {"", "وضعیت"}:
            await self.gateway.send_message(message.chat_id, _chat_schedule_status(schedule))
            return
        if raw == "باز":
            if schedule.get("emergency_until"):
                self.store.save_chat_emergency(message.chat_id, None)
            await self._apply_chat_open_state(message.chat_id, True, message.sender_id, notify=False)
            self.store.save_chat_schedule_state(message.chat_id, "open")
            await self.gateway.send_message(message.chat_id, "🔓 چت برای اعضا باز شد.")
            return
        if raw in {"بسته", "بستن"}:
            await self._apply_chat_open_state(message.chat_id, False, message.sender_id, notify=False)
            self.store.save_chat_schedule_state(message.chat_id, "closed")
            await self.gateway.send_message(message.chat_id, "🔒 چت برای اعضا بسته شد.")
            return
        if raw in {"خودکار خاموش", "زمانبندی خاموش", "زمان‌بندی خاموش"}:
            self.store.save_chat_schedule(
                message.chat_id, enabled=False,
                close_time=str(schedule["close_time"]), open_time=str(schedule["open_time"]),
                timezone=str(schedule["timezone"]), last_state=str(schedule["last_state"] or "") or None,
                emergency_until=str(schedule["emergency_until"] or "") or None,
            )
            await self.gateway.send_message(message.chat_id, "⭕ باز و بسته‌شدن خودکار چت خاموش شد.")
            return
        if raw.startswith("اضطراری"):
            emergency_raw = raw.removeprefix("اضطراری").strip()
            if emergency_raw in {"لغو", "خاموش", "پایان"}:
                self.store.save_chat_emergency(message.chat_id, None)
                await self.gateway.send_message(message.chat_id, "⭕ حالت اضطراری لغو شد.")
                if bool(schedule["enabled"]):
                    await self.scheduled_tick()
                else:
                    await self._apply_chat_open_state(message.chat_id, True, message.sender_id, notify=True)
                    self.store.save_chat_schedule_state(message.chat_id, "open")
                return
            minutes = _find_duration(emergency_raw)
            if minutes is None or minutes < 1 or minutes > 7 * 24 * 60:
                await self.gateway.send_message(
                    message.chat_id,
                    "نمونه: چت اضطراری ۳۰دقیقه یا چت اضطراری ۲ساعت (حداکثر ۷ روز)",
                )
                return
            until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
            self.store.save_chat_schedule(
                message.chat_id, enabled=bool(schedule["enabled"]),
                close_time=str(schedule["close_time"]), open_time=str(schedule["open_time"]),
                timezone=str(schedule["timezone"]), last_state=None,
                emergency_until=until.isoformat(),
            )
            await self._apply_chat_open_state(message.chat_id, False, message.sender_id, notify=False)
            self.store.save_chat_schedule_state(message.chat_id, "emergency")
            self.store.log(
                message.chat_id, message.sender_id, None, Action.CHAT_SCHEDULE,
                f"emergency_minutes={minutes};until={until.isoformat()}",
            )
            await self.gateway.send_message(
                message.chat_id,
                f"🚨 چت اضطراری برای {minutes} دقیقه بسته شد و سپس خودکار باز/زمان‌بندی می‌شود.",
            )
            return
        match = re.fullmatch(
            r"(?:خودکار|زمان[‌-]?بندی)\s+(\d{1,2}:\d{2})\s*(?:تا|-|الی)\s*(\d{1,2}:\d{2})",
            raw,
        )
        if not match or not all(_valid_clock(item) for item in match.groups()):
            await self.gateway.send_message(
                message.chat_id,
                "فرمان نامعتبر است. نمونه: چت خودکار 23:00 تا 07:00",
            )
            return
        close_time, open_time = (_canonical_clock(item) for item in match.groups())
        self.store.save_chat_schedule(
            message.chat_id, enabled=True, close_time=close_time, open_time=open_time,
            timezone=self.schedule_timezone, last_state=None,
            emergency_until=str(schedule["emergency_until"] or "") or None,
        )
        self.store.log(
            message.chat_id, message.sender_id, None, Action.CHAT_SCHEDULE,
            f"enabled=true;close={close_time};open={open_time};timezone={self.schedule_timezone}",
        )
        await self.gateway.send_message(
            message.chat_id,
            f"⏰ زمان‌بندی فعال شد: بسته‌شدن {close_time}، بازشدن {open_time} "
            f"(منطقه زمانی {self.schedule_timezone})",
        )
        await self.scheduled_tick()

    async def scheduled_tick(self, now: datetime | None = None) -> bool:
        """Apply a persisted schedule; safe to call repeatedly from a worker."""
        schedule = self.store.chat_schedule(self.managed_chat, self.schedule_timezone)
        previous_state = schedule["last_state"]
        emergency_until = _parse_iso_datetime(schedule.get("emergency_until"))
        check_now = now or datetime.now(timezone.utc)
        emergency_active = emergency_until is not None and check_now.astimezone(timezone.utc) < emergency_until
        if emergency_until is not None and not emergency_active:
            self.store.save_chat_emergency(self.managed_chat, None)
            schedule["emergency_until"] = None
            schedule["last_state"] = None
        if not bool(schedule["enabled"]) and not emergency_active:
            if previous_state == "emergency":
                await self._apply_chat_open_state(self.managed_chat, True, "system", notify=True)
                self.store.save_chat_schedule_state(self.managed_chat, "open")
                return True
            return False
        tz = _parse_timezone(str(schedule["timezone"]))
        local_now = check_now.astimezone(tz)
        current_minutes = local_now.hour * 60 + local_now.minute
        closed = _inside_closed_period(
            current_minutes,
            _clock_minutes(str(schedule["close_time"])),
            _clock_minutes(str(schedule["open_time"])),
        )
        if emergency_active:
            closed = True
            state = "emergency"
        else:
            state = "closed" if closed else "open"
        if schedule["last_state"] == state:
            return False
        await self._apply_chat_open_state(self.managed_chat, not closed, "system", notify=True)
        self.store.save_chat_schedule_state(self.managed_chat, state)
        return True

    async def _apply_chat_open_state(
        self, chat_id: str, allowed: bool, actor_id: str, *, notify: bool,
    ) -> None:
        permissions = self.store.permissions(chat_id, DEFAULT_PERMISSIONS)
        permissions["send_messages"] = allowed
        success = await self.gateway.set_default_permissions(chat_id, permissions)
        if not success:
            raise RuntimeError("سرور سروش تغییر دسترسی ارسال پیام را نپذیرفت.")
        self.store.save_permissions(chat_id, permissions)
        self.store.log(
            chat_id, actor_id, None, Action.CHAT_SCHEDULE,
            f"send_messages={allowed}",
        )
        if notify:
            await self.gateway.send_message(
                chat_id,
                "🔓 چت طبق برنامه باز شد." if allowed else "🔒 چت طبق برنامه بسته شد.",
            )

    async def _add_reply(self, message: Message) -> None:
        raw = _remove_prefix(message.text, "➕", "افزودن جواب", "اضافه کردن جواب")
        if "|" not in raw:
            await self.gateway.send_message(message.chat_id, "نمونه: افزودن جواب سلام | درود، خوش آمدید.")
            return
        trigger, response = (part.strip() for part in raw.split("|", 1))
        if not trigger or not response:
            await self.gateway.send_message(message.chat_id, "عبارت و پاسخ نباید خالی باشند.")
            return
        self.store.save_reply(message.chat_id, trigger, response, message.sender_id)
        self.store.log(message.chat_id, message.sender_id, None, Action.REPLY_ADD, trigger)
        await self.gateway.send_message(message.chat_id, "✅ پاسخ خودکار ذخیره شد.")

    async def _call_members(self, message: Message) -> None:
        members = await self.gateway.list_members(message.chat_id, self.call_members_limit)
        selected = [member for member in members if member.get("id") or member.get("username")]
        if not selected:
            await self.gateway.send_message(
                message.chat_id,
                "⚠️ سروش‌پلاس فهرست اعضای این گروه را در اختیار ربات نگذاشت. "
                "بعد از اینکه اعضا در گروه پیام بدهند، ربات آن‌ها را می‌شناسد؛ "
                "برای یک نفر هم روی پیامش ریپلای کنید و فرمان «تگ» را بفرستید.",
            )
            return
        note = _remove_prefix(message.text, "📣", "صدا زدن اعضا") or "فراخوان اعضا"
        batches = [
            selected[index:index + self.call_batch_size]
            for index in range(0, len(selected), self.call_batch_size)
        ]
        sent_count = 0
        for index, batch in enumerate(batches, start=1):
            heading = f"📣 {note}\nبخش {index} از {len(batches)}"
            await self._send_with_plain_fallback(
                message.chat_id,
                heading + "\n" + " ".join(_member_mention(member) for member in batch),
                heading + "\n" + " ".join(_member_plain_text(member) for member in batch),
            )
            sent_count += len(batch)
            if index < len(batches) and self.call_batch_delay:
                await asyncio.sleep(self.call_batch_delay)
        self.store.log(message.chat_id, message.sender_id, None, Action.CALL_MEMBERS, f"count={sent_count}")
        await self.gateway.send_message(message.chat_id, f"✅ فراخوان {sent_count} عضو در {len(batches)} بخش انجام شد.")
        if any(member.get("source") == "observed" for member in selected):
            await self.gateway.send_message(
                message.chat_id,
                "ℹ️ فهرست کامل از سرور دریافت نشد؛ اعضای فعالِ شناخته‌شده فراخوانی شدند.",
            )

    async def _tag_member(self, message: Message) -> None:
        target = await self._target(message)
        if target is None:
            return
        members = await self.gateway.list_members(message.chat_id)
        member = next((item for item in members if str(item.get("id", "")) == target.sender_id), None)
        member = member or {"id": target.sender_id, "name": "کاربر", "username": ""}
        note = _remove_prefix(message.text, "🏷️", "تگ")
        suffix = note or "صداتون کردند."
        await self._send_with_plain_fallback(
            message.chat_id,
            f"{_member_mention(member)} {suffix}",
            f"{_member_plain_text(member)} {suffix}",
        )
        self.store.log(message.chat_id, message.sender_id, target.sender_id, Action.TAG_MEMBER, note)

    async def _send_with_plain_fallback(self, chat_id: str, formatted: str, plain: str) -> None:
        """Retry without mention markup when Soroush rejects formatting."""
        try:
            await self.gateway.send_message(chat_id, formatted)
        except Exception:
            await self.gateway.send_message(chat_id, plain)

    async def _mute(self, message: Message, user_id: str, minutes: int) -> None:
        await self.gateway.restrict_member(message.chat_id, user_id, timedelta(minutes=minutes))
        self.store.log(message.chat_id, message.sender_id, user_id, Action.MUTE, f"minutes={minutes}")
        await self.gateway.send_message(message.chat_id, f"🔇 کاربر برای {minutes} دقیقه ساکت شد.")

    async def _apply_warning_action(self, message: Message, user_id: str) -> None:
        s = self.store.settings(message.chat_id)
        if s.warning_action is Action.BAN:
            await self.gateway.ban_member(message.chat_id, user_id)
            self.store.log(message.chat_id, "system", user_id, Action.BAN, "warning-limit")
        else:
            await self._mute(message, user_id, s.mute_minutes)

    async def _settings(self, message: Message) -> None:
        raw = message.text.removeprefix("⚙️").removeprefix("تنظیمات").strip()
        current = self.store.settings(message.chat_id)
        values = dict(re.findall(r"(اخطار|سکوت|ضدلینک|خوش‌آمد)=([^\s]+)", raw))
        try:
            updated = replace(
                current,
                warning_limit=int(values.get("اخطار", current.warning_limit)),
                mute_minutes=_parse_minutes(values.get("سکوت", f"{current.mute_minutes}m")),
                anti_link={"روشن": True, "خاموش": False}.get(values.get("ضدلینک", ""), current.anti_link),
                welcome_text=values.get("خوش‌آمد", current.welcome_text).replace("_", " "),
            )
            if updated.warning_limit < 1 or updated.mute_minutes < 1:
                raise ValueError
        except ValueError:
            await self.gateway.send_message(message.chat_id, "تنظیمات نامعتبر است. نمونه: اخطار=3 سکوت=1h ضدلینک=روشن")
            return
        self.store.save_settings(message.chat_id, updated)
        await self.gateway.send_message(message.chat_id, "⚙️ تنظیمات ذخیره شد.")


def _parse_minutes(value: str) -> int:
    if value.endswith("h"):
        return int(value[:-1]) * 60
    if value.endswith("m"):
        return int(value[:-1])
    return int(value)


def _find_duration(text: str) -> int | None:
    normal = text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    minute = re.search(r"(\d+)\s*(?:دقیقه|دقيقه)", normal)
    if minute:
        return int(minute.group(1))
    hour = re.search(r"(\d+)\s*(?:ساعت)", normal)
    if hour:
        return int(hour.group(1)) * 60
    return None


def _remove_prefix(text: str, *prefixes: str) -> str:
    value = text.strip()
    for prefix in prefixes:
        if value.startswith(prefix):
            return value[len(prefix):].strip()
    return value


def _member_mention(member: dict[str, str]) -> str:
    """Build SplusThon's username mention syntax (accepted by Soroush)."""
    username = str(member.get("username", "")).strip().lstrip("@")
    name = str(member.get("name", "")).strip() or (f"@{username}" if username else "عضو")
    safe_name = re.sub(r"([\\\[\]])", r"\\\1", name)
    if username:
        return f"[{safe_name}](@{username})"
    # Soroush rejects tg://user?id=... mentions with BAD_REQUEST. A member
    # without a username can only be addressed by visible name in this API.
    return safe_name


def _member_plain_text(member: dict[str, str]) -> str:
    username = str(member.get("username", "")).strip().lstrip("@")
    if username:
        return f"@{username}"
    return str(member.get("name", "")).strip() or "عضو"


def _parse_access_mode(value: str) -> AccessMode:
    normal = re.sub(r"\s+", " ", value.strip()).replace("كاملا", "کاملا")
    if normal == "آزاد":
        return AccessMode.FREE
    if normal.replace(" ", "") == "فقطادمین":
        return AccessMode.ADMINS
    return AccessMode.LOCKED


def _mode_blocks(mode: AccessMode, is_admin: bool) -> bool:
    if mode is AccessMode.FREE:
        return False
    if mode is AccessMode.ADMINS:
        return not is_admin
    return True


def _lock_status(settings: GroupSettings) -> str:
    return (
        "🔐 وضعیت قفل‌ها\n\n"
        f"↪️ فوروارد: {MODE_NAMES[settings.forward_mode]}\n"
        f"🔗 لینک و آیدی: {MODE_NAMES[settings.link_mode]}\n"
        f"🖼 رسانه و فایل: {MODE_NAMES[settings.media_mode]}\n"
        f"💬 ارسال پیام: {MODE_NAMES[settings.send_mode]}"
    )


def _advanced_permissions_help() -> str:
    return (
        "🔐 قفل پیشرفته و دسترسی‌های گروه\n\n"
        "این تنظیم‌ها مستقیماً روی دسترسی اعضای عادی در سرور اعمال می‌شوند.\n\n"
        "• دسترسی‌ها — نمایش وضعیت کامل\n"
        "• دسترسی پیام خاموش\n"
        "• دسترسی رسانه خاموش\n"
        "• دسترسی استیکر روشن\n"
        "• دسترسی گیف خاموش\n"
        "• دسترسی نظرسنجی خاموش\n"
        "• دسترسی افزودن عضو خاموش\n"
        "• دسترسی سنجاق پیام خاموش\n"
        "• دسترسی همه روشن / خاموش\n\n"
        "فرمان کوتاه نیز ممکن است: قفل رسانه، بازکردن رسانه"
    )


def _normal_permission_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold().replace("ي", "ی").replace("ك", "ک"))


def _is_simple_permission_lock(text: str) -> bool:
    normal = _normal_permission_text(text)
    if not normal.startswith("قفل "):
        return False
    target = normal.removeprefix("قفل ").strip()
    return target == "همه" or target in PERMISSION_ALIASES


def _parse_permission_command(text: str) -> tuple[str, bool] | None:
    normal = _normal_permission_text(text)
    if normal in {"دسترسی", "دسترسی‌ها", "دسترسی ها", "قفل پیشرفته"}:
        return None
    allowed: bool
    if normal.startswith("قفل "):
        target_text = normal.removeprefix("قفل ").strip()
        allowed = False
    elif normal.startswith("بازکردن "):
        target_text = normal.removeprefix("بازکردن ").strip()
        allowed = True
    elif normal.startswith("دسترسی "):
        body = normal.removeprefix("دسترسی ").strip()
        states = {
            " روشن": True, " فعال": True, " آزاد": True,
            " خاموش": False, " غیرفعال": False, " قفل": False,
        }
        state = next(((suffix, value) for suffix, value in states.items() if body.endswith(suffix)), None)
        if state is None:
            return None
        suffix, allowed = state
        target_text = body[:-len(suffix)].strip()
    else:
        return None
    if target_text == "همه":
        return "all", allowed
    permission = PERMISSION_ALIASES.get(target_text)
    return (permission, allowed) if permission else None


def _permissions_status(permissions: dict[str, bool]) -> str:
    lines = ["🔐 دسترسی‌های پیشرفتهٔ گروه", ""]
    for key, label in PERMISSION_LABELS.items():
        lines.append(f"{'✅' if permissions.get(key, True) else '🔒'} {label}")
    lines.extend(("", "نمونه: دسترسی رسانه خاموش", "فرمان کوتاه: قفل رسانه / بازکردن رسانه"))
    return "\n".join(lines)


def _looks_like_advertising(text: str) -> bool:
    if STRONG_AD_RE.search(text):
        return True
    return len(AD_WORD_RE.findall(text)) >= 2


def _parse_ad_filter_command(text: str) -> tuple[str, bool] | None:
    normal = _normal_permission_text(text).removeprefix("حذف تبلیغات").strip()
    if normal in {"", "وضعیت"}:
        return None
    states = {
        " روشن": True, " فعال": True,
        " خاموش": False, " غیرفعال": False,
    }
    state = next(((suffix, value) for suffix, value in states.items() if normal.endswith(suffix)), None)
    if state is None:
        return None
    suffix, enabled = state
    target_text = normal[:-len(suffix)].strip()
    if target_text in {"", "همه"}:
        return "all", enabled
    filter_name = AD_FILTER_ALIASES.get(target_text)
    return (filter_name, enabled) if filter_name else None


def _ad_filter_help() -> str:
    return (
        "🧹 حذف خودکار تبلیغات\n\n"
        "• حذف تبلیغات همه روشن\n"
        "• حذف تبلیغات لینک روشن\n"
        "• حذف تبلیغات آیدی روشن\n"
        "• حذف تبلیغات شماره روشن\n"
        "• حذف تبلیغات فوروارد روشن\n"
        "• حذف تبلیغات کلمات روشن\n"
        "• حذف تبلیغات وضعیت\n\n"
        "برای خاموش‌کردن هر مورد، به‌جای «روشن» بنویسید «خاموش».\n"
        "پیام ادمین‌ها از این فیلتر مستثناست."
    )


def _ad_filter_status(filters: dict[str, bool]) -> str:
    lines = ["🧹 وضعیت حذف تبلیغات", ""]
    for key, label in AD_FILTER_LABELS.items():
        lines.append(f"{'✅' if filters.get(key) else '⭕'} {label}")
    lines.extend(("", "نمونه: حذف تبلیغات همه روشن"))
    return "\n".join(lines)


def _extract_links(text: str) -> list[str]:
    trailing = ".,!?:;،؛)]}>»'\""
    return [match.group(0).rstrip(trailing) for match in LINK_EXTRACT_RE.finditer(text)]


def _link_type(link: str) -> str:
    normal = link.casefold()
    if normal.startswith(("http://", "https://")):
        normal = normal.split("://", 1)[1]
    host = normal.split("/", 1)[0].removeprefix("www.")
    if host in {"t.me", "telegram.me", "splus.ir", "sapp.ir"}:
        return "group_channel"
    return "website"


def _link_processing_help() -> str:
    return (
        "🔗 پردازش لینک\n\n"
        "همهٔ لینک‌های گروه، کانال و سایت بدون حذف پیام در گزارش ثبت می‌شوند.\n\n"
        "• پردازش لینک روشن\n"
        "• پردازش لینک خاموش\n"
        "• پردازش لینک وضعیت\n"
        "• پردازش لینک گزارش\n"
        "• پردازش لینک گزارش 20\n\n"
        "حداکثر ۵۰ مورد از آخرین لینک‌ها قابل نمایش است."
    )


def _support_help() -> str:
    return (
        "📞 پشتیبانی\n\n"
        "برای اعضا:\n"
        "• 📞 پشتیبانی\n"
        "• پشتیبانی\n"
        "• ارتباط با پشتیبانی\n\n"
        "تنظیم توسط ادمین:\n"
        "• پشتیبانی تنظیم @support\n"
        "• پشتیبانی تنظیم https://example.com/support\n"
        "• پشتیبانی وضعیت\n"
        "• پشتیبانی حذف"
    )


def _is_support_request(text: str) -> bool:
    meaningful_lines: list[str] = []
    for line in text.splitlines():
        cleaned = line.strip().strip("|").strip()
        if not cleaned or re.fullmatch(r"[-: ]+", cleaned):
            continue
        meaningful_lines.append(cleaned)
    normal = _normal_permission_text(" ".join(meaningful_lines))
    return normal in {
        "پشتیبانی",
        "📞 پشتیبانی",
        "☎️ پشتیبانی",
        "ارتباط با پشتیبانی",
        "📞 پشتیبانی ارتباط با پشتیبانی",
        "☎️ پشتیبانی ارتباط با پشتیبانی",
    }


def _full_help() -> str:
    return (
        "📋 راهنمای دستورات ربات\n\n"
        "👥 مدیریت اعضا (با ریپلای)\n"
        "• سکوت ۵دقیقه\n"
        "• اخطار\n"
        "• مسدود کردن\n"
        "• حذف پیام\n\n"
        "📣 اعضا و پاسخ خودکار\n"
        "• صدا زدن اعضا متن دلخواه\n"
        "• تگ متن دلخواه\n"
        "• افزودن جواب سلام | درود\n"
        "• حذف جواب سلام\n"
        "• جواب‌ها\n\n"
        "🔐 قفل و دسترسی\n"
        "• قفل همه فقط ادمین\n"
        "• دسترسی رسانه خاموش\n"
        "• دسترسی گیف خاموش\n"
        "• دسترسی‌ها\n\n"
        "🧹 تبلیغات و فیلتر\n"
        "• حذف تبلیغات همه روشن\n"
        "• فیلتر افزودن عبارت ممنوع\n"
        "• فیلتر روشن / فیلتر لیست\n\n"
        "🛡 ضداسپم\n"
        "• ضداسپم روشن\n"
        "• ضداسپم وضعیت\n"
        "• ضداسپم همه روشن\n\n"
        "⏰ چت\n"
        "• چت باز / چت بسته\n"
        "• چت خودکار 23:00 تا 07:00\n"
        "• چت اضطراری ۳۰دقیقه\n\n"
        "🔗 پردازش لینک\n"
        "• پردازش لینک روشن\n"
        "• پردازش لینک گزارش\n\n"
        "📞 پشتیبانی\n"
        "• پشتیبانی\n"
        "• پشتیبانی تنظیم @support (ادمین)\n\n"
        "برای جزئیات هر بخش، عنوان همان بخش را از پنل ارسال کنید."
    )


def _normalize_spam_text(text: str) -> str:
    return re.sub(
        r"\s+", " ",
        text.strip().casefold().replace("ي", "ی").replace("ك", "ک"),
    )


def _chat_id_keys(value: str) -> set[str]:
    """Return comparable forms for Soroush public names and MTProto peer IDs."""
    raw = str(value or "").strip().casefold()
    if not raw:
        return set()
    keys = {raw, raw.removeprefix("@")} if raw.startswith("@") else {raw}
    numeric = raw.lstrip("+-")
    if numeric.isdigit():
        compact = numeric.lstrip("0") or "0"
        keys.add(compact)
        # MTProto-style group IDs commonly wrap the entity ID as -100<id>.
        if compact.startswith("100") and len(compact) > 6:
            keys.add(compact[3:].lstrip("0") or "0")
    return keys


def _chat_id_matches(event_chat_id: str, configured: set[str]) -> bool:
    event_keys = _chat_id_keys(event_chat_id)
    return any(event_keys & _chat_id_keys(item) for item in configured)


def _phrase_matches(normal_text: str, phrase: str) -> bool:
    normal_phrase = _normalize_spam_text(phrase)
    if not normal_phrase:
        return False
    if " " in normal_phrase:
        return normal_phrase in normal_text
    return re.search(
        rf"(?<!\w){re.escape(normal_phrase)}(?!\w)", normal_text,
    ) is not None


def _parse_spam_limits(raw: str) -> dict[str, int] | None:
    match = re.fullmatch(r"(?:سرعت|فلود)\s+(\d+)\s+(?:در|/)\s+(\d+)", raw)
    if match:
        count, seconds = (int(value) for value in match.groups())
        if 2 <= count <= 30 and 1 <= seconds <= 300:
            return {"flood_count": count, "flood_seconds": seconds}
        return None
    match = re.fullmatch(r"تکرار\s+(\d+)\s+(?:در|/)\s+(\d+)", raw)
    if match:
        count, seconds = (int(value) for value in match.groups())
        if 2 <= count <= 10 and 5 <= seconds <= 600:
            return {"duplicate_count": count, "duplicate_seconds": seconds}
        return None
    match = re.fullmatch(r"(?:منشن|تگ)\s+(\d+)", raw)
    if match and 1 <= int(match.group(1)) <= 50:
        return {"mention_limit": int(match.group(1))}
    match = re.fullmatch(r"(?:کشیده|حروف کشیده)\s+(\d+)", raw)
    if match and 3 <= int(match.group(1)) <= 100:
        return {"repeat_char_limit": int(match.group(1))}
    match = re.fullmatch(r"(?:طول|طولانی)\s+(\d+)", raw)
    if match and 50 <= int(match.group(1)) <= 10000:
        return {"max_length": int(match.group(1))}
    return None


def _spam_status(options: dict[str, bool | int]) -> str:
    state = lambda key: "✅" if bool(options[key]) else "⭕"
    return (
        "🛡 وضعیت ضداسپم و فیلترها\n\n"
        f"{'✅ روشن' if bool(options['enabled']) else '⭕ خاموش'} ضداسپم اصلی\n"
        f"{state('flood_enabled')} فلود: بیش از {int(options['flood_count'])} پیام در "
        f"{int(options['flood_seconds'])} ثانیه\n"
        f"{state('duplicate_enabled')} تکرار: {int(options['duplicate_count'])} پیام یکسان در "
        f"{int(options['duplicate_seconds'])} ثانیه\n"
        f"{state('mentions_enabled')} تگ زیاد: بیش از {int(options['mention_limit'])} آیدی\n"
        f"{state('repeat_chars_enabled')} حروف کشیده: {int(options['repeat_char_limit'])} نویسه\n"
        f"{state('length_enabled')} متن طولانی: بیش از {int(options['max_length'])} نویسه\n"
        f"{state('word_filter_enabled')} فیلتر کلمات ممنوع"
    )


def _spam_help() -> str:
    return (
        "🛡 ضداسپم و فیلترها\n\n"
        "• ضداسپم روشن / خاموش / وضعیت\n"
        "• ضداسپم همه روشن / همه خاموش\n"
        "• ضداسپم فلود روشن\n"
        "• ضداسپم تکرار روشن\n"
        "• ضداسپم منشن روشن\n"
        "• ضداسپم کشیده روشن\n"
        "• ضداسپم طولانی روشن\n\n"
        "تنظیم حدها:\n"
        "• ضداسپم سرعت 5 در 10\n"
        "• ضداسپم تکرار 3 در 60\n"
        "• ضداسپم منشن 5\n"
        "• ضداسپم کشیده 12\n"
        "• ضداسپم طول 1500\n\n"
        "فیلتر کلمات:\n"
        "• فیلتر روشن / خاموش\n"
        "• فیلتر افزودن عبارت ممنوع\n"
        "• فیلتر حذف عبارت ممنوع\n"
        "• فیلتر لیست\n"
        "• فیلتر پاکسازی\n\n"
        "پیام ادمین‌ها از ضداسپم و فیلتر کلمات مستثناست."
    )


def _chat_schedule_help() -> str:
    return (
        "⏰ باز و بسته‌شدن چت\n\n"
        "• چت باز\n"
        "• چت بسته\n"
        "• چت خودکار 23:00 تا 07:00\n"
        "• چت اضطراری ۳۰دقیقه\n"
        "• چت اضطراری ۲ساعت\n"
        "• چت اضطراری لغو\n"
        "• چت خودکار خاموش\n"
        "• چت وضعیت\n\n"
        "در حالت بسته، دسترسی ارسال پیام اعضای عادی در خود گروه غیرفعال می‌شود."
    )


def _normal_digits(value: str) -> str:
    return value.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))


def _valid_clock(value: str) -> bool:
    try:
        hours, minutes = (int(item) for item in value.split(":", 1))
    except (TypeError, ValueError):
        return False
    return 0 <= hours <= 23 and 0 <= minutes <= 59


def _canonical_clock(value: str) -> str:
    hours, minutes = (int(item) for item in value.split(":", 1))
    return f"{hours:02d}:{minutes:02d}"


def _clock_minutes(value: str) -> int:
    hours, minutes = (int(item) for item in value.split(":", 1))
    return hours * 60 + minutes


def _inside_closed_period(current: int, close_at: int, open_at: int) -> bool:
    if close_at == open_at:
        return True
    if close_at < open_at:
        return close_at <= current < open_at
    return current >= close_at or current < open_at


def _parse_timezone(value: str):
    normal = value.strip()
    match = re.fullmatch(r"([+-])(\d{1,2}):(\d{2})", normal)
    if match:
        sign, hours, minutes = match.groups()
        offset = timedelta(hours=int(hours), minutes=int(minutes))
        return timezone(offset if sign == "+" else -offset)
    try:
        return ZoneInfo(normal)
    except ZoneInfoNotFoundError:
        return timezone.utc


def _chat_schedule_status(schedule: dict[str, object]) -> str:
    emergency = _parse_iso_datetime(schedule.get("emergency_until"))
    emergency_line = ""
    if emergency and emergency > datetime.now(timezone.utc):
        emergency_line = f"\n🚨 اضطراری تا: {emergency.isoformat(timespec='minutes')}"
    if not bool(schedule["enabled"]):
        return "⏰ زمان‌بندی چت: خاموش" + emergency_line + "\nنمونه: چت خودکار 23:00 تا 07:00"
    return (
        "⏰ زمان‌بندی چت: روشن ✅\n"
        f"🔒 بسته‌شدن: {schedule['close_time']}\n"
        f"🔓 بازشدن: {schedule['open_time']}\n"
        f"🌍 منطقهٔ زمانی: {schedule['timezone']}"
        f"{emergency_line}"
    )


def _parse_iso_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
