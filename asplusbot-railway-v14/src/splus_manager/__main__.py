"""Run the manager after configuring .env environment variables."""
from __future__ import annotations

import asyncio
import os
import sys
import threading

from .service import (
    COMMAND_PREFIXES,
    PANEL_COMMANDS,
    PUBLIC_COMMANDS,
    STATUS_COMMANDS,
    Manager,
)
from .soropy_gateway import SoroPyGateway
from .storage import Store


def main() -> None:
    _load_dotenv()
    group_id = os.getenv("SOROUSH_GROUP_ID")
    phone = os.getenv("SOROUSH_PHONE")
    if not group_id or not phone:
        raise SystemExit("SOROUSH_GROUP_ID و SOROUSH_PHONE را در محیط یا فایل .env تنظیم کنید.")
    try:
        from soropy import SoroushClient
    except ImportError as exc:
        raise SystemExit("ابتدا pip install -e '.[soroush]' را اجرا کنید.") from exc

    # SoroPy v1.x requires the phone when creating its client. OTP is requested
    # interactively and never written into .env or the database.
    session_file = os.getenv("SESSION_NAME", "data/soroush.session")
    session_dir = os.getenv("SESSION_DIR") or os.path.dirname(session_file) or "."
    os.makedirs(session_dir, exist_ok=True)
    client = SoroushClient(
        phone,
        backend=os.getenv("SOROUSH_BACKEND", "websocket"),
        session_dir=session_dir,
    )
    status = client.login(code_callback=lambda: input("کد ورود سروش‌پلاس: ").strip())
    if getattr(status, "value", str(status)) not in {"success", "already_logged_in", "session_restored"}:
        raise SystemExit(f"ورود ناموفق بود: {status}")
    if "--login-only" in sys.argv[1:]:
        client.close()
        print("ورود با موفقیت ذخیره شد. اکنون سرویس ربات را راه‌اندازی یا ری‌استارت کنید.")
        return

    group_target = os.getenv("SOROUSH_GROUP_TARGET") or None
    gateway = SoroPyGateway(client, group_target)
    group_aliases = _resolve_group_aliases(client, group_id, group_target)
    print(f"شناسه‌های پذیرفته‌شدهٔ گروه: {sorted(group_aliases)}", flush=True)
    manager = Manager(
        gateway,
        Store(os.getenv("DATABASE_PATH", "data/manager.db")),
        group_id,
        managed_chat_aliases=group_aliases,
        call_members_limit=int(os.getenv("CALL_MEMBERS_LIMIT", "500")),
        call_batch_size=int(os.getenv("CALL_MEMBERS_BATCH", "20")),
        call_batch_delay=float(os.getenv("CALL_MEMBERS_DELAY_SECONDS", "1.5")),
        schedule_timezone=os.getenv("CHAT_SCHEDULE_TIMEZONE", "+03:30"),
    )

    def on_message(event):
        from .models import Message
        raw = event if isinstance(event, dict) else event.data
        message_id = raw.get("message_id", raw.get("id"))
        if message_id in (None, ""):
            return
        reply_to = raw.get("reply_to_id")
        msg = Message(
            chat_id=str(raw.get("chat_id")), message_id=int(message_id),
            sender_id=str(raw.get("sender_id", raw.get("from_id", ""))), text=raw.get("text", ""),
            reply_to_id=int(reply_to) if str(reply_to).isdigit() else None,
            is_outgoing=bool(raw.get("is_outgoing", False)),
            sender_name=str(raw.get("sender_name", "") or ""),
            sender_username=str(raw.get("sender_username", raw.get("username", "")) or ""),
        )
        gateway.remember_message(msg)
        # SoroPy invokes event handlers from its worker thread.
        asyncio.run(manager.handle(msg))

    # SoroPy emits `new_message`; adapt this short registration if the selected version names it differently.
    client.on("new_message", on_message)
    schedule_stop = threading.Event()

    def schedule_worker():
        interval = max(5.0, float(os.getenv("CHAT_SCHEDULE_CHECK_SECONDS", "20")))
        while not schedule_stop.wait(interval):
            try:
                asyncio.run(manager.scheduled_tick())
            except Exception as exc:
                print(f"خطای زمان‌بندی چت: {exc}")

    threading.Thread(target=schedule_worker, name="chat-schedule", daemon=True).start()
    threading.Thread(
        target=_outgoing_command_worker,
        args=(client, manager, group_id, group_target, schedule_stop),
        name="outgoing-command-monitor",
        daemon=True,
    ).start()
    try:
        asyncio.run(manager.scheduled_tick())
    except Exception as exc:
        print(f"خطای بررسی اولیهٔ زمان‌بندی چت: {exc}")
    print("مدیر گروه فعال است. برای توقف Ctrl+C را فشار دهید.")
    try:
        client.start_monitor(blocking=True)
    finally:
        schedule_stop.set()


def _resolve_group_aliases(client, group_id: str, group_target: str | None) -> set[str]:
    """Resolve the public group target to its numeric MTProto entity ID."""
    aliases = {str(group_id)}
    if group_target:
        aliases.add(str(group_target))
    target = group_target or group_id
    try:
        engine = client._backend._engine

        async def resolve():
            return await engine._resolve(target)

        entity = engine._runner.run(resolve(), timeout=30)
        entity_id = getattr(entity, "id", None)
        if entity_id not in (None, ""):
            aliases.add(str(entity_id))
            aliases.add(f"-100{entity_id}")
            aliases.add(f"-10000{entity_id}")
    except Exception as exc:
        print(f"هشدار: تشخیص خودکار شناسهٔ عددی گروه انجام نشد: {exc}", flush=True)
    return aliases


def _is_outgoing_command_text(text: str) -> bool:
    """Accept one-line commands typed by the logged-in account, not bot replies."""
    normal = str(text or "").strip()
    if not normal or "\n" in normal or "\r" in normal:
        return False
    if normal in STATUS_COMMANDS or normal in PANEL_COMMANDS or normal in PUBLIC_COMMANDS:
        return True
    textual_prefixes = tuple(item for item in COMMAND_PREFIXES if item and item[0].isalnum())
    emoji_commands = (
        "🔇 سکوت", "🚫 مسدود کردن", "⚠️ اخطار", "🧹 حذف پیام",
        "📢 اطلاعیه", "⚙️ تنظیمات", "📣 صدا زدن اعضا", "➕ افزودن جواب",
        "🗑 حذف جواب", "📋 جواب‌ها", "🏷️ تگ", "🔐 قفل",
    )
    return normal.startswith(textual_prefixes + emoji_commands)


def _outgoing_command_worker(client, manager, group_id, group_target, stop) -> None:
    """Poll commands manually sent by the same personal account.

    SoroPy's realtime ``new_message`` subscription is incoming-only. Without
    this small poller, buttons pressed by the logged-in account are invisible.
    """
    target = group_target or group_id
    interval = max(2.0, float(os.getenv("OUTGOING_COMMAND_CHECK_SECONDS", "3")))
    seen: set[str] = set()
    seeded = False
    try:
        me = client.get_me() or {}
        sender_id = str(me.get("id", ""))
    except Exception:
        sender_id = ""
    while not stop.wait(interval):
        try:
            engine = client._backend._engine
            messages = engine.get_messages(target, limit=30, incoming_only=False) or []
            outgoing = [item for item in messages if bool(item.get("is_outgoing"))]
            current_ids = {str(item.get("id", "")) for item in outgoing if item.get("id") not in (None, "")}
            if not seeded:
                seen.update(current_ids)
                seeded = True
                print("پایش فرمان‌های ارسالیِ حساب ربات فعال شد.", flush=True)
                continue
            for item in outgoing:
                message_id = str(item.get("id", ""))
                text = str(item.get("text", "") or "")
                if not message_id or message_id in seen or not _is_outgoing_command_text(text):
                    continue
                seen.add(message_id)
                print(f"[OUTGOING COMMAND] id={message_id} text={text!r}", flush=True)
                from .models import Message
                asyncio.run(manager.handle(Message(
                    chat_id=str(group_id),
                    message_id=int(message_id),
                    sender_id=sender_id,
                    text=text,
                    is_outgoing=True,
                )))
            seen.update(current_ids)
            if len(seen) > 300:
                seen.intersection_update(current_ids)
        except Exception as exc:
            print(f"خطای پایش فرمان‌های ارسالی: {exc}", flush=True)


def _load_dotenv(path: str = ".env") -> None:
    """Small dependency-free .env reader; existing environment wins."""
    try:
        lines = open(path, encoding="utf-8")
    except FileNotFoundError:
        return
    with lines:
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"'))


if __name__ == "__main__":
    main()
